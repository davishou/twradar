"""命令列入口。

  python -m pipeline.run daily          收盤後：行情、漲停族群、法人、券商分點、隔日表現、統計、氣氛（17:05）
  python -m pipeline.run daily 2026-10-16   重跑指定日（補漏抓的資料；分點只能抓最近一個交易日）
  python -m pipeline.run brokers        只重抓最近一個交易日失敗的分點
  python -m pipeline.run disposal       處置預測（19:30）
  python -m pipeline.run borrow         券差借券費率（20:08）
  python -m pipeline.run etf            主動 ETF 持股異動（22:30）
  python -m pipeline.run announce       自結/季報/營收/庫藏/事件（每 5 分鐘）
  python -m pipeline.run all            以上全部
  python -m pipeline.run backfill 120   補抓最近 120 個交易日歷史行情（第一次部署必跑）
  python -m pipeline.run mock           以模擬資料產生完整示範網站（離線可用）
  python -m pipeline.run serve [port]   本機預覽網站
  python -m pipeline.run reset          清除所有產生的資料
"""
from __future__ import annotations

import logging
import shutil
import sys
from datetime import date, timedelta

from . import active_etf, announce, borrow, brief, brokers, config, disposal, limitup, sources, store
from .util import now_tw

log = logging.getLogger("twradar")


def companies(src) -> dict:
    st = store.state("companies", {}) or {}
    if src is sources and st.get("_date", "") >= (date.today() - timedelta(days=7)).isoformat():
        return st["data"]
    data = src.fetch_companies()
    if data:
        store.save_state("companies", {"_date": date.today().isoformat(), "data": data})
        return data
    return st.get("data", {})


def latest_day() -> date | None:
    ds = store.trading_days()
    return ds[-1] if ds else None


def job_daily(src, d: date | None = None, light: bool = False) -> date | None:
    td, quotes = src.fetch_quotes(d)
    if not quotes or not td:
        log.info("沒有行情資料（非交易日或尚未收盤）：%s", d or "最新")
        return None
    store.save_day(td, quotes)
    comp = companies(src)
    if not light and src is sources:
        heal_missing_tpex(td, comp)
    context: dict[str, list[str]] = {}
    if not light:
        for m in src.fetch_material():
            if not m.get("date") or m["date"] == td.isoformat():
                context.setdefault(m["code"], []).append(m["subject"])
    inst = src.fetch_institutional(td) if hasattr(src, "fetch_institutional") else {}
    daily = limitup.build_daily(td, quotes, comp, context, src=src, inst=inst)
    nd = limitup.build_nextday(td, quotes)
    nxt = store.next_day(td)
    if nxt:  # 重跑過去某天時，順便更新下一天的隔日表現
        limitup.build_nextday(nxt, list(store.load_day(nxt).values()))
    if not light:
        limitup.build_stats()
        brief.commentary(daily, nd)
        brief.touch_meta("daily", td)
        brief.line_copy()
    log.info("%s 漲停 %d 檔（上市 %d、上櫃 %d）、%d 族群", td, daily["count"], daily["twse"], daily["tpex"], daily["n_groups"])
    if not light:
        job_brokers(src, td, daily, inst)
    return td


def heal_missing_tpex(td: date, comp: dict, lookback: int = 10) -> None:
    """近幾個交易日如果整批缺櫃買行情，補抓並重建該日漲停與隔日表現"""
    for d in [x for x in store.trading_days()[-lookback:] if x < td]:
        day = store.load_day(d)
        if any(q["market"] == "TPEX" for q in day.values()):
            continue
        tp = sources._tpex_by_date(d)
        if not tp:
            log.warning("補抓 %s 櫃買行情仍失敗", d)
            continue
        quotes = [q for q in day.values() if q["market"] != "TPEX"] + tp
        store.save_day(d, quotes)
        limitup.build_daily(d, quotes, comp, {}, full=False)
        limitup.build_nextday(d, quotes)
        nxt = store.next_day(d)
        if nxt:
            limitup.build_nextday(nxt, list(store.load_day(nxt).values()))
        log.info("已補上 %s 櫃買行情 %d 檔並重建當日資料", d, len(tp))


def broker_targets(td: date, daily: dict | None, inst: dict | None) -> list[dict]:
    """要抓分點的股票：當日漲停（看誰在買）＋昨日漲停（看隔日誰在賣）"""
    quotes = store.load_day(td)
    inst = inst or {}
    out, seen = [], set()
    for s in (daily or {}).get("stocks", []):
        q = quotes.get(s["code"])
        if q:
            out.append(brokers.target(q, s["name"], inst.get(s["code"]) or s.get("inst"), "limit"))
            seen.add(s["code"])
    prev = store.prev_day(td)
    for s in ((limitup.load_daily(prev) or {}).get("stocks", []) if prev else []):
        q = quotes.get(s["code"])
        if q and s["code"] not in seen:
            out.append(brokers.target(q, s["name"], inst.get(s["code"]), "next"))
    return out


def job_brokers(src, td: date | None = None, daily: dict | None = None, inst: dict | None = None) -> None:
    """券商分點：證交所網站只保留最近一個交易日，所以只對最新一天抓"""
    td = td or latest_day()
    if not td:
        return
    daily = daily or limitup.load_daily(td)
    if src is not sources:
        brokers.build_mock(td, broker_targets(td, daily, inst), store.prev_day(td))
        return
    if td != latest_day():
        log.info("%s 不是最近一個交易日，略過券商分點", td)
        return
    if inst is None:
        inst = src.fetch_institutional(td)
    try:
        st = brokers.build(td, broker_targets(td, daily, inst))
        log.info("券商分點 %s：成功 %d／%d 檔", td, st["ok"], st["total"])
    except Exception as e:  # noqa: BLE001  分點失敗不影響其他資料
        log.exception("券商分點失敗：%s", e)


def job_disposal(src) -> None:
    today = latest_day()
    if not today:
        log.warning("尚無歷史行情，請先執行 daily 或 backfill")
        return
    quotes = list(store.load_day(today).values())
    if src is sources and quotes and not any(q["market"] == "TPEX" for q in quotes):
        log.info("%s 缺櫃買行情（17:05 時可能尚未公布），重跑當日", today)
        job_daily(src, today)
        quotes = list(store.load_day(today).values())
    notices = src.fetch_notices(today - timedelta(days=50), today)
    punish = src.fetch_punish(today - timedelta(days=45), today)
    res = disposal.build(today, quotes, notices, punish, src.fetch_holidays(), src.fetch_valuation())
    brief.touch_meta("disposal", today)
    brief.line_copy()
    log.info("處置預測 → %s：差1次 %d 檔、差2次 %d 檔、處置中 %d 檔", res["target"], len(res["minus1"]),
             len(res["minus2"]), len(res["current"]))


def job_announce(src) -> None:
    today = latest_day()
    quotes = list(store.load_day(today).values()) if today else []
    res = announce.build(src.fetch_material(), src.fetch_revenue(), src.fetch_eps(), quotes, today)
    brief.touch_meta("announce")
    brief.line_copy()
    log.info("公告：自結 %d、季報 %d、營收 %d、庫藏 %d、事件 %d", *(len(res[k]) for k in ("att", "fin", "rev", "treasury", "events")))


def job_borrow(src) -> None:
    today = latest_day()
    if not today:
        return
    res = borrow.build(today, src.fetch_borrow_fee(today), list(store.load_day(today).values()))
    brief.touch_meta("borrow", today)
    log.info("券差：%d 檔", len(res["summary"]))


def job_etf(src) -> None:
    today = latest_day()
    if not today:
        return
    active_etf.collect(today, src)
    res = active_etf.build(companies(src), list(store.load_day(today).values()))
    brief.touch_meta("etf", today)
    log.info("主動 ETF：%d 檔基金", len(res["funds"]))


def backfill(n: int) -> None:
    d = now_tw().date()
    got = []
    tries = 0
    while len(got) < n and tries < n * 2:
        tries += 1
        if d.weekday() < 5 and not (config.HISTORY_DIR / f"{d.isoformat()}.json").exists():
            td, quotes = sources.fetch_quotes(d)
            if quotes:
                store.save_day(td, quotes)
                got.append(td)
                log.info("補抓 %s：%d 檔", td, len(quotes))
        elif (config.HISTORY_DIR / f"{d.isoformat()}.json").exists():
            got.append(d)
        d -= timedelta(days=1)
    # 依序重建最近 30 天的漲停資料，讓連板、族群連續天數正確
    comp = companies(sources)
    for td in store.trading_days()[-30:]:
        q = list(store.load_day(td).values())
        limitup.build_daily(td, q, comp, {}, full=False)
        limitup.build_nextday(td, q)
    limitup.build_stats()
    brief.touch_meta("backfill")


def reset() -> None:
    """清掉所有產生的資料（不會動 themes.json、etf_inbox）"""
    for p in (config.HISTORY_DIR, config.STATE_DIR, config.DATA_DIR / "etf", config.OUT_DIR):
        shutil.rmtree(p, ignore_errors=True)


def clear_mock_if_needed() -> None:
    """第一次跑真實資料時，自動清掉示範用的模擬資料"""
    if (store.read_json(config.OUT_DIR / "meta.json", {}) or {}).get("mock"):
        log.info("偵測到模擬資料，先清除再抓真實資料")
        reset()


def build_mock() -> None:
    from .mock import MockSource
    reset()
    src = MockSource()
    # 前 90 天只寫歷史，最後 40 天逐日跑完整流程
    for d in src.days[:-40]:
        store.save_day(d, src.quotes[d])
    for d in src.days[-40:]:
        job_daily(src, d, light=True)
    limitup.build_stats()
    last = src.days[-1]
    brief.commentary(limitup.load_daily(last), limitup.build_nextday(last, src.quotes[last]))
    job_brokers(src, src.days[-2])
    job_brokers(src, last)
    brief.touch_meta("daily", last)
    job_disposal(src)
    job_announce(src)
    job_borrow(src)
    active_etf.collect(src.days[-2], src)
    job_etf(src)
    brief.touch_meta("mock")
    meta = store.read_json(config.OUT_DIR / "meta.json", {})
    meta["mock"] = True
    store.write_json(config.OUT_DIR / "meta.json", meta)


def serve(port: int = 8000) -> None:
    import functools
    import http.server
    h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(config.SITE_DIR))
    print(f"開啟 http://localhost:{port}")
    http.server.ThreadingHTTPServer(("", port), h).serve_forever()


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cmd = argv[0] if argv else "all"
    src = sources
    if cmd not in ("mock", "serve", "reset"):
        clear_mock_if_needed()
    if cmd == "daily" and len(argv) > 1:
        job_daily(src, date.fromisoformat(argv[1]))
        return 0
    if cmd == "brokers":
        job_brokers(src)
        return 0
    jobs = {"daily": lambda: job_daily(src), "disposal": lambda: job_disposal(src), "announce": lambda: job_announce(src),
            "borrow": lambda: job_borrow(src), "etf": lambda: job_etf(src)}
    if cmd in jobs:
        jobs[cmd]()
    elif cmd == "all":
        for f in jobs.values():
            f()
    elif cmd == "backfill":
        backfill(int(argv[1]) if len(argv) > 1 else 120)
    elif cmd == "reset":
        reset()
    elif cmd == "mock":
        build_mock()
    elif cmd == "serve":
        serve(int(argv[1]) if len(argv) > 1 else 8000)
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

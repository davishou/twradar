"""命令列入口。

  python -m pipeline.run daily          收盤後：行情、漲停族群、法人、券商分點、隔日表現、統計、氣氛（17:05）
  python -m pipeline.run daily 2026-10-16   重跑指定日（補漏抓的資料；分點只能抓最近一個交易日）
  python -m pipeline.run brokers        只重抓最近一個交易日失敗的分點
  python -m pipeline.run disposal       處置預測（21:45，融資融券約 21:00 後公布）
  python -m pipeline.run borrow         券差借券費率（20:08）
  python -m pipeline.run etf            主動 ETF 持股異動（22:30）
  python -m pipeline.run announce       自結/季報/營收/庫藏/事件（每 5 分鐘）
  python -m pipeline.run all            以上全部
  python -m pipeline.run retheme        族群重分類（用 AI；主要經營業務補齊後執行一次）
  python -m pipeline.run cb             可轉債（最近交易日）
  python -m pipeline.run markets        國際行情：商品、各國指數、匯率（缺的代號自動補全部歷史）
  python -m pipeline.run treasury 20    庫藏股歷史回補約 6 個月（每次跑 20 分鐘，續跑）
  python -m pipeline.run history 40     長期資料庫：回補歷史（先 10 年再到 2004）（每次跑 40 分鐘，續跑）
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

from . import active_etf, announce, archive, borrow, brief, brokers, config, disposal, limitup, sources, store
from .util import now_tw

log = logging.getLogger("twradar")


def companies(src) -> dict:
    st = store.state("companies", {}) or {}
    has_tpex = any(v.get("market") == "TPEX" and v.get("shares") for v in (st.get("data") or {}).values())
    if src is sources and has_tpex and st.get("_date", "") >= (date.today() - timedelta(days=7)).isoformat():
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
    if d is None and src is sources:
        # 證交所 OpenAPI 的「最新行情」有時好幾個小時都還是前一天，
        # 所以先用依日期查詢抓今天，抓不到（休市或尚未收盤）才用 OpenAPI 的最新資料
        now = now_tw()
        day = now.date() if now.hour * 60 + now.minute >= 14 * 60 + 30 else now.date() - timedelta(days=1)
        for _ in range(6):
            if day.weekday() < 5:
                td, quotes = src.fetch_quotes(day)
                if quotes and td == day and any(q["market"] == "TWSE" for q in quotes):
                    return _daily(src, td, quotes, light)
                log.info("依日期查詢 %s 沒有行情（休市或尚未公布）", day)
            day -= timedelta(days=1)
    td, quotes = src.fetch_quotes(d)
    return _daily(src, td, quotes, light, d)


def _daily(src, td, quotes, light: bool = False, d=None) -> date | None:
    if not quotes or not td:
        log.info("沒有行情資料（非交易日或尚未收盤）：%s", d or "最新")
        return None
    store.save_day(td, quotes)
    store.prune()               # data/history 只留近 260 個交易日
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
    if src is sources:  # 長期資料庫（回測用）
        archive.save_quotes(td, quotes)
        if inst:
            archive.save_inst(td, inst)
        archive.save_limitup(td, daily)
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
        retheme_history(src)
        job_brokers(src, td, daily, inst)
        job_cb(src, td, inst)
    return td


def job_cb(src, d: date | None = None, inst: dict | None = None) -> None:
    """可轉債：行情、看板、發行資料 → site/data/cb.json（櫃買約 16~18 點公布；21:45 處置工作會再補一次）"""
    if src is not sources:
        return
    from . import cb
    try:
        res = cb.run(d, inst=inst)
        if res:
            brief.touch_meta("cb", d)
            from . import cbtemp
            cbtemp.update(date.fromisoformat(res["date"]))   # CB 溫度計（鄭大委買均價換算）
            from . import cbsig
            cbsig.run()                                      # CB 訊號標記（鄭大規則＋回測結果）
        from . import cbipo
        cbipo.run()
    except Exception as e:  # noqa: BLE001  可轉債失敗不影響其他資料
        log.exception("可轉債失敗：%s", e)


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


def retheme_history(src, days: int = 120) -> None:
    """有 AI 之後，一次性把近 N 天仍用官方產業別的漲停股重新分類（結果寫回 themes.json），再重建隔日與統計"""
    from . import ai
    if src is not sources or not ai.enabled() or (store.state("retheme", {}) or {}).get("v") == 1:
        return
    comp = companies(src)
    dates = limitup.daily_dates()[-days:]
    for d in dates:
        dj = limitup.load_daily(d) or {}
        if any(s.get("theme_source") == "industry" for s in dj.get("stocks", [])):
            limitup.build_daily(d, list(store.load_day(d).values()), comp, {}, full=False)
    for d in dates:
        nxt = store.next_day(d)
        if nxt:
            limitup.build_nextday(nxt, list(store.load_day(nxt).values()))
    limitup.build_stats()
    store.save_state("retheme", {"v": 1})
    log.info("已用 AI 重新分類近 %d 天的漲停股", len(dates))


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


def update_margin(src, today: date) -> dict:
    """融資融券餘額歷史（第七款要近 6 日券資比）。缺的日子補抓，保留 8 個交易日"""
    st = store.state("margin_hist", {}) or {}
    data = st.get("data") or {}
    days = [d.isoformat() for d in store.days_before(today, 7)]
    for d in days:
        if d in data or not hasattr(src, "fetch_margin"):
            continue
        got = src.fetch_margin(date.fromisoformat(d))
        if got:
            got.pop("_n", None)
            data[d] = got
    data = {k: v for k, v in data.items() if k in days}
    store.save_state("margin_hist", {"data": data})
    have = sorted(data)
    return {"today": today.isoformat() if today.isoformat() in data else None, "days": have, "data": data}


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
    margin = update_margin(src, today)
    if src is sources:
        for d, m in margin["data"].items():
            archive.save_margin(date.fromisoformat(d), m)
        archive.save_notices(notices)
        archive.save_punish(punish)
    res = disposal.build(today, quotes, notices, punish, src.fetch_holidays(), src.fetch_valuation(),
                         companies(src), margin)
    brief.touch_meta("disposal", today)
    cur = (store.read_json(config.OUT_DIR / "cb.json", {}) or {}).get("date")
    if src is sources and cur != today.isoformat():
        job_cb(src, today)
    brief.line_copy()
    log.info("處置預測 → %s：差1次 %d 檔、差2次 %d 檔、處置中 %d 檔", res["target"], len(res["minus1"]),
             len(res["minus2"]), len(res["current"]))


def job_announce(src) -> None:
    from . import findb
    today = latest_day()
    quotes = list(store.load_day(today).values()) if today else []
    if src is sources:
        st = store.state("findb_run", {}) or {}
        if st.get("d") != date.today().isoformat():   # 財報資料庫一天更新一次
            findb.update()
            store.save_state("findb_run", {"d": date.today().isoformat()})
        db = announce.update_material(sources.fetch_material_mops, now_tw().date())
        material = [v for k, v in db.items() if not k.startswith("_")]
        announce.keep_treasury_raw(material, now_tw().date())
        exr = sources.fetch_exrights()
    else:
        material, exr = src.fetch_material(), []
    res = announce.build(material, src.fetch_revenue(), quotes, today, exr,
                         treasury_extra=announce.treasury_raw_items() if src is sources else None)
    brief.touch_meta("announce")
    brief.line_copy()
    log.info("公告：自結 %d、季報 %d、營收 %d、庫藏 %d、事件 %d、其他 %d", *(len(res[k]) for k in ("att", "fin", "rev", "treasury", "events", "others")))
    if src is sources:
        try:   # 國際行情現價：每 30 分鐘更新一次（Yahoo，延遲約 10~20 分）
            from . import markets
            markets.maybe_quick(30)
        except Exception as e:  # noqa: BLE001
            log.exception("國際行情更新失敗：%s", e)
    try:   # 私募案（從重大訊息整理，不呼叫 AI）
        from . import private
        log.info("私募：%d 案", private.run())
    except Exception as e:  # noqa: BLE001
        log.exception("私募整理失敗：%s", e)


def job_treasury(minutes: float = 20, days: int = 185) -> None:
    """庫藏股歷史回補：往回抓約 6 個月重大訊息，只留庫藏股公告，再重建庫藏頁。可續跑，不呼叫 AI"""
    res = announce.backfill_treasury(sources.fetch_material_mops, now_tw().date(), days=days, minutes=minutes)
    if res["fetched"] or res["found"]:
        job_announce(sources)


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


def job_history(minutes: float = 40) -> None:
    """長期資料庫：分批回補行情／法人／融資融券（先 10 年、再到 2004）、上市注意處置股、同步漲停族群、重算還原因子"""
    try:   # 國際行情：每晚補最近幾天收盤（週末也跑，接得到美股週五收盤）
        from . import markets
        markets.update()
    except Exception as e:  # noqa: BLE001
        log.exception("國際行情更新失敗：%s", e)
    st = archive.backfill(sources, minutes=minutes * 0.5)    # 先 10 年，補完自動延伸到 2004
    archive.backfill_notices(sources)
    try:
        archive.backfill_fundamentals(sources, minutes=minutes * 0.25)   # 月營收、季報歷史（2013 起）
    except Exception as e:  # noqa: BLE001
        log.exception("基本面回補失敗：%s", e)
    try:   # 可轉債行情 2007 起、資訊看板 2017 起
        from . import cb
        cb.backfill(minutes=minutes * 0.15)
        log.info("可轉債快照補建 %d 天", cb.rebuild_history())
    except Exception as e:  # noqa: BLE001
        log.exception("可轉債回補失敗：%s", e)
    try:   # 族群分類用的『主要經營業務』，全部公司慢慢補齊（不呼叫 AI）
        from . import themes
        n_biz = themes.prefetch_business(sources.fetch_business, sorted(companies(sources)), minutes=minutes * 0.15)
        log.info("主要經營業務：本次補 %d 家", n_biz)
    except Exception as e:  # noqa: BLE001
        log.exception("主要經營業務補抓失敗：%s", e)
    archive.sync_limitup()
    try:
        job_treasury(minutes=10)          # 庫藏股回補沒補完就順便續補；補完後幾乎不花時間
    except Exception as e:  # noqa: BLE001
        log.exception("庫藏股回補失敗：%s", e)
    n = archive.build_adjust()
    log.info("還原因子 %d 筆；回補完成：%s", n, st.get("complete"))


def job_retheme() -> None:
    """族群重分類（會用 AI）：把只分到官方產業別的股票，用主要經營業務重新分類，再重建所有歷史漲停頁、隔日、統計"""
    from . import themes
    comp = companies(sources)
    res = themes.reclassify_weak({c: v.get("name", "") for c, v in comp.items()}, {c: v.get("industry", "") for c, v in comp.items()})
    log.info("族群重分類：%s", res)
    store.save_state("retheme", {"v": 2, **res})
    dates = limitup.daily_dates()
    # 歷史漲停股中還沒有族群紀錄的（當初用關鍵字或產業別），先分批分類好，重建時就不會每天各叫一次 AI
    known = {c for v in themes.load_themes().values() for c in v.get("codes", [])}
    todo = {}
    for d in dates:
        for st in (limitup.load_daily(d) or {}).get("stocks", []):
            if st["code"] not in known and st.get("theme_source") != "keyword":
                todo[st["code"]] = {"code": st["code"], "name": st["name"], "industry": st.get("industry", "")}
    biz = themes.businesses(list(todo), None)
    items = list(todo.values())
    for i in range(0, len(items), 50):
        themes.classify(items[i:i + 50], {}, biz)
    log.info("補分類歷史漲停股 %d 檔", len(items))
    for d in dates:
        limitup.build_daily(d, list(store.load_day(d).values()), comp, {}, full=False)
    for d in dates:
        nxt = store.next_day(d)
        if nxt:
            limitup.build_nextday(nxt, list(store.load_day(nxt).values()))
    limitup.build_stats()
    brief.line_copy()
    log.info("已重建 %d 天的漲停與隔日資料", len(dates))


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
    from . import spark
    spark.write()
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
    jobs = {"cb": lambda: job_cb(src), "daily": lambda: job_daily(src), "disposal": lambda: job_disposal(src), "announce": lambda: job_announce(src),
            "borrow": lambda: job_borrow(src), "etf": lambda: job_etf(src)}
    if cmd in jobs:
        jobs[cmd]()
    elif cmd == "all":
        for f in jobs.values():
            f()
    elif cmd == "markets":
        from . import markets
        markets.update(full=len(argv) > 1 and argv[1] == "full")
        brief.touch_meta("markets")
    elif cmd == "retheme":
        job_retheme()
    elif cmd == "cbhist":                # 可轉債歷史集中回補（白天手動跑，約 25 分鐘一輪）
        from . import cb
        cb.backfill(minutes=float(argv[1]) if len(argv) > 1 else 24)
        cb.rebuild_history()
    elif cmd == "treasury":
        job_treasury(float(argv[1]) if len(argv) > 1 else 20)
    elif cmd == "history":
        job_history(float(argv[1]) if len(argv) > 1 else 40)
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

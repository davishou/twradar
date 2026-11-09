"""選股策略通知：什麼時候該買、該賣，第一時間推到手機（GitHub Actions 每次 announce／daily 工作都會跑一次）

多策略組合（營收主力＋除權息前 10 天／前一天買＋第二次處置前放空＋打入全額交割放空；規則見 pipeline/strats.py）
會發的通知（每則只發一次，記在 data/state/notify.json）
  明天要做的事   前一個交易日 22:00 後（處置預測 21:45 才出來）：所有策略下個交易日的進出場、能不能融資融券
  今天要做的事   交易日早上 08:00 後：同上（除權息「開盤賣」要在開盤前看到）
  營收主力名單   進場日早上（營收公布家數未達上月 97% 先等，最晚 12:00）
  停損警示       收盤後：收盤虧損達 15% → 下個交易日開盤出場
  全額交割公告   看到重大訊息就發
另外：進場日收盤後把當月名單凍結記到 data/state/picks_log.json（實際紀錄，之後不改）。

通知管道（GitHub Secrets，設哪個就發哪個；都沒設就只記紀錄不發）
  LINE_CHANNEL_TOKEN, LINE_USER_ID      LINE 官方帳號（Messaging API；輕用量每月 200 則免費，一則推給自己算 1 則）
  NTFY_TOPIC                         ntfy.sh 推播（手機裝 ntfy App、訂閱同一個主題名稱；主題名稱請取長一點的亂碼）
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID  Telegram 機器人
  SMTP_USER, SMTP_PASS, NOTIFY_EMAIL    Email（Gmail 要用「應用程式密碼」）

python -m pipeline.notify          檢查並發送
python -m pipeline.notify test     發一則測試通知
"""
from __future__ import annotations

import logging
import os
import smtplib
import sys
from datetime import date, datetime
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo

from datetime import timedelta

from . import config, picks, strats
from .util import read_json, write_json

log = logging.getLogger(__name__)
STATE = config.STATE_DIR / "notify.json"
TZ = ZoneInfo("Asia/Taipei")
URL = "https://davishou.github.io/twradar/#/picks"


def send(title: str, body: str) -> list[str]:
    import requests
    sent = []
    tok, uid = os.environ.get("LINE_CHANNEL_TOKEN", "").strip(), os.environ.get("LINE_USER_ID", "").strip()
    if tok and uid:
        try:
            text = f"{title}\n\n{body}\n\n{URL}"[:4900]
            requests.post("https://api.line.me/v2/bot/message/push", headers={"Authorization": f"Bearer {tok}"},
                          json={"to": uid, "messages": [{"type": "text", "text": text}]}, timeout=20).raise_for_status()
            sent.append("line")
        except Exception as e:  # noqa: BLE001
            log.warning("LINE 失敗：%s", getattr(getattr(e, "response", None), "text", "") or e)
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if topic:
        try:
            requests.post(f"https://ntfy.sh/{topic}", data=body.encode("utf-8"),
                          headers={"Title": title.encode("utf-8"), "Click": URL, "Tags": "chart_with_upwards_trend"}, timeout=20).raise_for_status()
            sent.append("ntfy")
        except Exception as e:  # noqa: BLE001
            log.warning("ntfy 失敗：%s", e)
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(), os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if tok and chat:
        try:
            requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                          json={"chat_id": chat, "text": f"{title}\n\n{body}\n\n{URL}", "disable_web_page_preview": True}, timeout=20).raise_for_status()
            sent.append("telegram")
        except Exception as e:  # noqa: BLE001
            log.warning("Telegram 失敗：%s", e)
    user, pw, to = (os.environ.get(k, "").strip() for k in ("SMTP_USER", "SMTP_PASS", "NOTIFY_EMAIL"))
    if user and pw and to:
        try:
            msg = MIMEText(f"{body}\n\n{URL}", "plain", "utf-8")
            msg["Subject"], msg["From"], msg["To"] = title, user, to
            with smtplib.SMTP_SSL(os.environ.get("SMTP_HOST", "smtp.gmail.com"), 465, timeout=30) as s:
                s.login(user, pw)
                s.sendmail(user, [x.strip() for x in to.split(",")], msg.as_string())
            sent.append("email")
        except Exception as e:  # noqa: BLE001
            log.warning("Email 失敗：%s", e)
    return sent


def _holidays() -> set[date]:
    try:
        from . import sources
        return sources.fetch_holidays()
    except Exception:  # noqa: BLE001
        return set()


def fmt_list(items, with_rank=False) -> str:
    return "\n".join(f"・{x['code']} {x['name']}" + (f"（第 {x['rank']} 名）" if with_rank and x.get("rank") else "")
                     + (f"［{x['why']}］" if x.get("why") else "") for x in items)


def _size(close: float | None, taiex: float | None) -> str:
    """有設 CAPITAL（GitHub Variables）時，換算 4% 資金約幾張、幾口微台"""
    cap = float(os.environ.get("CAPITAL") or 0)
    if not cap or not close:
        return ""
    amt = cap * strats.PER
    lots = amt / (close * 1000)
    s = f"（4% ≈ {amt / 1e4:,.0f} 萬，約 {lots:.1f} 張"
    if taiex:
        s += f"；避險約 {amt / (taiex * 10):.1f} 口微台"
    return s + "）"


def check(now: datetime | None = None, dry: bool = False) -> list[str]:
    now = now or datetime.now(TZ)
    today = now.date()
    hol = _holidays()
    st = read_json(STATE, {}) or {}
    sent_keys = st.setdefault("sent", {})
    book0 = strats.load_book()
    res = picks.build(today=today, holidays=hol, reserved=len(book0["open"]))
    if not res:
        return []
    days, adj, vals, meta = picks.price_panel()
    from . import store
    last_close = {c: q.get("close") for c, q in store.load_day(days[-1]).items()}
    picks.update_log(res, adj, days, last_close)

    out = []
    nx = res["next"]
    nxt = date.fromisoformat(nx["date"])
    data_day = date.fromisoformat(res["date"])
    pend = nx.get("pending") or {}
    full = pend.get("reported_prev") and pend.get("reported", 0) >= 0.97 * pend["reported_prev"]

    def emit(key, title, body):
        if key in sent_keys:
            return
        ch = [] if dry else send(title, body)
        log.info("通知 %s → %s\n%s\n%s", key, ch or "（未設定管道，只記錄）", title, body)
        sent_keys[key] = {"at": now.strftime("%Y-%m-%d %H:%M"), "to": ch}
        out.append(key)

    # ---------- 短線事件：更新部位紀錄 ----------
    qdays, quotes = strats.recent_quotes(25)
    book = strats.load_book()
    done = {strats.key(p) for p in book["open"] + book["closed"]}
    day_close = {c: q.get("close") for c, q in store.load_day(data_day).items()}

    # 除權息：預告表裡符合的，存成計畫；進場日收盤後轉成持有
    plans = {strats.key(p): p for p in book["planned"]}
    for p in strats.exdiv_plans(today, data_day, hol, quotes):
        plans.setdefault(strats.key(p), p)
    # 全額交割：重大訊息（近 20 天）
    for n in strats.fulldel_news(data_day - timedelta(days=20)):
        if not n["eff"]:
            continue
        eff = date.fromisoformat(n["eff"])
        ent = strats.trading_before(eff, 1, hol)
        p = {"strat": "打入全額交割放空", "code": n["code"], "name": n["name"], "side": "short", "entry": ent.isoformat(), "entry_at": "收盤",
             "exit": strats.trading_after(eff, 19, hol).isoformat(), "exit_at": "收盤", "eff": n["eff"]}
        if p["entry"] > data_day.isoformat() and strats.key(p) not in done:
            if strats.key(p) not in plans:
                plans[strats.key(p)] = p
                emit(f"fd:{n['code']}:{n['eff']}", f"📢 {n['code']} {n['name']} 將打入全額交割（{eff:%m/%d} 生效）",
                     f"策略：{ent:%m/%d} 收盤「借券賣出」放空（全額交割股不能融券），{p['exit'][5:].replace('-', '/')} 收盤回補。\n"
                     f"先問券商有沒有券可借；借不到就不做。回測勝率約 76%、每筆平均 +13%，但一年只有 3~4 次。")
    # 計畫到了進場日、而且已經有當天收盤 → 轉成持有
    for k, p in list(plans.items()):
        if p["entry"] <= data_day.isoformat():
            px = day_close.get(p["code"]) if p["entry"] == data_day.isoformat() else None
            if px and k not in done:
                book["open"].append({**p, "entry_close": px})
            plans.pop(k)
    # 處置：今天公布第二次處置、今天不是一字漲停 → 當作今天收盤已放空，持有 5 個交易日
    for x in strats.punish_today(data_day):
        q = (quotes.get(x["code"]) or [{}])[-1]
        if strats.one_limit_up(q) or strats.avg_value(quotes.get(x["code"]) or []) < strats.MIN_VAL:
            continue
        p = {"strat": "第二次處置前放空", "code": x["code"], "name": x["name"], "side": "short", "entry": data_day.isoformat(), "entry_at": "收盤",
             "exit": strats.trading_after(data_day, 5, hol).isoformat(), "exit_at": "收盤", "entry_close": day_close.get(x["code"]),
             "punish": f"{x['start']}~{x['end']}"}
        if strats.key(p) not in done and p["entry_close"]:
            book["open"].append(p)
            done.add(strats.key(p))
    # 持有中：到期、停損
    exits, stops = [], []
    still = []
    for p in book["open"]:
        c = day_close.get(p["code"])
        if p["exit"] < nxt.isoformat() and p["exit"] <= data_day.isoformat():
            book["closed"].append({**p, "exit_close": c, "why": "到期"})
            continue
        if c and p.get("entry_close") and data_day.isoformat() > p["entry"] and not p.get("stopped"):
            r = c / p["entry_close"] - 1
            if (p["side"] == "long" and r <= -strats.STOP) or (p["side"] == "short" and r >= strats.STOP):
                p["stopped"] = data_day.isoformat()
                stops.append(p)
        if p.get("stopped") and p["stopped"] < data_day.isoformat():
            book["closed"].append({**p, "exit_close": c, "why": "停損"})
            continue
        if p["exit"] == nxt.isoformat() and not p.get("stopped"):
            exits.append(p)
        still.append(p)
    book["open"] = still
    book["planned"] = list(plans.values())
    book["closed"] = book["closed"][-300:]
    strats.save_book(book)

    # ---------- 下個交易日要做的事 ----------
    entries = [p for p in book["planned"] if p["entry"] == nxt.isoformat()]
    watch = strats.disposal_watch()
    dwatch = [w for w in watch["rows"] if watch.get("target") == nxt.isoformat()
              and strats.avg_value(quotes.get(w["code"]) or []) >= strats.MIN_VAL]
    need_credit = entries or dwatch or exits or stops
    margin = strats.margin_now(data_day) if need_credit else {}
    fl = strats.full_list_now() if need_credit else set()
    pun = strats.punish_codes(nxt)
    taiex = (((read_json(config.STATE_DIR / "markets.json", {}) or {}).get("live") or {}).get("taiex") or {}).get("price")
    exs = {p["code"]: date.fromisoformat(p["ex"]) for p in book["planned"] if p.get("ex")}

    def note(code, side, until=None):
        ex = exs.get(code)
        soon = ex if (side == "short" and ex and until and ex <= until) else None
        return strats.credit_note(code, side, margin, fl, pun, soon)

    lines = []
    for p in entries:
        if p["strat"].startswith("除權息"):
            lines.append(f"【{p['strat']}】{p['entry_at']}買 {p['code']} {p['name']}（殖利率 {p['yield']:.1%}，{p['ex'][5:].replace('-', '/')} 除權息）{_size(last_close.get(p['code']), taiex)}\n"
                         f"　同時放空等值台指期（微台指 1 口 ≈ 加權指數×10 元）；{p['exit'][5:].replace('-', '/')} {p['exit_at']}賣出、回補期貨。\n　{note(p['code'], 'long')}")
        else:
            lines.append(f"【{p['strat']}】{p['entry_at']}借券賣出 {p['code']} {p['name']}{_size(last_close.get(p['code']), None)}；{p['exit'][5:].replace('-', '/')} 收盤回補。\n　{note(p['code'], 'short')}")
    for w in dwatch:
        until = strats.trading_after(nxt, 5, hol)
        cond = "；".join(w["cond"]) or "量能等其他條件（看網站處置頁）"
        lines.append(f"【第二次處置前放空（有條件）】{w['code']} {w['name']}（前收 {w['close']}）：{nxt:%m/%d} 可能被第二次處置。\n"
                     f"　若收盤符合：{cond} → 收盤放空{_size(w['close'], None)}；收在一字漲停就不要空。持有到 {until:%m/%d} 收盤回補。\n　{note(w['code'], 'short', until)}")
    for p in exits:
        act = "回補" if p["side"] == "short" else "賣出"
        lines.append(f"【{p['strat']}】{p['exit_at']}{act} {p['code']} {p['name']}（到期）" + ("，同時回補台指期" if p.get("hedge") else ""))
    for p in stops:
        act = "回補" if p["side"] == "short" else "賣出"
        lines.append(f"【停損】開盤{act} {p['code']} {p['name']}（{p['strat']}，收盤已虧 15%）" + ("，同時回補台指期" if p.get("hedge") else ""))
    main_sell = [x for x in nx["sell"]]
    if main_sell:
        lines.append("【營收主力】" + "、".join(f"{x['code']} {x['name']}（{'開盤停損' if x['why'] == '停損' else '收盤到期賣'}）" for x in main_sell))
    main_buy = nx["buy"]
    n_open = len(book["open"]) + nx.get("live_open", 0)

    # 停損警示：當天行情進來就發
    if stops and data_day == today and now.hour >= 15:
        emit(f"stop2:{today}", f"⚠️ 停損：{len(stops)} 筆下個交易日（{nxt:%m/%d}）開盤出場",
             "\n".join(f"・{p['code']} {p['name']}（{p['strat']}）" for p in stops))
    if [x for x in main_sell if x["why"] == "停損"] and data_day == today and now.hour >= 15:
        emit(f"stop:{today}", f"⚠️ 營收主力停損：下個交易日（{nxt:%m/%d}）開盤賣",
             fmt_list([x for x in main_sell if x["why"] == "停損"]) + "\n\n收盤跌破買價 −15%，空出的份數等下個月。")

    head = f"目前占用約 {n_open}／{strats.SLOTS} 份（每份 4%）；份數不夠時短線事件優先。"
    # 晚上預告（處置預測 21:45 才出來，所以 22:00 後）
    if (lines or main_buy) and nxt > today and now.hour >= 22 and data_day <= today:
        body = "\n\n".join(lines)
        if main_buy:
            body += ("\n\n" if body else "") + f"【營收主力】收盤買 {len(main_buy)} 檔（名單在進場日早上再確認）：\n" + fmt_list(main_buy, True)
        emit(f"pre:{nxt}", f"📋 下個交易日（{nxt:%m/%d}）要做的事", head + "\n\n" + body)
    # 當天早上
    if nxt == today and now.hour >= 8 and lines:
        emit(f"today2:{today}", f"🔔 今天（{today:%m/%d}）要做的事", head + "\n\n" + "\n\n".join(lines)
             + "\n\n停損：收盤虧損達 15% → 下個交易日開盤出場。")
    if nxt == today and main_buy and now.hour >= 8 and (full or now.hour >= 12):
        emit(f"today:{today}", f"🔔 今天（{today:%m/%d}）收盤買營收主力 {len(main_buy)} 檔",
             f"每檔總資金 4%：\n{fmt_list(main_buy, True)}\n\n停損：收盤跌破買價 −15% 隔天開盤賣；沒停損持有 60 個交易日。")
    st["last_check"] = now.strftime("%Y-%m-%d %H:%M")
    st["next"] = nx
    st["lines"] = lines
    write_json(STATE, st)
    return out


def main(argv):
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if argv and argv[0] == "test":
        ch = send("盤後雷達 測試通知", "看到這則就代表通知設定成功。\n之後進場日早上、停損觸發時會收到通知。")
        print("已送出：", ch or "沒有設定任何管道（LINE_*／NTFY_TOPIC／TELEGRAM_*／SMTP_*）")
        return 0 if ch else 1
    check(dry="dry" in argv)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

"""選股策略通知：什麼時候該買、該賣，第一時間推到手機（GitHub Actions 每次 announce／daily 工作都會跑一次）

會發的通知（每則只發一次，記在 data/state/notify.json）
  進場預告   進場日前一個交易日 20:00 後：下個交易日收盤要買的名單（營收可能還有少數沒公布）
  今日操作   有買或賣的交易日早上 08:00 後：今天收盤買哪些、賣哪些（停損、到期）
             營收公布家數還不到上個月的 97% 時先等，最晚 12:00 照發
  停損警示   每天收盤後（當天行情進來後）：有持股收盤跌破停損價 → 下一個交易日收盤賣
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

from . import config, picks
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


def check(now: datetime | None = None, dry: bool = False) -> list[str]:
    now = now or datetime.now(TZ)
    today = now.date()
    hol = _holidays()
    st = read_json(STATE, {}) or {}
    sent_keys = st.setdefault("sent", {})
    res = picks.build(today=today, holidays=hol)
    if not res:
        return []
    # 實際紀錄
    days, adj, vals, meta = picks.price_panel()
    last_close = {}
    from . import store
    for c, q in store.load_day(days[-1]).items():
        last_close[c] = q.get("close")
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

    # 停損警示：今天行情進來後（data_day＝今天），持有中觸發停損 → 下個交易日收盤賣
    stops = [x for x in nx["sell"] if x["why"] == "停損"]
    if data_day == today and stops and now.hour >= 15:
        emit(f"stop:{today}", f"⚠️ 停損：{len(stops)} 檔下個交易日（{nxt:%m/%d}）收盤賣",
             fmt_list(stops) + f"\n\n收盤跌破買價 −20%。規則：{nxt:%m/%d} 收盤賣出，空出的份數等下個月。")
    # 進場預告：明天是進場日
    if nx["buy"] and nxt > today and now.hour >= 20 and data_day == today:
        emit(f"pre:{nxt}", f"📋 下個交易日（{nxt:%m/%d}）收盤進場：預計買 {len(nx['buy'])} 檔",
             fmt_list(nx["buy"], True) + f"\n\n{pend.get('ym')} 營收已公布 {pend.get('reported')}／上月 {pend.get('reported_prev')} 家，名單在進場日早上會再確認一次。"
             + (f"\n同一天收盤賣：\n{fmt_list(nx['sell'])}" if nx["sell"] else ""))
    # 今日操作：今天就是下一個交易日（早上，今天的行情還沒進來）
    if nxt == today and (nx["buy"] or nx["sell"]) and now.hour >= 8 and (full or now.hour >= 12 or not nx["buy"]):
        parts = []
        if nx["sell"]:
            parts.append(f"今天收盤【賣出】{len(nx['sell'])} 檔：\n" + fmt_list(nx["sell"]))
        if nx["buy"]:
            parts.append(f"今天收盤【買進】{len(nx['buy'])} 檔（資金 20 份，每份一樣多）：\n" + fmt_list(nx["buy"], True))
        emit(f"today:{today}", f"🔔 今天（{today:%m/%d}）收盤要操作", "\n\n".join(parts) + "\n\n停損：收盤跌破買價 −20% 隔天收盤賣；沒停損持有 60 個交易日。")
    st["last_check"] = now.strftime("%Y-%m-%d %H:%M")
    st["next"] = nx
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

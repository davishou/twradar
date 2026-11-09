"""多策略組合的短線事件訊號與部位紀錄（給 pipeline/notify.py 用）

組合規則（research/multi_strat.py 回測，3 折手續費、2013 起：年化約 +39%、回落約 −25%）
  每筆用總資金 4%（25 份），份數不夠時短線事件優先、營收主力少買；全部策略收盤虧損達 15% → 下個交易日開盤停損。
策略
  除權息前 10 天買   殖利率 ≥ 4%：除權息日前第 11 個交易日收盤買、前一天收盤賣；同時放空等值台指期（避險）
  除權息前一天買     殖利率 ≥ 6%：除權息前一天收盤買、除權息當天開盤賣；同時放空等值台指期
  第二次處置前放空   明天可能被第二次處置的股票：明天收盤放空（公布當天不是一字漲停），持有 5 個交易日收盤回補
  打入全額交割放空   公告將變更交易方法（全額交割）：生效前一天收盤借券賣出（不能融券），生效後第 19 個交易日收盤回補
都要 20 日均成交 ≥ 1 億（全額交割不限）。殖利率＝現金股利（＋股票股利換算）÷ 最新收盤。

部位紀錄 data/state/strat_book.json：訊號確定後就當作已進場，到期、停損時提醒（使用者實際有沒有做不影響紀錄）。
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, timedelta

from . import config, store
from .util import read_json, write_json

log = logging.getLogger(__name__)
BOOK = config.STATE_DIR / "strat_book.json"
SLOTS, PER, STOP = 25, 0.04, 0.15
MIN_VAL = 1e8


# ------------------------------------------------------------------ 交易日
def trading_after(d: date, n: int, holidays: set[date]) -> date:
    """d 之後第 n 個交易日（n=1＝下一個交易日）"""
    x, k = d, 0
    while k < n:
        x += timedelta(days=1)
        if x.weekday() < 5 and x not in holidays:
            k += 1
    return x


def trading_before(d: date, n: int, holidays: set[date]) -> date:
    x, k = d, 0
    while k < n:
        x -= timedelta(days=1)
        if x.weekday() < 5 and x not in holidays:
            k += 1
    return x


def is_trading(d: date, holidays: set[date]) -> bool:
    return d.weekday() < 5 and d not in holidays


# ------------------------------------------------------------------ 行情與信用交易資訊
def recent_quotes(n: int = 20):
    days = list(store.trading_days())[-n:]
    out = {}
    for d in days:
        for c, q in store.load_day(d).items():
            out.setdefault(c, []).append(q)
    return days, out


def avg_value(qs: list[dict]) -> float:
    v = [q.get("value") or 0 for q in qs[-20:]]
    return sum(v) / len(v) if len(v) >= 15 else 0.0


def margin_now(day: date) -> dict:
    """{code: [資餘額, 資限額, 券餘額, 券限額]}（張）；同一天只抓一次，存在 data/state/margin_now.json"""
    p = config.STATE_DIR / "margin_now.json"
    st = read_json(p, {}) or {}
    if st.get("date") == day.isoformat() and st.get("data"):
        return st["data"]
    try:
        from . import sources
        m = sources.fetch_margin(day) or {}
        m.pop("_n", None)
    except Exception as e:  # noqa: BLE001
        log.warning("融資融券抓取失敗：%s", e)
        return st.get("data") or {}
    if m:
        write_json(p, {"date": day.isoformat(), "data": m})
        return m
    return st.get("data") or {}


def credit_note(code: str, side: str, margin: dict, full_list: set[str], punish_now: set[str],
                ex_soon: date | None = None) -> str:
    """一行白話：能不能融資／融券、要注意什麼"""
    if code in full_list:
        return "全額交割股：不能融資、融券；放空只能「借券賣出」（先問券商有沒有券），買賣都要預收款券。"
    if not margin:
        return "今天沒抓到融資融券資料，能不能融資券請以券商畫面為準。"
    m = margin.get(code)
    if not m:
        base = "不是信用交易標的（或今天沒有資料）：不能融資融券" + ("，放空只能借券賣出" if side == "short" else "") + "。"
        return base
    fin_bal, fin_lim, sh_bal, sh_lim = (x or 0 for x in m)
    parts = []
    if side == "short":
        left = sh_lim - sh_bal
        if sh_lim <= 0:
            parts.append("目前不能融券（額度 0），只能借券賣出")
        elif left <= 0:
            parts.append(f"融券額度已滿（{sh_bal:,.0f}／{sh_lim:,.0f} 張），只能借券賣出")
        else:
            parts.append(f"可融券，剩約 {left:,.0f} 張額度")
        if ex_soon:
            parts.append(f"⚠️ {ex_soon:%m/%d} 除權息前後會停止融券、融券要在最後回補日前回補，以券商公告為準")
    else:
        parts.append("可融資" if fin_lim > 0 and fin_bal < fin_lim else "融資額度已滿或不能融資，用現股")
    if code in punish_now:
        parts.append("處置中：信用交易要先收足保證金／自備款（預收款券）")
    return "；".join(parts) + "。"


# ------------------------------------------------------------------ 除權息
def exright_schedule() -> list[dict]:
    """交易所除權息預告（上市＋上櫃），存一份到 data/state/exrights.json 當備援"""
    p = config.STATE_DIR / "exrights.json"
    try:
        from . import sources
        rows = sources.fetch_exrights_raw()
        if rows:
            write_json(p, {"fetched": date.today().isoformat(), "rows": rows})
            return rows
    except Exception as e:  # noqa: BLE001
        log.warning("除權息預告抓取失敗：%s", e)
    return (read_json(p, {}) or {}).get("rows", [])


def exdiv_plans(today: date, last_day: date, holidays: set[date], quotes: dict) -> list[dict]:
    out = []
    for r in exright_schedule():
        code, ex = r["code"], date.fromisoformat(r["date"])
        if ex <= last_day:
            continue
        qs = quotes.get(code) or []
        if not qs or not qs[-1].get("close"):
            continue
        px = qs[-1]["close"]
        cash, stock = r.get("cash") or 0, r.get("stock") or 0      # 現金股利（元）、股票股利（元，面額 10）
        y = 1 - (px - cash) / (px * (1 + stock / 10)) if px else 0
        if y < 0.04 or avg_value(qs) < MIN_VAL:
            continue
        base = {"code": code, "name": r.get("name") or qs[-1].get("name"), "ex": ex.isoformat(), "yield": round(y, 4), "side": "long", "hedge": True}
        e10, x10 = trading_before(ex, 11, holidays), trading_before(ex, 1, holidays)
        out.append({**base, "strat": "除權息前10天買", "entry": e10.isoformat(), "entry_at": "收盤", "exit": x10.isoformat(), "exit_at": "收盤"})
        if y >= 0.06:
            out.append({**base, "strat": "除權息前一天買", "entry": x10.isoformat(), "entry_at": "收盤", "exit": ex.isoformat(), "exit_at": "開盤"})
    return [p for p in out if p["entry"] > last_day.isoformat()]          # 進場日已過（太晚才公告）就不做


# ------------------------------------------------------------------ 處置
def disposal_watch() -> dict:
    """site/data/disposal.json（處置工作每晚產生）：明天可能第二次處置的股票"""
    d = read_json(config.OUT_DIR / "disposal.json", {}) or {}
    rows = []
    for x in d.get("minus1", []) or []:
        if (x.get("times") or 0) < 2:
            continue
        cond = []
        c1 = x.get("c1") or {}
        for k, lab in (("up", "收盤 ≥"), ("down", "收盤 ≤")):
            v = c1.get(k) or {}
            if v.get("status") == "可能":
                cond.append(f"{lab} {v['price']}（{v['pct']:+.1f}%）")
        for v in x.get("c2") or []:
            if v.get("status") == "可能":
                cond.append(f"收盤 ≥ {v['price']}（{v['pct']:+.1f}%，{v['days']} 日漲幅條件）")
        rows.append({"code": x["code"], "name": x["name"], "close": x.get("close"), "cond": cond, "main": x.get("main")})
    return {"date": d.get("date"), "target": d.get("target"), "rows": rows}


def punish_today(today: date) -> list[dict]:
    p = read_json(config.STATE_DIR / "punish.json", []) or []
    return [x for x in p if x.get("announce") == today.isoformat() and (x.get("times") or 0) >= 2 and re.fullmatch(r"\d{4}", x.get("code", ""))]


def punish_codes(today: date) -> set[str]:
    p = read_json(config.STATE_DIR / "punish.json", []) or []
    return {x["code"] for x in p if x.get("start", "") <= today.isoformat() <= x.get("end", "")}


def one_limit_up(q: dict) -> bool:
    pc, c, lo = q.get("prev_close"), q.get("close"), q.get("low")
    if not pc or not c or not lo:
        return False
    from .util import limit_up
    lu = limit_up(pc)
    return c >= lu - 1e-9 and lo >= lu - 1e-9


# ------------------------------------------------------------------ 全額交割
ROC = r"(\d{2,3})[年/.](\d{1,2})[月/.](\d{1,2})"


def fulldel_news(since: date) -> list[dict]:
    """重大訊息裡「變更交易方法／全額交割」的公告（排除繼續、恢復、取消、澄清），抓生效日"""
    db = read_json(config.STATE_DIR / "material_db.json", {}) or {}
    out, seen = [], set()
    for k, v in db.items():
        if k.startswith("_") or (v.get("date") or "") < since.isoformat():
            continue
        sj = re.sub(r"\s+", "", v.get("subject") or "")
        if not re.search("變更交易方法|全額交割", sj) or re.search("繼續|仍|維持|取消|澄清|恢復", sj):
            continue
        code = v.get("code", "")
        if not re.fullmatch(r"\d{4}", code) or code in seen:
            continue
        txt = sj + re.sub(r"\s+", "", v.get("body") or "")
        m = re.search(r"自" + ROC + r"起", txt)
        eff = date(int(m.group(1)) + 1911, int(m.group(2)), int(m.group(3))) if m else None
        seen.add(code)
        out.append({"code": code, "name": v.get("name"), "date": v.get("date"), "eff": eff.isoformat() if eff else None, "subject": v.get("subject")})
    return out


def full_list_now() -> set[str]:
    """目前全額交割股（證交所 TWT85U 當天名單＋櫃買 OpenAPI）；抓不到就用上次的"""
    p = config.STATE_DIR / "fulldel_now.json"
    codes: set[str] = set()
    try:
        from .sources import get_json
        js = get_json("https://www.twse.com.tw/rwd/zh/fullDelivery/TWT85U?response=json") or {}
        for t in js.get("tables") or [js]:
            for r in t.get("data") or []:
                c = str(r[0]).strip() if r else ""
                if re.fullmatch(r"\d{4}", c):
                    codes.add(c)
        tp = get_json("https://www.tpex.org.tw/openapi/v1/tpex_cmode") or []
        for r in tp:
            c = str(r.get("SecuritiesCompanyCode") or r.get("Code") or "").strip()
            if re.fullmatch(r"\d{4}", c):
                codes.add(c)
    except Exception as e:  # noqa: BLE001
        log.warning("全額交割名單抓取失敗：%s", e)
    if codes:
        write_json(p, {"date": date.today().isoformat(), "codes": sorted(codes)})
        return codes
    return set((read_json(p, {}) or {}).get("codes", []))


# ------------------------------------------------------------------ 部位紀錄
def load_book() -> dict:
    b = read_json(BOOK, {}) or {}
    b.setdefault("open", [])
    b.setdefault("closed", [])
    b.setdefault("planned", [])
    return b


def save_book(b: dict) -> None:
    write_json(BOOK, b)


def key(p: dict) -> str:
    return f"{p['strat']}|{p['code']}|{p['entry']}"

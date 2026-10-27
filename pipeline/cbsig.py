"""可轉債訊號：把鄭詩翰在 FB 分享過的 CB 規則寫成程式，每天標出符合的 CB，並附上歷史回測結果。

規則定義只寫一次（detect），每日標記（本檔 run）和歷史回測（research/cb_signals.py）共用，
兩邊各自把資料整理成同樣的「每檔 CB 每天一筆特徵」再丟進 detect，確保回測的就是網站上標的。

每筆特徵（dict）：
  price      CB 價格（最後成交價；當天沒成交沿用前一天）
  hi60 lo60  CB 前 59 個交易日的最高／最低價（不含當天）
  lots v20   CB 當天成交張數、前 20 日平均張數
  chg        CB 當天漲跌（元）
  conv conv1 conv20   轉換價值：今天、前一天、20 個交易日前
  stock shi60 slo60 sma87 sret20   標的股價、前 59 日最高／最低、87 日均線、20 日漲跌
  cret20     CB 20 日漲跌
  remain     流通餘額比率（%）
  age        上市後第幾個交易日（1＝第一天）；age_days 上市後日曆天數
  put_end    最近一次賣回期間結束日（已過去才有意義）；d 當天日期
  yrs yrs1   距到期年數：今天、前一天
python -m pipeline.cbsig     用 data/cb_history 快照重算今天的標記
"""
from __future__ import annotations

import logging
import sys
from datetime import date

from . import config, store
from .util import write_json

log = logging.getLogger(__name__)
STATE = "cb_sig"
OUT = config.OUT_DIR / "cb_sig.json"
RECENT = 5          # 網站顯示最近幾個交易日內觸發的訊號

# key, 名稱, 類型（多／警）, 規則白話, 他的說法與出處
SIGNALS = [
    ("cbhigh", "CB 過高股未過高", "多", "CB 價格創 60 日新高（105~150 元），標的股價仍低於 60 日高點 3% 以上",
     "他最常用的訊號：CB 先創新高、股價還沒，後面多半會創高（2019 台燿、2021 界霖、2025 家登／中砂）"),
    ("convup", "站上轉換價", "多", "轉換價值由 100 以下站上 100，且 20 天前還在 95 以下",
     "站上轉換價是 CB 的關鍵價、波段起漲前哨，常伴隨事件跳空（2023）；他的 XQ 雷達有「突破轉換價策略」（2024）"),
    ("cbvol", "CB 爆量", "多", "CB 成交量 ≥ 前 20 日均量 5 倍且 ≥ 100 張，當天不跌，價格 ≤ 130",
     "「可轉債神奇量能潮」：CB 不能當沖、籌碼集中，成交量異常最有資訊；利空低檔爆量是買點（2021、2024）"),
    ("age1y", "上市滿一年", "多", "上市滿 365 天的第一個交易日，轉換價值 80~110（股價在轉換價附近）",
     "CB 上市一年後有異常報酬；滿一年後股價在轉換價附近動起來，才是公司派真行情（2025 毅嘉、耀登）"),
    ("afterput", "賣回日後", "多", "賣回期間結束後 10 天內，流通餘額 > 70%，轉換價值 85~115",
     "賣回日過了沒人轉換、股價離轉換價不遠，公司通常會做多表態，CB 價格也不貴（2023 雙鴻、2025）"),
    ("expiry", "快到期條件", "多", "剩餘年限剛跌破 1 年，流通餘額 > 50%，轉換價值 ≥ 75，股價站上 87 日均線",
     "剩餘 > 半年、轉換率 < 50%、轉換價值 > 75~80、技術面轉多，公司有動機拉過轉換價（2024）"),
    ("hold", "股崩 CB 撐", "多", "標的股 20 日跌 15% 以上，CB 20 日跌不到 3%",
     "崩盤時 CB 相對強勢、沒有破底，是他逆勢進場的關鍵訊號（2026/7 股災復盤）"),
    ("new6", "上市第 6 天", "警", "上市後第 6 個交易日（拆解日）",
     "他的 XQ 回測：上市第 6 天買、持有 20 天，68 次勝率 55.9%、平均只有 +0.48%，大盤下行時別碰（2026/7）"),
    ("cblow", "CB 先破底", "警", "CB 價格跌破 60 日低點且 < 105 元，標的股價仍高於 60 日低點 5% 以上",
     "CB 先破底、股價還沒＝有人先知道利空（2019 宜特、2022 定穎／桂盟）"),
    ("below100", "跌破面額", "警", "CB 價格跌破 98 元（60 日內第一次）",
     "連特定人都不要的「垃圾債」，他會逢高放空股票（2019 VHQ、2021）"),
]
SIG = {k: (n, kind) for k, n, kind, *_ in SIGNALS}

# 分組回測補充（research/cb_signals_horizon.py，2026/10；回答「這個訊號是短線還是長線、要配什麼條件」）
NOTES = {
    "cbhigh": "你的看法是短線（1~15 天）股票會漲。分組回測：之後 5／10 天股票只比大盤多 +0.3%／+0.2%，勝率 41%（所有發 CB 的股票是 42%），"
              "短線沒有看到優勢。股價離高點 3~10% 的那組 60 天 +1.2% 稍好；離高點超過 10% 反而 −3.9%。"
              "改成他大亞案例的「CB 創 10 日新高、股價沒有」也一樣沒有優勢。",
    "cbvol": "你的看法是長線、要在低檔才是發動訊號。分組回測結果相反：低檔爆量（CB ≤ 110 且股價在 60 日區間下 1/3），之後 60 天股票落後大盤 3.3~3.6%、"
             "CB 落後全部 CB 1~2%，當天漲或跌都一樣；高檔爆量（CB > 130）之後 60 天股票反而 +2.4%、CB +4.8%，比較像「強者恆強」。"
             "他說的「利空低檔爆量」可能還要加上「剛出利空」（財報、重訊）這個條件，目前程式還沒有。",
    "hold": "你的看法是可能隨時反彈，也可能之後 CB 跟跌。回測：CB 撐住的那組，之後 20 天 CB 再跌 5% 以上的機率 11%，比「CB 也跟著跌」那組的 15% 低，"
            "CB 確實比較抗跌；但股票並沒有比較會反彈（20 天內反彈超過大盤 5% 的機率 26% 對 29%），CB 之後 60 天還落後全部 CB 3.2%——"
            "撐住的 CB 價格偏貴、上漲空間小。只有大盤也一起崩（全市場 20 日平均跌 8% 以上）時，股票之後 60 天 +2.1%。",
    "new6": "他的原文（2026/7/16 社團）：用 XQ 找「剛上市六天的 CB」（約是 CBAS 可以開始拆解的時間），68 次勝率 55.88%、平均只有 +0.48%，"
            "提醒市場下行時別急著拆解剛上市的 CB，「拆解日買放一個月反而越放越低」。所以這是「沒有優勢、別急著進」，不是看空。"
            "回測：第 6 天買 CB 持有 20 天平均 +1.3%、勝率 51%，和他的結果接近；股票之後也沒有明顯落後，應當成中性看待。",
    "cblow": "週期看股票（他的做法是放空股票）。回測之後 5／20／60 天股票超額都在 ±0.4% 以內，20 天落後大盤 10% 以上的機率 10%（所有發 CB 的股票 12%），"
             "目前看不出預警效果。",
    "below100": "週期看股票 20~60 天。原規則 60 天落後大盤 1.7%，和所有發 CB 的股票（−0.7%）差不多。只有「跌破面額、但股價還在 60 日區間上半」那組（42 次）"
                "20 天落後 2.5%、落後 10% 以上的機率 20%（基準 12%），符合他說的「逢高放空」，但樣本太少。",
}


def detect(f: dict) -> list[str]:
    """一檔 CB 某一天的特徵 → 觸發的訊號 key"""
    out = []
    px, conv, st = f.get("price"), f.get("conv"), f.get("stock")
    if px and f.get("hi60") and 105 <= px <= 150 and px > f["hi60"] and st and f.get("shi60") and st < f["shi60"] * 0.97:
        out.append("cbhigh")
    if conv and f.get("conv1") is not None and f.get("conv20") is not None and f["conv1"] < 100 <= conv and f["conv20"] < 95:
        out.append("convup")
    if f.get("lots") and f.get("v20") and px and f["lots"] >= 100 and f["lots"] >= 5 * f["v20"] and (f.get("chg") or 0) >= 0 and px <= 130:
        out.append("cbvol")
    if f.get("age_days") is not None and f.get("age_days1") is not None and f["age_days1"] < 365 <= f["age_days"] and conv and 80 <= conv <= 110:
        out.append("age1y")
    pe, d = f.get("put_end"), f.get("d")
    if pe and d and 0 < (date.fromisoformat(d) - date.fromisoformat(pe)).days <= 10 and (f.get("remain") or 0) > 70 and conv and 85 <= conv <= 115:
        out.append("afterput")
    if f.get("yrs") is not None and f.get("yrs1") is not None and f["yrs1"] > 1 >= f["yrs"] and (f.get("remain") or 0) > 50 \
            and conv and conv >= 75 and st and f.get("sma87") and st > f["sma87"]:
        out.append("expiry")
    if f.get("sret20") is not None and f.get("cret20") is not None and f["sret20"] <= -0.15 and f["cret20"] > -0.03:
        out.append("hold")
    if f.get("age") == 6:
        out.append("new6")
    if px and f.get("lo60") and px < f["lo60"] and px < 105 and st and f.get("slo60") and st > f["slo60"] * 1.05:
        out.append("cblow")
    if px and px < 98 and f.get("lo60") and f["lo60"] >= 98:
        out.append("below100")
    return out


# ------------------------------------------------------------------ 每日標記

def _num(v):
    try:
        return None if v in ("", None) else float(v)
    except (TypeError, ValueError):
        return None


def features_daily(days: int = 120) -> dict[str, list[dict]]:
    """用 data/cb_history 快照（約 260 日）＋ data/history 股價，組出每檔 CB 最近 days 個交易日的特徵"""
    from . import archive, cb
    files = sorted(cb.HIST_DIR.glob("????-??-??.json"))
    if not files:
        return {}
    from .util import read_json
    snaps = [(p.stem, read_json(p)) for p in files]
    rows_now = {r["code"]: r for r in (read_json(cb.OUT) or {}).get("rows", [])}
    # 標的股價序列
    tdays = [d for d in store.trading_days()]
    stock_series: dict[str, dict[str, float]] = {}
    for d in tdays[-260:]:
        for c, q in store.load_day(d).items():
            if q.get("close"):
                stock_series.setdefault(c, {})[d.isoformat()] = q["close"]
    board_today = {r["code"]: r for r in archive.read("cbb", snaps[-1][0])}
    out: dict[str, list[dict]] = {}
    per: dict[str, list[tuple[str, dict]]] = {}
    for ds, js in snaps:
        fl = js["fields"]
        for code, vals in js["rows"].items():
            per.setdefault(code, []).append((ds, dict(zip(fl, vals))))
    for code, ser in per.items():
        meta = rows_now.get(code) or {}
        stock = meta.get("stock") or code[:4]
        sp = stock_series.get(stock, {})
        sdates = sorted(sp)
        listing = meta.get("listing_date")
        maturity = meta.get("maturity")
        b = board_today.get(code) or {}
        put_end = b.get("put_end") or None
        last_px, prices, lots_hist, convs, feats = None, [], [], [], []
        for i, (ds, r) in enumerate(ser):
            px = r.get("close") or last_px
            last_px = px
            prices.append(px)
            lots_hist.append(r.get("lots") or 0)
            convs.append(r.get("conv_value"))
            if i < len(ser) - days:
                continue
            si = [x for x in sdates if x <= ds]
            s_now = sp.get(si[-1]) if si else None
            s_win = [sp[x] for x in si[-60:-1]]
            s87 = [sp[x] for x in si[-87:]]
            prev = [p for p in prices[max(0, i - 59):i] if p]
            f = {"d": ds, "price": px, "hi60": max(prev) if len(prev) >= 40 else None, "lo60": min(prev) if len(prev) >= 40 else None,
                 "lots": lots_hist[i], "v20": (sum(lots_hist[max(0, i - 20):i]) / 20) if i >= 20 else None,
                 "chg": (px - prices[i - 1]) if px and i and prices[i - 1] else None,
                 "conv": convs[i], "conv1": convs[i - 1] if i else None, "conv20": convs[i - 20] if i >= 20 else None,
                 "stock": s_now, "shi60": max(s_win) if len(s_win) >= 40 else None, "slo60": min(s_win) if len(s_win) >= 40 else None,
                 "sma87": sum(s87) / len(s87) if len(s87) >= 87 else None,
                 "sret20": (s_now / sp[si[-21]] - 1) if s_now and len(si) >= 21 and sp.get(si[-21]) else None,
                 "cret20": (px / prices[i - 20] - 1) if px and i >= 20 and prices[i - 20] else None,
                 "remain": (meta.get("remain") if meta.get("remain") is not None else None),
                 "put_end": put_end, "age": None, "age_days": None, "age_days1": None, "yrs": None, "yrs1": None}
            if listing:
                ld = date.fromisoformat(listing)
                f["age_days"] = (date.fromisoformat(ds) - ld).days
                f["age_days1"] = (date.fromisoformat(ser[i - 1][0]) - ld).days if i else None
                f["age"] = sum(1 for x, _ in ser[: i + 1] if x >= listing) if ser[0][0] < listing else None
            if maturity:
                md = date.fromisoformat(maturity)
                f["yrs"] = (md - date.fromisoformat(ds)).days / 365.25
                f["yrs1"] = (md - date.fromisoformat(ser[i - 1][0])).days / 365.25 if i else None
            feats.append(f)
        out[code] = feats
    return out


def run() -> dict | None:
    feats = features_daily(days=RECENT + 2)
    if not feats:
        return None
    last = max(f[-1]["d"] for f in feats.values() if f)
    days = sorted({x["d"] for f in feats.values() for x in f})[-RECENT:]
    tags: dict[str, list[list[str]]] = {}
    for code, fl in feats.items():
        for f in fl:
            if f["d"] not in days:
                continue
            for k in detect(f):
                tags.setdefault(code, []).append([k, f["d"]])
    st = store.state(STATE, {}) or {}
    res = {"date": last, "days": days, "tags": tags, "signals": [
        {"key": k, "name": n, "kind": kind, "rule": rule, "source": src, "note": NOTES.get(k), **(st.get("stats", {}).get(k) or {})}
        for k, n, kind, rule, src in SIGNALS],
        "stats_range": st.get("range"), "stats_updated": st.get("updated"), "split": st.get("split")}
    write_json(OUT, res)
    log.info("CB 訊號 %s：%d 檔有標記", last, len(tags))
    return res


def save_stats(stats: dict, rng: list[str], split: str) -> None:
    from datetime import date as _d
    store.save_state(STATE, {"stats": stats, "range": rng, "split": split, "updated": _d.today().isoformat()})


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run()
    return 0


if __name__ == "__main__":
    sys.exit(main())

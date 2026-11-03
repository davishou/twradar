"""公開收購截止前放空：python -m research.tender_bt [btdata 的 out 資料夾]

資料：觀測站重大訊息（tools/backfill_bt.py material 掃出來的 out/material/*.csv），
從公告內文抓：被收購公司、收購價、收購期間（有延長就用最後的截止日）、是否全部收購（含下市／合併字樣）。
被收購公司名稱→代號：用行情資料裡當天有交易的股票，簡稱的字依序出現在全名裡就算符合。
策略：截止日前第 2 個交易日（最後能買來應賣的一天）收盤放空，隔天開盤／隔天收盤／截止日收盤／截止後 3 天回補。
濾網：放空當天收盤 ≥ 收購價 97%（代表套利買盤在撐）。
"""
from __future__ import annotations

import glob
import re
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from research import event_bt as eb

ROC = r"(?:民國)?\s*(\d{2,3})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"


def _d(y, m, d):
    try:
        return date(int(y) + 1911, int(m), int(d))
    except ValueError:
        return None


def parse(row) -> dict | None:
    body = re.sub(r"\s+", "", str(row["body"]))
    subj = re.sub(r"\s+", "", str(row["subject"]))
    txt = subj + body
    if "公開收購" not in txt[:600]:
        return None
    self_target = bool(re.search(r"公開收購本公司|收購本公司|本公司普通股之公開收購|接獲.{0,40}公開收購", subj)) and "本公司公開收購" not in subj
    tgt = re.search(r"被收購(?:有價證券之)?(?:公開發行)?公司(?:之)?名稱[:：]?(.+?)(?:\(|（|股份有限公司|，|。|\d\.)", body)
    if not tgt:
        tgt = re.search(r"公開收購(.{2,20}?)(?:股份有限公司|\(股\)公司)", subj)
    code_in = re.search(r"(?:上市|上櫃|股票)代號[:：]?(\d{4})", body)
    price = re.search(r"每股(?:普通股)?(?:為)?(?:現金)?(?:新(?:臺|台)幣)?\s*([\d,]+(?:\.\d+)?)\s*元", body)
    ends = []
    for pat in (r"(?:公開)?收購期間[^。]{0,40}?" + ROC + r"[^。]{0,40}?至" + ROC,
                r"(?:延長)[^。]{0,80}?至" + ROC):
        for m in re.finditer(pat, body):
            ends.append(_d(*m.groups()[-3:]))
    m = re.search(r"屆滿之日期[:：](\d{2,3})/(\d{1,2})/(\d{1,2})", body) or re.search(r"收購期間已?於" + ROC + r"屆滿", body)
    if m:
        ends.append(_d(*m.groups()[-3:]))
    ends = [e for e in ends if e]
    if not ends:
        return None
    full = bool(re.search(r"100%|百分之百|全部(?:已發行)?(?:普通)?股|下市|終止上市|終止櫃檯買賣|合併|股份轉換", body))
    return {"ann": row["date"], "row_code": row["code"], "self": self_target,
            "code_in": code_in.group(1) if code_in else None,
            "target": tgt.group(1).replace("臺", "台") if tgt else "",
            "price": float(price.group(1).replace(",", "")) if price else np.nan, "end": max(ends), "full": full,
            "subject": subj[:80]}


def match_codes(tg: pd.DataFrame, names: pd.DataFrame) -> pd.Series:
    out = []
    for r in tg.itertuples(index=False):
        cand = names[names["date"] == pd.Timestamp(r.ann)] if pd.Timestamp(r.ann) in set(names["date"]) else None
        if cand is None or cand.empty or not r.target:
            out.append(None)
            continue
        full = r.target
        best, bl = None, 0
        for c, nm in zip(cand["code"], cand["name"]):
            nm = str(nm).replace("臺", "台").replace("-KY", "").replace("*", "").strip()
            if not nm or nm[0] != full[0]:
                continue
            it = iter(full)
            if all(ch in it for ch in nm) and len(nm) > bl:
                best, bl = c, len(nm)
        out.append(best)
    return pd.Series(out, index=tg.index)


def main(argv):
    src = Path(argv[0]) if argv else Path("btdata")
    fs = sorted(glob.glob(str(src / "material_*.csv")) + glob.glob(str(src / "material" / "*.csv")))
    raw = pd.concat([pd.read_csv(f, dtype=str) for f in fs], ignore_index=True)
    recs = [p for p in (parse(r) for _, r in raw.iterrows()) if p]
    tg = pd.DataFrame(recs)
    print(f"公開收購相關公告 {len(raw[raw.subject.str.contains('公開收購', na=False)])} 則，解析出 {len(tg)} 則")
    from pipeline import backtest as bt
    q = bt.load_quotes()
    import gzip  # noqa: F401
    want = set(tg.loc[~tg["self"] & tg["code_in"].isna(), "ann"])
    names = pd.concat([pd.read_csv(f, usecols=["code", "name"], dtype=str).assign(date=pd.Timestamp(Path(f).name[:10]))
                       for f in sorted(glob.glob(str(bt.ARCHIVE / "quotes" / "*" / "*.csv.gz")))
                       if Path(f).name[:10] in want], ignore_index=True)
    names = names[names["code"].str.fullmatch(r"\d{4}")]
    tg["code"] = match_codes(tg, names)
    tg.loc[tg["self"], "code"] = tg.loc[tg["self"], "row_code"]
    tg.loc[tg["code_in"].notna(), "code"] = tg.loc[tg["code_in"].notna(), "code_in"]
    tg = tg.dropna(subset=["code", "end"]).sort_values(["code", "ann"])
    tg["annd"] = pd.to_datetime(tg["ann"])
    tg["grp"] = tg.groupby("code")["annd"].transform(lambda x: (x.diff().dt.days.fillna(0) > 150).cumsum())
    ev = tg.groupby(["code", "grp"]).agg(ann=("ann", "min"), target=("target", "first"), price=("price", lambda x: x.dropna().iloc[0] if x.notna().any() else np.nan),
                                          end=("end", "max"), full=("full", "max")).reset_index()
    M = eb.mats()
    days, C = M["adj"].index, M["close"]
    rows = []
    for r in ev.itertuples(index=False):
        e = pd.Timestamp(r.end)
        k = days.searchsorted(e, side="right") - 1          # 截止日（或之前最後交易日）
        if k < 3 or r.code not in C.columns:
            continue
        i = k - 2                                           # 截止日前第 2 個交易日
        px = C.iat[i, C.columns.get_loc(r.code)]
        if not np.isfinite(px):
            continue
        rows.append({"code": r.code, "target": r.target, "offer": r.price, "end": days[k].date(), "i": i, "k": k,
                     "px": px, "ratio": px / r.price if r.price == r.price and r.price > 0 else np.nan, "full": r.full})
    E = pd.DataFrame(rows)
    out = [f"可用事件 {len(E)} 筆（全部收購 {int(E.full.sum())}）；{E.end.min()}~{E.end.max()}"]
    print(out[0])
    E.to_csv(eb.pf.OUT / "tender_events.csv", index=False)

    def D(i):
        return days[min(i, len(days) - 1)]
    for flt, fn in ((lambda x: x, "全部"), (lambda x: x[x.full], "全部收購"), (lambda x: x[x.ratio >= 0.97], "收盤≥收購價97%"),
                    (lambda x: x[x.full & (x.ratio >= 0.97)], "全部收購且≥97%")):
        e1 = flt(E)
        for ex, d1f in (("隔天開盤", lambda i: (D(i + 1), "open")), ("隔天收盤", lambda i: (D(i + 1), "close")),
                        ("截止日收盤", lambda i: (D(i + 2), "close")), ("截止後3天", lambda i: (D(i + 5), "close"))):
            dd = [d1f(i) for i in e1.i]
            t = pd.DataFrame({"code": e1.code.to_numpy(), "d0": [D(i) for i in e1.i], "f0": "close",
                              "d1": [x[0] for x in dd], "f1": [x[1] for x in dd], "side": -1})
            r = eb.run(t, slots=None, slip=0.003, label=f"{fn} 截止前2日收盤空 → {ex}")
            out.append(eb.fmt(r))
            print(out[-1])
    (eb.pf.OUT / "tender_bt.txt").write_text("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

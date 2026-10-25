"""私募：從重大訊息偵測公司「自己辦私募」的公告，整理成一案一列。

一個私募案常見的流程（每一步都會發一則重大訊息）：
  董事會擬辦 → 股東會通過 → 董事會定價（含應募人）→ 收足股款 → （三年後補辦公開發行）
  中途可能「取消定價」「不繼續辦理」「股款未收足、另行擇期」。

抓的欄位（重大訊息的私募公告是固定格式 1.~18. 項）：
  2. 種類（普通股／轉換公司債／特別股）  3. 應募人與關係  4. 股數  11. 參考價  12. 實際私募價
  9. 獨立董事反對或保留意見
另外判斷應募人類型：內部人（董事長、總經理、董事、配偶、一親等…）／策略投資人（公司名稱、策略性投資人）／未定。
排除：金控、壽險「取得」別人的私募基金或私募債（那是投資，不是增資），代子公司辦私募另外標示。

不呼叫 AI、不抓網路，只讀 data/state/material_db.json（保留 45 天）與 data/history 收盤價。
python -m pipeline.private     產生 site/data/announce/private.json
"""
from __future__ import annotations

import logging
import re
import sys
from datetime import date

from . import config, store
from .util import parse_date, write_json

log = logging.getLogger(__name__)
OUT = config.OUT_DIR / "announce" / "private.json"
KEEP = "private_db"          # 私募案累積存檔（material_db 只留 45 天）

STAGES = [   # (階段, 判斷：subject 關鍵字)；由上往下第一個符合者
    ("取消", re.compile(r"取消|不繼續辦理|終止|撤銷|未於期限內收足|另行擇期|未收足")),
    ("收足股款", re.compile(r"收足股款|增資基準日")),
    ("定價", re.compile(r"定價|訂價|訂定價格|價格")),
    ("應募人", re.compile(r"應募人|認購協議")),
    ("董事會擬辦", re.compile(r"決議.{0,12}私募|以私募方式|辦理.{0,6}私募")),
    ("轉換/賣回", re.compile(r"轉換|賣回|贖回")),
    ("資金運用", re.compile(r"資金運用|資金用途")),
]
ORDER = {"董事會擬辦": 1, "應募人": 2, "定價": 3, "收足股款": 4, "取消": 5, "轉換/賣回": 6, "資金運用": 7}
INSIDER = re.compile(r"董事長|總經理|董事|監察人|經理人|配偶|親等|內部人|關係人|大股東")
SKIP_SUBJ = re.compile(r"取得.{0,40}(私募|PRIVATE|Fund|L\.?P\.?|基金)|處分|PRIVATELY", re.I)


def _item(body: str, n: int) -> str:
    """取第 n 項內容（到下一項編號為止）"""
    m = re.search(rf"(?:^|\n)\s*{n}\s*[\.．、]\s*(.*?)(?=\n\s*{n + 1}\s*[\.．、]|\Z)", body, re.S)
    if not m:
        return ""
    t = m.group(1).strip()
    head, sep, rest = t.partition(":") if ":" in t[:40] else t.partition("：")
    return (rest if sep and len(head) <= 40 else t).strip()


def _num(s: str) -> float | None:
    m = re.search(r"(\d[\d,]*(?:\.\d+)?)", s or "")
    return float(m.group(1).replace(",", "")) if m else None


def _price(s: str) -> float | None:
    if not s or re.search(r"不適用|尚未|俟|未定", s[:20]):
        return None
    m = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*元", s) or re.search(r"(\d[\d,]*\.\d+)", s)
    return float(m.group(1).replace(",", "")) if m else None


def _shares(s: str) -> tuple[float | None, bool]:
    """回傳（股數, 是否為上限）"""
    if not s:
        return None, False
    cap = bool(re.search(r"不超過|以內|為限|上限|額度", s))
    m = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*(仟股|千股|萬股|股|張)", s)
    if not m:
        return None, cap
    v = float(m.group(1).replace(",", ""))
    v *= {"仟股": 1000, "千股": 1000, "萬股": 10000, "張": 1000}.get(m.group(2), 1)
    return v, cap


def _kind(s: str, subj: str) -> str:
    t = (s or "") + subj
    if re.search(r"轉換公司債|可轉債|轉債", t):
        return "私募CB"
    if "特別股" in t:
        return "特別股"
    if "公司債" in t:
        return "公司債"
    return "普通股"


def _investor(s: str) -> tuple[str, list[str]]:
    if not s:
        return "未定", []
    if re.search(r"並無已洽定|尚未洽定|目前並無|尚無", s):
        return "未定", []
    names: list[str] = []
    s = re.split(r"前十名|前十大|主要股東", s)[0]          # 法人應募人的股東名單不算
    corp = r"[一-鿿]{2,20}(?:股份)?有限公司|[A-Za-z0-9][A-Za-z0-9 .,&\-]{2,60}?(?:Limited|Ltd\.?|Inc\.?|Corp\.?|LLC|Co\.|PTE|GmbH|B\.V\.|S\.A\.)"
    for line in s.splitlines():
        line = line.strip()
        m = re.match(rf"(?:[(（]?\d{{1,2}}[.、)）]\s*)?({corp}|[一-鿿]{{2,4}}(?=[，,\s(（]|持股|$))", line)
        if not m:
            continue
        nm = m.group(1).strip(" ,，")
        if re.search(r"應募|名稱|股東|對象|規定|特定人|本公司|私募|關係|法人|自然人|認購|股數|變動|適用|說明|如下|名單", nm) or nm in names:
            continue
        names.append(nm)
    kind = "內部人" if INSIDER.search(s) else ("策略投資人" if (names or re.search(r"策略性投資人|策略投資", s)) else "未定")
    if kind == "內部人" and names and all(re.search(r"有限公司|Limited|Ltd|Inc|Corp", n) for n in names) and \
            not re.search(r"董事長|總經理|配偶|親等|經理人", s):
        kind = "策略投資人"         # 只是法人董事代表兼任之類的關係，應募人是外部公司
    return kind, names[:6]


def parse(rec: dict) -> dict | None:
    subj, body = rec.get("subject", ""), (rec.get("body") or "").replace("\r", "")
    if "私募" not in subj and "私募" not in body[:400]:
        return None
    if SKIP_SUBJ.search(subj):
        return None
    stage = next((s for s, rx in STAGES if rx.search(subj)), None)
    if stage is None:
        if "私募" not in subj:
            return None
        stage = "其他"
    sub = bool(re.search(r"代子公司|代.{2,8}公告", subj))
    i3 = _item(body, 3)
    inv_kind, names = _investor(i3)
    shares, cap = _shares(_item(body, 4))
    ref, px = _price(_item(body, 11)), _price(_item(body, 12))
    if px is None:
        px = _price(re.search(r"(?:私募|發行|認購)價格[^\n]{0,8}?(?:訂為|定為|為)[^\n]{0,30}", body).group(0)) if re.search(r"(?:私募|發行|認購)價格[^\n]{0,8}?(?:訂為|定為|為)", body) else None
    if ref is None:
        m = re.search(r"參考價格[^\n]{0,20}?(\d[\d,]*(?:\.\d+)?)\s*元", body)
        ref = float(m.group(1).replace(",", "")) if m else None
    m9 = re.search(r"獨立董事反對或保留意見\s*[:：]\s*([^\n]{0,20})", body)
    oppose = bool(m9 and not re.match(r"\s*(無|否|不適用|未有|沒有|NA|N/A)", m9.group(1))) or "反對意見" in subj
    return {
        "date": rec["date"], "time": rec.get("time", ""), "code": rec["code"], "name": rec["name"],
        "market": rec.get("market", ""), "subject": subj, "stage": stage, "kind": _kind(_item(body, 2), subj),
        "sub": sub, "investor": inv_kind, "names": names, "shares": shares, "cap": cap,
        "ref": ref, "price": px, "disc": round(px / ref, 4) if px and ref and not sub else None,
        "amount": round(px * shares / 1e8, 2) if px and shares and not cap else None,   # 億元
        "oppose": oppose, "body": body[:6000],
    }


def collect() -> list[dict]:
    md = store.state("material_db", {}) or {}
    keep = store.state(KEEP, {}) or {}
    for k, v in md.items():
        if k.startswith("_") or not isinstance(v, dict):
            continue
        p = parse(v)
        if p:
            keep[k] = p
    store.save_state(KEEP, keep)
    return list(keep.values())


def cases(items: list[dict]) -> list[dict]:
    """同一家公司、相近時間的公告合成一案。用最新一則決定目前階段。"""
    out: list[dict] = []
    for it in sorted(items, key=lambda x: (x["code"], x["date"], x["time"])):
        cur = out[-1] if out and out[-1]["code"] == it["code"] and (parse_date(it["date"]) - parse_date(out[-1]["last"])).days <= 120 \
            and out[-1]["stage"] not in ("收足股款", "取消") else None
        if cur is None or it["stage"] in ("轉換/賣回", "資金運用"):
            cur = {"code": it["code"], "name": it["name"], "market": it["market"], "kind": it["kind"], "sub": it["sub"],
                   "first": it["date"], "events": []}
            out.append(cur)
        cur["events"].append({k: it[k] for k in ("date", "time", "stage", "subject", "body")})
        cur["last"], cur["stage"] = it["date"], it["stage"]
        for k in ("investor", "names", "shares", "cap", "ref", "price", "disc", "amount"):
            if it.get(k) not in (None, [], "未定") or k not in cur:
                cur[k] = it[k]
        if it["kind"] != "普通股":
            cur["kind"] = it["kind"]
        cur["oppose"] = cur.get("oppose", False) or it["oppose"]
        if it["stage"] == "定價":
            cur["priced"] = it["date"]
    return out


def enrich(cs: list[dict]) -> None:
    ds = store.trading_days()
    if not ds:
        return
    last = store.load_day(ds[-1])
    for c in cs:
        q = last.get(c["code"]) or {}
        c["close"] = q.get("close")
        if c.get("price") and c["close"] and not c["sub"]:
            c["vs_price"] = round(c["close"] / c["price"] - 1, 4)     # 現價比私募價高多少
        d0 = parse_date(c["first"])
        before = [d for d in ds if d < d0]
        if before and c["close"]:
            q0 = store.load_day(before[-1]).get(c["code"]) or {}
            if q0.get("close"):
                c["ret"] = round(c["close"] / q0["close"] - 1, 4)     # 第一則公告前一日收盤至今
                c["mkt"] = round(store.market_avg_change(before[-1], ds[-1]) / 100, 4)


def run() -> int:
    cs = cases(collect())
    enrich(cs)
    cs.sort(key=lambda c: (c["last"], ORDER.get(c["stage"], 9)), reverse=True)
    ds = store.trading_days()
    for c in cs:
        c["key"] = f'{c["code"]}-{c["first"]}-{c["events"][0]["time"]}'
        c["date"], c["time"] = c["last"], c["events"][-1]["time"]
        c["subject"], c["body"] = c["events"][-1]["subject"], c["events"][-1]["body"]
    write_json(OUT, {"updated": ds[-1].isoformat() if ds else date.today().isoformat(), "items": cs})
    return len(cs)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log.info("私募：%d 案", run())
    return 0


if __name__ == "__main__":
    sys.exit(main())

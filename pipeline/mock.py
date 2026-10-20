"""模擬資料源：與 sources.py 介面相同，產生虛構但結構逼真的市場資料。
用途：離線測試、在沒有網路或非交易時段預覽網站。所有公司名稱皆為虛構。"""
from __future__ import annotations

import random
from datetime import date, timedelta

from .sources import INDUSTRY
from .util import limit_down, limit_up, price_down_to_tick

_A = list("華台聯宏大新永光達鴻興泰國金元信嘉晶旺豐昇凱群志德亞立創益鼎")
_B = list("科電通精材光訊能技揚碩盛微控源工昌寶威通宇德達")
THEMES = ["低軌衛星", "CPO矽光子", "軟板FPC", "PCB設備", "AI伺服器", "散熱", "機器人", "重電",
          "生技新藥", "記憶體", "軟體", "鋼鐵", "電腦週邊", "被動元件", "營建資產", "航運"]


class MockSource:
    def __init__(self, end: date | None = None, days: int = 130, n_stocks: int = 420, seed: int = 42):
        rnd = random.Random(seed)
        self.rnd = rnd
        end = end or date.today()
        while end.weekday() >= 5:
            end -= timedelta(days=1)
        ds, d = [], end
        while len(ds) < days:
            if d.weekday() < 5:
                ds.append(d)
            d -= timedelta(days=1)
        self.days = ds[::-1]
        codes = rnd.sample(range(1101, 9960), n_stocks)
        self.stocks = []
        names = set()
        for i, c in enumerate(sorted(codes)):
            while True:
                nm = rnd.choice(_A) + rnd.choice(_B) + (rnd.choice(_B) if rnd.random() < .3 else "")
                if nm not in names:
                    names.add(nm)
                    break
            ind = rnd.choice(list(INDUSTRY)[:36])
            p0 = round(rnd.choice([rnd.uniform(8, 50), rnd.uniform(20, 150), rnd.uniform(80, 900)]), 1)
            self.stocks.append({
                "code": str(c), "name": nm, "market": "TWSE" if i % 2 == 0 else "TPEX",
                "industry_code": ind, "industry": INDUSTRY[ind], "theme": THEMES[i % len(THEMES)],
                "capital": rnd.choice([3e8, 8e8, 1.5e9, 4e9, 1e10]), "p0": p0,
                "eps": round(rnd.uniform(-2, 12), 2), "bvps": round(rnd.uniform(8, 80), 1),
            })
        for s in self.stocks:
            s["shares"] = s["capital"] / 10
        self._simulate()

    # ------------------------------------------------------------ 模擬行情
    def _simulate(self):
        rnd = self.rnd
        self.quotes: dict[date, list[dict]] = {}
        price = {s["code"]: s["p0"] for s in self.stocks}
        heat = {t: 0.0 for t in THEMES}
        for d in self.days:
            for t in THEMES:  # 族群熱度：隨機遊走 + 偶發爆發
                heat[t] = heat[t] * 0.7 + rnd.gauss(0, 0.012) + (0.06 if rnd.random() < 0.04 else 0)
            mkt = rnd.gauss(0.0005, 0.008)
            rows = []
            for s in self.stocks:
                pc = price[s["code"]]
                r = mkt + heat[s["theme"]] * rnd.uniform(.5, 1.3) + rnd.gauss(0, 0.02) + (0.075 if rnd.random() < 0.035 else 0)
                up, dn = limit_up(pc), limit_down(pc)
                close = min(max(price_down_to_tick(pc * (1 + r)), dn), up)
                if close >= up * 0.985 and rnd.random() < 0.5:
                    close = up
                o = min(max(price_down_to_tick(pc * (1 + r * rnd.uniform(0, 0.8))), dn), up)
                hi = max(o, close, min(up, price_down_to_tick(max(o, close) * (1 + abs(rnd.gauss(0, .01))))))
                lo = min(o, close, max(dn, price_down_to_tick(min(o, close) * (1 - abs(rnd.gauss(0, .01))))))
                vol = int(s["shares"] * rnd.uniform(0.002, 0.012) * (1 + abs(r) * 25)) // 1000 * 1000 + 1000
                avg = round((o + hi + lo + close) / 4, 2)
                rows.append({"code": s["code"], "name": s["name"], "market": s["market"], "open": o, "high": hi,
                             "low": lo, "close": close, "change": round(close - pc, 2), "prev_close": pc,
                             "volume": vol, "value": int(vol * avg), "trades": vol // 3000 + 1, "avg": avg})
                price[s["code"]] = close
            self.quotes[d] = rows

    def theme_of(self, code: str) -> str:
        if not hasattr(self, "_tm"):
            self._tm = {s["code"]: s["theme"] for s in self.stocks}
        return self._tm.get(code, "其他")

    # ------------------------------------------------------------ 介面（與 sources 相同）
    def fetch_quotes(self, d: date | None = None):
        d = d or self.days[-1]
        return (d, self.quotes[d]) if d in self.quotes else (None, [])

    def fetch_institutional(self, d: date):
        import random
        rnd = random.Random(f"inst-{d}")
        out = {}
        for q in self.quotes.get(d, []):
            lots = max(q["volume"] // 1000, 1)
            out[q["code"]] = {"f": rnd.randint(-lots // 6, lots // 4), "t": rnd.choice([0, 0, rnd.randint(-lots // 20, lots // 10)]),
                              "d": rnd.randint(-lots // 30, lots // 20)}
        return out

    def fetch_holidays(self):
        return set()

    def fetch_margin(self, d: date):
        """融資融券：少數股票券資比在最近幾天放大"""
        out = {}
        for s in self.stocks:
            rnd = random.Random(f"m{s['code']}")
            hot = rnd.random() < 0.15
            lim = s["shares"] / 1000 * 0.25
            fin = lim * rnd.uniform(0.1, 0.5)
            r = rnd.uniform(0.02, 0.06)
            if hot:
                k = (d.toordinal() % 7) / 6
                r = r * (1 + 5 * k)
            out[s["code"]] = [round(fin), round(lim), round(fin * r), round(lim * 0.4)]
        return out

    def fetch_companies(self):
        return {s["code"]: {k: s[k] for k in ("code", "name", "market", "industry_code", "industry", "capital", "shares")}
                for s in self.stocks}

    def fetch_valuation(self):
        last = {q["code"]: q["close"] for q in self.quotes[self.days[-1]]}
        return {s["code"]: {"pe": round(last[s["code"]] / s["eps"], 2) if s["eps"] > 0 else None,
                            "pb": round(last[s["code"]] / s["bvps"], 2), "dy": 2.0} for s in self.stocks}

    def _closes(self, code, i, n):
        if not hasattr(self, "_cm"):
            self._cm = [{q["code"]: q["close"] for q in self.quotes[d]} for d in self.days]
        return [self._cm[j][code] for j in range(i - n, i + 1)]

    def fetch_notices(self, start: date, end: date):
        """以第一款（6 日漲跌）與隨機第六款產生注意股"""
        if not hasattr(self, "_all_notices"):
            self._all_notices = self._gen_notices()
        return [n for n in self._all_notices if start.isoformat() <= n["date"] <= end.isoformat()]

    def _gen_notices(self):
        out = []
        idx = None
        for i, d in enumerate(self.days):
            if i < 7:
                continue
            rnd = random.Random(f"n{d}")
            for s in self.stocks:
                cs = self._closes(s["code"], i, 6)
                chg = cs[-1] / cs[0] - 1
                th = 0.32 if s["market"] == "TWSE" else 0.30
                cl = []
                if abs(chg) > th:
                    cl.append(1)
                if rnd.random() < 0.006:
                    cl.append(6)
                if cl:
                    out.append({"date": d.isoformat(), "code": s["code"], "name": s["name"], "market": s["market"],
                                "clauses": cl, "text": "、".join(f"第{c}款" for c in cl)})
        _ = idx
        return out

    def fetch_punish(self, start: date, end: date):
        from collections import defaultdict
        notes = self.fetch_notices(self.days[0], self.days[-1])
        by = defaultdict(list)
        for n in notes:
            by[n["code"]].append(date.fromisoformat(n["date"]))
        out = []
        for code, ds in by.items():
            ds = sorted(set(ds))
            for k in range(2, len(ds)):
                a, b, c = ds[k - 2:k + 1]
                if self.days.index(c) - self.days.index(a) == 2:
                    i = self.days.index(c)
                    if i + 1 >= len(self.days) - 8 and i + 1 < len(self.days):
                        s0 = self.days[i + 1]
                        e0 = self.days[min(i + 5, len(self.days) - 1)] if i + 5 < len(self.days) else s0 + timedelta(days=6)
                        st = next(x for x in self.stocks if x["code"] == code)
                        out.append({"code": code, "name": st["name"], "market": st["market"], "announce": c.isoformat(),
                                    "start": s0.isoformat(), "end": e0.isoformat(), "minutes": 5,
                                    "reason": "連續3日第一款", "times": 1})
                        break
        return out

    def fetch_material(self):
        d = self.days[-1]
        rnd = random.Random(f"m{d}")
        out = []
        pick = rnd.sample(self.stocks, 40)
        m = (d.month - 2) % 12 + 1
        roc = lambda x: f"{x.year - 1911}/{x.month:02d}/{x.day:02d}"  # noqa: E731
        for i, s in enumerate(pick):
            t = f"{rnd.randint(13, 21):02d}:{rnd.randint(0, 59):02d}"
            base = {"date": d.isoformat(), "time": t, "code": s["code"], "name": s["name"], "market": s["market"], "clause": ""}
            q_eps = round(s["eps"] / 4 * rnd.uniform(0.6, 1.4), 2)
            if i < 8:
                eps = round(q_eps / 3 * rnd.uniform(0.4, 2.2), 2)
                out.append({**base, "subject": "本公司有價證券於集中交易市場達公布注意交易資訊標準 故公布相關財務業務等重大訊息",
                            "body": f"3.財務業務資訊:\n     科目       115年 {m}月    同期增減   115年第2季   同期增減   最近四季\n"
                                    f"營業收入(百萬)   {rnd.randint(80, 900)}   {rnd.uniform(-30, 80):.2f}   {rnd.randint(300, 2500)}   12.3   4,000\n"
                                    f"每股(虧損)盈餘(元)  {eps}   {rnd.uniform(-50, 120):.2f}   {q_eps}   15.2   {round(s['eps'], 2)}\n"})
            elif i < 11:
                lo = round(s["p0"] * 0.9, 1)
                out.append({**base, "subject": "公告本公司董事會決議買回庫藏股事宜",
                            "body": f"1.董事會決議日期:{roc(d)}\n2.買回股份目的:{rnd.choice(['轉讓股份予員工', '維護公司信用及股東權益', '註銷股份'])}\n"
                                    f"5.預定買回之期間:{roc(d + timedelta(days=1))}~{roc(d + timedelta(days=60))}\n"
                                    f"6.預定買回之數量(股):{rnd.randint(5, 30) * 100000:,}\n7.買回區間價格(元):{lo}~{round(lo * 1.6, 1)}"})
            elif i < 15:
                cum = round(q_eps * 3, 2)
                out.append({**base, "subject": "公告本公司115年第3季合併財務報告業經董事會決議通過",
                            "body": f"3.財務報告或年度自結財務資訊報導期間\n起訖日期(XXX/XX/XX~XXX/XX/XX):115/01/01~115/09/30\n"
                                    f"4.1月1日累計至本期止營業收入(仟元):{rnd.randint(500000, 9000000):,}\n"
                                    f"5.1月1日累計至本期止營業毛利(毛損) (仟元):{rnd.randint(100000, 900000):,}\n"
                                    f"6.1月1日累計至本期止營業利益(損失) (仟元):{rnd.randint(50000, 500000):,}\n"
                                    f"7.1月1日累計至本期止稅前淨利(淨損) (仟元):{rnd.randint(60000, 600000):,}\n"
                                    f"10.1月1日累計至本期止基本每股盈餘(損失) (元):{cum}"})
            elif i < 22:
                ev = d + timedelta(days=rnd.randint(1, 15))
                kind = rnd.choice(["法", "財", "息"])
                subj, body = {"法": ("本公司受邀參加法人說明會", f"1.召開法人說明會之日期：{roc(ev)}"),
                              "財": ("115年第3季財務報告董事會預計召開日期", f"2.董事會預計召開日期:{roc(ev)}"),
                              "息": ("公告本公司訂定除息基準日", f"2.除權、息類別（請填入「除權」、「除息」或「除權息」）:除息\n4.除權（息）交易日:{roc(ev)}")}[kind]
                out.append({**base, "subject": subj, "body": body})
            else:
                subj = rnd.choice(["公告本公司董事會決議發行國內第一次無擔保轉換公司債", "澄清媒體報導", "公告本公司取得機器設備",
                                   "代子公司公告取得使用權資產", "公告本公司董事會通過合併案", "公告本公司重要人事異動"])
                out.append({**base, "subject": subj, "body": f"說明：{subj}，詳見公開資訊觀測站。"})
        return out

    def fetch_revenue(self):
        d = self.days[-1]
        rnd = random.Random(f"r{d}")
        ym = f"{d.year - 1911}{((d.month - 2) % 12) + 1:02d}"
        out = []
        for s in rnd.sample(self.stocks, 70):
            rev = rnd.randint(50_000, 9_000_000)
            prev, ly = int(rev / rnd.uniform(0.7, 1.4)), int(rev / rnd.uniform(0.6, 1.6))
            out.append({"ym": ym, "code": s["code"], "name": s["name"], "market": s["market"], "industry": s["industry"],
                        "rev": rev, "rev_prev": prev, "rev_ly": ly, "mom": round((rev / prev - 1) * 100, 2),
                        "yoy": round((rev / ly - 1) * 100, 2), "cum": rev * 8, "cum_yoy": round(rnd.uniform(-30, 60), 2),
                        "note": rnd.choice(["", "", "", "新產品出貨增加", "客戶拉貨遞延", "匯率影響"])})
        return out

    def fetch_eps(self):
        d = self.days[-1]
        rnd = random.Random(f"e{d}")
        out = []
        y = d.year - 1911
        for s in self.stocks:
            for q, f in ((1, 1.0), (2, 1.0)):
                out.append({"year": y, "quarter": q, "code": s["code"], "name": s["name"], "market": s["market"],
                            "industry": s["industry"], "eps": round(s["eps"] / 4 * rnd.uniform(.7, 1.3) * f, 2),
                            "revenue": 1e6, "op_income": 1e5, "net_income": 8e4})
        for s in rnd.sample(self.stocks, 12):
            out.append({"year": y, "quarter": 3, "code": s["code"], "name": s["name"], "market": s["market"],
                        "industry": s["industry"], "eps": round(s["eps"] / 4 * rnd.uniform(.3, 2.2), 2),
                        "revenue": 1e6, "op_income": 1e5, "net_income": 8e4})
        return out

    def fetch_borrow_fee(self, d: date):
        rnd = random.Random(f"b{d}")
        out = []
        for s in rnd.sample(self.stocks, 25):
            for _ in range(rnd.randint(1, 4)):
                out.append({"date": d.isoformat(), "code": s["code"], "name": s["name"], "market": s["market"],
                            "lots": rnd.randint(1, 120), "rate": round(rnd.choice([0.05, 0.1, 0.3, 0.8, 1.5, 3.5, 7.0]) * rnd.uniform(.8, 1.2), 2)})
        return out

    def etf_holdings(self, etf: str, d: date):
        """回傳 [{code,name,shares,weight}]，每天隨機加減碼"""
        base = random.Random(etf)
        held = base.sample(self.stocks, 35)
        rnd = random.Random(f"{etf}{d}")
        out = []
        for s in held:
            sh = base.randint(50, 3000) * 1000 + rnd.choice([0, 0, 0, 1, -1]) * rnd.randint(1, 200) * 1000
            if sh > 0:
                out.append({"code": s["code"], "name": s["name"], "shares": sh})
        tot = sum(x["shares"] for x in out)
        for x in out:
            x["weight"] = round(x["shares"] / tot * 100, 2)
        return out

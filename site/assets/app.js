/* 盤後雷達前端：讀取 data/*.json，hash 路由單頁應用，無框架。 */
(() => {
"use strict";
const app = document.getElementById("app");
const cache = new Map();
let META = {};

// ---------------- utils ----------------
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
async function load(path) {
  if (cache.has(path)) return cache.get(path);
  try {
    const r = await fetch("data/" + path, {cache: "no-cache"});
    const js = r.ok ? await r.json() : null;
    cache.set(path, js);
    return js;
  } catch { return null; }
}
const fx = (n, d = 2) => n == null || isNaN(n) ? "—" : Number(n).toLocaleString("zh-TW", {minimumFractionDigits: d, maximumFractionDigits: d});
const fp = n => n == null || isNaN(n) ? "—" : fx(n, n < 50 ? 2 : n < 500 ? 1 : n < 1000 ? 1 : 0);
const fi = n => n == null || isNaN(n) ? "—" : Math.round(n).toLocaleString("zh-TW");
const sign = n => n == null ? "" : n > 0 ? "up" : n < 0 ? "down" : "";
const pc = (n, d = 2) => n == null ? '<span class="muted">—</span>' : `<span class="${sign(n)}">${n > 0 ? "+" : ""}${fx(n, d)}%</span>`;
const yi = n => n == null ? "—" : Math.abs(n) >= 1e8 ? fx(n / 1e8, 2) + " 億" : fx(n / 1e4, 0) + " 萬";
const mk = m => `<span class="mk" title="${m === "TWSE" ? "上市" : "上櫃"}">${m === "TWSE" ? "市" : "櫃"}</span>`;
const stockLink = (code, name) => `<a href="#/stock/${esc(code)}">${esc(name || code)}</a>`;
const md = s => s ? s.slice(5).replace("-", "/") : "";
function toast(msg) { const t = document.getElementById("toast"); t.textContent = msg; t.classList.add("show"); setTimeout(() => t.classList.remove("show"), 1600); }
async function copy(text) {
  try { await navigator.clipboard.writeText(text); toast("已複製"); }
  catch { const ta = document.createElement("textarea"); ta.value = text; document.body.append(ta); ta.select(); document.execCommand("copy"); ta.remove(); toast("已複製"); }
}
function setTitle(t) { document.title = (t ? t + "｜" : "") + (META.site_name || "盤後雷達"); }
const emptyBox = msg => `<div class="tw"><div class="empty">${esc(msg)}</div></div>`;

/* 通用表格：columns [{k,t,n,f,s,w}]，opts {sort:[k,dir], expand(row)->html, rowClick, empty} */
function table(el, columns, rows, opts = {}) {
  let [sk, sd] = opts.sort || [null, 1];
  let open = new Set();
  const val = (c, r) => c.s ? c.s(r) : r[c.k];
  function draw() {
    const data = rows.slice();
    if (sk) {
      const c = columns.find(c => c.k === sk);
      data.sort((a, b) => {
        const x = val(c, a), y = val(c, b);
        if (x == null) return 1; if (y == null) return -1;
        return (x > y ? 1 : x < y ? -1 : 0) * sd;
      });
    }
    if (!data.length) { el.innerHTML = emptyBox(opts.empty || "沒有資料"); return; }
    const head = columns.map(c => `<th class="${c.n ? "n" : ""} ${c.k && c.sortable !== false ? "s" : ""}" data-k="${c.k || ""}" scope="col"${c.k && c.sortable !== false ? ' tabindex="0"' : ""}>${c.t}${sk === c.k ? `<span class="ar">${sd > 0 ? "▲" : "▼"}</span>` : ""}</th>`).join("");
    const body = data.map((r, i) => {
      const id = opts.id ? opts.id(r) : i;
      const tr = `<tr class="${opts.expand || opts.rowClick ? "click" : ""} ${opts.rowClass ? opts.rowClass(r) : ""}" data-i="${esc(id)}"${opts.expand ? ` aria-expanded="${open.has(String(id))}"` : ""}>${columns.map(c =>
        `<td class="${c.n ? "n" : ""} ${c.w ? "wrap" : ""}">${c.f ? c.f(r) : esc(r[c.k] ?? "—")}</td>`).join("")}</tr>`;
      const ex = opts.expand && open.has(String(id)) ? `<tr class="detail"><td colspan="${columns.length}">${opts.expand(r)}</td></tr>` : "";
      return tr + ex;
    }).join("");
    el.innerHTML = `<div class="tw"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
    el._rows = new Map(data.map((r, i) => [String(opts.id ? opts.id(r) : i), r]));
  }
  el.onclick = e => {
    if (e.target.closest("a") || e.target.closest(".tipbtn")) return;
    const th = e.target.closest("th.s");
    if (th) { const k = th.dataset.k; sd = sk === k ? -sd : (columns.find(c => c.k === k).n ? -1 : 1); sk = k; draw(); return; }
    const tr = e.target.closest("tr[data-i]");
    if (!tr) return;
    const r = el._rows.get(tr.dataset.i);
    if (opts.expand) { const id = tr.dataset.i; open.has(id) ? open.delete(id) : open.add(id); draw(); }
    else if (opts.rowClick) opts.rowClick(r);
  };
  el.onkeydown = e => { if ((e.key === "Enter" || e.key === " ") && e.target.matches("th.s")) { e.preventDefault(); e.target.click(); } };
  draw();
  return { set(newRows) { rows = newRows; draw(); } };
}

function chips(el, items, current, onPick) {
  el.innerHTML = items.map(([v, label]) => `<button type="button" class="chip ${v === current ? "on" : ""}" data-v="${esc(v)}" aria-pressed="${v === current}">${esc(label)}</button>`).join("");
  el.onclick = e => { const b = e.target.closest(".chip"); if (!b) return; chips(el, items, b.dataset.v, onPick); onPick(b.dataset.v); };
}

function dateSelect(dates, cur, onChange) {
  const s = document.createElement("select");
  s.setAttribute("aria-label", "選擇日期");
  s.innerHTML = dates.map(d => `<option value="${d}" ${d === cur ? "selected" : ""}>${d}</option>`).join("");
  s.onchange = () => onChange(s.value);
  return s;
}

// ---------------- pages ----------------
const P = {};

P.home = async () => {
  setTitle("");
  const d = META.daily_dates?.[0];
  const [daily, com, line, nd] = await Promise.all([d ? load(`daily/${d}.json`) : null, d ? load(`commentary/${d}.json`) : null, load("line.json"), META.nextday_dates?.[0] ? load(`nextday/${META.nextday_dates[0]}.json`) : null]);
  if (!daily) { app.innerHTML = `<h1>還沒有資料</h1><p class="sub">執行 <code>python -m pipeline.run backfill 120</code> 與 <code>python -m pipeline.run all</code> 產生資料，或用 <code>python -m pipeline.run mock</code> 先看示範。</p>`; return; }
  const maxStreak = Math.max(...daily.groups.map(g => g.streak), 1);
  const heat = daily.groups.map(g => {
    const L = 64 - Math.round((g.streak - 1) / Math.max(maxStreak - 1, 1) * 26);
    return `<a href="#/daily/${daily.date}?t=${encodeURIComponent(g.theme)}" style="flex:${g.count} 1 0;background:hsl(2 62% ${L}%)" title="${esc(g.theme)}：${g.count} 檔，連續 ${g.streak} 天">
      ${g.streak > 1 ? `<span class="s">連 ${g.streak} 天</span>` : ""}<span class="n">${g.count}</span><span class="t">${esc(g.emoji)} ${esc(g.theme)}</span></a>`;
  }).join("");
  const j = META.jobs || {};
  app.innerHTML = `
  <section class="hero">
    <div>
      <div class="date">${daily.date} 收盤</div>
      <div class="big">漲停 ${daily.count}<small>檔，${daily.n_groups} 個族群</small></div>
      <div class="split"><span>上市 <b>${daily.twse}</b></span><span>上櫃 <b>${daily.tpex}</b></span><span>前四大族群占 <b>${daily.top4_share}%</b></span>${nd ? `<span>昨日漲停今收勝率 <b>${fx(nd.summary.close_win, 1)}%</b></span>` : ""}</div>
    </div>
    <div class="sched"><dl>
      <dt>漲停／氣氛</dt><dd>每日 17:05${j.daily ? `，上次 ${md(j.daily.slice(0,10))} ${j.daily.slice(11)}` : ""}</dd>
      <dt>處置預測</dt><dd>每日 19:30</dd><dt>券差</dt><dd>每日 20:08</dd><dt>主動 ETF</dt><dd>每日 22:30</dd>
      <dt>公告偵測</dt><dd>每 5 分鐘${j.announce ? `，上次 ${j.announce.slice(11)}` : ""}</dd></dl></div>
  </section>
  <div class="heat" role="list" aria-label="今日漲停族群">${heat}</div>
  <div class="heat-legend">寬度代表漲停檔數，顏色越深代表族群連續出現漲停的天數越長。點族群看個股。</div>
  <div class="cols" style="margin-top:26px">
    <section class="panel prose">
      <h2>今日盤面主軸</h2>
      <p>${esc(com?.text || "尚未產生評論。")}</p>
      <p class="small muted">${com?.source === "ai" ? "AI 依當日資料自動生成" : "依當日資料以規則生成"}${com ? `，${esc(com.generated)}` : ""}。<a href="#/commentary">所有氣氛評論</a></p>
    </section>
    <section class="panel">
      <div class="row" style="justify-content:space-between"><h2 style="margin:0">盤前 LINE 轉貼版</h2><button class="btn" id="cpLine" type="button">複製文字</button></div>
      <pre class="copy">${esc(line?.text || "尚未產生")}</pre>
    </section>
  </div>
  <h2>從哪裡開始看</h2>
  <div class="links">
    <a href="#/daily"><b>當日漲停族群</b><span>每檔歸到哪個題材、均量比、連板數</span></a>
    <a href="#/nextday"><b>漲停隔日表現</b><span>昨天漲停的股票今天開盤、均價、收盤賺多少</span></a>
    <a href="#/disposal"><b>處置預測</b><span>還差幾次會被處置、明天的觸發價</span></a>
    <a href="#/att"><b>公告速報</b><span>自結、季報、營收、庫藏股，標出盤後才公告、還沒交易過的</span></a>
    <a href="#/borrow"><b>券差借券費率</b><span>當沖券差的借券日費率，看券源稀缺程度</span></a>
    <a href="#/etf"><b>主動 ETF 持股異動</b><span>經理人加碼、減碼了哪些股票</span></a>
  </div>`;
  document.getElementById("cpLine").onclick = () => copy(line?.text || "");
};

P.daily = async (date) => {
  const dates = META.daily_dates || [];
  date = date || dates[0];
  const data = date && await load(`daily/${date}.json`);
  setTitle(`${date || ""} 漲停當日`);
  if (!data) { app.innerHTML = `<h1>當日漲停</h1>${emptyBox("沒有這天的資料")}`; return; }
  const q = new URLSearchParams(location.hash.split("?")[1] || "");
  let theme = q.get("t") || "", market = "", sel = q.get("s") || "";
  app.innerHTML = `<h1>當日漲停</h1>
    <p class="sub">${data.date} 共 ${data.count} 檔漲停（上市 ${data.twse}、上櫃 ${data.tpex}），${data.n_groups} 個族群；全市場上漲 ${data.market_up} 家、下跌 ${data.market_down} 家。點個股看法人與券商分點。</p>
    <div class="toolbar"><span id="ds"></span><span class="chips" id="mk"></span></div>
    <div class="chips" id="th" style="margin-bottom:12px"></div>
    <div id="tbl"></div>
    <p class="small muted">族群來源：<span class="tsrc">設定</span> themes.json 指定、<span class="tsrc ai">AI</span> AI 判斷後寫回 themes.json、<span class="tsrc">關鍵字</span>、<span class="tsrc">產業別</span> 官方產業別。法人單位為張；均量比＝漲停日成交量 ÷ 前 5 日均量（1x 以下＝安靜漲停，10x 以上＝爆量漲停）。</p>
    <section class="bk" id="bk" hidden></section>`;
  document.getElementById("ds").append(dateSelect(dates, date, v => location.hash = `#/daily/${v}`));
  const instCell = k => r => r.inst ? `<span class="${sign(r.inst[k])}">${r.inst[k] > 0 ? "+" : ""}${fi(r.inst[k])}</span>` : '<span class="muted">—</span>';
  const srcTag = {manual: ["設定", ""], ai: ["AI", "ai"], keyword: ["關鍵字", ""], industry: ["產業別", ""]};
  const cols = [
    {k: "market", t: "所", f: r => mk(r.market)}, {k: "code", t: "代號"}, {k: "name", t: "名稱", f: r => stockLink(r.code, r.name)},
    {k: "close", t: "收盤", n: 1, f: r => `<span class="up">${fp(r.close)}</span>`}, {k: "lots", t: "量(張)", n: 1, f: r => fi(r.lots)},
    {k: "inst_f", t: "外資", n: 1, s: r => r.inst?.f, f: instCell("f")}, {k: "inst_t", t: "投信", n: 1, s: r => r.inst?.t, f: instCell("t")},
    {k: "inst_d", t: "自營", n: 1, s: r => r.inst?.d, f: instCell("d")},
    {k: "streak", t: "連板", n: 1, f: r => (r.streak > 1 ? `<span class="tag up">${r.streak} 連板</span>` : "1") + (r.one_price ? ' <span class="tag up">一價</span>' : !r.locked ? ' <span class="muted small">打開過</span>' : "")},
    {k: "vol_ratio", t: "均量比", n: 1, f: r => r.vol_ratio == null ? "—" : fx(r.vol_ratio, 1) + "x"},
    {k: "why", t: "漲停原因", w: 1, sortable: false, f: r => `<span class="why">${esc(r.why || r.reason || "")}</span>`},
    {k: "theme", t: "族群", f: r => { const [l, c] = srcTag[r.theme_source] || [r.theme_source, ""]; return `<span class="nowrap" title="${esc(r.reason)}">${esc(themeEmoji(r.theme))} ${esc(r.theme)} <span class="tsrc ${c}">${l}</span></span>`; }},
  ];
  const emo = Object.fromEntries(data.groups.map(g => [g.theme, g.emoji]));
  function themeEmoji(t) { return emo[t] || ""; }
  const t = table(document.getElementById("tbl"), cols, [], {sort: ["streak", -1], id: r => r.code,
    rowClass: r => r.code === sel ? "sel" : "", rowClick: r => pick(r.code, true)});
  const rowsNow = () => data.stocks.filter(s => (!theme || s.theme === theme) && (!market || s.market === market));
  function refresh() { t.set(rowsNow()); }
  function pick(code, scroll) {
    sel = code;
    const qs = new URLSearchParams(); if (theme) qs.set("t", theme); qs.set("s", code);
    history.replaceState(null, "", `#/daily/${data.date}?${qs}`);
    refresh();
    showBrokers(data, data.stocks.find(s => s.code === code), scroll);
  }
  chips(document.getElementById("mk"), [["", "全部"], ["TWSE", "上市"], ["TPEX", "上櫃"]], market, v => { market = v; refresh(); });
  chips(document.getElementById("th"), [["", `全部 ${data.count}`], ...data.groups.map(g => [g.theme, `${g.emoji} ${g.theme} ${g.count}`])], theme, v => { theme = v; refresh(); });
  refresh();
  if (sel && data.stocks.some(s => s.code === sel)) pick(sel, true);
};

/* ---------- 券商分點（當日頁、隔日頁共用） ---------- */
const PL_TIP = "總損益 = 已沖銷 + 未沖銷 − 手續費 − 交易稅\n已沖銷 = (賣均價 − 買均價) × 配對張數\n未沖銷 = (收盤價 − 成本均價) × 剩餘張數（空單反向）\n手續費 = 成交金額 × 0.1425% × 1.4 折\n交易稅 = 當沖賣出 0.15%／一般賣出 0.3%";
function dayPL(x, close) {
  const m = Math.min(x.b, x.s);
  const realized = (x.sa - x.ba) * m;
  const open = x.b > x.s ? (close - x.ba) * (x.b - x.s) : (x.sa - close) * (x.s - x.b);
  const fee = (x.b * x.ba + x.s * x.sa) * 0.001425 * 0.14;
  const tax = m * x.sa * 0.0015 + (x.s - m) * x.sa * 0.003;
  return (realized + open - fee - tax) * 1000;
}
const p2 = v => v == null ? "—" : fx(v, 2);
const sgnI = v => `${v > 0 ? "+" : ""}${fi(v)}`;
function parseBranches(bk) {
  return bk.branches.map(([n, b, s, ba, sa, bsd, ssd]) => ({n, b, s, ba, sa, bsd, ssd, net: b - s, tot: b + s,
    dt: b && s ? Math.min(b, s) / Math.max(b, s) : 0}));
}
const vwapOf = B => { const t = B.reduce((a, x) => a + x.tot, 0); return t ? B.reduce((a, x) => a + (x.ba || 0) * x.b + (x.sa || 0) * x.s, 0) / t : null; };
const instHead = (title, code, name, inst) => {
  const pill = (l, v) => `<span class="ipill ${sign(v)}">${l} ${v == null ? "—" : sgnI(v)}</span>`;
  return `<div class="bk-head"><h2>${title} <span class="muted">${esc(code)} ${esc(name)}</span></h2>
    <div class="ipills">${pill("外資", inst?.f)}${pill("投信", inst?.t)}${pill("自營", inst?.d)}</div></div>`;
};
function statsHTML(B, lots) {
  const buys = B.filter(x => x.net > 0).sort((a, c) => c.net - a.net).slice(0, 15);
  const sells = B.filter(x => x.net < 0).sort((a, c) => a.net - c.net).slice(0, 15);
  const sb = buys.reduce((a, x) => a + x.net, 0), ss = sells.reduce((a, x) => a - x.net, 0), diff = sb - ss;
  const nb = B.filter(x => x.net > 0).length, ns = B.filter(x => x.net < 0).length;
  return `<div class="bk-stats">
    <div><span>前 15 買超合計</span><b class="up">${fi(sb)}</b></div>
    <div><span>前 15 賣超合計</span><b class="down">${fi(ss)}</b></div>
    <div><span>主力買賣超（集中度）</span><b class="${sign(diff)}">${sgnI(diff)}<small class="muted"> ${lots ? fx(diff / lots * 100, 1) + "%" : ""}</small></b></div>
    <div><span>買超／賣超家數</span><b><span class="up">${nb}</span> / <span class="down">${ns}</span></b></div></div>`;
}
function topPairHTML(B) {
  const buys = B.filter(x => x.net > 0).sort((a, c) => c.net - a.net).slice(0, 15);
  const sells = B.filter(x => x.net < 0).sort((a, c) => a.net - c.net).slice(0, 15);
  const side = (rows, sd) => `<div class="bk-side ${sd}"><div class="cap">${sd === "b" ? "買超" : "賣超"} Top15</div><div class="tw"><table>
    <thead><tr><th scope="col">券商</th><th class="n" scope="col">${sd === "b" ? "買超" : "賣超"}</th><th class="n" scope="col">買均</th><th class="n" scope="col">買張</th><th class="n" scope="col">賣張</th><th class="n" scope="col">賣均</th></tr></thead>
    <tbody>${rows.map(x => `<tr data-n="${esc(x.n)}"><td>${esc(x.n)}</td><td class="n ${sign(x.net)}">${sgnI(x.net)}</td><td class="n">${p2(x.ba)}</td><td class="n ${x.b ? "up" : "muted"}">${x.b ? "+" + fi(x.b) : "0"}</td><td class="n ${x.s ? "down" : "muted"}">${x.s ? "+" + fi(x.s) : "0"}</td><td class="n">${p2(x.sa)}</td></tr>`).join("") || '<tr><td colspan="6" class="muted">無</td></tr>'}</tbody></table></div></div>`;
  return `<div class="bk-pair">${side(buys, "b")}${side(sells, "s")}</div>`;
}
function dtHTML(bk, B, title) {
  const dt = B.filter(x => x.b && x.s).map(x => ({...x, dq: Math.min(x.b, x.s), pl: dayPL(x, bk.close)}))
    .sort((a, c) => c.dq - a.dq).slice(0, 10);
  return `<h3 class="bk-dt">${title}</h3>
    <div class="tw"><table><thead><tr><th scope="col">券商</th><th class="n" scope="col">交易張數</th><th class="n" scope="col">總損益 ${tipBtn(PL_TIP)}</th><th class="n" scope="col">買張數</th><th class="n" scope="col">買均價</th><th class="n" scope="col">賣張數</th><th class="n" scope="col">賣均價</th><th class="n" scope="col">留倉</th><th class="n" scope="col">當沖比</th></tr></thead>
    <tbody>${dt.map(x => `<tr data-n="${esc(x.n)}"><td>${esc(x.n)}</td><td class="n">${fi(x.tot)}</td><td class="n ${sign(x.pl)}">${sgnI(x.pl)}</td><td class="n up">${fi(x.b)}</td><td class="n">@${p2(x.ba)}</td><td class="n down">${fi(x.s)}</td><td class="n">@${p2(x.sa)}</td><td class="n ${sign(x.net)}">${sgnI(x.net)}</td><td class="n">${Math.round(x.dt * 100)}%</td></tr>`).join("") || '<tr><td colspan="9" class="muted">沒有同時買賣的券商</td></tr>'}</tbody></table></div>
    <p class="small muted">排序依當沖張數（買進與賣出較小的一方）。總損益含手續費（1.4 折）與證交稅，以收盤價結算未沖銷部位。當沖比＝較小方 ÷ 較大方。</p>`;
}
function allHTML(B, key) {
  const rows = B.slice().sort((a, c) => key === "net" ? c.net - a.net : key === "dt" ? c.dt - a.dt : c.tot - a.tot).slice(0, 30);
  const hb = (k, t) => `<button type="button" class="sortbtn" data-sort="${k}" aria-pressed="${key === k}">${t}${key === k ? " ▼" : ""}</button>`;
  return `<div class="tw"><table><thead><tr><th scope="col">券商</th><th class="n" scope="col">${hb("tot", "成交張數")}</th><th class="n" scope="col">買進</th><th class="n" scope="col">賣出</th><th class="n" scope="col">${hb("net", "買賣超")}</th><th class="n" scope="col">買均</th><th class="n" scope="col">賣均</th><th class="n" scope="col">${hb("dt", "當沖比")}</th></tr></thead>
    <tbody>${rows.map(x => `<tr data-n="${esc(x.n)}"><td>${esc(x.n)}</td><td class="n">${fi(x.tot)}</td><td class="n">${fi(x.b)}</td><td class="n">${fi(x.s)}</td><td class="n ${sign(x.net)}">${sgnI(x.net)}</td><td class="n">${p2(x.ba)}</td><td class="n">${p2(x.sa)}</td><td class="n ${x.dt >= .8 ? "" : "muted"}">${x.dt ? Math.round(x.dt * 100) + "%" : "—"}</td></tr>`).join("")}</tbody></table></div>`;
}
const LEGEND = `<div class="bk-legend"><span><i class="dot up"></i>買進</span><span><i class="dot down"></i>賣出</span>
  <span><i class="ln gold"></i>金線：同一券商又買又賣，賣均高於買均（有價差）</span><span><i class="ln silver"></i>銀線：賣均不高於買均</span>
  <span>常駐顯示當沖量前 5 大的連線，滑過券商可看其他；線越粗＝當沖比越高</span><span><i class="ln avg"></i>全日均價</span></div>`;

/* refs: [{v, label, cls}] 右側價位標記；隔日頁用來標開盤/均價/收盤 */
function bubbleSVG(bk, B, refs = []) {
  const W = 1000, H = 480, ml = 74, mr = refs.length ? 96 : 24, mt = 26, mb = 44, cx = ml + (W - ml - mr) / 2, half = (W - ml - mr) / 2 - 34;
  const top = B.slice().sort((a, c) => c.tot - a.tot).slice(0, 35);  // 畫成交量前 35 大；線條、外框、字都用細的，維持清爽
  const maxV = Math.max(1, ...top.map(x => Math.max(x.b, x.s)));
  const X = (v, side) => cx + side * (8 + Math.sqrt(v / maxV) * half);
  const R = v => 2.5 + Math.sqrt(v / maxV) * 20;
  const vw = vwapOf(B);
  const prices = top.flatMap(x => [x.b ? x.ba : null, x.s ? x.sa : null]).concat(refs.map(r => r.v), [bk.close, vw]).filter(v => v != null);
  const limit = bk.limit || bk.close;
  let lo = Math.min(bk.prev_close, ...prices), hi = Math.max(...prices);
  const showLimit = hi >= bk.prev_close + (limit - bk.prev_close) * .6;
  if (showLimit) hi = Math.max(hi, limit);
  const pad = (hi - lo) * .06 || hi * .01; lo -= pad; hi += pad;
  const Y = v => mt + (hi - v) / (hi - lo) * (H - mt - mb);
  const step = (() => { const raw = (hi - lo) / 6, m = Math.pow(10, Math.floor(Math.log10(raw))), e = raw / m; return (e >= 5 ? 10 : e >= 2 ? 5 : e >= 1 ? 2 : 1) * m; })();
  let g = "";
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) g += `<line class="grid" x1="${ml}" x2="${W - mr}" y1="${Y(v)}" y2="${Y(v)}"/><text class="ax" x="${ml - 8}" y="${Y(v) + 4}" text-anchor="end">${+v.toFixed(2)}</text>`;
  const xt = [0, 10, 25, 50, 100, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000].filter(v => v <= maxV * 1.02);
  const xtk = xt.filter((v, i) => i === 0 || Math.sqrt(v / maxV) - Math.sqrt(xt[i - 1] / maxV) > .08);
  xtk.forEach(v => [-1, 1].forEach(sd => { if (v === 0 && sd > 0) return; const x = v === 0 ? cx : X(v, sd);
    g += `<line class="grid" x1="${x}" x2="${x}" y1="${mt}" y2="${H - mb}"/><text class="ax" x="${x}" y="${H - mb + 18}" text-anchor="middle">${v}</text>`; }));
  g += `<line class="mid" x1="${cx}" x2="${cx}" y1="${mt}" y2="${H - mb}"/>`;
  if (showLimit) g += `<line class="lim" x1="${ml}" x2="${W - mr}" y1="${Y(limit)}" y2="${Y(limit)}"/><text class="limt" x="${ml - 8}" y="${Y(limit) + 4}" text-anchor="end">漲停 ${fp(limit)}</text>`;
  g += `<line class="flat" x1="${ml}" x2="${W - mr}" y1="${Y(bk.prev_close)}" y2="${Y(bk.prev_close)}"/><text class="flatt" x="${ml - 8}" y="${Y(bk.prev_close) + 4}" text-anchor="end">平盤 ${fp(bk.prev_close)}</text>`;
  if (vw && !refs.length) g += `<line class="vw" x1="${ml}" x2="${W - mr}" y1="${Y(vw)}" y2="${Y(vw)}"/><text class="vwt" x="${cx + 6}" y="${Y(vw) - 5}">全日均價 ${fx(vw, 2)}</text>`;
  // 右側價位標記（避免文字重疊）
  let lastY = -99;
  refs.slice().sort((a, c) => Y(a.v) - Y(c.v)).forEach(r => {
    const y = Y(r.v), ty = Math.max(y + 4, lastY + 13); lastY = ty;
    g += `<line class="ref ${r.cls}" x1="${W - mr}" x2="${W - mr + 8}" y1="${y}" y2="${y}"/><text class="reft ${r.cls}" x="${W - mr + 12}" y="${ty}">${r.label} ${fp(r.v)}</text>`;
    if (r.cls === "avg") g += `<line class="vw" x1="${ml}" x2="${W - mr}" y1="${y}" y2="${y}"/>`;
  });
  g += `<text class="side up" x="${ml + 8}" y="${mt + 4}">← 買進</text><text class="side down" x="${W - mr - 8}" y="${mt + 4}" text-anchor="end">賣出 →</text>`;
  const links = [], dots = [], cand = [];
  // 所有買賣同時有的券商都畫細連線；當沖張數前 5 大稍粗一點
  const dtTop = new Set(top.filter(x => x.b && x.s).sort((p, q) => Math.min(q.b, q.s) - Math.min(p.b, p.s)).slice(0, 5).map(x => x.n));
  top.forEach(x => {
    const a = x.b ? {cx: X(x.b, -1), cy: Y(x.ba), r: R(x.b)} : null, c = x.s ? {cx: X(x.s, 1), cy: Y(x.sa), r: R(x.s)} : null;
    const n = esc(x.n);
        if (a && c) links.push(`<line class="lk ${x.sa > x.ba ? "gold" : "silver"} ${dtTop.has(x.n) ? "top" : ""}" data-n="${n}" x1="${a.cx.toFixed(1)}" y1="${a.cy.toFixed(1)}" x2="${c.cx.toFixed(1)}" y2="${c.cy.toFixed(1)}" style="stroke-width:${(dtTop.has(x.n) ? 1.1 + x.dt * 1.2 : .7).toFixed(2)}"/>`);
    [[a, "b", x.b], [c, "s", x.s]].forEach(([p, sd, v]) => { if (!p) return;
      dots.push([p.r, `<circle class="bb ${sd}" data-n="${n}" cx="${p.cx.toFixed(1)}" cy="${p.cy.toFixed(1)}" r="${p.r.toFixed(1)}"/>`]);
      cand.push({n, v, x: p.cx, y: p.cy - p.r - 5}); });
  });
  // 標籤：依張數由大到小放，和已放的標籤重疊就先藏起來（滑過時才顯示）
  const placed = [], labels = [];
  cand.sort((p, q) => q.v - p.v).forEach(c => {
    const w = c.n.length * 9.5 + 4, box = [c.x - w / 2, c.y - 10, c.x + w / 2, c.y + 2];
    const hit = placed.length >= 24 || placed.some(b => !(box[2] < b[0] || box[0] > b[2] || box[3] < b[1] || box[1] > b[3]));
    if (!hit) placed.push(box);
    labels.push(`<text class="lb ${hit ? "hid" : ""}" data-n="${c.n}" x="${c.x.toFixed(1)}" y="${c.y.toFixed(1)}" text-anchor="middle">${c.n}</text>`);
  });
  dots.sort((a, c) => c[0] - a[0]);
  g += `<g>${links.join("")}</g><g>${dots.map(d => d[1]).join("")}</g><g>${labels.join("")}</g>`;
  g += `<text class="info up" data-i="B1" x="${ml + 8}" y="${H - mb - 26}"></text><text class="info up" data-i="B2" x="${ml + 8}" y="${H - mb - 8}"></text>`;
  g += `<text class="info down" data-i="S1" x="${W - mr - 8}" y="${H - mb - 26}" text-anchor="end"></text><text class="info down" data-i="S2" x="${W - mr - 8}" y="${H - mb - 8}" text-anchor="end"></text>`;
  return `<div class="bk-chart"><div class="bk-scroll"><svg class="bubble" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(bk.name)} ${esc(bk.date)} 券商分點泡泡圖">${g}</svg></div></div>`;
}

/* 滑過/點選券商：泡泡、連線、表格列一起亮起。scope 是包含圖與表的容器 */
function wireBubble(scope, Blist) {
  const svgs = [...scope.querySelectorAll("svg.bubble")];
  const maps = svgs.map((svg, i) => new Map((Blist[i] || Blist[0]).map(x => [x.n, x])));
  let pinned = "";
  function hl(n) {
    svgs.forEach((svg, i) => {
      svg.classList.toggle("focus", !!n);
      svg.querySelectorAll(".hl").forEach(e => e.classList.remove("hl"));
      svg.querySelectorAll("text.info").forEach(e => e.textContent = "");
      if (!n) return;
      svg.querySelectorAll("[data-n]").forEach(e => { if (e.dataset.n === n) { e.classList.add("hl"); if (e.tagName === "text") e.parentNode.appendChild(e); } });
      const x = maps[i].get(n), set = (k, t) => { const el = svg.querySelector(`text[data-i="${k}"]`); if (el) el.textContent = t; };
      if (x?.b) { set("B1", `買均 ${fx(x.ba, 2)}`); set("B2", `買量 ${fi(x.b)}張`); }
      if (x?.s) { set("S1", `賣均 ${fx(x.sa, 2)}`); set("S2", `賣量 ${fi(x.s)}張`); }
    });
    scope.querySelectorAll("tr.hl").forEach(e => e.classList.remove("hl"));
    if (n) scope.querySelectorAll("tr[data-n]").forEach(e => { if (e.dataset.n === n) e.classList.add("hl"); });
  }
  const nameOf = e => e.target.closest("[data-n]")?.dataset.n || "";
  // 用屬性指定而非 addEventListener，切換個股時不會重複綁定
  scope.onpointerover = e => { const n = nameOf(e); if (n && !pinned) hl(n); };
  scope.onpointerout = e => { if (!pinned && nameOf(e) && !e.relatedTarget?.closest?.("[data-n]")) hl(""); };
  scope.onclick = e => { const n = nameOf(e); if (!n) return; pinned = n !== pinned ? n : ""; hl(pinned); };
}

async function showBrokers(daily, stock, scroll) {
  const box = document.getElementById("bk");
  if (!box || !stock) return;
  box.hidden = false;
  box.innerHTML = `<p class="muted">載入 ${esc(stock.code)} ${esc(stock.name)} 分點資料…</p>`;
  const bk = await load(`brokers/${daily.date}/${stock.code}.json`);
  if (scroll) box.scrollIntoView({behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start"});
  const head = instHead("法人買賣", stock.code, stock.name, (bk && bk.inst) || stock.inst);
  if (!bk) {
    const st = await load(`brokers/${daily.date}/_status.json`);
    const why = st?.stocks?.[stock.code]?.msg;
    box.innerHTML = head + `<div class="empty">${esc(why ? `這檔沒有分點資料：${why}` : "這天沒有分點資料。分點只能在收盤當天抓取，較早的日期沒有。")}</div>`;
    return;
  }
  const B = parseBranches(bk);
  let key = "tot";
  box.innerHTML = head + statsHTML(B, bk.lots) + topPairHTML(B) + bubbleSVG(bk, B) + LEGEND +
    `<p class="small muted">每家券商最多兩顆泡泡：左邊買進、右邊賣出，越外側張數越多；高度是成交均價，泡泡大小是張數。滑過或點選券商可對照，再點一次取消。</p>` +
    dtHTML(bk, B, `${esc(bk.code)} ${esc(bk.name)} ${md(bk.date)} 當沖 Top10（收盤 ${fp(bk.close)}）`) +
    `<h3 class="bk-dt">全部分點（前 30）</h3><div id="bkAll">${allHTML(B, key)}</div>`;
  box.querySelector("#bkAll").addEventListener("click", e => { const b = e.target.closest("button[data-sort]"); if (!b) return; e.stopPropagation(); key = b.dataset.sort; box.querySelector("#bkAll").innerHTML = allHTML(B, key); });
  wireBubble(box, [B]);
}

/* 隔日頁：漲停日前 15 大買超券商，隔日怎麼動 */
async function showFollow(nd, row, scroll) {
  const box = document.getElementById("bk");
  if (!box || !row) return;
  box.hidden = false;
  box.innerHTML = `<p class="muted">載入 ${esc(row.code)} ${esc(row.name)} 分點資料…</p>`;
  const [b1, b2] = await Promise.all([load(`brokers/${nd.limit_date}/${row.code}.json`), load(`brokers/${nd.date}/${row.code}.json`)]);
  if (scroll) box.scrollIntoView({behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start"});
  const title = `${esc(row.code)} ${esc(row.name)} 漲停日 ${md(nd.limit_date)} 前15大買超券商 → 隔日 ${md(nd.date)} 動向`;
  if (!b1) {
    let html = `<h2 class="bk-title">${title}</h2><div class="empty">沒有漲停日 ${esc(nd.limit_date)} 的分點資料（分點從開始抓取的那天才有，且只能在收盤當天抓），所以無法對照主力買家。</div>`;
    if (b2) {
      const B2 = parseBranches(b2);
      const refs = [{v: b2.open, label: "開盤", cls: "open"}, {v: b2.avg, label: "均價", cls: "avg"}, {v: b2.close, label: "收盤", cls: "close"}].filter(r => r.v);
      html += instHead(`隔日 ${md(nd.date)} 分點`, row.code, row.name, b2.inst) + statsHTML(B2, b2.lots) + topPairHTML(B2) + bubbleSVG(b2, B2, refs) + LEGEND +
        dtHTML(b2, B2, `${esc(b2.code)} ${esc(b2.name)} ${md(b2.date)} 當沖 Top10（收盤 ${fp(b2.close)}）`);
      box.innerHTML = html;
      wireBubble(box, [B2]);
    } else {
      const st = await load(`brokers/${nd.date}/_status.json`);
      const why = st?.stocks?.[row.code]?.msg;
      box.innerHTML = html + (why ? `<div class="empty">隔日也沒有分點資料：${esc(why)}</div>` : "");
    }
    return;
  }
  const B1 = parseBranches(b1), B2 = b2 ? parseBranches(b2) : [];
  const m2 = new Map(B2.map(x => [x.n, x]));
  const top = B1.filter(x => x.net > 0).sort((a, c) => c.net - a.net).slice(0, 15);
  const maxN = Math.max(1, ...top.map(x => Math.abs(m2.get(x.n)?.net || 0)));
  const sum = {net: 0, n2: 0, s2: 0, b2: 0};
  const rows = top.map((x, i) => {
    const y = m2.get(x.n);
    sum.net += x.net;
    const sd = x.bsd ? `<small class="muted"> ±${fx(x.bsd, 2)}</small>` : "";
    const left = `<td class="rk">${i + 1}</td><td>${esc(x.n)}</td><td class="n up g1">${sgnI(x.net)}</td><td class="n g1">${p2(x.ba)}${sd}</td>`;
    if (!y) return `<tr class="idle" data-n="${esc(x.n)}">${left}<td colspan="6" class="idle-msg">${b2 ? "未交易（持股不動）" : "—"}</td></tr>`;
    sum.n2 += y.net; sum.s2 += y.s; sum.b2 += y.b;
    const w = Math.round(Math.abs(y.net) / maxN * 46);
    const out = x.net ? Math.min(y.s / x.net, 9.99) : 0;
    return `<tr data-n="${esc(x.n)}">${left}<td class="n"><span class="${sign(y.net)}">${sgnI(y.net)}</span><span class="bar ${y.net >= 0 ? "up" : "down"}" style="width:${w}px"></span></td>
      <td class="n">${p2(y.sa)}${y.ssd ? `<small class="muted"> ±${fx(y.ssd, 2)}</small>` : ""}</td><td class="n down">${fi(y.s)}</td><td class="n up">${fi(y.b)}</td><td class="n">${p2(y.ba)}${y.bsd ? `<small class="muted"> ±${fx(y.bsd, 2)}</small>` : ""}</td><td class="n">${y.s ? Math.round(out * 100) + "%" : "—"}</td></tr>`;
  }).join("");
  const tbl = `<div class="tw"><table class="follow"><thead>
    <tr class="grp"><th colspan="2"></th><th colspan="2" class="g1">漲停日 ${md(nd.limit_date)}</th><th colspan="6">隔日 ${md(nd.date)}</th></tr>
    <tr><th scope="col">#</th><th scope="col">券商</th><th class="n g1" scope="col">買超</th><th class="n g1" scope="col">均價</th><th class="n" scope="col">${md(nd.date)} 買賣超</th><th class="n" scope="col">賣均</th><th class="n" scope="col">賣</th><th class="n" scope="col">買</th><th class="n" scope="col">買均</th><th class="n" scope="col">賣出比例 <span class="info" title="隔日賣出張數 ÷ 漲停日買超張數">ⓘ</span></th></tr></thead>
    <tbody>${rows}</tbody>
    <tfoot><tr><td></td><td>合計</td><td class="n up g1">${sgnI(sum.net)}</td><td class="g1"></td><td class="n ${sign(sum.n2)}">${b2 ? sgnI(sum.n2) : "—"}</td><td></td><td class="n down">${b2 ? fi(sum.s2) : ""}</td><td class="n up">${b2 ? fi(sum.b2) : ""}</td><td></td><td class="n">${b2 && sum.net ? Math.round(sum.s2 / sum.net * 100) + "%" : ""}</td></tr></tfoot></table></div>
    <p class="small muted">均價旁的 ± 是該券商買進價格的分散程度（標準差），越小代表越集中在同一價位。灰色列是隔日沒有交易的券商。</p>`;
  let html = `<h2 class="bk-title">${title}</h2>` + tbl;
  if (b2) {
    const refs = [{v: b2.open, label: "開盤", cls: "open"}, {v: b2.avg, label: "均價", cls: "avg"}, {v: b2.close, label: "收盤", cls: "close"}].filter(r => r.v);
    html += instHead(`隔日 ${md(nd.date)} 分點`, row.code, row.name, b2.inst) + statsHTML(B2, b2.lots) + bubbleSVG(b2, B2, refs) + LEGEND +
      dtHTML(b2, B2, `${esc(b2.code)} ${esc(b2.name)} ${md(b2.date)} 當沖 Top10（收盤 ${fp(b2.close)}）`);
  } else {
    html += `<div class="empty">隔日 ${esc(nd.date)} 的分點資料還沒有或抓取失敗。</div>`;
  }
  box.innerHTML = html;
  wireBubble(box, [B2]);
}

const TAG_ORDER = ["續漲停", "強續漲", "弱續漲", "開高走低", "直接跌"];
const TAG_CLS = {"續漲停": "up strong", "強續漲": "up", "弱續漲": "up soft", "開高走低": "warn", "直接跌": "down"};
const TAG_TIP = "續漲停：收在漲停｜強續漲：開高且收盤 ≥ 開盤｜弱續漲：收紅但不是強續漲｜開高走低：開高但收黑｜直接跌：沒開高且收黑";
function tipBtn(text) { return `<button type="button" class="tipbtn" data-tip="${esc(text)}" aria-label="說明">ⓘ</button>`; }
document.addEventListener("click", e => {
  const b = e.target.closest(".tipbtn");
  document.querySelectorAll(".tippop").forEach(x => x.remove());
  if (!b) return;
  e.stopPropagation();
  const p = document.createElement("div");
  p.className = "tippop"; p.textContent = b.dataset.tip; p.setAttribute("role", "tooltip");
  document.body.append(p);
  const r = b.getBoundingClientRect();
  p.style.left = Math.max(8, Math.min(window.innerWidth - p.offsetWidth - 8, r.left + r.width / 2 - p.offsetWidth / 2)) + "px";
  p.style.top = (r.bottom + window.scrollY + 6) + "px";
});

P.nextday = async (date) => {
  const dates = META.nextday_dates || [];
  date = date || dates[0];
  const data = date && await load(`nextday/${date}.json`);
  setTitle("漲停隔日表現");
  if (!data) { app.innerHTML = `<h1>漲停隔日</h1>${emptyBox("需要至少兩個交易日的資料")}`; return; }
  const s = data.summary;
  const q = new URLSearchParams(location.hash.split("?")[1] || "");
  let selN = q.get("s") || "", tag = "", theme = q.get("t") || "";
  const md2 = d => d.slice(5).replace("-", "/");
  const diff = v => v == null ? "" : `<span class="dif ${v > 0 ? "up" : v < 0 ? "down" : ""}" title="與前一個漲停日比較（百分點）">${v > 0 ? "↑" : v < 0 ? "↓" : ""}${fx(Math.abs(v), 1)}</span>`;
  app.innerHTML = `<h1>漲停隔日</h1>
    <p class="sub">漲停日 ${data.limit_date} → 隔日 ${data.date}。報酬以漲停日收盤價為基準。</p>
    <div class="toolbar"><span id="ds"></span></div>
    <div class="kpis">
      <div class="kpi"><div class="l">開盤均報酬</div><div class="v">${pc(s.open_avg)}</div><div class="d">當日勝率 ${fx(s.open_win, 1)}% ${diff(s.open_win_prev)}</div></div>
      <div class="kpi"><div class="l">均價均報酬</div><div class="v">${pc(s.avg_avg)}</div><div class="d">當日勝率 ${fx(s.avg_win, 1)}% ${diff(s.avg_win_prev)}</div></div>
      <div class="kpi"><div class="l">收盤均報酬</div><div class="v">${pc(s.close_avg)}</div><div class="d">當日勝率 ${fx(s.close_win, 1)}% ${diff(s.close_win_prev)}</div></div>
      <div class="kpi"><div class="l">續漲停</div><div class="v up">${s.cont} 檔</div><div class="d">${s.n} 檔漲停</div></div>
    </div>
    <h2>族群 ${md2(data.limit_date)} 漲停 vs ${md2(data.date)} 隔日</h2>
    <div id="g"></div>
    <p class="small muted">點族群篩選下方個股，再點一次取消。</p>
    <h2 id="stockHead">個股明細（${s.n} 檔）</h2>
    <p class="small muted">標籤根據隔日實際開盤與收盤價格分類，僅描述已發生之走勢。 ${tipBtn(TAG_TIP)}</p>
    <div class="toolbar"><span class="chips" id="tags"></span></div>
    <div id="t"></div>
    <p class="small muted">加權＝（2 × 開盤報酬 ＋ 均價報酬）÷ 3，假設三分之二在開盤賣、三分之一在均價賣。點個股看漲停日的主力買家隔天怎麼動。</p>
    <section class="bk" id="bk" hidden></section>`;
  document.getElementById("ds").append(dateSelect(dates, date, v => location.hash = `#/nextday/${v}`));
  const gt = table(document.getElementById("g"), [
    {k: "theme", t: "族群", f: r => `${esc(r.emoji)} ${esc(r.theme)}`},
    {k: "streak", t: `連續 ${tipBtn("該族群連續幾天出現在漲停板上（含漲停日），代表市場對該題材的關注持續性")}`, n: 1,
      f: r => r.streak > 1 ? `<span class="tag warn">${r.streak}天</span>` : '<span class="muted">—</span>'},
    {k: "win", t: `當日勝率 ${tipBtn("以漲停日收盤價為基準，⅔ 開盤報酬 + ⅓ 均價報酬 > 0 的比例")}`, n: 1,
      f: r => `${fx(r.win, 1)}% <span class="muted small">${r.wins}/${r.n}</span>`},
    {k: "open", t: "開盤", n: 1, f: r => pc(r.open)}, {k: "avg", t: "均價", n: 1, f: r => pc(r.avg)}, {k: "close", t: "收盤", n: 1, f: r => pc(r.close)},
  ], data.groups, {sort: ["avg", -1], id: r => r.theme, rowClass: r => r.theme === theme ? "sel" : "",
    rowClick: r => { theme = theme === r.theme ? "" : r.theme; gt.set(data.groups); refresh(); }});
  const emo = Object.fromEntries(data.groups.map(g => [g.theme, g.emoji]));
  const tt = table(document.getElementById("t"), [
    {k: "market", t: "所", f: r => mk(r.market)}, {k: "code", t: "代號"}, {k: "name", t: "名稱", f: r => stockLink(r.code, r.name)},
    {k: "ref", t: "漲停價", n: 1, f: r => fp(r.ref)}, {k: "vol_ratio", t: `量比 ${tipBtn("量比＝隔日成交量 ÷ 漲停日成交量（同原網站）。\n1x 以下：隔日量縮（常見於再鎖漲停）；10x 以上：隔日爆量換手。\n均量比（漲停日量 ÷ 前 5 日均量）在當日頁。")}`, n: 1, s: r => r.vol_ratio, f: r => r.vol_ratio == null ? "—" : fx(r.vol_ratio, 1) + "x"},
    {k: "ret_open", t: "隔日開", n: 1, f: r => `${fp(r.open)} ${pc(r.ret_open)}`}, {k: "ret_avg", t: "隔日均價", n: 1, f: r => `${fp(r.avg)} ${pc(r.ret_avg)}`},
    {k: "ret_close", t: "隔日收", n: 1, f: r => `${fp(r.close)} ${pc(r.ret_close)}`},
    {k: "ret_wavg", t: "加權", n: 1, f: r => pc(r.ret_wavg)},
    {k: "tag", t: "標籤", s: r => TAG_ORDER.indexOf(r.tag), f: r => `<span class="tag ${TAG_CLS[r.tag] || ""}">${esc(r.tag)}</span>`},
    {k: "theme", t: "族群", f: r => `${esc(emo[r.theme] || "")} ${esc(r.theme)}`},
  ], [], {sort: ["ret_avg", -1], id: r => r.code, rowClass: r => r.code === selN ? "sel" : "",
    rowClick: r => { selN = r.code; refresh(); showFollow(data, r, true); }});
  function refresh() {
    const rows = data.stocks.filter(x => (!tag || x.tag === tag) && (!theme || x.theme === theme));
    tt.set(rows);
    document.getElementById("stockHead").textContent = theme ? `個股明細：${theme}（${rows.length} 檔）` : `個股明細（${rows.length} 檔）`;
  }
  const tagItems = TAG_ORDER.filter(k => data.tags[k]).map(k => [k, `${k} ${data.tags[k]}`]);
  chips(document.getElementById("tags"), [["", `全部 ${s.n}`], ...tagItems], tag, v => { tag = v; refresh(); });
  refresh();
  // 預設展開第一檔有分點資料的股票
  const first = selN ? data.stocks.find(x => x.code === selN) : null;
  if (first) { showFollow(data, first, false); return; }
  const st = await load(`brokers/${data.limit_date}/_status.json`);
  const pick = data.stocks.find(x => st?.stocks?.[x.code]?.ok);
  if (pick) { selN = pick.code; refresh(); showFollow(data, pick, false); }
};

P.stats = async () => {
  setTitle("漲停統計");
  const st = await load("stats.json");
  if (!st || !st.series.length) { app.innerHTML = `<h1>統計</h1>${emptyBox("資料累積中")}`; return; }
  const S = st.series;
  const R = st.rotation || {dates: [], items: []};
  const ld = R.last_done ? md(R.last_done) : "";
  app.innerHTML = `<h1>漲停統計</h1><p class="sub">漲停日 ${S[0].date} ～ ${S[S.length - 1].date}，共 ${st.window} 個交易日。跨日看漲停家數、族群輪動與隔日延續力。</p>
    <h2>漲停後隔日強度</h2>
    <p class="small muted">柱體是漲停家數（紅色深的部分是隔天續漲停），折線是這批漲停股隔日的開盤、均價、收盤平均報酬。滑過可看當天數字。</p>
    <div class="chart combo" id="combo"></div><div class="combo-info" id="ci"></div>
    <h2>族群輪動</h2>
    <p class="small muted">焦點：最新一天或 ${ld} 有漲停的族群，依 ${ld} 漲停股的隔日收盤漲跌排序；小長條是近 14 個交易日每天的漲停檔數，顏色是隔日收盤表現。矩陣：所有近 14 日出現過的族群。點族群會篩選下方族群表與個股表。</p>
    <div class="toolbar"><span class="chips" id="rv"></span></div>
    <div id="rot"></div>
    <div class="heat-legend legend-scale"><span>色階（隔日收盤）：</span>${[["≥+8%", "c5"], ["+4~+8%", "c4"], ["+1~+4%", "c3"], ["±1%", "c2"], ["-1~-4%", "c1"], ["<-4%", "c0"], ["待隔日", "cn"]].map(([t, c]) => `<i class="hc ${c}"></i>${t}`).join(" ")}</div>
    <h2>族群跨日統計</h2><p class="small muted">按族群彙總出現天數、漲停股數與隔日平均報酬。</p><div id="tt"></div>
    <h2>個股隔日報酬</h2><p class="small muted">個股漲停後隔日的平均報酬（天＝期間內漲停次數）。</p>
    <div class="toolbar"><input type="search" id="sq" placeholder="股號或名稱" aria-label="搜尋股號或名稱"></div><div id="st"></div>`;
  // ---- 組合圖
  const W = 1000, H = 300, ml = 40, mr = 48, mt = 16, mb = 30, n = S.length, bw = (W - ml - mr) / n;
  const mx = Math.max(...S.map(x => x.count), 1);
  const rets = S.flatMap(x => [x.nd_open, x.nd_avg, x.nd_close]).filter(v => v != null);
  const rmax = Math.max(4, ...rets.map(Math.abs)), rlim = Math.ceil(rmax / 2) * 2;
  const Yc = v => H - mb - (H - mt - mb) * v / mx, Yr = v => mt + (H - mt - mb) * (rlim - v) / (2 * rlim);
  let g = "";
  for (let v = -rlim; v <= rlim; v += rlim / 2) g += `<line class="grid" x1="${ml}" x2="${W - mr}" y1="${Yr(v)}" y2="${Yr(v)}"/><text class="ax" x="${W - mr + 6}" y="${Yr(v) + 4}">${v > 0 ? "+" : ""}${v}%</text>`;
  [0, Math.round(mx / 2), mx].forEach(v => g += `<text class="ax" x="${ml - 6}" y="${Yc(v) + 4}" text-anchor="end">${v}</text>`);
  S.forEach((x, i) => {
    const X = ml + i * bw, cont = x.cont || 0;
    g += `<rect class="cb" x="${X + 0.5}" y="${Yc(x.count)}" width="${Math.max(bw - 1, 1)}" height="${Yc(0) - Yc(x.count)}"/>`;
    if (cont) g += `<rect class="cc" x="${X + 0.5}" y="${Yc(cont)}" width="${Math.max(bw - 1, 1)}" height="${Yc(0) - Yc(cont)}"/>`;
    if (i % Math.ceil(n / 10) === 0) g += `<text class="ax" x="${X + bw / 2}" y="${H - 10}" text-anchor="middle">${md(x.date)}</text>`;
    g += `<rect class="hit" data-i="${i}" x="${X}" y="${mt}" width="${bw}" height="${H - mt - mb}"/>`;
  });
  const line = (k, c) => { const pts = S.map((x, i) => x[k] == null ? null : `${(ml + i * bw + bw / 2).toFixed(1)},${Yr(x[k]).toFixed(1)}`);
    let d = "", on = false; pts.forEach(p => { if (p) { d += (on ? "L" : "M") + p; on = true; } else on = false; }); return `<path class="ln ${c}" d="${d}"/>`; };
  g += line("nd_open", "lo") + line("nd_avg", "la") + line("nd_close", "lc");
  g += `<line class="zero" x1="${ml}" x2="${W - mr}" y1="${Yr(0)}" y2="${Yr(0)}"/><line class="cur" id="cur" x1="0" x2="0" y1="${mt}" y2="${H - mb}" visibility="hidden"/>`;
  const combo = document.getElementById("combo");
  combo.innerHTML = `<div class="legend"><span><i class="sw cc"></i>續漲停</span><span><i class="sw cb"></i>其餘漲停</span><span><i class="ln-s lo"></i>開盤</span><span><i class="ln-s la"></i>均價</span><span><i class="ln-s lc"></i>收盤</span></div>
    <div class="bk-scroll"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="每日漲停家數與隔日報酬">${g}</svg></div>`;
  const info = document.getElementById("ci");
  const show = i => { const x = S[i]; if (!x) return;
    info.innerHTML = `<b>${md(x.date)} 漲停 ${x.count} 檔</b>${x.nd_date ? ` → ${md(x.nd_date)} 隔日｜續漲停 ${x.cont ?? "—"} 檔｜開盤 ${pc(x.nd_open)}｜均價 ${pc(x.nd_avg)}｜收盤 ${pc(x.nd_close)}｜收盤勝率 ${x.nd_win == null ? "—" : fx(x.nd_win, 1) + "%"}` : "｜隔日待統計"}｜最大族群 ${esc(x.top)}`;
    const c = combo.querySelector("#cur"), X = ml + i * bw + bw / 2; c.setAttribute("x1", X); c.setAttribute("x2", X); c.setAttribute("visibility", "visible"); };
  combo.onpointermove = e => { const h = e.target.closest(".hit"); if (h) show(+h.dataset.i); };
  show(S.findLastIndex(x => x.nd_close != null));
  // ---- 族群輪動
  const hc = v => v == null ? "cn" : v >= 8 ? "c5" : v >= 4 ? "c4" : v >= 1 ? "c3" : v > -1 ? "c2" : v > -4 ? "c1" : "c0";
  let view = "focus", pickT = "";
  const spark = (arr, closes) => { const m = Math.max(1, ...arr); return `<svg class="spk" viewBox="0 0 ${arr.length * 8} 24" aria-hidden="true">${arr.map((v, i) => `<rect class="hc ${hc(closes[i])}" x="${i * 8 + 1}" y="${24 - Math.max(v ? 3 : 1, v / m * 22)}" width="6" height="${Math.max(v ? 3 : 1, v / m * 22)}"/>`).join("")}</svg>`; };
  function drawRot() {
    const box = document.getElementById("rot");
    if (view === "focus") {
      box.className = "rot-cards";
      const focus = R.items.filter(x => x.today || x.last_close != null);
      box.innerHTML = focus.map(x => `<button type="button" class="rcard ${x.theme === pickT ? "on" : ""}" data-t="${esc(x.theme)}">
        <div class="rh"><b>${esc(x.emoji)} ${esc(x.theme)}</b><span class="muted small">今日 ${x.today}</span></div>
        ${spark(x.spark, x.closes)}
        <div class="rf"><span class="muted small">${ld} 收盤</span><b class="${sign(x.last_close)}">${x.last_close == null ? "—" : (x.last_close > 0 ? "+" : "") + fx(x.last_close) + "%"}</b></div>
        <div class="rf small muted"><span>近 14 日 ${x.n14} 檔 / ${x.d14} 天</span><span class="${sign(x.avg14)}">${x.avg14 == null ? "" : (x.avg14 > 0 ? "+" : "") + fx(x.avg14) + "%"}</span></div></button>`).join("");
    } else {
      box.className = "tw";
      box.innerHTML = `<table class="matrix"><thead><tr><th scope="col">族群</th>${R.dates.map(d => `<th class="n" scope="col">${md(d)}</th>`).join("")}</tr></thead><tbody>
        ${R.items.map(x => `<tr class="click ${x.theme === pickT ? "sel" : ""}" data-t="${esc(x.theme)}"><td>${esc(x.emoji)} ${esc(x.theme)}</td>${x.spark.map((v, i) => `<td class="n"><span class="hm hc ${v ? hc(x.closes[i]) : "c-"}" title="${v ? `${v} 檔，隔日收盤 ${x.closes[i] == null ? "待隔日" : fx(x.closes[i]) + "%"}` : ""}">${v || ""}</span></td>`).join("")}</tr>`).join("")}</tbody></table>`;
    }
  }
  document.getElementById("rot").onclick = e => { const b = e.target.closest("[data-t]"); if (!b) return; pickT = pickT === b.dataset.t ? "" : b.dataset.t; drawRot(); drawTables(); };
  chips(document.getElementById("rv"), [["focus", "焦點"], ["matrix", "矩陣"]], view, v => { view = v; drawRot(); });
  // ---- 族群表、個股表
  const tt = table(document.getElementById("tt"), [
    {k: "theme", t: "族群", f: r => `${esc(r.emoji)} ${esc(r.theme)}`},
    {k: "days", t: "天數", n: 1, f: r => `${r.days}<span class="muted small">/${st.window}</span>`}, {k: "total", t: "股數", n: 1},
    {k: "open", t: "開盤", n: 1, f: r => pc(r.open)}, {k: "avg", t: "均價", n: 1, f: r => pc(r.avg)}, {k: "close", t: "收盤", n: 1, f: r => pc(r.close)},
    {k: "nd_win", t: "收盤勝率", n: 1, f: r => r.nd_win == null ? "—" : fx(r.nd_win, 1) + "%"},
    {k: "last", t: "最近出現", f: r => `<a href="#/daily/${r.last}">${md(r.last)}</a>`},
  ], [], {sort: ["total", -1]});
  const themeOf = {};
  Object.entries(await load("stock_history.json") || {}).forEach(([c, h]) => themeOf[c] = new Set(h.events.map(e => e.theme)));
  let sq = "";
  const stt = table(document.getElementById("st"), [
    {k: "code", t: "代號", f: r => `<span class="code">${esc(r.code)}</span>`}, {k: "name", t: "名稱", f: r => stockLink(r.code, r.name)},
    {k: "n", t: "天", n: 1}, {k: "open", t: "開盤", n: 1, f: r => pc(r.open)}, {k: "avg", t: "均價", n: 1, f: r => pc(r.avg)}, {k: "close", t: "收盤", n: 1, f: r => pc(r.close)},
  ], [], {sort: ["n", -1]});
  function drawTables() {
    tt.set(st.themes.filter(x => !pickT || x.theme === pickT));
    stt.set((st.stocks || []).filter(x => (!pickT || themeOf[x.code]?.has(pickT)) && (!sq || x.code.includes(sq) || x.name.includes(sq))));
  }
  document.getElementById("sq").oninput = e => { sq = e.target.value.trim(); drawTables(); };
  drawRot(); drawTables();
};

P.commentary = async (date) => {
  const idx = await load("commentary/index.json") || [];
  if (date) {
    const c = await load(`commentary/${date}.json`);
    setTitle(`${date} 盤後氣氛`);
    app.innerHTML = c ? `<h1>${date} 盤後氣氛</h1><p class="sub">${c.source === "ai" ? "AI 依當日資料自動生成" : "依當日資料以規則生成"}，${esc(c.generated)}</p>
      <div class="panel prose"><p>${esc(c.text)}</p></div>
      <h2>評論依據的資料</h2><pre class="copy">${esc(c.facts)}</pre>
      <p><a href="#/daily/${date}">看當日漲停族群</a>　<a href="#/commentary">回列表</a></p>` : `<h1>找不到評論</h1>`;
    return;
  }
  setTitle("盤後氣氛");
  app.innerHTML = `<h1>盤後氣氛</h1><p class="sub">每個交易日收盤後，依漲停族群與隔日表現整理的盤面評論。</p>
    <div class="tw"><table><tbody>${idx.map(x => `<tr><td><a href="#/commentary/${x.date}">${x.date}</a></td><td class="wrap">${esc(x.excerpt)}…</td></tr>`).join("") || '<tr><td class="empty">尚無評論</td></tr>'}</tbody></table></div>`;
};

// ---- 公告類 ----
const newTag = r => r.new ? '<span class="tag new">新</span>' : "";
const SCALE_TIP = "AI 依公告數字逐筆判斷，-9 ~ +9：\n+8~9 高度超預期｜+6~7 值得關注｜+4~5 有亮點待觀察\n+1~3 符合預期｜0 無特別資訊｜負分＝衰退警示\n\n沒有 AI 時改用規則分數（標示「規則」）。評分僅供參考。";
const RUBRIC_TIP = {
  att: "自結驚喜度：① 單月 EPS 對比上季月均（上季 EPS÷3）② 獲利趨勢能否延續 ③ 本業驅動優於業外",
  fin: "季報驚喜度：① 單季 EPS 對比上季 ② 延續性 ③ 毛利率、營益率改善且業外占比低較佳",
  rev: "營收：① 同樣成長率，營收規模越大越驚人；低基期的高年增扣分 ② 月增連續加速優於單月跳升 ③ 備註有具體產品/客戶/訂單加分",
};
function scoreTag(r) {
  if (r.score == null) return '<span class="muted">—</span>';
  const lv = r.score >= 6 ? "s3" : r.score >= 3 ? "s2" : r.score > 0 ? "s1" : r.score <= -6 ? "n3" : r.score <= -3 ? "n2" : r.score < 0 ? "n1" : "z";
  return `<span class="score ${lv}" title="${r.score_src === "ai" ? "AI" : "規則"}評分${r.why ? "：" + esc(r.why) : ""}">${r.score > 0 ? "+" : ""}${r.score}</span>${r.score_src === "rule" ? '<span class="muted small"> 規則</span>' : ""}`;
}
const v2 = (x, d = 2) => x == null ? '<span class="muted">—</span>' : fx(x, d);
const pct = x => x == null ? '<span class="muted">—</span>' : fx(x, 2) + "%";
const MOPS = "https://mopsov.twse.com.tw/mops/web/t05sr01_1";
const timeCol = {k: "time", t: "時間", f: r => `${md(r.date)} ${esc(r.time || "")}`, s: r => (r.date || "") + (r.time || "")};
const idCols = [{k: "code", t: "代號", f: r => `<span class="code">${esc(r.code)}</span>`}, {k: "name", t: "名稱", f: r => `${stockLink(r.code, r.name)} ${newTag(r)}`}];
const pxCols = [{k: "close", t: "股價", n: 1, f: r => fp(r.close)}, {k: "chg", t: "漲跌", n: 1, f: r => pc(r.chg)}];
function rawBlock(r, extra = "") {
  return `<div class="ann-detail">${extra}
    <div class="row" style="justify-content:space-between"><h4>公告原文 <span class="muted small">${esc(r.date)} ${esc(r.time || "")}｜${esc(r.subject || "")}</span></h4>
    <a class="btn" href="${MOPS}" target="_blank" rel="noopener">到觀測站查證</a></div>
    <pre class="raw">${esc(r.body || "（沒有原文）")}</pre></div>`;
}

/* 公告頁共用：上方篩選，依「市場未反映／歷史」分組，點列展開原文與計算 */
async function annPage(kind, title, sub, cols, opts = {}) {
  setTitle(title);
  const js = await load(`announce/${kind}.json`);
  const items = js?.items || [];
  const groups = opts.groups || [[`市場未反映（${js?.cutoff || "最近收盤"} 後公告）`, r => !r.traded, "hot"], ["歷史公告", r => r.traded, ""]];
  app.innerHTML = `<h1>${title}</h1><p class="sub">${sub}</p>
    <div class="toolbar"><span class="chips" id="f"></span>${opts.extraFilter || ""}<input type="search" id="q" placeholder="代號或名稱" aria-label="搜尋代號或名稱">
      <span class="small muted">更新 ${esc(js?.updated || "—")}</span></div>
    <div id="groups"></div>
    <p class="small muted">${opts.foot || "資料來源：公開資訊觀測站（上市＋上櫃）。表格數字由程式從公告原文抽取，可能有誤，請點列展開對照原文，或到觀測站查證。"}</p>`;
  const box = document.getElementById("groups");
  box.innerHTML = groups.map((g, i) => `<section class="ann-group ${g[2]}"><h2 class="ann-h"><span>${esc(g[0])}</span> <span class="muted small" id="gc${i}"></span></h2><div id="gt${i}"></div></section>`).join("");
  const tables = groups.map((g, i) => table(document.getElementById(`gt${i}`), cols, [],
    {sort: opts.sort, expand: opts.expand, id: r => r.key, empty: "沒有資料"}));
  let flt = "", q = "", extra = {};
  const filters = opts.filters || [];
  function apply() {
    const base = items.filter(r => (!flt || filters.find(f => f[0] === flt)[2](r)) && (!q || r.code.includes(q) || (r.name || "").includes(q))
      && (!opts.extraApply || opts.extraApply(r, extra)));
    groups.forEach((g, i) => { const rows = base.filter(g[1]); tables[i].set(rows); document.getElementById(`gc${i}`).textContent = `（${rows.length} 筆）`; });
  }
  chips(document.getElementById("f"), [["", "全部"], ...filters.map(f => [f[0], f[1]])], "", v => { flt = v; apply(); });
  document.getElementById("q").oninput = e => { q = e.target.value.trim(); apply(); };
  if (opts.extraBind) opts.extraBind(extra, apply);
  apply();
}

P.att = () => annPage("att", "自結", "公司自行結算的月或季損益，包含交易所要求注意股公布的財務業務資訊。上季數字來自已公布的財報。", [
  timeCol, ...idCols,
  {k: "score", t: `AI ${tipBtn(SCALE_TIP + "\n\n" + RUBRIC_TIP.att)}`, n: 1, f: scoreTag, s: r => r.score ?? -99},
  {k: "period", t: "期間", f: r => esc(r.period || "—")}, {k: "eps", t: "EPS", n: 1, f: r => v2(r.eps)},
  {k: "eps_m", t: "月均 EPS", n: 1, f: r => v2(r.eps_m)}, {k: "gm", t: "毛利率", n: 1, f: r => pct(r.gm)}, {k: "om", t: "營益率", n: 1, f: r => pct(r.om)},
  {k: "base_label", t: "上季", f: r => esc(r.base_label || "—")}, {k: "base_eps_m", t: "上季 EPS÷3", n: 1, f: r => v2(r.base_eps_m)},
  {k: "base_eps", t: "上季 EPS", n: 1, f: r => v2(r.base_eps)}, {k: "base_gm", t: "上季毛利率", n: 1, f: r => pct(r.base_gm)},
  {k: "base_om", t: "上季營益率", n: 1, f: r => pct(r.base_om)}, ...pxCols,
], {sort: ["time", -1],
  filters: [["beat", "月 EPS > 上季÷3", r => r.eps_m != null && r.base_eps_m != null && r.eps_m > r.base_eps_m],
            ["gm", "毛利率成長", r => r.gm != null && r.base_gm != null && r.gm > r.base_gm],
            ["om", "營益率成長", r => r.om != null && r.base_om != null && r.om > r.base_om],
            ["pos", "AI 正分", r => r.score > 0]],
  expand: r => rawBlock(r, `<div class="calc"><table><thead><tr><th></th><th class="n">本期（${esc(r.period || "—")}）</th><th class="n">月均</th><th class="n">上季（${esc(r.base_label || "—")}）</th><th class="n">上季月均</th></tr></thead>
    <tbody><tr><td>EPS</td><td class="n">${v2(r.eps)}</td><td class="n">${v2(r.eps_m)}</td><td class="n">${v2(r.base_eps)}</td><td class="n">${v2(r.base_eps_m)}</td></tr>
    <tr><td>營收(百萬)</td><td class="n">${v2(r.rev, 0)}</td><td></td><td></td><td></td></tr>
    <tr><td>毛利率</td><td class="n">${pct(r.gm)}</td><td></td><td class="n">${pct(r.base_gm)}</td><td></td></tr>
    <tr><td>營益率</td><td class="n">${pct(r.om)}</td><td></td><td class="n">${pct(r.base_om)}</td><td></td></tr></tbody></table>
    <p class="small muted">${r.why ? `評分理由：${esc(r.why)}｜` : ""}${r.extracted_by === "ai" ? "數字由 AI 從原文抽取｜" : ""}月均＝本期 EPS ÷ 期間月數；上季月均＝上季 EPS ÷ 3。</p></div>`)});

P.fin = () => annPage("fin", "季報", "董事會通過的季度財報。單季數字＝本期累計 − 上一季累計；上季數字來自觀測站的綜合損益表彙總。", [
  timeCol, ...idCols,
  {k: "score", t: `AI ${tipBtn(SCALE_TIP + "\n\n" + RUBRIC_TIP.fin)}`, n: 1, f: scoreTag, s: r => r.score ?? -99},
  {k: "period", t: "期間"}, {k: "eps", t: "單季 EPS", n: 1, f: r => r.single_ok ? v2(r.eps) : `<span class="muted" title="缺上一季累計，暫無法換算單季">累計 ${v2(r.cum_eps)}</span>`},
  {k: "gm", t: "毛利率", n: 1, f: r => pct(r.gm)}, {k: "om", t: "營益率", n: 1, f: r => pct(r.om)}, {k: "nonop_pct", t: "業外%", n: 1, f: r => pct(r.nonop_pct)},
  {k: "prev_label", t: "上季", f: r => esc(r.prev_label || "—")}, {k: "prev_eps", t: "EPS", n: 1, f: r => v2(r.prev_eps)},
  {k: "prev_gm", t: "毛利率", n: 1, f: r => pct(r.prev_gm)}, {k: "prev_om", t: "營益率", n: 1, f: r => pct(r.prev_om)},
  {k: "prev_nonop_pct", t: "業外%", n: 1, f: r => pct(r.prev_nonop_pct)}, ...pxCols,
], {sort: ["time", -1],
  filters: [["gm", "毛利率成長", r => r.gm != null && r.prev_gm != null && r.gm > r.prev_gm],
            ["om", "營益率成長", r => r.om != null && r.prev_om != null && r.om > r.prev_om],
            ["eps", "EPS 成長", r => r.eps != null && r.prev_eps != null && r.eps > r.prev_eps], ["pos", "AI 正分", r => r.score > 0]],
  expand: r => rawBlock(r, `<p class="small muted">${r.why ? `評分理由：${esc(r.why)}｜` : ""}累計 EPS ${v2(r.cum_eps)}；業外% ＝（稅前淨利 − 營業利益）÷ 稅前淨利。</p>`)});

P.rev = () => annPage("rev", "營收", "上市櫃公司月營收。營收單位百萬元；偵測時間是程式第一次看到該公司申報的時間（誤差約 10 分鐘），不是正式公告時間。", [
  ...idCols, {k: "score", t: `AI ${tipBtn(SCALE_TIP + "\n\n" + RUBRIC_TIP.rev)}`, n: 1, f: scoreTag, s: r => r.score ?? -99},
  {k: "first_seen", t: "偵測時間", f: r => esc((r.first_seen || "").slice(5))},
  {k: "rev", t: "營收(M)", n: 1, f: r => r.rev == null ? "—" : fx(r.rev / 1000, 1)},
  {k: "mom", t: "MoM%", n: 1, f: r => pc(r.mom)}, {k: "yoy", t: "YoY%", n: 1, f: r => pc(r.yoy)}, {k: "cum_yoy", t: "累計 YoY%", n: 1, f: r => pc(r.cum_yoy)},
  {k: "note", t: "備註", w: 1, sortable: false, f: r => `<span class="why">${esc(r.note || "")}</span>`},
], {sort: ["first_seen", -1],
  groups: [["市場未反映（最近收盤後首次偵測）", r => !r.traded, "hot"], ["已反映", r => r.traded, ""]],
  filters: [["new", "僅新申報", r => r.new], ["ai", "有 AI 評分", r => r.score_src === "ai"], ["note", "有備註", r => !!r.note]],
  extraFilter: `<label class="numf">YoY &gt; <input type="number" id="fy" inputmode="numeric" aria-label="YoY 大於">%</label><label class="numf">MoM &gt; <input type="number" id="fm" inputmode="numeric" aria-label="MoM 大於">%</label>`,
  extraApply: (r, x) => (x.y == null || (r.yoy ?? -1e9) > x.y) && (x.m == null || (r.mom ?? -1e9) > x.m),
  extraBind: (x, apply) => {
    const on = (id, k) => document.getElementById(id).oninput = e => { const v = e.target.value; x[k] = v === "" ? null : +v; apply(); };
    on("fy", "y"); on("fm", "m");
  },
  expand: r => {
    const h = r.hist || [];
    const mx = Math.max(1, ...h.map(x => x[1] || 0));
    const bars = h.map(([ym, v]) => `<div class="rb"><div class="rbv" style="height:${Math.round((v || 0) / mx * 60)}px"></div><span>${esc(ym.slice(-2))}月</span><b>${fx((v || 0) / 1000, 0)}</b></div>`).join("");
    return `<div class="ann-detail"><h4>近幾個月營收（百萬）</h4>${h.length > 1 ? `<div class="revbars">${bars}</div>` : '<p class="muted small">歷史月營收會隨每月申報逐步累積。</p>'}
      ${r.why ? `<p class="small">評分理由：${esc(r.why)}</p>` : ""}<p class="small">${esc(r.note || "沒有備註")}</p></div>`;
  }});

P.treasury = () => annPage("treasury", "庫藏股", "董事會決議買回自家股票。進度取自公司公告的執行結果；期間尚未結束的進度可能還沒公告。", [
  {k: "market", t: "所", f: r => mk(r.market)}, ...idCols,
  {k: "purpose", t: "目的", f: r => `<span class="tag ${r.purpose === "銷除" ? "pur" : r.purpose === "護盤" ? "warn" : "ok"}">${esc(r.purpose || "—")}</span>`},
  {k: "lots", t: "預定(萬股)", n: 1, f: r => fx(r.lots, r.lots < 10 ? 1 : 0)},
  {k: "low", t: "價格區間", n: 1, f: r => r.low ? `${fp(r.low)}~${fp(r.high)}` : "—"},
  {k: "pos", t: "現價位置", n: 1, s: r => r.low && r.close ? (r.close - r.low) / (r.high - r.low) : null,
   f: r => r.low && r.close ? (r.close < r.low ? '<span class="tag up">低於下限</span>' : r.close > r.high ? '<span class="muted">高於上限</span>' : `區間 ${Math.round((r.close - r.low) / (r.high - r.low) * 100)}%`) : "—"},
  {k: "start", t: "期間", f: r => r.start ? `${md(r.start)}~${md(r.end)}` : "—"},
  {k: "progress", t: "進度", n: 1, s: r => r.progress ?? -1, f: r => r.progress == null ? '<span class="muted">—</span>' : `<span class="prog"><i style="width:${Math.min(100, r.progress)}%"></i></span> ${r.progress}%`},
  {k: "board", t: "決議日", f: r => md(r.board || r.date)}, ...pxCols,
], {sort: ["board", -1],
  groups: [["市場未反映（最近收盤後決議）", r => !r.traded, "hot"], ["執行中", r => r.traded && r.status !== "完成", ""], ["近期完成", r => r.traded && r.status === "完成", ""]],
  filters: [["emp", "員工", r => r.purpose === "員工"], ["cut", "銷除", r => r.purpose === "銷除"], ["def", "護盤", r => r.purpose === "護盤"], ["below", "低於區間下限", r => r.close && r.low && r.close < r.low]],
  expand: r => rawBlock(r, r.done_body ? `<h4>執行結果（${esc(r.done_date || "")}）</h4><pre class="raw">${esc(r.done_body)}</pre>` : "")});

P.events = async () => {
  await annPage("events", "事件", "財報董事會、法說會、除權息的日期，以及從宣布日到現在的股價變化。日期由程式從公告原文抽取。", [
    {k: "from", t: "預定", f: r => r.to && r.to !== r.from ? `${md(r.from)}-${md(r.to)}` : md(r.from), s: r => r.from},
    {k: "kind", t: "類", f: r => `<span class="tag ev-${esc(r.kind)}">${esc(r.kind)}</span>`},
    ...idCols,
    {k: "ann_close", t: "宣布日股價", n: 1, f: r => r.ann_close ? `${fp(r.ann_close)} <span class="muted small">${md(r.ann_day || "")}</span>` : "—"},
    {k: "close", t: "目前股價", n: 1, f: r => r.close ? `${fp(r.close)} <span class="muted small">+${r.days_since ?? 0} 日</span>` : "—"},
    {k: "chg_since", t: "宣布後漲跌", n: 1, f: r => pc(r.chg_since)},
  ], {sort: ["from", 1],
    groups: [["即將舉行", r => r.upcoming, "hot"], ["近 10 天已舉行", r => !r.upcoming, ""]],
    filters: [["財", "財報", r => r.kind === "財"], ["法", "法說", r => r.kind === "法"], ["權", "除權", r => r.kind.includes("權")], ["息", "除息", r => r.kind.includes("息")]],
    expand: r => rawBlock(r),
    foot: "資料來源：公開資訊觀測站重大訊息、證交所與櫃買中心除權除息預告表。宣布日股價＝公告當天（或之前最近一個交易日）的收盤。"});
  const js = await load("announce/others.json");
  const items = js?.items || [];
  const sec = document.createElement("section");
  sec.innerHTML = `<h2>其他重大訊息 <span class="muted small">（近 ${items.length} 筆，依主旨分類）</span></h2><div class="toolbar"><span class="chips" id="of"></span></div><div id="ot"></div>`;
  app.append(sec);
  let k = "";
  const t = table(document.getElementById("ot"), [timeCol, ...idCols, {k: "kind", t: "類別", f: r => `<span class="tag">${esc(r.kind)}</span>`},
    {k: "subject", t: "主旨", w: 1}, ...pxCols, {k: "traded", t: "反應", f: r => r.traded ? '<span class="muted">已交易</span>' : '<span class="tag warn">未反映</span>', s: r => r.traded ? 1 : 0}],
    items, {sort: ["time", -1], expand: r => rawBlock(r), id: r => r.key});
  const kinds = [...new Set(items.map(x => x.kind))];
  chips(document.getElementById("of"), [["", "全部"], ...kinds.map(x => [x, x])], "", v => { k = v; t.set(items.filter(x => !k || x.kind === k)); });
};

P.borrow = async () => {
  setTitle("券差借券費率");
  const js = await load("borrow.json");
  app.innerHTML = `<h1>券差借券費率</h1>
    <p class="sub">應付現股當日沖銷券差的借券費率，上市與上櫃合併。費率是借券人付給出借人的日費率（非年化），越高代表券源越稀缺。${js ? `資料日 ${js.date}。` : ""}</p>
    <h2>每檔彙總</h2><div id="s"></div><h2>原始明細</h2><div id="d"></div>`;
  if (!js) return;
  const by = {};
  js.detail.forEach(r => (by[r.code] ||= []).push(r));
  table(document.getElementById("s"), [
    {k: "code", t: "代號"}, {k: "name", t: "名稱", f: r => stockLink(r.code, r.name)}, {k: "market", t: "所", f: r => mk(r.market)},
    {k: "close", t: "股價", n: 1, f: r => fp(r.close)}, {k: "chg", t: "漲幅", n: 1, f: r => pc(r.chg)},
    {k: "lots_traded", t: "成交量(張)", n: 1, f: r => fi(r.lots_traded)}, {k: "lots", t: "借量(張)", n: 1, f: r => fx(r.lots, 0)},
    {k: "avg_rate", t: "均費率", n: 1, f: r => `<b>${fx(r.avg_rate, 2)}%</b>`}, {k: "min_rate", t: "最低", n: 1, f: r => fx(r.min_rate) + "%"},
    {k: "max_rate", t: "最高", n: 1, f: r => fx(r.max_rate) + "%"}, {k: "n", t: "筆", n: 1},
  ], js.summary, {sort: ["avg_rate", -1], id: r => r.code, empty: "今日沒有券差借券",
    expand: r => `<table><thead><tr><th>借張</th><th>費率</th></tr></thead><tbody>${by[r.code].map(x => `<tr><td>${fx(x.lots, 0)}</td><td>${fx(x.rate)}%</td></tr>`).join("")}</tbody></table>`});
  table(document.getElementById("d"), [
    {k: "date", t: "日期"}, {k: "code", t: "代號"}, {k: "name", t: "名稱", f: r => stockLink(r.code, r.name)}, {k: "market", t: "所", f: r => mk(r.market)},
    {k: "close", t: "股價", n: 1, f: r => fp(r.close)}, {k: "chg", t: "漲幅", n: 1, f: r => pc(r.chg)},
    {k: "lots_traded", t: "成交量", n: 1, f: r => fi(r.lots_traded)}, {k: "lots", t: "借張", n: 1, f: r => fx(r.lots, 0)}, {k: "rate", t: "費率", n: 1, f: r => fx(r.rate) + "%"},
  ], js.detail, {sort: ["rate", -1]});
};

// ---- 處置 ----
const COND = {c1: "連續3日第1款", any: "連續5日（第1~8款）", w10: "10日內6次", w30: "30日內12次"};
const prog = ([a, b]) => `<span class="prog" aria-label="${a}/${b}">${Array.from({length: b}, (_, i) => `<i class="${i < a ? "f" : ""}"></i>`).join("")}</span> <span class="small">${a}/${b}</span>`;
function trig(o, dir) {
  if (!o) return "—";
  if (o.status === "跌停仍符合" || o.status === "漲停仍符合") return `<span class="warn">${o.status}</span>`;
  if (o.status === "明日不可達" || o.status === "資料不足" || o.status === "歷史不足") return `<span class="muted">${o.status}</span>`;
  return `<b>${fp(o.price)}</b> ${dir}${pc(o.pct, 1)}`;
}
const XOK = ["可能", "跌停仍符合", "漲停仍符合"];
function pcTxt(p) {
  if (!p) return "—";
  if (p.status === "跌停仍符合" || p.status === "漲停仍符合") return `<span class="warn">${p.status}</span>`;
  if (p.status === "明日不可達") return `<span class="muted">需${p.dir === "up" ? "≥" : "≤"}${fp(p.price)}，明日不可達</span>`;
  return `收盤${p.dir === "up" ? "≥" : "≤"}<b>${fp(p.price)}</b> ${pc(p.pct, 1)}`;
}
function xTag(st) {
  if (XOK.includes(st)) return `<span class="tag up">可能</span>`;
  if (st === "需集中度") return `<span class="tag warn">看集中度</span>`;
  return `<span class="tag">${esc(st || "—")}</span>`;
}
// 同類股（同產業）平均：有比就顯示數字，依規定不比時顯示原因
const indTxt = x => !x || x.ind === undefined ? "" : x.ind_skip ? `；同類股（${esc(x.ind || "—")}）不比：${esc(x.ind_skip)}` : `，同類股（${esc(x.ind)}，${x.ind_n} 家）平均 ${pc(x.ind_avg)}`;
function dispX(c) {
  const c3 = c.c3 || {}, c4 = c.c4 || {}, c6 = c.c6 || {}, c7 = c.c7 || {};
  const p = c3.price || c4.price || c7.price;
  const pTxt = p ? `<p class="small muted">價格條件：6 日累積漲跌超過 ${p.th}% 且與全體平均、同類股平均都差 20 個百分點以上（起點 ${md(p.base_date)} 收 ${fp(p.base)}，目前 ${pc(p.cum)}${p.mkt != null ? `；全體平均 ${pc(p.mkt)}` : ""}${indTxt(p)}）</p>` : "";
  return `<div><h4>③ 量放大 ${xTag(c3.status)}</h4>${c3.lots ? `<p>${pcTxt(c3.price)}</p><p>量 ≥ <b>${fi(c3.lots)}</b> 張（60 日均量 ${fi(c3.avg60)} 張的 ${c3.mult} 倍；全市場今日 ${c3.mkt_mult} 倍）</p><p class="small muted">今日為均量 ${c3.today_mult} 倍</p>` : "<p class='muted'>資料不足</p>"}${pTxt}</div>
    <div><h4>④ 週轉率 ${xTag(c4.status)}</h4>${c4.lots ? `<p>${pcTxt(c4.price)}</p><p>量 ≥ <b>${fi(c4.lots)}</b> 張（週轉率 ≥ ${c4.to}%；全市場平均 ${c4.mkt_to}%）</p><p class="small muted">今日週轉率 ${c4.today_to}%</p>` : "<p class='muted'>資料不足</p>"}</div>
    <div><h4>⑤ 單一券商占比</h4><p class="muted">需要全市場每檔股票的券商分點資料（櫃買分點有真人驗證、上市每檔都要解驗證碼），無法每天估算。</p></div>
    <div><h4>⑥ 本益比／淨值比 ${xTag(c6.status)}</h4>${c6.price ? `<p>${c6.status === "跌停仍符合" ? "本益比、淨值比已達標（跌停仍符合）" : `收盤 ≥ <b>${fp(c6.price)}</b> ${pc(c6.pct, 1)}`}，量 ≥ ${fi(c6.lots)} 張</p>
      <p class="small">本益比 ${c6.loss ? "虧損（已符合）" : `${c6.pe} → 需 ≥ ${c6.pe_th}`}；淨值比 ${c6.pb} → 需 ≥ ${c6.pb_th}</p>
      <p class="small muted">另需：淨值比 ≥ 產業平均${c6.ind_pb ? ` ${c6.ind_pb}` : ""} 的 ${c6.ind_mult} 倍，或單一券商／投資人成交占比過高${c6.status === "需集中度" ? "（產業條件達不到，只剩集中度，無法估算）" : ""}</p>` : `<p class="muted">${esc(c6.status || "資料不足")}</p>`}</div>
    <div><h4>⑦ 券資比 ${xTag(c7.status)}</h4>${c7.ratio != null ? `<p>今日券資比 ${c7.ratio}%（6 日最低 ${c7.min6 ?? "—"}%），融資使用率 ${c7.fin_use}%、融券使用率 ${c7.short_use}%</p>
      ${c7.fails?.length ? `<p class="small muted">未達：${c7.fails.map(esc).join("、")}</p>` : `<p>融資券條件已符合，${pcTxt(c7.price)}</p>`}` : `<p class="muted">${esc(c7.status || "資料不足")}</p>`}</div>`;
}
function dispDetail(c) {
  const c1 = c.c1;
  return `<div class="detail-grid">
    <div><h4>處置進度</h4>${Object.entries(COND).map(([k, v]) => `<p>${v}：${prog(c.progress[k])}</p>`).join("")}</div>
    <div><h4>第一款（6 日累積漲跌）</h4>${c1 ? `<p>起點 ${c1.base_date} 收 ${fp(c1.base)}，目前累積 ${pc(c1.cum)}，同期全體平均 ${pc(c1.mkt)}${indTxt(c1)}</p>
      <p class="small muted">需超過門檻，且與全體平均、同類股平均的差都 ≥ 20 個百分點</p>
      <p>往上觸發：${trig(c1.up, "↑")}</p><p>往下觸發：${trig(c1.down, "↓")}</p>` : "<p class='muted'>歷史資料不足 6 日</p>"}</div>
    <div><h4>第二款（30/60/90 日）</h4>${c.c2.map(x => `<p>${x.days} 日（門檻 ${x.th}%）：${x.cum != null ? `累積 ${pc(x.cum, 1)}，` : ""}${trig(x, "↑")}${x.mkt != null ? `<br><span class="small muted">全體平均 ${pc(x.mkt)}${indTxt(x)}，差幅需 ≥ ${x.gap}%</span>` : ""}</p>`).join("")}</div>
    <div><h4>明日價格範圍</h4><p>平盤 ${fp(c.limits.flat)}，漲停 ${fp(c.limits.up)}，跌停 ${fp(c.limits.down)}</p>
      <p>本益比 ${c.pe ?? "虧損或無"}，淨值比 ${c.pb ?? "—"}</p></div>
    <div><h4>注意股紀錄</h4><p>${c.record.map(r => `${md(r.date)}（第${r.clauses.join("、")}款）`).join("，")}</p></div>
    ${dispX(c)}
  </div>`;
}
P.disposal = async () => {
  setTitle("處置預測");
  const js = await load("disposal.json");
  if (!js) { app.innerHTML = `<h1>處置預測</h1>${emptyBox("尚未產生")}`; return; }
  app.innerHTML = `<h1>明日處置預測</h1>
    <p class="sub">適用 ${js.target} 交易日。依注意股累計次數判斷還差幾次會被處置，並估算第一～四、六、七款的明日觸發條件（點一檔看細節）。條件為程式估算，不是交易所預告。${js.margin_date ? "" : "<br><span class=\"warn\">今日融資融券尚未公布，第七款暫無法判斷。</span>"}</p>
    <div class="panel"><div class="row" style="justify-content:space-between"><h2 style="margin:0">LINE 轉貼版</h2><button class="btn" id="cp" type="button">複製文字</button></div>
      <pre class="copy">${esc(js.line_text)}</pre></div>
    <h2><span class="up">差 1 次就處置</span>（${js.minus1.length} 檔）</h2><div id="m1"></div>
    <h2><span class="warn">差 2 次</span>（${js.minus2.length} 檔）</h2><div id="m2"></div>
    <h2>目前處置中（${js.current.length} 檔）</h2><div id="cur"></div>
    <div class="notice">處置期間通常改為分盤集合競價（每數分鐘撮合一次），且買賣需預收款券。實際條件與期間以交易所、櫃買中心公告為準。</div>`;
  document.getElementById("cp").onclick = () => copy(js.line_text);
  const cols = [
    {k: "market", t: "所", f: r => mk(r.market)}, {k: "code", t: "代號"}, {k: "name", t: "名稱", f: r => stockLink(r.code, r.name)},
    {k: "close", t: "收盤", n: 1, f: r => fp(r.close)}, {k: "main", t: "最接近的條件", f: r => esc(COND[r.main])},
    {k: "c1u", t: "第一款觸發", s: r => r.c1?.up?.pct, f: r => r.c1 ? (["可能", "跌停仍符合"].includes(r.c1.up.status) ? trig(r.c1.up, "↑") : ["可能", "漲停仍符合"].includes(r.c1.down.status) ? trig(r.c1.down, "↓") : '<span class="muted">明日不符合</span>') : "—"},
    {k: "xs", t: "其他款", sortable: false, f: r => ["c3", "c4", "c6", "c7"].filter(k => XOK.includes(r[k]?.status) || r[k]?.status === "需集中度").map(k => `<span class="tag ${r[k].status === "需集中度" ? "" : "up"}">${"③④⑤⑥⑦"["c3c4c5c6c7".indexOf(k) / 2]}</span>`).join(" ") || '<span class="muted">—</span>'},
    {k: "earliest", t: "最快處置", f: r => `${md(r.earliest)} 第${r.times}次`},
    {k: "p1", t: "連3①", f: r => prog(r.progress.c1), sortable: false}, {k: "p2", t: "連5", f: r => prog(r.progress.any), sortable: false},
    {k: "p3", t: "10日6次", f: r => prog(r.progress.w10), sortable: false}, {k: "p4", t: "30日12次", f: r => prog(r.progress.w30), sortable: false},
  ];
  table(document.getElementById("m1"), cols, js.minus1, {expand: dispDetail, id: r => r.code, empty: "沒有差 1 次就處置的股票"});
  table(document.getElementById("m2"), cols, js.minus2, {expand: dispDetail, id: r => r.code, empty: "沒有差 2 次的股票"});
  table(document.getElementById("cur"), [
    {k: "market", t: "所", f: r => mk(r.market)}, {k: "code", t: "代號"}, {k: "name", t: "名稱", f: r => stockLink(r.code, r.name)},
    {k: "minutes", t: "撮合", f: r => r.minutes ? `${r.minutes} 分` : "—"}, {k: "start", t: "開始", f: r => md(r.start)}, {k: "end", t: "結束", f: r => md(r.end)},
    {k: "exit", t: "出關日", f: r => md(r.exit)}, {k: "remain", t: "剩餘交易日", n: 1, f: r => r.remain ? r.remain + " 天" : '<span class="tag down">出關</span>'},
    {k: "reason", t: "處置原因", w: 1, f: r => `${esc(r.reason)}｜第${r.times}次處置`},
  ], js.current, {sort: ["exit", 1]});
};

// ---- 主動 ETF ----
P.etf = async () => {
  setTitle("主動 ETF 持股異動");
  const js = await load("etf.json");
  if (!js || !js.funds.length) { app.innerHTML = `<h1>主動 ETF</h1><p class="sub">還沒有持股資料。把投信下載的持股檔放到 <code>data/etf_inbox/代號_YYYYMMDD.csv</code>，或在 <code>pipeline/active_etf.py</code> 加入自動抓取。</p>`; return; }
  const T = js.totals;
  let sel = "";
  app.innerHTML = `<h1>主動 ETF 持股異動</h1>
    <p class="sub">各檔主動式股票 ETF 最新揭露持股與前一次比較。變動金額以揭露日成交均價估算。揭露日期範圍 ${js.range[0]}～${js.range[1]}。</p>
    <div class="kpis"><div class="kpi"><div class="l">合計買進</div><div class="v up">${yi(T.buy)}</div></div>
      <div class="kpi"><div class="l">合計賣出</div><div class="v down">${yi(T.sell)}</div></div>
      <div class="kpi"><div class="l">買賣超</div><div class="v ${sign(T.net)}">${yi(T.net)}</div></div>
      <div class="kpi"><div class="l">基金數</div><div class="v">${js.funds.length}</div></div></div>
    <h2>股票總表</h2><p class="small muted">點一檔股票，下方持股明細只顯示持有它的基金。</p><div id="s"></div>
    <h2>持股明細 <span id="selname" class="muted small"></span></h2>
    <div class="toolbar"><span class="chips" id="fund"></span><button class="btn ghost" id="clr" type="button" hidden>清除股票篩選</button></div><div id="h"></div>
    <h2>各基金買賣概況</h2><div id="f"></div>`;
  let fund = "";
  const ht = table(document.getElementById("h"), [
    {k: "fund", t: "基金", f: r => `${esc(r.fund)} <span class="muted small">${esc(r.fund_name !== r.fund ? r.fund_name : "")}</span>`},
    {k: "name", t: "股票", f: r => `${stockLink(r.code, r.name)} <span class="muted small">${r.code}</span>`},
    {k: "weight", t: "比例", n: 1, f: r => r.weight == null ? "—" : fx(r.weight) + "%"}, {k: "lots", t: "張數", n: 1, f: r => fi(r.lots)},
    {k: "mv", t: "估市值", n: 1, f: r => yi(r.mv)}, {k: "delta_amt", t: "變動估金額", n: 1, f: r => `<span class="${sign(r.delta_amt)}">${r.delta_amt ? yi(r.delta_amt) : "—"}</span>`},
    {k: "delta_lots", t: "變動張數", n: 1, f: r => r.delta_lots ? `<span class="${sign(r.delta_lots)}">${r.delta_lots > 0 ? "+" : ""}${fi(r.delta_lots)}</span>` : "—"},
    {k: "status", t: "", f: r => r.status ? `<span class="tag ${r.status === "新增" ? "up" : "down"}">${r.status}</span>` : ""},
    {k: "cap_ratio", t: "△股本比", n: 1, f: r => r.cap_ratio ? fx(r.cap_ratio, 3) + "%" : "—"}, {k: "chg", t: "日漲跌", n: 1, f: r => pc(r.chg)},
  ], js.holdings, {sort: ["delta_amt", -1]});
  const apply = () => {
    ht.set(js.holdings.filter(r => (!sel || r.code === sel) && (!fund || r.fund === fund)));
    document.getElementById("clr").hidden = !sel;
    const s = js.stocks.find(x => x.code === sel);
    document.getElementById("selname").textContent = s ? `${s.name}（${s.code}）` : "";
  };
  table(document.getElementById("s"), [
    {k: "name", t: "股票", f: r => `${esc(r.name)} <span class="muted small">${r.code}</span>`}, {k: "n_funds", t: "持有基金數", n: 1},
    {k: "buy", t: "買進", n: 1, f: r => r.buy ? `<span class="up">${yi(r.buy)}</span>` : "—"}, {k: "sell", t: "賣出", n: 1, f: r => r.sell ? `<span class="down">${yi(r.sell)}</span>` : "—"},
    {k: "net", t: "買賣超", n: 1, f: r => `<span class="${sign(r.net)}">${r.net ? yi(r.net) : "—"}</span>`},
    {k: "net_lots", t: "淨張數", n: 1, f: r => fi(r.net_lots)}, {k: "close", t: "股價", n: 1, f: r => fp(r.close)}, {k: "chg", t: "日漲跌", n: 1, f: r => pc(r.chg)},
  ], js.stocks, {sort: ["net", -1], id: r => r.code, rowClick: r => { sel = r.code; apply(); document.getElementById("h").scrollIntoView({behavior: "smooth", block: "start"}); }});
  document.getElementById("clr").onclick = () => { sel = ""; apply(); };
  chips(document.getElementById("fund"), [["", "全部基金"], ...js.funds.map(f => [f.code, f.code])], "", v => { fund = v; apply(); });
  table(document.getElementById("f"), [
    {k: "code", t: "代號"}, {k: "name", t: "名稱"}, {k: "date", t: "揭露日"}, {k: "prev", t: "比較日", f: r => r.prev || "首次"},
    {k: "n", t: "持股數", n: 1}, {k: "buy", t: "買進", n: 1, f: r => `<span class="up">${yi(r.buy)}</span>`},
    {k: "sell", t: "賣出", n: 1, f: r => `<span class="down">${yi(r.sell)}</span>`}, {k: "net", t: "買賣超", n: 1, f: r => `<span class="${sign(r.net)}">${yi(r.net)}</span>`},
  ], js.funds, {sort: ["net", -1]});
};

// ---- 個股 ----
P.stock = async (code) => {
  const hist = await load("stock_history.json") || {};
  setTitle(code ? `${code} 個股` : "個股查詢");
  if (!code) {
    const list = Object.entries(hist).sort((a, b) => b[1].events.length - a[1].events.length).slice(0, 40);
    app.innerHTML = `<h1>個股查詢</h1><p class="sub">輸入代號，看這檔股票的漲停紀錄、隔日表現、處置與公告。</p>
      <form id="sf" class="toolbar"><input type="search" id="sq" placeholder="例如 2330" aria-label="股票代號" inputmode="numeric"><button class="btn">查詢</button></form>
      <h2>最常漲停</h2><div class="chips">${list.map(([c, h]) => `<a class="chip" href="#/stock/${c}">${esc(h.name)} ${c}<span class="muted">（${h.events.length}）</span></a>`).join("")}</div>`;
    document.getElementById("sf").onsubmit = e => { e.preventDefault(); const v = document.getElementById("sq").value.trim(); if (v) location.hash = `#/stock/${v}`; };
    return;
  }
  const h = hist[code];
  const [disp, att, rev, ev, tr] = await Promise.all([load("disposal.json"), load("announce/att.json"), load("announce/rev.json"), load("announce/events.json"), load("announce/treasury.json")]);
  const dc = [...(disp?.minus1 || []), ...(disp?.minus2 || [])].find(x => x.code === code);
  const cur = (disp?.current || []).find(x => x.code === code);
  const mine = [...(att?.items || []), ...(rev?.items || []), ...(ev?.items || []), ...(tr?.items || [])].filter(x => x.code === code);
  const name = h?.name || mine[0]?.name || dc?.name || cur?.name || "";
  app.innerHTML = `<h1>${esc(name)} <span class="muted">${esc(code)}</span></h1>
    <p class="sub">${h ? `近期共 ${h.events.length} 次漲停。` : "近期沒有漲停紀錄。"}${cur ? ` <span class="tag warn">處置中，${md(cur.exit)} 出關</span>` : ""}${dc ? ` <span class="tag up">差 ${dc.need} 次就處置</span>` : ""}</p>
    <h2>漲停紀錄</h2><div id="e"></div>
    ${dc ? `<h2>處置預測</h2><div class="panel">${dispDetail(dc)}</div>` : ""}
    <h2>近期公告</h2><div id="a"></div>`;
  table(document.getElementById("e"), [
    {k: "date", t: "漲停日", f: r => `<a href="#/daily/${r.date}">${r.date}</a>`}, {k: "theme", t: "族群"},
    {k: "streak", t: "連板", n: 1}, {k: "close", t: "漲停價", n: 1, f: r => fp(r.close)},
    {k: "nd_open", t: "隔日開", n: 1, f: r => pc(r.nd_open)}, {k: "nd_close", t: "隔日收", n: 1, f: r => pc(r.nd_close)},
    {k: "tag", t: "隔日走勢", f: r => r.tag ? `<span class="tag">${esc(r.tag)}</span>` : "—"},
  ], h?.events || [], {sort: ["date", -1], empty: "沒有漲停紀錄"});
  table(document.getElementById("a"), [
    {k: "date", t: "日期", f: r => `${r.date || ""} ${r.time || ""}`}, {k: "subject", t: "內容", w: 1, f: r => esc(r.subject || (r.ym ? `${r.ym} 營收年增 ${r.yoy}%、月增 ${r.mom}%` : ""))},
  ], mine, {empty: "近期沒有公告"});
};

// ---------------- router ----------------
const routes = {"": P.home, daily: P.daily, nextday: P.nextday, stats: P.stats, commentary: P.commentary,
  att: P.att, fin: P.fin, rev: P.rev, treasury: P.treasury, events: P.events, borrow: P.borrow, disposal: P.disposal, etf: P.etf, stock: P.stock};
async function route() {
  const [path] = location.hash.replace(/^#\/?/, "").split("?");
  const [name, arg] = path.split("/");
  const fn = routes[name] || P.home;
  document.querySelectorAll("nav.main a").forEach(a => a.classList.toggle("on", a.getAttribute("href") === "#/" + name));
  app.innerHTML = '<p class="muted">載入中…</p>';
  try { await fn(arg ? decodeURIComponent(arg) : undefined); }
  catch (e) { console.error(e); app.innerHTML = `<h1>這一頁載入失敗</h1><p class="sub">${esc(e.message)}。重新整理頁面，或確認資料流程是否正常執行。</p>`; }
  window.scrollTo(0, 0);
}

// theme toggle
const tb = document.getElementById("themeBtn");
try { const t = localStorage.getItem("theme"); if (t) document.documentElement.dataset.theme = t; } catch {}
tb.onclick = () => {
  const dark = document.documentElement.dataset.theme ? document.documentElement.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  document.documentElement.dataset.theme = dark ? "light" : "dark";
  try { localStorage.setItem("theme", document.documentElement.dataset.theme); } catch {}
};

/* 簡單密碼頁：gate.json 由部署流程依 GitHub Secret SITE_PASSWORD 產生（只放雜湊）。
   沒設密碼時 gate.json 為空，網站照常開放。這是擋一般訪客用，不是真正的帳號安全。 */
async function sha256(t) {
  const b = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(t));
  return [...new Uint8Array(b)].map(x => x.toString(16).padStart(2, "0")).join("");
}
async function gate() {
  let g = {};
  try { const r = await fetch("gate.json", {cache: "no-cache"}); if (r.ok) g = await r.json(); } catch {}
  if (!g.h) return;
  let saved = "";
  try { saved = localStorage.getItem("gate") || sessionStorage.getItem("gate") || ""; } catch {}
  if (saved === g.h) return;
  document.body.classList.add("locked");
  const box = document.createElement("div");
  box.className = "gate";
  box.innerHTML = `<form class="gate-card" autocomplete="on">
      <h1>盤後雷達</h1><p class="sub">請輸入密碼</p>
      <input type="password" id="gp" autocomplete="current-password" aria-label="密碼" required autofocus>
      <label class="small"><input type="checkbox" id="gr" checked> 這台裝置記住我</label>
      <button class="btn" type="submit">進入</button><p class="small up" id="ge" role="alert"></p></form>`;
  document.body.appendChild(box);
  await new Promise(done => {
    box.querySelector("form").onsubmit = async e => {
      e.preventDefault();
      const h = await sha256("twradar:" + document.getElementById("gp").value);
      if (h !== g.h) { document.getElementById("ge").textContent = "密碼不正確"; return; }
      try { (document.getElementById("gr").checked ? localStorage : sessionStorage).setItem("gate", h); } catch {}
      box.remove(); document.body.classList.remove("locked"); done();
    };
  });
}

(async () => {
  await gate();
  META = await load("meta.json") || {};
  if (META.site_name) { document.getElementById("siteName").textContent = META.site_name; }
  document.getElementById("mockbar").hidden = !META.mock;
  const j = META.jobs || {};
  document.getElementById("updated").textContent = Object.keys(j).length ? "最近更新：" + Object.entries(j).filter(([k]) => k !== "mock").map(([k, v]) => `${({daily: "漲停", disposal: "處置", announce: "公告", borrow: "券差", etf: "主動ETF", backfill: "補資料"})[k] || k} ${v}`).join("，") : "";
  window.addEventListener("hashchange", route);
  route();
})();
})();

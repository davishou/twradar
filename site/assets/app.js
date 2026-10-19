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
    if (e.target.closest("a")) return;
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
    <a href="#/daily"><b>當日漲停族群</b><span>每檔歸到哪個題材、量比、連板數</span></a>
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
    <p class="small muted">族群來源：<span class="tsrc">設定</span> themes.json 指定、<span class="tsrc ai">AI</span> AI 判斷後寫回 themes.json、<span class="tsrc">關鍵字</span>、<span class="tsrc">產業別</span> 官方產業別。法人單位為張；量比為成交量除以前 5 日均量。</p>
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
    {k: "vol_ratio", t: "量比", n: 1, f: r => r.vol_ratio == null ? "—" : fx(r.vol_ratio, 1) + "x"},
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
const PL_TIP = "以收盤價計算：賣出金額 − 買進金額 ＋ 未沖銷張數 × 收盤價，未扣手續費與證交稅";
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
  const dt = B.filter(x => x.b && x.s).map(x => ({...x, dq: Math.min(x.b, x.s), pl: (x.s * x.sa - x.b * x.ba + (x.b - x.s) * bk.close) * 1000}))
    .sort((a, c) => c.dq - a.dq).slice(0, 10);
  return `<h3 class="bk-dt">${title}</h3>
    <div class="tw"><table><thead><tr><th scope="col">券商</th><th class="n" scope="col">交易張數</th><th class="n" scope="col">總損益 <span class="info" title="${PL_TIP}" aria-label="${PL_TIP}">ⓘ</span></th><th class="n" scope="col">買張數</th><th class="n" scope="col">買均價</th><th class="n" scope="col">賣張數</th><th class="n" scope="col">賣均價</th><th class="n" scope="col">留倉</th><th class="n" scope="col">當沖比</th></tr></thead>
    <tbody>${dt.map(x => `<tr data-n="${esc(x.n)}"><td>${esc(x.n)}</td><td class="n">${fi(x.tot)}</td><td class="n ${sign(x.pl)}">${sgnI(x.pl)}</td><td class="n up">${fi(x.b)}</td><td class="n">@${p2(x.ba)}</td><td class="n down">${fi(x.s)}</td><td class="n">@${p2(x.sa)}</td><td class="n ${sign(x.net)}">${sgnI(x.net)}</td><td class="n">${Math.round(x.dt * 100)}%</td></tr>`).join("") || '<tr><td colspan="9" class="muted">沒有同時買賣的券商</td></tr>'}</tbody></table></div>
    <p class="small muted">排序依當沖張數（買進與賣出較小的一方）。總損益${PL_TIP.slice(2)}。當沖比＝較小方 ÷ 較大方。</p>`;
}
function allHTML(B, key) {
  const rows = B.slice().sort((a, c) => key === "net" ? c.net - a.net : key === "dt" ? c.dt - a.dt : c.tot - a.tot).slice(0, 30);
  const hb = (k, t) => `<button type="button" class="sortbtn" data-sort="${k}" aria-pressed="${key === k}">${t}${key === k ? " ▼" : ""}</button>`;
  return `<div class="tw"><table><thead><tr><th scope="col">券商</th><th class="n" scope="col">${hb("tot", "成交張數")}</th><th class="n" scope="col">買進</th><th class="n" scope="col">賣出</th><th class="n" scope="col">${hb("net", "買賣超")}</th><th class="n" scope="col">買均</th><th class="n" scope="col">賣均</th><th class="n" scope="col">${hb("dt", "當沖比")}</th></tr></thead>
    <tbody>${rows.map(x => `<tr data-n="${esc(x.n)}"><td>${esc(x.n)}</td><td class="n">${fi(x.tot)}</td><td class="n">${fi(x.b)}</td><td class="n">${fi(x.s)}</td><td class="n ${sign(x.net)}">${sgnI(x.net)}</td><td class="n">${p2(x.ba)}</td><td class="n">${p2(x.sa)}</td><td class="n ${x.dt >= .8 ? "" : "muted"}">${x.dt ? Math.round(x.dt * 100) + "%" : "—"}</td></tr>`).join("")}</tbody></table></div>`;
}
const LEGEND = `<div class="bk-legend"><span><i class="dot up"></i>買進</span><span><i class="dot down"></i>賣出</span>
  <span><i class="ln gold"></i>金線：同一券商又買又賣，賣均高於買均（有價差）</span><span><i class="ln silver"></i>銀線：賣均不高於買均</span>
  <span>線越粗＝當沖比越高</span><span><i class="ln avg"></i>全日均價</span></div>`;

/* refs: [{v, label, cls}] 右側價位標記；隔日頁用來標開盤/均價/收盤 */
function bubbleSVG(bk, B, refs = []) {
  const W = 1000, H = 480, ml = 74, mr = refs.length ? 96 : 24, mt = 26, mb = 44, cx = ml + (W - ml - mr) / 2, half = (W - ml - mr) / 2 - 34;
  const top = B.slice().sort((a, c) => c.tot - a.tot).slice(0, 40);
  const maxV = Math.max(1, ...top.map(x => Math.max(x.b, x.s)));
  const X = (v, side) => cx + side * (8 + Math.sqrt(v / maxV) * half);
  const R = v => 3 + Math.sqrt(v / maxV) * 24;
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
  if (vw && !refs.length) g += `<line class="vw" x1="${ml}" x2="${W - mr}" y1="${Y(vw)}" y2="${Y(vw)}"/><text class="vwt" x="${W - mr - 4}" y="${Y(vw) - 5}" text-anchor="end">全日均價 ${fx(vw, 2)}</text>`;
  // 右側價位標記（避免文字重疊）
  let lastY = -99;
  refs.slice().sort((a, c) => Y(a.v) - Y(c.v)).forEach(r => {
    const y = Y(r.v), ty = Math.max(y + 4, lastY + 13); lastY = ty;
    g += `<line class="ref ${r.cls}" x1="${W - mr}" x2="${W - mr + 8}" y1="${y}" y2="${y}"/><text class="reft ${r.cls}" x="${W - mr + 12}" y="${ty}">${r.label} ${fp(r.v)}</text>`;
    if (r.cls === "avg") g += `<line class="vw" x1="${ml}" x2="${W - mr}" y1="${y}" y2="${y}"/>`;
  });
  g += `<text class="side up" x="${ml + 8}" y="${mt + 4}">← 買進</text><text class="side down" x="${W - mr - 8}" y="${mt + 4}" text-anchor="end">賣出 →</text>`;
  const links = [], dots = [], labels = [];
  top.forEach(x => {
    const a = x.b ? {cx: X(x.b, -1), cy: Y(x.ba), r: R(x.b)} : null, c = x.s ? {cx: X(x.s, 1), cy: Y(x.sa), r: R(x.s)} : null;
    const n = esc(x.n);
    if (a && c) links.push(`<line class="lk ${x.sa > x.ba ? "gold" : "silver"}" data-n="${n}" x1="${a.cx.toFixed(1)}" y1="${a.cy.toFixed(1)}" x2="${c.cx.toFixed(1)}" y2="${c.cy.toFixed(1)}" style="stroke-width:${(.8 + x.dt * 2.4).toFixed(2)};opacity:${(.3 + x.dt * .6).toFixed(2)}"/>`);
    [[a, "b"], [c, "s"]].forEach(([p, sd]) => { if (!p) return;
      dots.push([p.r, `<circle class="bb ${sd}" data-n="${n}" cx="${p.cx.toFixed(1)}" cy="${p.cy.toFixed(1)}" r="${p.r.toFixed(1)}"/>`]);
      labels.push(`<text class="lb" data-n="${n}" x="${p.cx.toFixed(1)}" y="${(p.cy - p.r - 4).toFixed(1)}" text-anchor="middle">${n}</text>`); });
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
    box.innerHTML = `<h2 class="bk-title">${title}</h2><div class="empty">沒有漲停日 ${esc(nd.limit_date)} 的分點資料（分點從開始抓取的那天才有，且只能在收盤當天抓）。</div>`;
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
      <td class="n">${p2(y.sa)}</td><td class="n down">${fi(y.s)}</td><td class="n up">${fi(y.b)}</td><td class="n">${p2(y.ba)}</td><td class="n">${y.s ? Math.round(out * 100) + "%" : "—"}</td></tr>`;
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

P.nextday = async (date) => {
  const dates = META.nextday_dates || [];
  date = date || dates[0];
  const data = date && await load(`nextday/${date}.json`);
  setTitle("漲停隔日表現");
  if (!data) { app.innerHTML = `<h1>漲停隔日表現</h1>${emptyBox("需要至少兩個交易日的資料")}`; return; }
  const s = data.summary;
  let selN = "";
  const vs = v => v == null ? "" : `<div class="d">比近 20 次平均 ${v > 0 ? "高" : "低"} ${fx(Math.abs(v), 1)} 個百分點</div>`;
  let tag = "";
  app.innerHTML = `<h1>漲停隔日表現</h1>
    <p class="sub">${data.limit_date} 漲停的 ${s.n} 檔，在 ${data.date} 的表現。報酬以前一日漲停價為基準；勝率為報酬大於 0 的比例。</p>
    <div class="toolbar"><span id="ds"></span></div>
    <div class="kpis">
      <div class="kpi"><div class="l">開盤平均報酬</div><div class="v ${sign(s.open_avg)}">${pc(s.open_avg)}</div><div class="d">勝率 ${fx(s.open_win, 1)}%</div>${vs(s.open_win_vs20)}</div>
      <div class="kpi"><div class="l">均價平均報酬</div><div class="v">${pc(s.avg_avg)}</div><div class="d">勝率 ${fx(s.avg_win, 1)}%</div>${vs(s.avg_win_vs20)}</div>
      <div class="kpi"><div class="l">收盤平均報酬</div><div class="v">${pc(s.close_avg)}</div><div class="d">勝率 ${fx(s.close_win, 1)}%</div>${vs(s.close_win_vs20)}</div>
      <div class="kpi"><div class="l">加權平均報酬</div><div class="v">${pc(s.wavg_avg)}</div><div class="d">2/3 開盤賣＋1/3 均價賣</div></div>
      <div class="kpi"><div class="l">續漲停</div><div class="v up">${s.cont} 檔</div><div class="d">共 ${s.n} 檔漲停</div></div>
    </div>
    <h2>族群表現</h2><div id="g"></div>
    <h2>個股明細</h2>
    <div class="toolbar"><span class="chips" id="tags"></span></div>
    <div id="t"></div>
    <p class="small muted">標籤依隔日實際開盤與收盤價格分類，只描述已發生的走勢。加權＝（2 × 開盤報酬 ＋ 均價報酬）÷ 3，假設三分之二在開盤賣、三分之一在均價賣。點個股看漲停日的主力買家隔天怎麼動。</p>
    <section class="bk" id="bk" hidden></section>`;
  document.getElementById("ds").append(dateSelect(dates, date, v => location.hash = `#/nextday/${v}`));
  table(document.getElementById("g"), [
    {k: "theme", t: "族群", f: r => `${esc(r.emoji)} ${esc(r.theme)}`}, {k: "streak", t: "連續天數", n: 1, f: r => r.streak + " 天"},
    {k: "win", t: "收盤勝率", n: 1, f: r => `${fx(r.win, 1)}% <span class="muted small">${r.wins}/${r.n}</span>`},
    {k: "open", t: "開盤", n: 1, f: r => pc(r.open)}, {k: "avg", t: "均價", n: 1, f: r => pc(r.avg)}, {k: "close", t: "收盤", n: 1, f: r => pc(r.close)},
  ], data.groups, {sort: ["close", -1]});
  const tt = table(document.getElementById("t"), [
    {k: "market", t: "所", f: r => mk(r.market)}, {k: "code", t: "代號"}, {k: "name", t: "名稱", f: r => stockLink(r.code, r.name)},
    {k: "ref", t: "漲停價", n: 1, f: r => fp(r.ref)}, {k: "vol_ratio", t: "量比", n: 1, f: r => r.vol_ratio == null ? "—" : fx(r.vol_ratio, 1) + "x"},
    {k: "ret_open", t: "隔日開", n: 1, f: r => `${fp(r.open)} ${pc(r.ret_open)}`}, {k: "ret_avg", t: "隔日均價", n: 1, f: r => `${fp(r.avg)} ${pc(r.ret_avg)}`},
    {k: "ret_close", t: "隔日收", n: 1, f: r => `${fp(r.close)} ${pc(r.ret_close)}`},
    {k: "ret_wavg", t: '加權 <span class="info" title="（2 × 開盤報酬 ＋ 均價報酬）÷ 3">ⓘ</span>', n: 1, f: r => pc(r.ret_wavg)},
    {k: "ret_high", t: "最高", n: 1, f: r => pc(r.ret_high)},
    {k: "tag", t: "標籤", f: r => `<span class="tag ${r.tag === "續漲停" || r.tag.endsWith("走高") ? "up" : "down"}">${esc(r.tag)}</span>`},
    {k: "theme", t: "族群"},
  ], data.stocks, {sort: ["ret_close", -1], id: r => r.code, rowClass: r => r.code === selN ? "sel" : "",
    rowClick: r => { selN = r.code; tt.set(data.stocks.filter(x => !tag || x.tag === tag)); showFollow(data, r, true); }});
  chips(document.getElementById("tags"), [["", `全部 ${s.n}`], ...Object.entries(data.tags).map(([k, v]) => [k, `${k} ${v}`])], tag,
    v => { tag = v; tt.set(data.stocks.filter(x => !v || x.tag === v)); });
};

P.stats = async () => {
  setTitle("漲停統計");
  const st = await load("stats.json");
  if (!st || !st.series.length) { app.innerHTML = `<h1>統計</h1>${emptyBox("資料累積中")}`; return; }
  const S = st.series, W = 900, H = 220, pad = 28, bw = (W - pad * 2) / S.length, mx = Math.max(...S.map(x => x.count), 1);
  const bars = S.map((x, i) => {
    const h = (H - pad * 2) * x.count / mx, X = pad + i * bw, Y = H - pad - h;
    return `<rect x="${X + 1}" y="${Y}" width="${Math.max(bw - 2, 1)}" height="${h}" fill="var(--up)" opacity=".75"><title>${x.date}：${x.count} 檔（${esc(x.top)}）${x.nd_win != null ? `，隔日收盤勝率 ${x.nd_win}%` : ""}</title></rect>` +
      (i % Math.ceil(S.length / 8) === 0 ? `<text x="${X + bw / 2}" y="${H - 8}" text-anchor="middle">${md(x.date)}</text>` : "");
  }).join("");
  const avgY = H - pad - (H - pad * 2) * st.avg_count / mx;
  const svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="近 ${S.length} 個交易日漲停家數">
    <line x1="${pad}" x2="${W - pad}" y1="${avgY}" y2="${avgY}" stroke="var(--ink-3)" stroke-dasharray="4 4"/>
    <text x="${W - pad}" y="${avgY - 5}" text-anchor="end">平均 ${st.avg_count}</text>
    <text x="${pad}" y="14">${mx}</text>${bars}</svg>`;
  app.innerHTML = `<h1>漲停統計</h1><p class="sub">近 ${st.window} 個交易日的漲停家數，與各族群出現頻率、隔日表現。</p>
    <div class="chart">${svg}</div>
    <h2>族群排行</h2><div id="t"></div>
    <h2>每日紀錄</h2><div id="d"></div>`;
  const maxT = Math.max(...st.themes.map(t => t.total), 1);
  table(document.getElementById("t"), [
    {k: "theme", t: "族群", f: r => `${esc(r.emoji)} ${esc(r.theme)}`},
    {k: "total", t: "累計漲停檔次", n: 1, f: r => `<span class="bar" style="width:${Math.round(r.total / maxT * 80)}px"></span> ${r.total}`},
    {k: "days", t: "出現天數", n: 1}, {k: "nd_avg", t: "隔日收盤平均", n: 1, f: r => pc(r.nd_avg)},
    {k: "nd_win", t: "隔日勝率", n: 1, f: r => r.nd_win == null ? "—" : `${fx(r.nd_win, 1)}% <span class="muted small">n=${r.nd_n}</span>`},
    {k: "last", t: "最近出現", f: r => `<a href="#/daily/${r.last}">${r.last}</a>`},
  ], st.themes, {sort: ["total", -1]});
  table(document.getElementById("d"), [
    {k: "date", t: "日期", f: r => `<a href="#/daily/${r.date}">${r.date}</a>`}, {k: "count", t: "漲停", n: 1},
    {k: "twse", t: "上市", n: 1}, {k: "tpex", t: "上櫃", n: 1}, {k: "groups", t: "族群數", n: 1}, {k: "top", t: "最大族群"},
    {k: "nd_close", t: "隔日收盤平均", n: 1, f: r => pc(r.nd_close)}, {k: "nd_win", t: "隔日勝率", n: 1, f: r => r.nd_win == null ? "—" : fx(r.nd_win, 1) + "%"},
  ], S, {sort: ["date", -1]});
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
const tradedTag = r => r.traded ? '<span class="tag">已交易過</span>' : '<span class="tag warn" title="公告在最近一次收盤之後，股價還沒反應">尚未交易</span>';
const newTag = r => r.new ? '<span class="tag new">新</span>' : "";
const scoreTag = r => `<span class="tag ${r.score > 0 ? "up" : r.score < 0 ? "down" : ""}" title="${r.score_src === "ai" ? "AI 評分" : "規則評分"}${r.why ? "：" + esc(r.why) : ""}">${r.score > 0 ? "+" : ""}${r.score}</span>`;
const baseCols = [
  {k: "new", t: "", f: newTag, s: r => r.new ? 1 : 0},
  {k: "time", t: "公告時間", f: r => `${md(r.date)} ${esc(r.time)}`, s: r => (r.date || "") + (r.time || "")},
  {k: "market", t: "所", f: r => mk(r.market)}, {k: "code", t: "代號"}, {k: "name", t: "名稱", f: r => stockLink(r.code, r.name)},
];
const pxCols = [{k: "close", t: "股價", n: 1, f: r => fp(r.close)}, {k: "chg", t: "當日漲跌", n: 1, f: r => pc(r.chg)}];

async function annPage(kind, title, sub, cols, opts = {}) {
  setTitle(title);
  const js = await load(`announce/${kind}.json`);
  const items = js?.items || [];
  app.innerHTML = `<h1>${title}</h1><p class="sub">${sub}</p>
    <div class="toolbar"><span class="chips" id="f"></span><input type="search" id="q" placeholder="代號或名稱" aria-label="搜尋代號或名稱"><span class="small muted">更新 ${esc(js?.updated || "—")}，共 ${items.length} 筆</span></div>
    <div id="t"></div>`;
  let flt = "", q = "";
  const t = table(document.getElementById("t"), cols, items, {sort: opts.sort, expand: opts.expand, id: r => r.key, empty: "目前沒有符合的公告"});
  const apply = () => t.set(items.filter(r => (!flt || (opts.filters.find(f => f[0] === flt)[2])(r)) && (!q || r.code.includes(q) || (r.name || "").includes(q))));
  const filters = opts.filters || [];
  chips(document.getElementById("f"), [["", "全部"], ...filters.map(f => [f[0], f[1]])], "", v => { flt = v; apply(); });
  document.getElementById("q").oninput = e => { q = e.target.value.trim(); apply(); };
}
const commonFilters = [["new", "本次新增", r => r.new], ["untraded", "尚未交易", r => !r.traded]];

P.att = () => annPage("att", "自結速報", "公司自行結算的月或季損益。評分比較本次每月 EPS 與上一季財報月均 EPS（有 AI 金鑰時由 AI 評分）。", [
  ...baseCols, {k: "period", t: "期間"}, {k: "eps", t: "EPS", n: 1, f: r => fx(r.eps)},
  {k: "eps_monthly", t: "月均 EPS", n: 1, f: r => fx(r.eps_monthly)}, {k: "last_q_monthly", t: "上季月均", n: 1, f: r => fx(r.last_q_monthly)},
  {k: "score", t: "評分", n: 1, f: scoreTag}, ...pxCols, {k: "traded", t: "反應", f: tradedTag, s: r => r.traded ? 1 : 0},
], {sort: ["score", -1], filters: [...commonFilters, ["pos", "評分為正", r => r.score > 0]],
   expand: r => `<div class="detail-grid"><div><h4>主旨</h4><p>${esc(r.subject)}</p></div><div><h4>評分理由</h4><p>${esc(r.why || (r.score_src === "rule" ? "規則評分：月均 EPS 相對上季月均的變化" : ""))}</p></div></div>`});

P.fin = () => annPage("fin", "季報速報", "最新一季財報 EPS，與上一季、去年同季比較。", [
  ...baseCols, {k: "period", t: "季別"}, {k: "eps", t: "EPS", n: 1, f: r => fx(r.eps)}, {k: "eps_prev_q", t: "上季", n: 1, f: r => fx(r.eps_prev_q)},
  {k: "eps_ly", t: "去年同季", n: 1, f: r => fx(r.eps_ly)},
  {k: "qoq", t: "季增", n: 1, s: r => r.eps_prev_q ? (r.eps - r.eps_prev_q) / Math.abs(r.eps_prev_q) : null, f: r => r.eps_prev_q ? pc((r.eps - r.eps_prev_q) / Math.abs(r.eps_prev_q) * 100, 1) : "—"},
  {k: "score", t: "評分", n: 1, f: scoreTag}, ...pxCols,
], {sort: ["score", -1], filters: [["new", "本次新增", r => r.new], ["pos", "評分為正", r => r.score > 0], ["loss", "虧損", r => r.eps < 0]]});

P.rev = () => annPage("rev", "營收速報", "上市櫃公司月營收。金額單位千元；有備註的通常是公司主動說明增減原因。", [
  ...baseCols.filter(c => c.k !== "time"), {k: "ym", t: "年月"}, {k: "industry", t: "產業"},
  {k: "rev", t: "當月營收(千元)", n: 1, f: r => fi(r.rev)}, {k: "mom", t: "月增", n: 1, f: r => pc(r.mom, 1)}, {k: "yoy", t: "年增", n: 1, f: r => pc(r.yoy, 1)},
  {k: "cum_yoy", t: "累計年增", n: 1, f: r => pc(r.cum_yoy, 1)}, {k: "note", t: "備註", w: 1, f: r => esc(r.note || "")}, ...pxCols,
], {sort: ["yoy", -1], filters: [["new", "本次新增", r => r.new], ["note", "有備註", r => r.has_note], ["plain", "無備註", r => !r.has_note], ["yoy30", "年增逾 30%", r => r.yoy >= 30]]});

P.treasury = () => annPage("treasury", "庫藏股", "董事會決議買回自家股票的公告。", [
  ...baseCols, {k: "lots", t: "預定買回(張)", n: 1, f: r => fi(r.lots)},
  {k: "low", t: "價格區間", f: r => r.low ? `${fp(r.low)}～${fp(r.high)}` : "—"},
  {k: "pos", t: "現價位置", n: 1, s: r => r.low && r.close ? (r.close - r.low) / (r.high - r.low) : null,
   f: r => r.low && r.close ? (r.close < r.low ? '<span class="down">低於下限</span>' : r.close > r.high ? '<span class="muted">高於上限</span>' : "區間內") : "—"},
  ...pxCols, {k: "traded", t: "反應", f: tradedTag, s: r => r.traded ? 1 : 0},
], {sort: ["time", -1], filters: commonFilters, expand: r => `<p style="white-space:pre-wrap;margin:0">${esc(r.body)}</p>`});

P.events = () => annPage("events", "重大事件", "其他重大訊息，依主旨自動分類。點一列看說明。", [
  ...baseCols, {k: "kind", t: "類別", f: r => `<span class="tag">${esc(r.kind)}</span>`},
  {k: "subject", t: "主旨", w: 1}, ...pxCols, {k: "traded", t: "反應", f: tradedTag, s: r => r.traded ? 1 : 0},
], {sort: ["time", -1], filters: [...commonFilters, ...["併購", "增資/可轉債", "資產交易", "澄清", "訂單/合約"].map(k => [k, k, r => r.kind === k])],
   expand: r => `<p style="white-space:pre-wrap;margin:0">${esc(r.body)}</p>`});

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
function dispDetail(c) {
  const c1 = c.c1;
  return `<div class="detail-grid">
    <div><h4>處置進度</h4>${Object.entries(COND).map(([k, v]) => `<p>${v}：${prog(c.progress[k])}</p>`).join("")}</div>
    <div><h4>第一款（6 日累積漲跌）</h4>${c1 ? `<p>起點 ${c1.base_date} 收 ${fp(c1.base)}，目前累積 ${pc(c1.cum)}，同期全體平均 ${pc(c1.mkt)}</p>
      <p>往上觸發：${trig(c1.up, "↑")}</p><p>往下觸發：${trig(c1.down, "↓")}</p>` : "<p class='muted'>歷史資料不足 6 日</p>"}</div>
    <div><h4>第二款（30/60/90 日）</h4>${c.c2.map(x => `<p>${x.days} 日（門檻 ${x.th}%）：${x.cum != null ? `累積 ${pc(x.cum, 1)}，` : ""}${trig(x, "↑")}</p>`).join("")}</div>
    <div><h4>明日價格範圍</h4><p>平盤 ${fp(c.limits.flat)}，漲停 ${fp(c.limits.up)}，跌停 ${fp(c.limits.down)}</p>
      <p>本益比 ${c.pe ?? "虧損或無"}，淨值比 ${c.pb ?? "—"}</p></div>
    <div><h4>注意股紀錄</h4><p>${c.record.map(r => `${md(r.date)}（第${r.clauses.join("、")}款）`).join("，")}</p></div>
    <div><h4>第三~八款</h4><p class="muted">需成交量放大倍數、單一券商占比、融資券使用率等資料，本專案未估算，請參考交易所公告。</p></div>
  </div>`;
}
P.disposal = async () => {
  setTitle("處置預測");
  const js = await load("disposal.json");
  if (!js) { app.innerHTML = `<h1>處置預測</h1>${emptyBox("尚未產生")}`; return; }
  app.innerHTML = `<h1>明日處置預測</h1>
    <p class="sub">適用 ${js.target} 交易日。依注意股累計次數判斷還差幾次會被處置，並估算第一、二款的明日觸發價。條件為程式估算，不是交易所預告。</p>
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

(async () => {
  META = await load("meta.json") || {};
  if (META.site_name) { document.getElementById("siteName").textContent = META.site_name; }
  document.getElementById("mockbar").hidden = !META.mock;
  const j = META.jobs || {};
  document.getElementById("updated").textContent = Object.keys(j).length ? "最近更新：" + Object.entries(j).filter(([k]) => k !== "mock").map(([k, v]) => `${({daily: "漲停", disposal: "處置", announce: "公告", borrow: "券差", etf: "主動ETF", backfill: "補資料"})[k] || k} ${v}`).join("，") : "";
  window.addEventListener("hashchange", route);
  route();
})();
})();

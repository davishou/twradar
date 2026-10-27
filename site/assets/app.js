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
let CBIDX = {};   // {股票代號: {cb: 檔數, ipo: 狀態}}（cb_index.json）
const stockLink = (code, name) => `<a href="#/stock/${esc(code)}">${esc(name || code)}</a>${CBIDX[code]?.ipo ? ` <a class="tag ipo" href="#/cbipo" title="可轉債 ${esc(CBIDX[code].ipo)}">IPO</a>` : ""}`;

/* ---------------- 小走勢圖 ----------------
   資料：spark.json（全部股票、最新一天）或每日漲停檔內嵌的 spark（只畫到那一天）。
   外框顏色＝圖中最大一段波動的幅度（小圖看不出刻度，用框色分辨漲 2 倍和漲 10 倍）：
   最大漲幅 ×10 以上 紅框、×5~10 黃框、×2~5 淡黃框；最大跌幅 −80% 以下 墨綠、−60~−80% 深綠、−30~−60% 淺綠。
   漲、跌都有時，取幅度較大的一邊（以倍數的對數比較，例如 ×2 和 −50% 一樣大）。 */
let SPARK = {};
const SPK = [];                                  // 這一頁畫過的資料，給浮出大圖用
const SPK_ALPHA = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_";
const spkVals = v => [...v].map(c => SPK_ALPHA.indexOf(c) / 63);
function spkTier(r) {
  const up = r.u || 1, dn = r.w || 0, su = Math.log(up), sd = -Math.log1p(dn / 100);
  if (su >= sd) {
    const t = up >= 10 ? "r3" : up >= 5 ? "r2" : up >= 2 ? "r1" : "";
    return [t, t ? "×" + (up < 10 ? up.toFixed(1) : Math.round(up)) : ""];
  }
  const t = dn <= -80 ? "g3" : dn <= -60 ? "g2" : dn <= -30 ? "g1" : "";
  return [t, t ? Math.round(dn) + "%" : ""];
}
function spkPath(vals, w, h, pad) {
  const n = vals.length;
  return vals.map((y, i) => `${(pad + (n === 1 ? 0 : i / (n - 1)) * (w - 2 * pad)).toFixed(1)},${(pad + (1 - y) * (h - 2 * pad)).toFixed(1)}`);
}
function spk(code, name, rec) {
  rec = rec && rec.v ? rec : SPARK[code];
  if (!rec || !rec.v) return "";
  const vals = spkVals(rec.v), w = 100, h = 24, pts = spkPath(vals, w, h, 2);
  const dir = rec.b >= rec.a ? "up" : "down";
  const [tier, lab] = spkTier(rec);
  const xy = i => pts[i].split(",");
  const dots = (rec.k || []).map(i => { const [x, y] = xy(i); return `<circle cx="${x}" cy="${y}" r="1.6"/>`; }).join("");
  // 格線：每月第一個交易日一條直線、期間起點價位一條虛線（小圖刻度各不相同，不畫橫向格子）
  const months = (rec.m || []).map(i => { const x = xy(i)[0]; return `<line x1="${x}" x2="${x}" y1="0" y2="${h}"/>`; }).join("");
  const by = (2 + (1 - (rec.a - rec.l) / ((rec.h - rec.l) || 1)) * (h - 4)).toFixed(1);
  SPK.push({code, name, rec});
  return `<span class="tspk" data-i="${SPK.length - 1}" tabindex="0" role="img" aria-label="${esc(name || code)} 近 ${vals.length} 日走勢，期間 ${((rec.b / rec.a - 1) * 100).toFixed(0)}%">`
    + `<span class="tbox ${tier}"><svg viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" aria-hidden="true">`
    + `<g class="grid">${months}<line class="base" x1="0" x2="${w}" y1="${by}" y2="${by}"/></g>`
    + `<polyline class="${dir}" points="${pts.join(" ")}"/><g class="lu">${dots}</g></svg></span>`
    + `<b class="${tier}">${lab}</b></span>`;
}
function spkBig(rec, w = 300, h = 120) {
  const vals = spkVals(rec.v), pts = spkPath(vals, w, h, 6), dir = rec.b >= rec.a ? "up" : "down";
  const hiI = vals.indexOf(1), loI = vals.indexOf(0);
  const dots = (rec.k || []).map(i => { const [x, y] = pts[i].split(","); return `<circle cx="${x}" cy="${y}" r="2.4"/>`; }).join("");
  const mark = (i, t, above) => { const [x, y] = pts[i].split(",").map(Number);
    return `<text x="${Math.min(w - 4, Math.max(4, x))}" y="${above ? y - 5 : y + 13}" text-anchor="${x < 40 ? "start" : x > w - 40 ? "end" : "middle"}">${t}</text>`; };
  return `<svg class="spkbig" viewBox="0 0 ${w} ${h + 8}" aria-hidden="true">
    <polygon class="${dir}" points="6,${h - 6} ${pts.join(" ")} ${w - 6},${h - 6}"/><polyline class="${dir}" points="${pts.join(" ")}"/>
    <g class="lu">${dots}</g>${hiI >= 0 ? mark(hiI, fp(rec.h), true) : ""}${loI >= 0 ? mark(loI, fp(rec.l), false) : ""}</svg>`;
}
function spkInfo(it) {
  const r = it.rec, chg = (r.b / r.a - 1) * 100, [tier, lab] = spkTier(r);
  return `<div class="spkh"><b>${esc(it.name || "")}</b> <span class="muted">${esc(it.code)}</span>
      <span class="muted small">近 ${r.v.length} 個交易日</span> ${pc(chg, 1)}${lab ? ` <span class="spkt ${tier}">${lab}</span>` : ""}</div>
    ${spkBig(r)}
    <div class="spkf small muted"><span>${esc(r.d)} 起</span><span>最高 ${fp(r.h)}　最低 ${fp(r.l)}</span></div>
    <div class="spkf small"><span>最大漲幅 <b class="up">×${r.u.toFixed(r.u < 10 ? 2 : 1)}</b></span><span>最大跌幅 <b class="down">${r.w.toFixed(1)}%</b></span>${(r.k || []).length ? `<span>漲停 <b class="up">${r.k.length}</b> 次</span>` : ""}</div>
    <div class="small muted">還原權息價；紅點＝漲停日。${r.e ? `畫到 ${esc(r.e)}。` : ""}</div>`;
}
const spkTip = document.createElement("div");
spkTip.className = "spktip"; spkTip.hidden = true; spkTip.setAttribute("role", "tooltip");
document.body.appendChild(spkTip);
let spkOn = null;
function spkShow(el) {
  const it = SPK[+el.dataset.i];
  if (!it) return;
  spkOn = el;
  spkTip.innerHTML = spkInfo(it);
  spkTip.hidden = false;
  const b = el.getBoundingClientRect(), tw = spkTip.offsetWidth, th = spkTip.offsetHeight;
  let x = Math.min(window.innerWidth - tw - 8, Math.max(8, b.left));
  let y = b.bottom + 6;
  if (y + th > window.innerHeight - 8) y = Math.max(8, b.top - th - 6);
  spkTip.style.left = x + "px"; spkTip.style.top = y + "px";
}
function spkHide() { spkTip.hidden = true; spkOn = null; }
const hoverable = matchMedia("(hover: hover)").matches;
document.addEventListener("mouseover", e => { if (!hoverable) return; const el = e.target.closest?.(".tspk"); if (el) spkShow(el); else if (spkOn && !e.target.closest?.(".spktip")) spkHide(); });
document.addEventListener("click", e => {
  const el = e.target.closest?.(".tspk");
  if (el) { e.preventDefault(); e.stopPropagation(); spkOn === el && !hoverable ? spkHide() : spkShow(el); return; }
  if (!e.target.closest?.(".spktip")) spkHide();
}, true);
document.addEventListener("focusin", e => { const el = e.target.closest?.(".tspk"); if (el) spkShow(el); });
document.addEventListener("keydown", e => { if (e.key === "Escape") spkHide(); });
window.addEventListener("scroll", () => { if (spkOn) spkHide(); }, {passive: true});
const md = s => s ? s.slice(5).replace("-", "/") : "";
function toast(msg) { const t = document.getElementById("toast"); t.textContent = msg; t.classList.add("show"); setTimeout(() => t.classList.remove("show"), 1600); }
async function copy(text) {
  try { await navigator.clipboard.writeText(text); toast("已複製"); }
  catch { const ta = document.createElement("textarea"); ta.value = text; document.body.append(ta); ta.select(); document.execCommand("copy"); ta.remove(); toast("已複製"); }
}
function setTitle(t) { document.title = (t ? t + "｜" : "") + (META.site_name || "盤後雷達"); }
const emptyBox = msg => `<div class="tw"><div class="empty">${esc(msg)}</div></div>`;

/* 通用表格：columns [{k,t,n,f,s,w}]，opts {sort:[k,dir], expand(row)->html, rowClick, empty} */
/* 有「名稱」欄的表格，自動在它右邊加一欄「走勢」（小走勢圖），所有圖對齊同一欄；點欄名可依最大漲幅排序 */
const SPK_TIP = "近 160 個交易日走勢（還原權息），紅點＝漲停日。\n外框＝圖中最大一段漲跌：\n紅框 漲到 10 倍以上｜黃框 5～10 倍｜淡黃框 2～5 倍\n淺綠框 跌 30～60%｜深綠框 跌 60～80%｜墨綠框 跌 80% 以上\n滑鼠移上去或點一下看大圖。";
function withSpark(columns) {
  const i = columns.findIndex(c => c.k === "name");
  if (i < 0 || columns.some(c => c.k === "_spk")) return columns;
  const rec = r => (r.spark && r.spark.v) ? r.spark : SPARK[r.code];
  const col = {k: "_spk", t: `走勢 ${tipBtn(SPK_TIP)}`, desc: 1, s: r => rec(r)?.u ?? null,
               f: r => spk(r.code, r.name, r.spark) || '<span class="muted small">—</span>'};
  return [...columns.slice(0, i + 1), col, ...columns.slice(i + 1)];
}
function table(el, columns, rows, opts = {}) {
  columns = withSpark(columns);
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
    const head = columns.map(c => `<th class="${c.n ? "n" : ""} ${c.k === "_spk" ? "spkc" : ""} ${c.k && c.sortable !== false ? "s" : ""}" data-k="${c.k || ""}" scope="col"${c.k && c.sortable !== false ? ' tabindex="0"' : ""}>${c.t}${sk === c.k ? `<span class="ar">${sd > 0 ? "▲" : "▼"}</span>` : ""}</th>`).join("");
    const body = data.map((r, i) => {
      const id = opts.id ? opts.id(r) : i;
      const tr = `<tr class="${opts.expand || opts.rowClick ? "click" : ""} ${opts.rowClass ? opts.rowClass(r) : ""} ${r.code && CBIDX[r.code]?.cb ? "hascb" : ""}" data-i="${esc(id)}"${opts.expand ? ` aria-expanded="${open.has(String(id))}"` : ""}>${columns.map(c =>
        `<td class="${c.n ? "n" : ""} ${c.w ? "wrap" : ""} ${c.cls || ""} ${c.k === "_spk" ? "spkc" : ""}">${c.f ? c.f(r) : esc(r[c.k] ?? "—")}</td>`).join("")}</tr>`;
      const ex = opts.expand && open.has(String(id)) ? `<tr class="detail"><td colspan="${columns.length}">${opts.expand(r)}</td></tr>` : "";
      return tr + ex;
    }).join("");
    el.innerHTML = `<div class="tw"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
    el._rows = new Map(data.map((r, i) => [String(opts.id ? opts.id(r) : i), r]));
  }
  el.onclick = e => {
    if (e.target.closest("a") || e.target.closest(".tipbtn")) return;
    const th = e.target.closest("th.s");
    if (th) { const k = th.dataset.k; sd = sk === k ? -sd : (columns.find(c => c.k === k).n || columns.find(c => c.k === k).desc ? -1 : 1); sk = k; draw(); return; }
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
    {k: "market", t: "所", f: r => mk(r.market)}, {k: "code", t: "代號"}, {k: "name", t: "名稱", f: r => stockLink(r.code, r.name, r.spark)},
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
    {k: "market", t: "所", f: r => mk(r.market)}, {k: "code", t: "代號"}, {k: "name", t: "名稱", f: r => stockLink(r.code, r.name, r.spark)},
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
    {k: "code", t: "代號", f: r => `<span class="code">${esc(r.code)}</span>`}, {k: "name", t: "名稱", f: r => stockLink(r.code, r.name, r.spark)},
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
const idCols = [{k: "code", t: "代號", f: r => `<span class="code">${esc(r.code)}</span>`}, {k: "name", t: "名稱", f: r => `${stockLink(r.code, r.name, r.spark)} ${newTag(r)}`}];
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
    {k: "code", t: "代號"}, {k: "name", t: "名稱", f: r => stockLink(r.code, r.name, r.spark)}, {k: "market", t: "所", f: r => mk(r.market)},
    {k: "close", t: "股價", n: 1, f: r => fp(r.close)}, {k: "chg", t: "漲幅", n: 1, f: r => pc(r.chg)},
    {k: "lots_traded", t: "成交量(張)", n: 1, f: r => fi(r.lots_traded)}, {k: "lots", t: "借量(張)", n: 1, f: r => fx(r.lots, 0)},
    {k: "avg_rate", t: "均費率", n: 1, f: r => `<b>${fx(r.avg_rate, 2)}%</b>`}, {k: "min_rate", t: "最低", n: 1, f: r => fx(r.min_rate) + "%"},
    {k: "max_rate", t: "最高", n: 1, f: r => fx(r.max_rate) + "%"}, {k: "n", t: "筆", n: 1},
  ], js.summary, {sort: ["avg_rate", -1], id: r => r.code, empty: "今日沒有券差借券",
    expand: r => `<table><thead><tr><th>借張</th><th>費率</th></tr></thead><tbody>${by[r.code].map(x => `<tr><td>${fx(x.lots, 0)}</td><td>${fx(x.rate)}%</td></tr>`).join("")}</tbody></table>`});
  table(document.getElementById("d"), [
    {k: "date", t: "日期"}, {k: "code", t: "代號"}, {k: "name", t: "名稱", f: r => stockLink(r.code, r.name, r.spark)}, {k: "market", t: "所", f: r => mk(r.market)},
    {k: "close", t: "股價", n: 1, f: r => fp(r.close)}, {k: "chg", t: "漲幅", n: 1, f: r => pc(r.chg)},
    {k: "lots_traded", t: "成交量", n: 1, f: r => fi(r.lots_traded)}, {k: "lots", t: "借張", n: 1, f: r => fx(r.lots, 0)}, {k: "rate", t: "費率", n: 1, f: r => fx(r.rate) + "%"},
  ], js.detail, {sort: ["rate", -1]});
};

// ---- 可轉債 ----
const yi2 = n => n == null ? "—" : fx(n / 1e8, n >= 1e9 ? 0 : 1);
const CB_P = [["1M", 21], ["3M", 63], ["6M", 126], ["1Y", 250]];
/* 三層圖：CB K 線（紅漲綠跌）、轉換溢價率、成交張數。hj：{dates, rows:[[開, 高, 低, 收, 張數, 轉換價值, 溢價率, 餘額(億)], ...]} */
function cbChart(hj, n) {
  const dates = hj?.dates || [];
  const h = (hj?.rows || []).map((x, i) => [i, ...x]).filter(x => x[4] != null || x[7] != null).slice(-n);
  if (h.length < 2) return '<p class="muted small">歷史走勢會隨每日資料累積（目前不足 2 天）。</p>';
  const w = 600, p = 6, k1 = 140, g = 10, k2 = 50, k3 = 34, axis = 44;
  const pw = w - p - axis, bw = pw / h.length, X = i => p + (i + 0.5) * bw;
  const px = h.flatMap(x => [x[2], x[3], x[4]]).filter(x => x != null);
  const lo = Math.min(...px), hi = Math.max(...px), sp = hi - lo || 1;
  const Y = y => p + (1 - (y - lo) / sp) * (k1 - 2 * p);
  const pr = h.map(x => x[7]).filter(x => x != null);
  const plo = Math.min(0, ...pr), phi = Math.max(...pr, plo + 1), psp = phi - plo || 1;
  const y2 = k1 + g, Y2 = v => y2 + (1 - (v - plo) / psp) * k2;
  const y3 = y2 + k2 + g, vmax = Math.max(1, ...h.map(x => x[5] || 0));
  let candles = "", vols = "";
  h.forEach((x, i) => {
    const [o, hh, l, c, v] = [x[1], x[2], x[3], x[4], x[5]];
    if (c != null && o != null) {
      const cls = c > o ? "up" : c < o ? "down" : "flat";
      candles += `<line class="${cls}" x1="${X(i)}" x2="${X(i)}" y1="${Y(hh ?? c)}" y2="${Y(l ?? c)}"/>`
        + `<rect class="${cls}" x="${X(i) - bw * 0.35}" y="${Math.min(Y(o), Y(c))}" width="${Math.max(1, bw * 0.7)}" height="${Math.max(1, Math.abs(Y(o) - Y(c)))}"/>`;
    }
    if (v) vols += `<rect class="${c != null && o != null && c < o ? "down" : "up"}" x="${X(i) - bw * 0.35}" y="${y3 + k3 - v / vmax * k3}" width="${Math.max(1, bw * 0.7)}" height="${v / vmax * k3}"/>`;
  });
  const prem = h.map((x, i) => x[7] == null ? null : `${X(i).toFixed(1)},${Y2(x[7]).toFixed(1)}`).filter(Boolean).join(" ");
  const ax = w - axis + 4, last = h.at(-1);
  const lastC = [...h].reverse().find(x => x[4] != null);
  const ref100 = lo <= 100 && hi >= 100 ? `<line class="ref" x1="${p}" x2="${w - axis}" y1="${Y(100)}" y2="${Y(100)}"/>` : "";
  const zero = plo < 0 ? `<line class="ref" x1="${p}" x2="${w - axis}" y1="${Y2(0)}" y2="${Y2(0)}"/>` : "";
  return `<svg class="cbchart" viewBox="0 0 ${w} ${y3 + k3 + 16}" role="img" aria-label="可轉債 K 線、溢價率與成交量">
    ${ref100}<g class="k">${candles}</g>
    ${!lastC || Math.abs(Y(hi) - Y(lastC[4])) > 12 ? `<text x="${ax}" y="${Y(hi) + 4}">${fp(hi)}</text>` : ""}${!lastC || Math.abs(Y(lo) - Y(lastC[4])) > 12 ? `<text x="${ax}" y="${Y(lo)}">${fp(lo)}</text>` : ""}${lastC ? `<text class="last" x="${ax}" y="${Y(lastC[4]) + 4}">${fp(lastC[4])}</text>` : ""}
    <line class="sep" x1="${p}" x2="${w - axis}" y1="${y2 - g / 2}" y2="${y2 - g / 2}"/>
    ${zero}<polyline class="prem" points="${prem}"/><text x="${p}" y="${y2 + 10}">溢價率</text>
    <text x="${ax}" y="${y2 + 9}">${fx(phi, 0)}%</text><text x="${ax}" y="${y2 + k2}">${fx(plo, 0)}%</text>
    <line class="sep" x1="${p}" x2="${w - axis}" y1="${y3 - g / 2}" y2="${y3 - g / 2}"/>
    <g class="v">${vols}</g><text x="${ax}" y="${y3 + 9}">${fi(vmax)}張</text>
    <text x="${p}" y="${y3 + k3 + 13}">${esc(dates[h[0][0]] || "")}</text><text x="${w - axis}" y="${y3 + k3 + 13}" text-anchor="end">${esc(dates[last[0]] || "")}</text></svg>`;
}
const CB_TIP = {
  cv: "轉換價值＝100 ÷ 轉換價 × 股價。代表立刻轉成股票值多少（以百元計）。",
  prem: "轉換溢價率＝CB 價 ÷ 轉換價值 − 1。越低代表 CB 越貼近股價走勢；負值（折價）代表轉換有套利空間。",
  remain: "剩餘比率＝餘額 ÷ 發行總額。低於 30% 以紅色提醒：大部分已轉成股票，可能已贖回或流動性變差。",
  put: "下次賣回日（有賣回權）或到期日。賣回報酬＝賣回價 ÷ CB 價 − 1；年化＝依剩餘年數換算。",
  opt: "理論權利金（百元報價）＝CB 價 − 賣回價 ÷ (1+折現率)^年數。這是用固定折現率估算，和券商實際 CBAS 報價（例如投資少數派引用的元大報價）可能不同。",
};
const addDays = (d, n) => { const x = new Date(d); x.setDate(x.getDate() + n); return x.toISOString().slice(0, 10); };

// ---- CB 溫度計（鄭詩翰「CB 整體市場委買均價」的換算版）----
const TZ = {x: ["極端恐慌", "tz-x"], p: ["恐慌", "tz-p"], l: ["低迷", "tz-l"], n: ["正常", "tz-n"], h: ["偏熱", "tz-h"]};
const TEMP_TIP = "鄭詩翰（社團「年輕人的投資夢」）用 XQ 追蹤全部可轉債的委買均價判斷市場溫度：121 正常、112 低迷、108~110 極端恐慌（他開始分批加碼）、2025/4/9 關稅崩盤 98。\n\n"
  + "我們沒有委買價，改用全市場 CB 的平均轉換價值換算：換算均價 ≈ 0.655 × 平均轉換價值 + 49.3。用他公布過的 8 個數字對照，相關係數 0.97，誤差約 ±3 元。\n\n"
  + "回測表是 2018 年以來，每天依當天溫度分組，看之後 20、60 個交易日全市場（等權）與大型股（成交金額前 50 大）的平均漲幅。歷史統計，不保證未來。";
function tempZoneOf(v) { return v < 105 ? "x" : v < 110 ? "p" : v < 113 ? "l" : v < 121 ? "n" : "h"; }
function cbTempChart(t, range) {
  const src = range === "all" ? t.weekly : t.daily;
  if (!src?.length) return "";
  const W = Math.round(Math.min(760, Math.max(340, (window.innerWidth || 760) - 70))), H = W < 500 ? 170 : 190, L = 34, R = 10, T = 8, B = 20;
  const vs = src.map(x => x[1]), lo = Math.min(95, Math.floor(Math.min(...vs) / 5) * 5), hi = Math.max(130, Math.ceil(Math.max(...vs) / 5) * 5);
  const x = i => L + (W - L - R) * i / Math.max(1, src.length - 1), y = v => T + (H - T - B) * (1 - (v - lo) / (hi - lo));
  const band = (a, b, cls) => `<rect class="${cls}" x="${L}" y="${y(Math.min(b, hi))}" width="${W - L - R}" height="${Math.max(0, y(Math.max(a, lo)) - y(Math.min(b, hi)))}"/>`;
  let g = band(lo, 110, "tzb-p") + band(121, hi, "tzb-h");
  for (let v = Math.ceil(lo / 10) * 10; v <= hi; v += 10) g += `<line class="grid" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/><text class="ax" x="${L - 5}" y="${y(v) + 4}" text-anchor="end">${v}</text>`;
  let last = "";
  const narrow = W < 500;
  src.forEach(([d], i) => { const k = range === "all" ? d.slice(0, 4) : d.slice(0, 7); if (k !== last) { last = k;
    if (range === "all" ? (!narrow || +k % 2 === 1) : +d.slice(5, 7) % (narrow ? 3 : 2) === 1) g += `<text class="ax" x="${x(i) + 2}" y="${H - 6}">${range === "all" ? k : (+d.slice(5, 7)) + "月"}</text>`; } });
  g += `<path class="tline" d="${src.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p[1]).toFixed(1)}`).join("")}"/>`;
  (t.his || []).forEach(([d, v]) => { const i = src.findIndex(p => p[0] >= d); if (i > 0 || (i === 0 && src[0][0].slice(0, 7) === d.slice(0, 7))) g += `<circle class="hisdot" cx="${x(i)}" cy="${y(v)}" r="3.5"><title>${d} 他公布 ${v}</title></circle>`; });
  const lx = x(src.length - 1), ly = y(vs[vs.length - 1]);
  g += `<circle class="tnow" cx="${lx}" cy="${ly}" r="4"/>`;
  return `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="CB 溫度計走勢">${g}</svg>`;
}
function cbTempCard(t) {
  if (!t) return "";
  const z = TZ[t.zone.key] || TZ.n, pct = v => v == null ? "—" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`;
  const b = (t.buckets || []).find(b => (b.lo == null || t.value >= b.lo) && (b.hi == null || t.value < b.hi));
  const gLo = 95, gHi = 130, gp = v => Math.max(0, Math.min(100, (v - gLo) / (gHi - gLo) * 100));
  const segs = [[gLo, 105, "x"], [105, 110, "p"], [110, 113, "l"], [113, 121, "n"], [121, gHi, "h"]];
  const lab = b => b.lo == null ? `< ${b.hi}` : b.hi == null ? `≥ ${b.lo}` : `${b.lo} ~ ${b.hi}`;
  const flag = t.high2y ? '<span class="tag warn">創兩年新高</span>' : t.low2y ? '<span class="tag ok">創兩年新低</span>' : "";
  return `<section class="tcard" aria-label="CB 溫度計">
    <div class="thead"><h2>CB 溫度計 ${tipBtn(TEMP_TIP)}</h2><span class="small muted">${esc(t.date)}，${fi(t.n)} 檔可轉債</span></div>
    <div class="tbody">
      <div class="tnum"><b>${t.value.toFixed(1)}</b><span class="tz ${z[1]}">${z[0]}</span> ${flag}
        <p class="small">${esc(t.zone.desc)}</p>
        <p class="small muted">平均轉換價值 ${t.conv.toFixed(1)}｜5 日 ${t.chg5 == null ? "—" : (t.chg5 >= 0 ? "+" : "") + t.chg5.toFixed(1)}｜兩年位階 ${t.pct2y ?? "—"}%</p></div>
      <div class="tgauge" aria-hidden="true"><div class="tbar">${segs.map(([a, c, k]) => `<i class="${TZ[k][1]}" style="left:${gp(a)}%;width:${gp(c) - gp(a)}%"></i>`).join("")}
        <em style="left:${gp(t.value)}%"></em></div>
        <div class="tticks">${[95, 105, 110, 113, 121, 130].map(v => `<span style="left:${gp(v)}%">${v}</span>`).join("")}</div>
        ${b ? `<p class="small">過去溫度在 <b>${lab(b)}</b> 的 ${fi(b.n)} 天，之後 60 天大盤平均 <b class="${b.r60 >= 0 ? "up" : "down"}">${pct(b.r60)}</b>（上漲比例 ${Math.round(b.w60 * 100)}%），大型股 ${pct(b.big60)}；全部日子平均 ${pct(t.base?.r60)}。</p>` : ""}</div>
    </div>
    <div class="trange chips" id="trg"></div><div id="tchart">${cbTempChart(t, "1y")}</div>
    <details class="adv"><summary>回測明細：各溫度之後的大盤、歷次恐慌</summary>
      <div class="tw"><table><thead><tr><th>換算均價</th><th class="n">天數</th><th class="n">之後 20 天</th><th class="n">之後 60 天</th><th class="n">60 天上漲比例</th><th class="n">大型股 60 天</th></tr></thead>
      <tbody>${(t.buckets || []).map(b => `<tr class="${b === bNow(t) ? "sel" : ""}"><td><span class="tz ${TZ[tempZoneOf(b.lo ?? 100)][1]}">${lab(b)}</span></td><td class="n">${fi(b.n)}</td><td class="n">${pct(b.r20)}</td><td class="n">${pct(b.r60)}</td><td class="n">${b.w60 == null ? "—" : Math.round(b.w60 * 100) + "%"}</td><td class="n">${pct(b.big60)}</td></tr>`).join("")}
      <tr><td>全部</td><td></td><td class="n">${pct(t.base?.r20)}</td><td class="n">${pct(t.base?.r60)}</td><td></td><td class="n">${pct(t.base?.big60)}</td></tr></tbody></table></div>
      <h4>首次跌破 110（恐慌，相隔 40 天以上算一次）</h4>
      <div class="tw"><table><thead><tr><th>日期</th><th class="n">換算均價</th><th class="n">之後 20 天</th><th class="n">之後 60 天</th><th class="n">大型股 60 天</th></tr></thead>
      <tbody>${(t.episodes || []).map(e => `<tr><td>${esc(e.date)}</td><td class="n">${e.value.toFixed(1)}</td><td class="n">${pct(e.r20)}</td><td class="n">${pct(e.r60)}</td><td class="n">${pct(e.big60)}</td></tr>`).join("")}</tbody></table></div>
      <h4>創兩年新高（偏熱）</h4>
      <div class="tw"><table><thead><tr><th>日期</th><th class="n">換算均價</th><th class="n">之後 20 天</th><th class="n">之後 60 天</th><th class="n">大型股 60 天</th></tr></thead>
      <tbody>${(t.highs || []).map(e => `<tr><td>${esc(e.date)}</td><td class="n">${e.value.toFixed(1)}</td><td class="n">${pct(e.r20)}</td><td class="n">${pct(e.r60)}</td><td class="n">${pct(e.big60)}</td></tr>`).join("")}</tbody></table></div>
      <p class="small muted">統計期間 ${esc((t.stats_range || []).join(" ~ "))}。恐慌之後大盤多半上漲，越深越強；但第一次跌破 110 常常不是最低點（2020/2 之後 3 月才見底），他一律分批、波段最多 6 成。創兩年新高之後大盤沒有明顯下跌，比較適合拿來降部位、保留子彈，不適合放空。圖上黑點是他在 FB 公布的數字。</p>
    </details>
  </section>`;
}
function bNow(t) { return (t.buckets || []).find(b => (b.lo == null || t.value >= b.lo) && (b.hi == null || t.value < b.hi)); }

P.cb = async () => {
  setTitle("可轉債");
  const [js, ipo, temp, sg] = await Promise.all([load("cb.json"), load("cbipo.json"), load("cb_temp.json"), load("cb_sig.json")]);
  const SG = sigMap(sg);
  if (!js) { app.innerHTML = `<h1>可轉債</h1>${emptyBox("可轉債資料還沒產生（每個交易日收盤後更新）")}`; return; }
  const today = js.date;
  const rows = js.rows.map(r => ({...r, spark: SPARK[r.stock], sig: sigTags(sg, r.code).filter(([k]) => SG[k])}));
  const nIpo = (ipo?.items || []).filter(x => x.status !== "已掛牌" && x.status !== "取消").length;
  const card = (n, t, href) => `<a class="kcard" ${href ? `href="${href}"` : ""}><b>${fi(n)}</b><span>${t}</span></a>`;
  app.innerHTML = `<h1>可轉債</h1>
    <p class="sub">資料日 ${esc(today)}。櫃買中心每日行情與轉換公司債資訊看板，加上發行資料，算出轉換價值、溢價率、剩餘比率、賣回報酬與理論權利金。點一列看 K 線與完整條件。</p>
    <div class="kcards">${card(rows.length, "可轉債檔數")}${card(new Set(rows.map(r => r.stock)).size, "發行公司數")}
      ${card(rows.filter(r => r.maturity && r.maturity <= addDays(today, 182)).length, "6 個月內到期")}
      ${card(rows.filter(r => r.lots > 0).length, "今日有成交")}${card(nIpo, "即將發行（IPO）", "#/cbipo")}</div>
    ${cbTempCard(temp)}
    <div class="toolbar"><span class="chips" id="cf"></span></div>
    ${sg ? `<div class="sigbar"><span class="lbl"><a href="#/cbsig">鄭大訊號</a> <span class="small muted">近 ${(sg.days || []).length} 個交易日</span></span><span class="chips" id="sf"></span></div>` : ""}
    <details class="adv"><summary>進階篩選（區間）</summary><div class="advgrid" id="adv"></div>
      <p class="small muted">留空＝不限制。條件可以組合，例如溢價率 −3～3（股債緊密連動）＋剩餘比率 ≥ 80＋有擔保。</p></details>
    <div class="toolbar"><input type="search" id="cq" placeholder="代號、名稱或股票" aria-label="搜尋可轉債"><span class="small muted" id="cn"></span></div>
    <div id="ct"></div>
    <p class="small muted">資料來源：證券櫃檯買賣中心（每日轉(交)換公司債買賣斷交易行情表、轉換公司債資訊看板、轉(交)換債發行資料）。走勢欄是標的股票近 160 日。
    理論權利金折現率 ${(js.discount * 100).toFixed(1)}%。所有數字由程式計算，僅供參考。</p>`;
  if (temp) chips(document.getElementById("trg"), [["1y", "近一年"], ["all", "2017 至今"]], "1y", v => { document.getElementById("tchart").innerHTML = cbTempChart(temp, v); });
  const quick = [
    ["", "全部", () => true],
    ["r30", "剩餘比率 < 30%", r => r.remain != null && r.remain < 30],
    ["r80", "剩餘比率 > 80%", r => r.remain > 80],
    ["p106", "CB 價 ≤ 106", r => r.price != null && r.price <= 106],
    ["deep", "深度價內（轉換價值 ≥ 130）", r => r.conv_value >= 130],
    ["tight", "股債緊密連動（溢價 ±3%）", r => r.premium != null && Math.abs(r.premium) <= 3],
    ["disc", "折價（溢價 < 0）", r => r.premium != null && r.premium < 0],
    ["new", "新發行（90 天內）", r => r.listing_date && r.listing_date >= addDays(today, -90)],
    ["mat", "快到期（90 天內）", r => r.maturity && r.maturity <= addDays(today, 90)],
    ["put", "一年內賣回／到期", r => r.target_date && r.target_date <= addDays(today, 365)],
    ["near100", "轉換價值 90~110", r => r.conv_value >= 90 && r.conv_value <= 110],
    ["opt", "權利金 < 5", r => r.option != null && r.option < 5],
    ["yield", "賣回年化 ≥ 2%", r => r.put_yield >= 2],
    ["traded", "今日有成交", r => r.lots > 0],
  ];
  const ranges = [["price", "CB 價格"], ["conv_price", "轉換價"], ["conv_value", "轉換價值"], ["premium", "溢價率 %"],
    ["stock_close", "股價"], ["remain", "剩餘比率 %"], ["years", "距賣回／到期（年）"], ["option", "理論權利金"]];
  const dates = [["issue_date", "發行日"], ["maturity", "到期日"]];
  document.getElementById("adv").innerHTML = ranges.map(([k, t]) => `<label><span>${t}</span><span class="rng"><input type="number" step="any" data-k="${k}" data-b="lo" placeholder="下限">～<input type="number" step="any" data-k="${k}" data-b="hi" placeholder="上限"></span></label>`).join("")
    + dates.map(([k, t]) => `<label><span>${t}</span><span class="rng"><input type="date" data-k="${k}" data-b="lo">～<input type="date" data-k="${k}" data-b="hi"></span></label>`).join("")
    + `<label><span>擔保</span><select id="cg"><option value="">不拘</option><option value="1">有擔保</option><option value="0">無擔保</option></select></label>`
    + `<label><span>&nbsp;</span><button type="button" class="btn" id="cclr">清除全部條件</button></label>`;
  let flt = "", q = "", per = {}, sflt = "";
  const H = {};   // 已載入的個別走勢 cbh/代號.json
  const adv = {};
  const t = table(document.getElementById("ct"), [
    {k: "code", t: "代號", f: r => `<span class="code">${esc(r.code)}</span>`},
    {k: "name", t: "名稱", f: r => `<b>${esc(r.name)}</b><br><span class="small muted">${stockLink(r.stock, r.stock_name || r.stock)} ${esc(r.stock)}</span>`
      + (r.sig.length ? `<div class="stags">${r.sig.sort((a, b) => (SIG_ORD[SG[a[0]].verdict] - SIG_ORD[SG[b[0]].verdict])).map(([k, d]) => sigTag(SG[k], d, sg.date)).join("")}</div>` : "")},
    {k: "price", t: "CB 價", n: 1, f: r => r.close != null ? `${fp(r.close)}<br>${pc(r.chg_pct, 1)}` : `<span class="muted" title="今日無成交，顯示參考價">${fp(r.price)}</span>`},
    {k: "lots", t: "張數", n: 1, f: r => r.lots ? fi(r.lots) : '<span class="muted">—</span>'},
    {k: "conv_value", t: `轉換價值 ${tipBtn(CB_TIP.cv)}`, n: 1, f: r => fx(r.conv_value, 2)},
    {k: "premium", t: `溢價率 ${tipBtn(CB_TIP.prem)}`, n: 1, f: r => r.premium == null ? "—" : `<span class="${r.premium < 0 ? "up" : Math.abs(r.premium) <= 3 ? "warn" : ""}">${r.premium > 0 ? "+" : ""}${fx(r.premium, 2)}%</span>`},
    {k: "stock_close", t: "股價", n: 1, f: r => `${fp(r.stock_close)}<br>${pc(r.stock_chg, 1)}`},
    {k: "conv_price", t: "轉換價", n: 1, f: r => fp(r.conv_price)},
    {k: "remain", t: `剩餘比率 ${tipBtn(CB_TIP.remain)}`, n: 1, f: r => r.remain == null ? "—" : r.remain < 30 ? `<span class="tag up">${fx(r.remain, 1)}%</span>` : fx(r.remain, 1) + "%"},
    {k: "out_amt", t: "餘額(億)", n: 1, f: r => yi2(r.out_amt)},
    {k: "target_date", t: `賣回／到期 ${tipBtn(CB_TIP.put)}`, f: r => r.target_date ? `${esc(r.target_date)}<br><span class="small muted">${r.target}${r.target_price ? " " + fx(r.target_price, 2) : ""}</span>` : "—"},
    {k: "put_yield", t: "賣回報酬", n: 1, f: r => r.put_ret == null ? "—" : `${pc(r.put_ret, 1)}<br><span class="small muted">年化 ${r.put_yield == null ? "—" : fx(r.put_yield, 1) + "%"}</span>`},
    {k: "option", t: `權利金 ${tipBtn(CB_TIP.opt)}`, n: 1, f: r => fx(r.option, 2)},
    {k: "guaranteed", t: "擔保", f: r => r.guaranteed ? '<span class="tag ok">有</span>' : '<span class="muted small">無</span>', s: r => r.guaranteed ? 1 : 0},
    {k: "issue_date", t: "發行日", f: r => esc(r.issue_date || "—")},
    {k: "maturity", t: "到期日", f: r => esc(r.maturity || "—")},
  ], [], {sort: ["code", 1], id: r => r.code, empty: "沒有符合條件的可轉債",
    expand: r => {
      const kv = (a, b) => `<tr><th>${a}</th><td>${b ?? "—"}</td></tr>`;
      const n = per[r.code] || 126;
      const hj = H[r.code];
      if (hj === undefined) { H[r.code] = null; load(`cbh/${r.code}.json`).then(x => { H[r.code] = x || {dates: [], rows: []}; apply(); }); }
      const outs = (hj?.rows || []).map((x, i) => [i, ...x]).filter(x => x[8] != null);
      const weeks = [];
      for (let i = outs.length - 1; i >= 0 && weeks.length < 6; i -= 5) weeks.push(outs[i]);
      const inst = r.inst ? r.inst.map((v, i) => `${["外資", "投信", "自營"][i]} <span class="${sign(v)}">${v > 0 ? "+" : ""}${fi(v)}</span>`).join("　") : "—";
      return `<div class="cbhead"><b>${esc(r.stock_name || r.stock)} ${esc(r.stock)}</b>
          <span>收盤 <b class="${sign(r.stock_chg)}">${fp(r.stock_close)}</b> ${pc(r.stock_chg, 2)}</span>
          <span>成交 ${r.stock_lots == null ? "—" : fi(r.stock_lots) + " 張"}</span>
          <span>MA5／MA20 ${fp(r.ma5)}／${fp(r.ma20)}${r.ma20 && r.stock_close ? ` <span class="small ${r.stock_close >= r.ma20 ? "up" : "down"}">${r.stock_close >= r.ma20 ? "站上月線" : "跌破月線"}</span>` : ""}</span>
          <span>5 日均量 ${r.v5 == null ? "—" : fi(r.v5) + " 張"}（月均 ${r.v20 == null ? "—" : fi(r.v20)}）</span>
          <span>三大法人 ${inst}</span></div>
        <div class="cbd"><div><div class="chips small" data-per="${esc(r.code)}">${CB_P.map(([l, v]) => `<button type="button" class="chip ${v === n ? "on" : ""}" data-n="${v}">${l}</button>`).join("")}</div>
          ${hj ? cbChart(hj, n) : '<p class="muted small">載入走勢中…</p>'}
          ${weeks.length > 1 ? `<h4>近幾週餘額</h4><table class="kv"><tbody>${weeks.map((x, i) => { const prev = weeks[i + 1]; const ch = prev && prev[8] ? (x[8] / prev[8] - 1) * 100 : null;
            return `<tr><th>${esc(hj.dates[x[0]])}</th><td>${fx(x[8], 2)} 億${ch ? `　<span class="${sign(ch)}">${ch > 0 ? "+" : ""}${fx(ch, 2)}%</span>` : ""}</td></tr>`; }).join("")}</tbody></table>` : ""}</div>
        <table class="kv"><tbody>
        ${kv("開／高／低／均", [r.open, r.high, r.low, r.avg].map(fp).join(" / "))}
        ${kv("成交", r.lots ? `${fi(r.lots)} 張、${fi(r.trades)} 筆、${yi(r.value)}${r.nego_lots ? `（議價 ${fi(r.nego_lots)} 張）` : ""}` : "今日無成交")}
        ${kv("目前轉換價", `${fp(r.conv_price)}${r.conv_price_issue && r.conv_price_issue !== r.conv_price ? `（發行時 ${fp(r.conv_price_issue)}）` : ""}${r.conv_next_date ? `，下次調整生效 ${esc(r.conv_next_date)}` : ""}`)}
        ${kv("轉換比例", r.ratio == null ? "—" : `每張 CB 可轉 ${fx(r.ratio, 4)} 張股票`)}
        ${kv("轉換期間", `${esc(r.conv_start || "—")} ~ ${esc(r.conv_end || "—")}`)}${r.stop_conv ? kv("停止轉換", r.stop_conv.map(esc).join(" ~ ")) : ""}
        ${kv("發行／餘額", `${yi2(r.issue_amt)} 億 → ${yi2(r.out_amt)} 億（剩餘 ${r.remain == null ? "—" : fx(r.remain, 1) + "%"}）`)}
        ${kv("可轉換股票", r.conv_lots == null ? "—" : `${fi(r.conv_lots)} 張（稀釋股本 ${r.dilution == null ? "—" : fx(r.dilution, 2) + "%"}）`)}
        ${kv("發行日／上櫃日／到期日", [r.issue_date, r.listing_date, r.maturity].map(x => esc(x || "—")).join(" / "))}
        ${kv("剩餘天數", r.days_left == null ? "—" : fi(r.days_left) + " 天")}
        ${kv("下次賣回", r.put_date ? `${esc(r.put_date)} 價格 ${fx(r.put_price, 4)}` : "無（以到期面額 100 計）")}
        ${r.call ? kv("強制贖回", `${esc(r.call[0])} ~ ${esc(r.call[1])} 價格 ${fx(r.call[2], 4)}`) : ""}
        ${r.halt ? kv("停止交易", r.halt.map(esc).join(" ~ ")) : ""}
        ${kv("票面利率", r.coupon == null ? "—" : fx(r.coupon, 3) + "%")}${kv("擔保", r.guaranteed ? esc(r.guarantee || "有") : "無擔保")}
        ${kv("評等", esc(r.rating || "—"))}${kv("受託／承銷", `${esc(r.trustee || "—")}／${esc(r.underwriter || "—")}`)}
        </tbody></table></div>`;
    }});
  function apply() {
    const f = quick.find(x => x[0] === flt)[2];
    const g = document.getElementById("cg").value;
    const ok = r => Object.entries(adv).every(([k, [lo, hi]]) => {
      const v = r[k]; if (lo === "" && hi === "") return true; if (v == null || v === "") return false;
      return (lo === "" || v >= (typeof v === "number" ? +lo : lo)) && (hi === "" || v <= (typeof v === "number" ? +hi : hi));
    });
    const sf = sflt === "" ? () => true : sflt === "*" ? r => r.sig.length > 0 : sflt === "pass" ? r => r.sig.some(([k]) => SG[k].verdict === "通過") : r => r.sig.some(([k]) => k === sflt);
    const out = rows.filter(r => f(r) && sf(r) && ok(r) && (g === "" || !!r.guaranteed === (g === "1"))
      && (!q || r.code.includes(q) || (r.name || "").includes(q) || (r.stock || "").includes(q) || (r.stock_name || "").includes(q)));
    document.getElementById("cn").textContent = `共 ${out.length} 檔`;
    t.set(out);
  }
  chips(document.getElementById("cf"), quick.map(f => [f[0], `${f[1]} ${rows.filter(f[2]).length}`]), "", v => { flt = v; apply(); });
  if (sg) {
    const cnt = k => rows.filter(r => r.sig.some(([x]) => x === k)).length;
    const sl = [...sg.signals].sort((a, b) => SIG_ORD[a.verdict] - SIG_ORD[b.verdict] || (a.kind === "警") - (b.kind === "警")).filter(s => cnt(s.key));
    chips(document.getElementById("sf"), [["", "不限"], ["pass", `★ 回測通過 ${rows.filter(r => r.sig.some(([k]) => SG[k].verdict === "通過")).length}`],
      ["*", `有任何訊號 ${rows.filter(r => r.sig.length).length}`], ...sl.map(s => [s.key, `${s.kind === "警" ? "⚠" : ""}${s.name} ${cnt(s.key)}`])], "", v => { sflt = v; apply(); });
  }
  document.getElementById("cq").oninput = e => { q = e.target.value.trim(); apply(); };
  document.getElementById("adv").oninput = e => {
    const el = e.target; if (!el.dataset.k) { apply(); return; }
    const cur = adv[el.dataset.k] || ["", ""]; cur[el.dataset.b === "lo" ? 0 : 1] = el.value; adv[el.dataset.k] = cur; apply();
  };
  document.getElementById("cclr").onclick = () => { document.querySelectorAll("#adv input").forEach(i => i.value = ""); document.getElementById("cg").value = ""; for (const k in adv) delete adv[k]; apply(); };
  document.getElementById("ct").addEventListener("click", e => {
    const b = e.target.closest("[data-per] .chip"); if (!b) return;
    e.stopPropagation(); per[b.closest("[data-per]").dataset.per] = +b.dataset.n; apply();
  }, true);
  apply();
};

// ---- CB 訊號（鄭詩翰的規則寫成程式＋歷史回測）----
const SIG_ORD = {"通過": 0, "只有一段有效": 1, "樣本不足": 2, "未通過": 3};
const SIG_VC = {"通過": "ok", "只有一段有效": "mid", "樣本不足": "na", "未通過": "no"};
const p1 = x => x == null ? "—" : `${x > 0 ? "+" : ""}${(x * 100).toFixed(1)}%`;
const p0 = x => x == null ? "—" : `${Math.round(x * 100)}%`;
const sigMap = sg => Object.fromEntries((sg?.signals || []).map(s => [s.key, s]));
function sigTags(sg, code) {   // 一檔 CB 近幾日的訊號（同訊號只留最近一天）
  const m = {};
  for (const [k, d] of sg?.tags?.[code] || []) if (!m[k] || d > m[k]) m[k] = d;
  return Object.entries(m).map(([k, d]) => [k, d]);
}
function sigTag(s, d, today) {
  if (!s) return "";
  const good = s.verdict === "通過", warn = s.kind === "警";
  const a = s.all || {};
  const tip = `${s.name}（${warn ? "警訊" : "做多"}，回測${s.verdict}）\n規則：${s.rule}\n觸發日 ${d}` +
    (a.cbx60 != null ? `\n歷史 ${a.n} 次：之後 60 日 CB 平均 ${p1(a.cb60)}（全部 CB ${p1(a.cbbase60)}）` +
      `\n${warn ? `大賠（≤−10%）機率 ${p0(a.loss)}（全部 CB ${p0(a.lossbase)}）` : `大賺（≥+20%）機率 ${p0(a.big)}（全部 CB ${p0(a.bigbase)}）`}` : "");
  return `<a class="stag ${warn ? "w" : good ? "g" : "b"}" href="#/cbsig/${esc(s.key)}" title="${esc(tip)}">${warn ? "⚠" : good ? "★" : ""}${esc(s.name)}${d !== today ? `<small>${esc(d.slice(5).replace("-", "/"))}</small>` : ""}</a>`;
}

P.cbsig = async (key) => {
  setTitle("CB 策略");
  const [sg, js] = await Promise.all([load("cb_sig.json"), load("cb.json")]);
  if (!sg) { app.innerHTML = `<h1>CB 策略</h1>${emptyBox("訊號資料還沒產生（每個交易日可轉債更新後產生）")}`; return; }
  const CBR = Object.fromEntries((js?.rows || []).map(r => [r.code, r]));
  const hits = {};
  for (const code of Object.keys(sg.tags)) for (const [k, d] of sigTags(sg, code)) (hits[k] ||= []).push([code, d]);
  for (const k in hits) hits[k].sort((a, b) => b[1].localeCompare(a[1]) || a[0].localeCompare(b[0]));
  const list = [...sg.signals].sort((a, b) => (SIG_ORD[a.verdict] ?? 9) - (SIG_ORD[b.verdict] ?? 9) || (a.kind === "警") - (b.kind === "警"));
  const rng = sg.stats_range || [], days = sg.days || [];
  const vd = s => `<span class="vd ${SIG_VC[s.verdict] || "na"}">${s.verdict === "通過" ? "✓ 回測通過" : s.verdict === "未通過" ? "✗ 回測未通過" : esc(s.verdict)}</span>`;
  const kd = s => s.kind === "警" ? '<span class="tag warn">警訊</span>' : '<span class="tag up">做多</span>';
  const vs = (x, b, warn) => x == null ? "—" : `<b class="${x > b * 1.2 ? (warn ? "down" : "up") : x < b ? "muted" : ""}">${p0(x)}</b> <span class="small muted">／全部 ${p0(b)}</span>`;
  const xs = x => x == null ? "—" : `<b class="${x > 0.005 ? "up" : x < -0.005 ? "down" : "muted"}">${p1(x)}</b>`;
  const hitRow = ([code, d]) => { const r = CBR[code] || {};
    return `<tr><td>${esc(d.slice(5).replace("-", "/"))}</td><td><span class="code">${esc(code)}</span> <b>${esc(r.name || "")}</b></td>
      <td class="small">${r.stock ? stockLink(r.stock, r.stock_name || r.stock) : "—"}</td><td class="num">${fp(r.price)}</td><td class="num">${fx(r.conv_value, 1)}</td>
      <td class="num">${r.premium == null ? "—" : fx(r.premium, 1) + "%"}</td><td class="num">${r.remain == null ? "—" : fx(r.remain, 0) + "%"}</td></tr>`; };
  const hitTable = l => `<div class="tw"><table><thead><tr><th>觸發</th><th>可轉債</th><th>股票</th><th class="num">CB 價</th><th class="num">轉換價值</th><th class="num">溢價率</th><th class="num">剩餘</th></tr></thead><tbody>${l.map(hitRow).join("")}</tbody></table></div>`;
  const card = s => {
    const warn = s.kind === "警", a = s.all || {}, h = hits[s.key] || [];
    const per = [["全部", a], [`前段（~${(sg.split || "").slice(0, 7)}）`, s.early || {}], ["後段", s.late || {}]];
    const yrs = Object.entries(s.yearly || {});
    return `<section class="sgc ${SIG_VC[s.verdict] || "na"}" id="sg-${esc(s.key)}">
      <div class="sgh"><h2>${esc(s.name)}</h2>${kd(s)}${vd(s)}<span class="small muted">近 ${days.length} 個交易日觸發 <b>${h.length}</b> 檔</span></div>
      <p class="rule"><b>規則</b>　${esc(s.rule)}</p>
      <p class="src"><b>他的說法</b>　${esc(s.source)}</p>
      <div class="sgnum">
        <div><span>之後 60 日 CB 平均</span><b class="${(a.cbx60 || 0) > 0.005 ? "up" : (a.cbx60 || 0) < -0.005 ? "down" : ""}">${p1(a.cb60)}</b><small>全部 CB 同期 ${p1(a.cbbase60)}</small></div>
        <div><span>${warn ? "大賠（≤−10%）機率" : "大賺（≥+20%）機率"}</span><b>${p0(warn ? a.loss : a.big)}</b><small>全部 CB ${p0(warn ? a.lossbase : a.bigbase)}</small></div>
        <div><span>歷史次數</span><b>${fi(a.n)}</b><small>${esc((rng[0] || "").slice(0, 4))}~${esc((rng[1] || "").slice(0, 4))}</small></div>
      </div>
      <div class="tw"><table class="mini"><thead><tr><th>期間</th><th class="num">次數</th><th class="num">CB 60 日超額</th><th class="num">大賺機率</th><th class="num">大賠機率</th><th class="num">股票 60 日超額</th></tr></thead><tbody>
        ${per.map(([l, x]) => `<tr><th>${l}</th><td class="num">${fi(x.n)}</td><td class="num">${xs(x.cbx60)}</td><td class="num">${vs(x.big, x.bigbase, false)}</td><td class="num">${vs(x.loss, x.lossbase, true)}</td><td class="num">${xs(x.mean60)}</td></tr>`).join("")}
      </tbody></table></div>
      ${a.hz ? `<h4>持有幾天比較好？</h4><div class="tw"><table class="mini hz"><thead><tr><th></th>${Object.keys(a.hz).map(n => `<th class="num">${n} 天</th>`).join("")}</tr></thead><tbody>
        <tr><th>股票比大盤</th>${Object.values(a.hz).map(v => `<td class="num">${xs(v[0])}${v[1] == null ? "" : `<br><span class="small muted">勝率 ${p0(v[1])}</span>`}</td>`).join("")}</tr>
        <tr><th>CB 比全部 CB</th>${Object.values(a.hz).map(v => `<td class="num">${xs(v[2])}</td>`).join("")}</tr></tbody></table></div>
        <p class="small muted">隔天收盤進場。參考：所有發 CB 的股票本身就常落後大盤（60 天平均約 −0.7%、勝率約 37~44%）。</p>` : ""}
      ${s.note ? `<div class="snote"><b>分組回測補充</b>${esc(s.note)}</div>` : ""}
      ${yrs.length ? `<div class="yrs" title="每年觸發後 60 日 CB 比全部 CB 多（紅）或少（綠）">${yrs.map(([y, v]) => {
        const x = v.cbx60, al = Math.min(1, Math.abs(x || 0) / 0.08);
        return `<div style="--a:${al.toFixed(2)}" class="${x > 0 ? "p" : "n"}"><span>${y.slice(2)}</span><b>${p1(x)}</b><small>${v.n} 次</small></div>`; }).join("")}</div>` : ""}
      ${h.length ? `<h4>近 ${days.length} 個交易日符合</h4>${hitTable(h)}` : `<p class="small muted">近 ${days.length} 個交易日沒有可轉債符合。</p>`}
      ${(s.examples || []).length ? `<details class="adv"><summary>歷史最近 ${s.examples.length} 次</summary><div class="tw"><table class="mini"><thead><tr><th>日期</th><th>可轉債</th><th class="num">CB 60 日</th><th class="num">超額</th></tr></thead><tbody>
        ${s.examples.slice().reverse().map(e => `<tr><td>${esc(e.date)}</td><td><span class="code">${esc(e.code)}</span> ${esc(e.name || "")}</td><td class="num">${e.cb60 == null ? '<span class="muted">未滿 60 日</span>' : pc(e.cb60 * 100, 1)}</td><td class="num">${e.cbx60 == null ? "—" : xs(e.cbx60)}</td></tr>`).join("")}</tbody></table></div></details>` : ""}
    </section>`;
  };
  const pass = list.filter(s => s.verdict === "通過");
  app.innerHTML = `<h1>CB 策略</h1>
    <p class="sub">把鄭詩翰在 FB 分享過的 ${list.length} 個可轉債規則寫成程式，每天收盤後標出符合的 CB（可轉債頁名稱下方的小標籤），
      並用 ${esc(rng[0] || "")} ~ ${esc(rng[1] || "")} 的歷史資料回測「訊號出現後 60 個交易日，這檔 CB 有沒有比全部 CB 平均漲得多」。資料日 ${esc(sg.date)}。</p>
    <div class="notice"><b>怎麼看</b>：他買的是 CB／CBAS，所以主要看 CB 本身。CB 報酬很偏（少數大賺拉高平均），不看勝率，看兩件事：
      ① 60 日平均有沒有比全部 CB 高（超額 &gt; 0）；② 大賺（60 日 ≥ +20%）的機率是不是全部 CB 的 1.2 倍以上。
      2022/7 前後兩段<b>都</b>成立、且各有 30 次以上才算「通過」；警訊反過來看大賠（≤ −10%）。
      ★ 紅標＝回測通過的做多訊號，灰標＝他有講但回測沒驗證到優勢，⚠ 黃標＝警訊。回測每週六用最新的長期資料庫自動重算${sg.stats_updated ? `（上次 ${esc(sg.stats_updated)}）` : ""}。</div>
    <div class="tw"><table class="sgsum"><thead><tr><th>訊號</th><th>類型</th><th>回測</th><th class="num">次數</th><th class="num">CB 60 日超額<br><span class="small muted">前段／後段</span></th><th class="num">大賺機率<br><span class="small muted">訊號／全部 CB</span></th><th class="num">近 ${days.length} 日</th></tr></thead><tbody>
      ${list.map(s => { const a = s.all || {}; return `<tr data-k="${esc(s.key)}"><td><a href="#/cbsig/${esc(s.key)}"><b>${esc(s.name)}</b></a></td><td>${kd(s)}</td><td>${vd(s)}</td><td class="num">${fi(a.n)}</td>
        <td class="num">${xs(s.early?.cbx60)}／${xs(s.late?.cbx60)}</td><td class="num">${p0(a.big)}／${p0(a.bigbase)}</td><td class="num">${(hits[s.key] || []).length ? `<b>${hits[s.key].length}</b>` : '<span class="muted">0</span>'}</td></tr>`; }).join("")}
    </tbody></table></div>
    ${pass.length ? `<h2>今天可以留意</h2><p class="small muted">回測通過的訊號，近 ${days.length} 個交易日符合的 CB。這只代表「歷史上平均比較好」，不是買進建議；仍要看公司基本面與 CB 條件。</p>
      ${pass.map(s => (hits[s.key] || []).length ? `<h3 class="sgt">${esc(s.name)}</h3>${hitTable(hits[s.key])}` : `<p class="small muted">${esc(s.name)}：近 ${days.length} 日沒有符合。</p>`).join("")}` : ""}
    <h2>每個訊號的回測</h2>
    <div class="sgcs">${list.map(card).join("")}</div>
    <p class="small muted">進場用訊號隔天收盤價；超額＝這檔 CB 之後 60 個交易日漲跌 − 同一天全部 CB 平均漲跌。同一檔同一訊號 20 個交易日內只算一次。
      股票超額＝標的股還原報酬 − 全市場等權報酬（股票資料目前 2018/7 起，長期資料庫補齊後會自動拉長）。訊號規則由他公開貼文整理，可能與他實際操作不同。所有數字僅供參考。</p>`;
  app.querySelectorAll(".sgsum tbody tr").forEach(tr => tr.onclick = e => { if (e.target.closest("a")) return; location.hash = `#/cbsig/${tr.dataset.k}`; });
  if (key) { const el = document.getElementById(`sg-${key}`); if (el) { el.classList.add("hl"); setTimeout(() => el.scrollIntoView({block: "start"}), 30); } }
};

// ---- 可轉債 IPO ----
const IPO_ORDER = {"詢圈中": 0, "競拍中": 1, "待開標": 2, "待詢圈": 3, "待競拍": 3, "待掛牌": 4, "已申報": 5, "已掛牌": 6, "取消": 7};
const IPO_ST = {"詢圈中": "up", "競拍中": "up", "待開標": "warn", "待詢圈": "warn", "待競拍": "warn", "待掛牌": "ok", "已申報": "", "已掛牌": "pur", "取消": ""};
P.cbipo = async () => {
  setTitle("可轉債 IPO");
  const js = await load("cbipo.json");
  app.innerHTML = `<h1>可轉債 IPO</h1>
    <p class="sub">預計發行與近 60 天上櫃的可轉債。合併證券商業同業公會的承銷／詢圈公告、證交所競價拍賣公告與櫃買發行資料。${js ? `更新 ${esc(js.date)}。` : ""}</p>
    <div class="toolbar"><span class="chips" id="if"></span><input type="search" id="iq" placeholder="代號或名稱" aria-label="搜尋"></div><div id="it"></div>
    <p class="small muted">詢圈價格區間是 CB 每百元的承銷價格範圍；競拍得標價也是每百元價格。轉換價值＝100 ÷ 發行轉換價 × 目前股價。TCRI 評等與證期會申報生效日不是公開資料，這裡沒有。</p>`;
  if (!js) { document.getElementById("it").innerHTML = emptyBox("資料還沒產生"); return; }
  const items = js.items.map(r => ({...r, code: r.stock, name: r.stock_name || r.company, spark: SPARK[r.stock]}));
  let flt = "", q = "";
  const t = table(document.getElementById("it"), [
    {k: "status", t: "狀態", s: r => IPO_ORDER[r.status] ?? 9, f: r => `<span class="tag ${IPO_ST[r.status] || ""}">${esc(r.status)}</span>`},
    {k: "code", t: "代號", f: r => r.stock ? `<span class="code">${esc(r.stock)}</span>` : "—"},
    {k: "name", t: "名稱", cls: "soft", f: r => `${r.stock ? stockLink(r.stock, r.stock_name) : esc(r.company)}${r.short ? `<br><span class="small muted">${esc(r.short)} ${esc(r.bond || "")}</span>` : ""}`},
    {k: "guaranteed", t: "擔保", f: r => r.guaranteed ? '<span class="tag ok">有</span>' : '<span class="muted small">無</span>', s: r => r.guaranteed ? 1 : 0},
    {k: "method", t: "方式", f: r => esc(r.method === "詢價圈購" ? "詢圈" : "競拍")},
    {k: "amount", t: "發行量(億)", n: 1, f: r => r.amount ? fx(r.amount / 1e8, 2) : (r.auc_lots ? `<span class="small muted">競拍 ${fi(r.auc_lots)} 張</span>` : "—")},
    {k: "underwriter", t: "主辦", f: r => esc((r.underwriter || "—").replace(/(綜合)?證券股份有限公司|股份有限公司/g, ""))},
    {k: "filed", t: "申報日", f: r => esc(r.filed || "—")},
    {k: "period", t: "詢圈／投標期間", s: r => r.bb_start || r.auc_start, f: r => r.bb_start ? `${md(r.bb_start)}~${md(r.bb_end)}` : r.auc_start ? `${md(r.auc_start)}~${md(r.auc_end)}<br><span class="small muted">開標 ${md(r.auc_open)}</span>` : "—"},
    {k: "price", t: "價格", s: r => r.won_avg || r.auc_min, f: r => r.bb_price ? `<span class="small">${esc(r.bb_price)}</span>` : r.won_avg ? `得標均價 <b>${fx(r.won_avg, 2)}</b><br><span class="small muted">${fx(r.won_low, 2)}~${fx(r.won_high, 2)}</span>` : r.auc_min ? `<span class="small">最低投標 ${fx(r.auc_min, 2)}</span>` : "—"},
    {k: "conv_price", t: "轉換價", n: 1, f: r => fp(r.conv_price)},
    {k: "parity", t: "轉換價值", n: 1, f: r => fx(r.parity, 2)},
    {k: "stock_close", t: "股價", n: 1, f: r => fp(r.stock_close)},
    {k: "listing", t: "掛牌日", f: r => esc(r.listing || "—")},
    {k: "tenor", t: "年期", n: 1, f: r => r.tenor ? r.tenor + " 年" : "—"},
    {k: "cb_close", t: "上櫃後", n: 1, f: r => r.cb_close ? `${fp(r.cb_close)}<br><span class="small muted">溢價 ${fx(r.cb_premium, 1)}%</span>` : "—"},
  ], [], {sort: ["status", 1], id: r => (r.stock || r.company) + (r.bond || "") + r.method + (r.filed || ""), empty: "沒有資料"});
  const filters = [["", "全部", () => true], ["live", "進行中（詢圈／競拍）", r => /中|待開標/.test(r.status)],
    ["soon", "即將掛牌", r => r.status === "待掛牌"], ["new", "近 60 天已掛牌", r => r.status === "已掛牌"], ["g", "有擔保", r => r.guaranteed]];
  function apply() {
    const f = filters.find(x => x[0] === flt)[2];
    t.set(items.filter(r => f(r) && (!q || (r.stock || "").includes(q) || (r.stock_name || r.company || "").includes(q) || (r.short || "").includes(q))));
  }
  chips(document.getElementById("if"), filters.map(f => [f[0], `${f[1]} ${items.filter(f[2]).length}`]), "", v => { flt = v; apply(); });
  document.getElementById("iq").oninput = e => { q = e.target.value.trim(); apply(); };
  apply();
};

// ---- 私募 ----
const PP_ST = {"董事會擬辦": "pur", "應募人": "warn", "定價": "up", "收足股款": "ok", "取消": "", "轉換/賣回": "", "資金運用": "", "其他": ""};
const PP_INV = {"內部人": "warn", "策略投資人": "up", "未定": ""};
P.private = () => annPage("private", "私募", "公司自己辦的私募增資（普通股、私募可轉債、特別股），同一家公司相近時間的公告合成一案。" +
  "私募價通常是參考價的八成，三年內不能賣；應募人是董事長、大股東自己，或是策略投資人，訊號意義不同。金控、壽險「取得」別人私募的投資公告已排除。", [
  {k: "stage", t: "階段", s: r => ({"董事會擬辦": 1, "應募人": 2, "定價": 3, "收足股款": 4, "取消": 5})[r.stage] ?? 6,
   f: r => `<span class="tag ${PP_ST[r.stage] || ""}">${esc(r.stage)}</span>${r.sub ? ' <span class="tag">子公司</span>' : ""}${r.oppose ? ' <span class="tag down" title="獨立董事有反對或保留意見">獨董反對</span>' : ""}`},
  ...idCols,
  {k: "kind", t: "種類", f: r => esc(r.kind)},
  {k: "investor", t: "應募人", f: r => `<span class="tag ${PP_INV[r.investor] || ""}">${esc(r.investor)}</span>${r.names?.length ? `<br><span class="small muted">${r.names.slice(0, 3).map(esc).join("、")}${r.names.length > 3 ? "…" : ""}</span>` : ""}`},
  {k: "shares", t: "股數(萬股)", n: 1, f: r => r.shares ? `${r.cap ? '<span class="small muted">上限 </span>' : ""}${fx(r.shares / 1e4, r.shares < 1e5 ? 1 : 0)}` : "—"},
  {k: "price", t: "私募價", n: 1, f: r => fp(r.price)},
  {k: "ref", t: "參考價", n: 1, f: r => fp(r.ref)},
  {k: "disc", t: "價格成數", n: 1, f: r => r.disc ? `<span class="${r.disc < 0.85 ? "" : r.disc >= 1 ? "up" : ""}">${fx(r.disc * 100, 0)}%</span>` : "—"},
  {k: "amount", t: "金額(億)", n: 1, f: r => r.amount ? fx(r.amount, r.amount < 10 ? 2 : 1) : "—"},
  {k: "close", t: "股價", n: 1, f: r => fp(r.close)},
  {k: "vs_price", t: "比私募價", n: 1, f: r => r.vs_price == null ? "—" : pc(r.vs_price * 100, 1)},
  {k: "ret", t: "公告後", n: 1, s: r => r.ret == null ? null : r.ret - (r.mkt || 0),
   f: r => r.ret == null ? "—" : `${pc(r.ret * 100, 1)}<br><span class="small muted">大盤 ${pc((r.mkt || 0) * 100, 1)}</span>`},
  {k: "date", t: "最新公告", f: r => md(r.date)},
], {sort: ["date", -1],
  groups: [["進行中（擬辦、定價、洽定應募人）", r => ["董事會擬辦", "應募人", "定價"].includes(r.stage), "hot"],
           ["已完成（收足股款）", r => r.stage === "收足股款", ""],
           ["取消、延後與其他（轉換、資金運用）", r => !["董事會擬辦", "應募人", "定價", "收足股款"].includes(r.stage), ""]],
  filters: [["ins", "內部人認購", r => r.investor === "內部人"], ["str", "策略投資人", r => r.investor === "策略投資人"],
            ["cb", "私募 CB／特別股", r => r.kind !== "普通股"], ["self", "排除子公司", r => !r.sub], ["opp", "獨董反對", r => r.oppose]],
  foot: "資料來源：公開資訊觀測站重大訊息。價格成數＝私募價 ÷ 參考價（法規下限通常八成；低於面額 10 元的公司常以面額發行，成數會超過 100%）。" +
    "比私募價＝目前股價 ÷ 私募價 − 1，代表應募人帳面賺賠（三年後才能賣）。公告後＝第一則公告前一日收盤到今天。數字由程式從原文抽取，請點列展開對照。",
  expand: r => rawBlock(r, `<h4>本案公告（${r.events.length} 則）</h4><ol class="small">${r.events.map(e => `<li>${md(e.date)} ${esc(e.time || "")}　<span class="tag ${PP_ST[e.stage] || ""}">${esc(e.stage)}</span> ${esc(e.subject)}</li>`).join("")}</ol>`)});

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
    {k: "market", t: "所", f: r => mk(r.market)}, {k: "code", t: "代號"}, {k: "name", t: "名稱", f: r => stockLink(r.code, r.name, r.spark)},
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
    {k: "market", t: "所", f: r => mk(r.market)}, {k: "code", t: "代號"}, {k: "name", t: "名稱", f: r => stockLink(r.code, r.name, r.spark)},
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
    {k: "name", t: "股票", f: r => `${stockLink(r.code, r.name, r.spark)} <span class="muted small">${r.code}</span>`},
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
    ${SPARK[code] ? `<div class="panel spkpage">${spkInfo({code, name, rec: SPARK[code]})}</div>` : ""}
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

// ---- 國際行情（商品、各國指數、匯率）----
const MK_R = [["1m", "1月", 31], ["3m", "3月", 92], ["6m", "6月", 183], ["1y", "1年", 366], ["3y", "3年", 1096], ["5y", "5年", 1827], ["10y", "10年", 3653], ["all", "全部", 0]];
const mkPx = (v, it) => v == null ? "—" : it?.unit === "%" ? fx(v, 3) : Math.abs(v) < 10 ? fx(v, 4) : Math.abs(v) < 1000 ? fx(v, 2) : fx(v, Math.abs(v) < 1e5 ? 2 : 0);
const mkNow = it => it.live != null && it.live_time && it.live_time.slice(0, 10) >= it.date ? it.live : it.close;
/* 歷史水位：現價在「史低～史高」之間的位置，每 10% 一個顏色（藍＝低檔、紅＝高檔） */
const LV_C = ["#1d4f91", "#2f6db5", "#5b8fd0", "#93b6e2", "#c8d6ea", "#efdcc2", "#f3bb86", "#ea9056", "#d6602f", "#b32d1e"];
const LV_T = ["#fff", "#fff", "#fff", "#10264a", "#10264a", "#4a2a08", "#4a2a08", "#fff", "#fff", "#fff"];
const LV_N = ["史低區", "低檔", "低檔", "中段", "中段", "中段", "中段", "高檔", "高檔", "史高區"];
const LV_W = {all: "全部歷史", y10: "近 10 年"};
const LV_TIP = "水位＝現價在「最低～最高」之間的位置：0% 是歷史最低、100% 是歷史最高，每 10% 一個顏色。\n0~10% 史低區｜10~30% 低檔｜30~70% 中段｜70~90% 高檔｜90~100% 史高區\n\n可切換「全部歷史」或「近 10 年」。各商品資料起始年不同（例如 S&P 500 從 1927 年、黃金從 2000 年），長期一路上漲的指數用全部歷史幾乎都在高檔，看近 10 年比較有參考性。\n\n百分位＝歷史上有幾 % 的交易日收盤比現在低（看現在的價格有多少見）。";
let MK = {view: "card", win: "all", grp: "all"};
try { Object.assign(MK, JSON.parse(localStorage.getItem("mk") || "{}")); } catch {}
const mkSave = () => { try { localStorage.setItem("mk", JSON.stringify(MK)); } catch {} };
function mkLv(it, win = MK.win) {
  const L = it?.lv?.[win] || it?.lv?.all;
  if (!L || (it.n || 0) < 250) return null;      // 不到一年的資料（剛開始累積）不算水位
  const now = mkNow(it), sp = L.hi - L.lo;
  const pos = sp > 0 ? Math.max(0, Math.min(1, (now - L.lo) / sp)) : 0.5;
  return {...L, pos, dec: Math.min(9, Math.floor(pos * 10)), now};
}
const lvChip = v => v ? `<span class="lv" style="background:${LV_C[v.dec]};color:${LV_T[v.dec]}">${LV_N[v.dec]} ${Math.round(v.pos * 100)}%</span>` : '<span class="muted small">累積中</span>';
const mkNote = it => it?.note ? `<span class="tag note" title="${esc(it.note.text)}">⚠ ${esc(it.note.tag)}</span>` : "";
const mkStale = it => it?.date && it.date < addDays(new Date().toISOString().slice(0, 10), -30) ? `<span class="tag warn" title="資料來源已停止更新">停更 ${esc(it.date)}</span>` : "";
function lvBar(v, big) {
  if (!v) return "";
  return `<span class="lvbar${big ? " big" : ""}" aria-label="水位 ${Math.round(v.pos * 100)}%">${LV_C.map(c => `<i style="background:${c}"></i>`).join("")}<em style="left:${(v.pos * 100).toFixed(1)}%"></em></span>`;
}
const ym = d => d ? `${d.slice(0, 4)}/${d.slice(5, 7)}` : "";
const lvLegend = () => `<div class="lvleg">${LV_C.map((c, i) => `<span style="background:${c};color:${LV_T[i]}">${i * 10}</span>`).join("")}<b>${tipBtn(LV_TIP)}</b>
  <small><span>← 史低區</span><span>低檔</span><span>中段</span><span>高檔</span><span>史高區 →</span></small></div>`;
/* 小走勢圖：全部歷史（spark_all），外觀比照股票的小走勢圖：外框、直線＝年份格線（期間 25 年以上每 10 年一條，
   否則每 5 年；不到 5 年每年一條）、虛線＝期初價位；線色紅漲綠跌（和期初比）；紅點史高、綠點史低。
   漲很多倍的用對數刻度，早年才看得出起伏 */
function mkSpark(sp, w = 120, h = 34) {
  const v = Array.isArray(sp) ? sp : sp?.v;
  if (!v || v.filter(x => x != null).length < 2) return "";
  const vs = v.filter(x => x != null), mx = Math.max(...vs), mn = Math.min(...vs);
  const lg = vs.every(x => x > 0) && mx / mn >= 8, tf = x => lg ? Math.log(x) : x;
  const lo = tf(mn), hi = tf(mx), rg = hi - lo || 1, pad = 2.5;
  const X = i => (i / (v.length - 1) * (w - 2 * pad) + pad), Y = x => pad + (1 - (tf(x) - lo) / rg) * (h - 2 * pad);
  const pts = v.map((x, i) => x == null ? null : `${X(i).toFixed(1)},${Y(x).toFixed(1)}`).filter(Boolean);
  const hiI = sp?.hi ?? v.indexOf(mx), loI = sp?.lo ?? v.indexOf(mn);
  const span = sp?.d0 ? (+sp.d1.slice(0, 4)) - (+sp.d0.slice(0, 4)) : 0;
  const step = span >= 25 ? 10 : span >= 5 ? 5 : 1;
  const grid = (sp?.y || []).filter(([, y]) => y % step === 0).map(([k]) => `<line x1="${X(k).toFixed(1)}" x2="${X(k).toFixed(1)}" y1="0" y2="${h}"/>`).join("");
  const by = Y(vs[0]).toFixed(1), dir = vs.at(-1) >= vs[0] ? "up" : "down";
  const tip = sp?.d0 ? `${sp.d0.slice(0, 4)}～${sp.d1.slice(0, 4)} 全部歷史${lg ? "（對數刻度）" : ""}｜直線：每 ${step} 年｜虛線：期初價位｜紅點史高、綠點史低` : "";
  return `<span class="mkbox" title="${esc(tip)}"><svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true">
    <g class="grid">${grid}<line class="base" x1="0" x2="${w}" y1="${by}" y2="${by}"/></g><polyline class="${dir}" points="${pts.join(" ")}"/>
    <line class="shi" x1="${X(hiI)}" x2="${X(hiI)}" y1="${Y(v[hiI])}" y2="${Y(v[hiI])}"/><line class="slo" x1="${X(loI)}" x2="${X(loI)}" y1="${Y(v[loI])}" y2="${Y(v[loI])}"/></svg></span>`;
}
const mkChg = it => { const now = mkNow(it); return it.prev ? (now / it.prev - 1) * 100 : it.chg; };
function mkCard(id, it) {
  if (!it || it.empty) return `<a class="mkcard empty" href="#/mkt/${id}"><span class="mkname">${esc(it?.name || id)}</span><span class="muted small">暫無資料</span></a>`;
  const v = mkLv(it);
  return `<a class="mkcard" href="#/mkt/${id}">
    <span class="mkname">${esc(it.name)}<small>${esc(it.unit)}</small> ${mkStale(it)}${mkNote(it)}</span>
    <span class="mkpx">${mkPx(mkNow(it), it)}</span><span class="mkchg">${pc(mkChg(it))}</span>
    ${mkSpark(it.spark_all || it.spark)}
    <span class="mklv">${lvBar(v)}${lvChip(v)}</span>${v ? `<span class="mkends"><i title="${esc(LV_W[MK.win])}最低（${esc(v.lo_d)}）">低 ${mkPx(v.lo, it)} <s>${esc(ym(v.lo_d))}</s></i><i title="${esc(LV_W[MK.win])}最高（${esc(v.hi_d)}）">高 ${mkPx(v.hi, it)} <s>${esc(ym(v.hi_d))}</s></i></span>` : ""}
    <span class="mkret"><i>1月 ${pc(it.m1, 1)}</i><i>今年 ${pc(it.ytd, 1)}</i><i>1年 ${pc(it.y1, 1)}</i></span></a>`;
}
const MK_TIP = "資料來源：Yahoo Finance（台灣櫃買、滬深 300、泰國、菲律賓、波蘭用鉅亨網；沙烏地用 KSA ETF 代替；俄羅斯用莫斯科交易所、越南用 DNSE／SSI、挪威用 Euronext 官方資料）。商品是期貨「連續近月」價格（換月時會小跳一下），報價延遲約 10~20 分鐘；盤中每 30 分鐘更新一次現價，每晚補齊收盤。\n各代號歷史從 Yahoo 最早有資料的那天開始（例如黃金 2000 年、S&P 500 1927 年、台灣加權 1997 年）。\n有設 FRED 金鑰時，原油、美債、美股指數、匯率會和美國聯準會（FRED）官方資料核對。";
P.mkt = async (id) => {
  const js = await load("mkt.json");
  if (!js) { setTitle("國際行情"); app.innerHTML = `<h1>國際行情</h1>${emptyBox("還沒有資料：下一次排程更新後就會出現。")}`; return; }
  if (id && js.items[id]) return mkDetail(js, id);
  setTitle("國際行情");
  const n = Object.values(js.items).filter(x => !x.empty).length;
  app.innerHTML = `<h1>國際行情 ${tipBtn(MK_TIP)}</h1>
    <p class="sub">${n} 項商品、各國股市指數、匯率利率的現價、全部歷史與歷史水位。點一項看長期走勢。<span class="small muted">更新：${esc(js.updated || "—")}</span></p>
    <div class="mktools"><span class="chips" id="mkv"></span><span class="chips" id="mkw"></span>${lvLegend()}</div>
    <div class="chips mkgchips" id="mkg"></div><div id="mkbody"></div>`;
  const draw = () => {
    if (MK.grp !== "all" && !js.groups.some(g => g.name === MK.grp)) MK.grp = "all";
    const groups = js.groups.filter(g => MK.grp === "all" || g.name === MK.grp);
    const body = document.getElementById("mkbody");
    if (MK.view === "card") {
      body.innerHTML = groups.map(g => `<section class="mkgrp"><h2>${esc(g.name)}</h2>${(g.subs || [{name: "", ids: g.ids}]).map(sb =>
        `${g.subs?.length > 1 ? `<h3 class="mksub">${esc(sb.name)}</h3>` : ""}<div class="mkgrid">${sb.ids.map(i => mkCard(i, js.items[i])).join("")}</div>`).join("")}</section>`).join("");
      return;
    }
    let ord = 0;
    const rows = groups.flatMap(g => g.ids.map(i => ({id: i, ord: ord++, ...js.items[i], grp: js.items[i]?.sub || g.name}))).filter(r => !r.empty)
      .map(r => { const v = mkLv(r); return {...r, now: mkNow(r), chgx: mkChg(r), v, pos: v ? v.pos : null, pr: v ? v.pr : null, offhi: r.ath ? (mkNow(r) / r.ath - 1) * 100 : null}; });
    body.innerHTML = '<div id="mktb"></div>';
    if (matchMedia("(max-width: 640px)").matches) {   // 手機：只留重點欄位，不用左右滑
      table(document.getElementById("mktb"), [
        {k: "ord", t: "名稱", f: r => `<a href="#/mkt/${r.id}">${esc(r.name)}</a>${r.note ? ` <span class="tag note">⚠ ${esc(r.note.tag)}</span>` : ""}<br><span class="small muted">${esc(r.grp)}</span>`},
        {k: "now", t: "現價", n: 1, f: r => `${mkPx(r.now, r)}<br>${pc(r.chgx)}`},
        {k: "y1", t: "1年", n: 1, f: r => pc(r.y1, 1)},
        {k: "pos", t: "水位", n: 1, f: r => lvChip(r.v)},
      ], rows, {sort: ["ord", 1], rowClick: r => { location.hash = "#/mkt/" + r.id; }});
      return;
    }
    table(document.getElementById("mktb"), [
      {k: "ord", t: "分類", cls: "mkc1", f: r => `<span class="small muted" title="${esc(r.grp)}">${esc(r.grp)}</span>`},
      {k: "nm", t: "名稱", cls: "mkc2", s: r => r.name, f: r => `<a href="#/mkt/${r.id}" title="${esc(r.name)}（${esc(r.unit)}）">${esc(r.name)}</a>${mkStale(r) ? '<span class="tag warn">停更</span>' : ""}${r.note ? ` <span class="tag note" title="${esc(r.note.text)}">⚠</span>` : ""}`},
      {k: "now", t: "現價", n: 1, f: r => mkPx(r.now, r)},
      {k: "chgx", t: "漲跌", n: 1, f: r => pc(r.chgx)},
      {k: "", t: "歷史走勢", sortable: false, cls: "mksp", f: r => mkSpark(r.spark_all || r.spark, 110, 28)},
      {k: "first", t: "起始", f: r => `<span class="small muted">${esc((r.first || "").slice(0, 4))}</span>`},
      {k: "pos", t: `水位<br><span class="small muted">${LV_W[MK.win]}</span>`, n: 1, f: r => lvChip(r.v)},
      {k: "pr", t: "百分位", n: 1, f: r => r.pr == null ? "—" : `${fx(r.pr, 0)}%`},
      {k: "offhi", t: "距史高", n: 1, f: r => pc(r.offhi, 1)},
      {k: "w1", t: "1週", n: 1, f: r => pc(r.w1, 1)}, {k: "m1", t: "1月", n: 1, f: r => pc(r.m1, 1)},
      {k: "ytd", t: "今年", n: 1, f: r => pc(r.ytd, 1)}, {k: "y1", t: "1年", n: 1, f: r => pc(r.y1, 1)}, {k: "y5", t: "5年", n: 1, f: r => pc(r.y5, 1)},
    ], rows, {sort: ["ord", 1], rowClick: r => { location.hash = "#/mkt/" + r.id; }});
  };
  const pick = () => { mkSave(); draw(); };
  chips(document.getElementById("mkv"), [["card", "卡片"], ["table", "總表（一次看全部）"]], MK.view, v => { MK.view = v; pick(); });
  chips(document.getElementById("mkw"), [["all", "水位：全部歷史"], ["y10", "水位：近 10 年"]], MK.win, v => { MK.win = v; pick(); });
  chips(document.getElementById("mkg"), [["all", "全部"], ...js.groups.map(g => [g.name, g.name])], MK.grp, v => { MK.grp = v; pick(); });
  draw();
};
function mkChart(d, c, it, logScale) {
  const W = Math.round(Math.min(1100, Math.max(330, (app.clientWidth || 760)))), H = W < 560 ? 240 : 320, L = 8, R = 62, T = 22, B = 24;
  let idx = d.map((_, i) => i);
  const step = Math.ceil(idx.length / 900);
  if (step > 1) idx = idx.filter((i, k) => k % step === 0 || i === d.length - 1);
  // 區間最高、最低一定要畫到（抽樣時不能漏掉）
  let iHi = 0, iLo = 0;
  c.forEach((v, i) => { if (v > c[iHi]) iHi = i; if (v < c[iLo]) iLo = i; });
  idx = [...new Set([...idx, iHi, iLo])].sort((a, b) => a - b);
  const vals = idx.map(i => c[i]);
  const useLog = logScale && Math.min(...vals) > 0;
  const tf = v => useLog ? Math.log(v) : v;
  let lo = c[iLo], hi = c[iHi];
  if (lo === hi) { lo -= 1; hi += 1; }
  const a = tf(lo), b = tf(hi), pad = (b - a) * 0.08;
  const X = k => L + (W - L - R) * k / Math.max(1, idx.length - 1), Y = v => T + (H - T - B) * (1 - (tf(v) - a + pad) / (b - a + 2 * pad));
  let g = "";
  const ticks = [];
  if (useLog) { for (let k = 0; k <= 4; k++) ticks.push(Math.exp(a + (b - a) * k / 4)); }
  else { const raw = (hi - lo) / 4, mag = 10 ** Math.floor(Math.log10(raw)), st = [1, 2, 2.5, 5, 10].map(x => x * mag).find(x => x >= raw) || raw;
    for (let v = Math.ceil(lo / st) * st; v <= hi + 1e-9; v += st) ticks.push(v); }
  const yLast = Y(c.at(-1));
  ticks.forEach(v => { g += `<line class="grid" x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}"/>${Math.abs(Y(v) - yLast) < 14 ? "" : `<text class="ax" x="${W - R + 6}" y="${Y(v) + 4}">${mkPx(v, it)}</text>`}`; });
  const span = (new Date(d.at(-1)) - new Date(d[idx[0]])) / 864e5;
  let last = "", lastX = -99;
  idx.forEach((i, k) => {
    const key = span > 1500 ? d[i].slice(0, 4) : d[i].slice(0, 7);
    if (key !== last) { last = key; const x = X(k);
      if (x - lastX > (span > 1500 ? 46 : 40) && k > 0) { g += `<line class="vgrid" x1="${x}" x2="${x}" y1="${T}" y2="${H - B}"/><text class="ax" x="${x + 3}" y="${H - 7}">${span > 1500 ? key : (+key.slice(5)) === 1 ? key.slice(0, 4) : (+key.slice(5)) + "月"}</text>`; lastX = x; } }
  });
  const line = idx.map((i, k) => `${k ? "L" : "M"}${X(k).toFixed(1)},${Y(c[i]).toFixed(1)}`).join("");
  const area = `${line}L${X(idx.length - 1).toFixed(1)},${H - B}L${L},${H - B}Z`;
  // 最高、最低標記：如果剛好是歷史最高／最低就寫「歷史」，否則寫「區間」
  const mark = (i, kind) => {
    const k = idx.indexOf(i), x = X(k), y = Y(c[i]);
    const isAll = kind === "hi" ? (it.ath != null && c[i] >= it.ath) : (it.atl != null && c[i] <= it.atl);
    const lab = `${isAll ? "歷史" : "區間"}${kind === "hi" ? "最高" : "最低"} ${mkPx(c[i], it)}（${d[i]}）`;
    const anchor = x < W * 0.25 ? "start" : x > (W - R) * 0.75 ? "end" : "middle";
    const ty = kind === "hi" ? Math.max(12, y - 8) : Math.min(H - B - 4, y + 16);
    return `<circle class="mk${kind}${isAll ? " ath" : ""}" cx="${x}" cy="${y}" r="${isAll ? 5 : 4}"/><text class="mklab mk${kind}${isAll ? " ath" : ""}" x="${x}" y="${ty}" text-anchor="${anchor}">${esc(lab)}</text>`;
  };
  return {html: `<svg class="mkchart ${c.at(-1) >= c[idx[0]] ? "up" : "down"}" viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="${esc(it.name)}走勢">
    <defs><linearGradient id="mkA" x1="0" y1="0" x2="0" y2="1"><stop offset="0" class="a0"/><stop offset="1" class="a1"/></linearGradient></defs>
    ${g}<path class="area" d="${area}"/><path class="ln" d="${line}"/>${mark(iHi, "hi")}${mark(iLo, "lo")}
    <line class="xh" id="mkx" y1="${T}" y2="${H - B}" hidden/><circle class="dot" id="mkd" r="4" hidden/>
    <text class="last" x="${W - R + 6}" y="${yLast + 4}">${mkPx(c.at(-1), it)}</text></svg>`, idx, X, Y, W};
}
function lvBlock(it, win) {
  const v = mkLv(it, win);
  if (!v) return "";
  return `<div class="lvblk"><div class="lvhd"><b>${LV_W[win]}</b><span class="small muted">${esc(v.from.slice(0, 4))} 起</span>${lvChip(v)}<span class="small">百分位 ${fx(v.pr, 0)}%</span></div>
    ${lvBar(v, 1)}<div class="lvends"><span>最低 <b>${mkPx(v.lo, it)}</b> <small>${esc(v.lo_d)}</small></span><span>最高 <b>${mkPx(v.hi, it)}</b> <small>${esc(v.hi_d)}</small></span></div></div>`;
}
async function mkDetail(js, id) {
  const it = js.items[id];
  setTitle(it.name);
  const h = await load(`mkt/${id}.json`);
  const grp = js.groups.flatMap(g => g.subs || [g]).find(g => g.ids.includes(id));
  const now = mkNow(it);
  const fr = it.fred;
  const lab = fr?.label || (fr?.fred ? "FRED " + fr.fred : "");
  const fredTxt = !fr ? "" : fr.ok ? `<span class="tag ok" title="最近 ${fr.n} 個共同交易日的收盤，中位數差距 ${fx(fr.median * (it.unit === "%" ? 1 : 100), 3)}${it.unit === "%" ? "" : "%"}">已和 ${esc(lab)} 核對</span>` : fr.n ? `<span class="tag warn">和 ${esc(lab)} 差 ${fx(fr.median * (it.unit === "%" ? 1 : 100), 2)}${it.unit === "%" ? "" : "%"}</span>` : "";
  const R = [["1 週", it.w1], ["1 個月", it.m1], ["3 個月", it.m3], ["今年", it.ytd], ["1 年", it.y1], ["5 年", it.y5], ["10 年", it.y10]];
  app.innerHTML = `<p class="small"><a href="#/mkt">← 國際行情</a>${grp ? `　<span class="muted">${esc(grp.name)}：</span>${grp.ids.filter(x => x !== id).map(x => `<a class="mklink" href="#/mkt/${x}">${esc(js.items[x]?.name || x)}</a>`).join("")}` : ""}</p>
    <h1>${esc(it.name)} <span class="small muted">${esc(it.sym)}｜${esc(it.unit)}</span></h1>${mkStale(it) ? `<p class="small">${mkStale(it)} 資料來源已停止更新，數字停在最後一天。</p>` : ""}${it.note ? `<p class="mknote"><b>⚠ ${esc(it.note.tag)}</b>　${esc(it.note.text)}</p>` : ""}
    <div class="mkhead"><b class="mkbig">${mkPx(now, it)}</b><span class="mkchg">${pc(mkChg(it))}</span>
      <span class="small muted">${it.live_time && it.live === now ? `現價 ${esc(it.live_time)}（延遲約 10~20 分）` : `收盤 ${esc(it.date)}`}</span> ${fredTxt}</div>
    <div class="lvwrap">${lvBlock(it, "all")}${lvBlock(it, "y10")}<div class="lvnote">${lvLegend()}</div></div>
    <div class="mkrets">${R.map(([t, v]) => `<div><span>${t}</span>${pc(v, 1)}</div>`).join("")}</div>
    <div class="mkbar"><div class="chips" id="mkr"></div><label class="small"><input type="checkbox" id="mklog"> 對數刻度</label></div>
    <div class="mkwrap"><div id="mkc"></div><div class="mktip" id="mkt" hidden></div></div>
    <div class="mkstats">
      <div><span>52 週最高</span><b>${mkPx(it.hi52, it)}</b></div><div><span>52 週最低</span><b>${mkPx(it.lo52, it)}</b></div>
      <div><span>歷史最高</span><b>${mkPx(it.ath, it)}</b><small>${esc(it.ath_date)}，距今 ${pc(it.ath ? (now / it.ath - 1) * 100 : null, 1)}</small></div>
      <div><span>歷史最低</span><b>${mkPx(it.atl, it)}</b><small>${esc(it.atl_date || "")}</small></div>
      <div><span>資料起始</span><b>${esc(it.first)}</b><small>${fi(it.n)} 個交易日</small></div></div>
    ${it.suspect?.length ? `<p class="small muted">這幾天的價格單日大跳又立刻彈回，可能是報價錯誤（保留原值）：${it.suspect.map(esc).join("、")}</p>` : ""}
    <p class="small muted">資料來源：${it.src && it.src !== "Yahoo" ? `${esc(it.src)}（Yahoo 沒有這個指數）。每晚更新收盤` : esc(MK_TIP.split("\n")[0].replace("資料來源：", ""))}${(it.n || 0) < 250 ? `。目前只有 ${fi(it.n)} 天資料，之後每天累積，滿一年才算歷史水位` : ""}</p>`;
  if (!h?.d?.length) { document.getElementById("mkc").innerHTML = '<p class="muted">走勢資料載入失敗。</p>'; return; }
  let range = "1y", logScale = false;
  const draw = () => {
    const days = MK_R.find(r => r[0] === range)[2];
    const from = days ? addDays(h.d.at(-1), -days) : "";
    const s = days ? Math.max(0, h.d.findIndex(x => x >= from)) : 0;
    const d = h.d.slice(s), c = h.c.slice(s);
    const box = document.getElementById("mkc"), tip = document.getElementById("mkt");
    if (d.length < 2) { box.innerHTML = '<p class="muted">資料不足。</p>'; return; }
    const ch = mkChart(d, c, it, logScale);
    box.innerHTML = ch.html;
    const svg = box.querySelector("svg"), xh = svg.querySelector("#mkx"), dot = svg.querySelector("#mkd");
    const move = e => {
      const r = svg.getBoundingClientRect(), x = (e.clientX - r.left) / r.width * ch.W;
      let k = 0, best = 1e9;
      ch.idx.forEach((_, j) => { const dx = Math.abs(ch.X(j) - x); if (dx < best) { best = dx; k = j; } });
      const i = ch.idx[k], px = ch.X(k), py = ch.Y(c[i]);
      xh.setAttribute("x1", px); xh.setAttribute("x2", px); xh.hidden = dot.hidden = false; tip.hidden = false;
      dot.setAttribute("cx", px); dot.setAttribute("cy", py);
      tip.innerHTML = `${esc(d[i])}<b>${mkPx(c[i], it)}</b><span class="small">區間 ${pc(c[0] ? (c[i] / c[0] - 1) * 100 : null, 1)}</span>`;
      tip.style.left = Math.min(Math.max(0, px / ch.W * r.width - 60), r.width - 130) + "px";
    };
    svg.onpointermove = move; svg.onpointerdown = move;
    svg.onpointerleave = () => { xh.hidden = dot.hidden = true; tip.hidden = true; };
  };
  chips(document.getElementById("mkr"), MK_R.map(r => [r[0], r[1]]), range, v => { range = v; draw(); });
  document.getElementById("mklog").onchange = e => { logScale = e.target.checked; draw(); };
  draw();
}

// ---------------- router ----------------
const routes = {"": P.home, daily: P.daily, nextday: P.nextday, stats: P.stats, commentary: P.commentary,
  att: P.att, fin: P.fin, rev: P.rev, treasury: P.treasury, events: P.events, borrow: P.borrow, cb: P.cb, cbsig: P.cbsig, cbipo: P.cbipo, private: P.private, disposal: P.disposal, etf: P.etf, stock: P.stock, mkt: P.mkt};
async function route() {
  const [path] = location.hash.replace(/^#\/?/, "").split("?");
  const [name, arg] = path.split("/");
  const fn = routes[name] || P.home;
  document.querySelectorAll("nav.main a").forEach(a => a.classList.toggle("on", a.getAttribute("href") === "#/" + name));
  document.body.classList.toggle("wide", ["cb", "cbsig", "cbipo", "mkt"].includes(name));
  app.innerHTML = '<p class="muted">載入中…</p>';
  SPK.length = 0; spkHide();
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
  const [meta, sp, ci] = await Promise.all([load("meta.json"), load("spark.json"), load("cb_index.json")]);
  META = meta || {};
  SPARK = sp?.s || {};
  CBIDX = ci || {};
  if (META.site_name) { document.getElementById("siteName").textContent = META.site_name; }
  document.getElementById("mockbar").hidden = !META.mock;
  // 專案容量提醒：部署時寫入 repo_size.json（GitHub 建議 1GB 以內），超過 800MB 顯示
  try {
    const rs = await fetch("repo_size.json", {cache: "no-cache"}).then(r => r.ok ? r.json() : null);
    if (rs && rs.mb >= 800) {
      const bar = document.getElementById("sizebar");
      bar.textContent = `提醒：GitHub 專案已達 ${rs.mb} MB（建議 1GB 以內），該處理長期資料庫的存放位置了。`;
      bar.hidden = false;
    }
  } catch {}
  const j = META.jobs || {};
  document.getElementById("updated").textContent = Object.keys(j).length ? "最近更新：" + Object.entries(j).filter(([k]) => k !== "mock").map(([k, v]) => `${({daily: "漲停", cb: "可轉債", disposal: "處置", announce: "公告", borrow: "券差", etf: "主動ETF", backfill: "補資料", markets: "國際行情"})[k] || k} ${v}`).join("，") : "";
  window.addEventListener("hashchange", route);
  route();
})();
})();

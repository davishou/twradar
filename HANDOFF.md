# 盤後雷達 交接文件（給下一個 Claude 對話）

> 新對話請先讀這份，再看 README.md。使用者偏好：**全部用中文回答**、先說結論、不懂技術名詞時用白話解釋。
> 使用者：大維壽（GitHub davishou），專案 `davishou/twradar`，網站 https://davishou.github.io/twradar/
> 參考對象：https://chengwaye.com（目標是頁面盡量做到一樣，保留我們較好的地方，做不到要說明原因）。

## 架構
- `pipeline/`（Python）由 GitHub Actions `.github/workflows/update.yml` 執行，產生 `site/data/*.json`，前端 `site/index.html`、`site/assets/app.js`、`style.css` 讀取。
- 狀態：`data/state/*.json`；近 120 日行情工作集：`data/history/`；**長期資料庫（回測用）：`data/archive/`**（見下）。
- 測試：`python -m unittest discover -s tests -q`（不要用 mock 在正式資料夾跑；測試會把輸出導到暫存）。
- 本機預覽：`cd site && python -m http.server`，截圖用 playwright（Chromium 已裝）。
- 這個工作環境連不到證交所／櫃買／公開資訊觀測站；要驗證真資料就推上去，用 `gh api -X POST repos/davishou/twradar/actions/workflows/update.yml/dispatches -f ref=main -f 'inputs[job]=<job>'` 觸發，再 `git pull` 看結果。`gh run view --log` 被擋，除錯靠把診斷寫進 `data/state/*.json`。

## 排程（cron-job.org 觸發 workflow_dispatch，GitHub 自己的 cron 當備援，常延遲數小時）
| 台灣時間 | job | 內容 |
|---|---|---|
| 17:05 | daily | 行情、漲停、族群（AI）、法人、上市券商分點、隔日、統計 |
| 18:40 | brokers | 重抓失敗分點 |
| 20:08 | borrow | 券差 |
| 21:45 | disposal | 處置預測（等融資融券公布） |
| 22:30 | etf | 主動 ETF（目前無資料） |
| 每 5 分 08:00–23:55 | announce | 自結／季報／營收／庫藏／事件 |
| 00:30（GitHub cron） | history | 長期資料庫回補：先補到 10 年（stage1），補完自動延伸到 2004-02（EARLIEST）；每晚最多 5×45 分鐘；也會續補庫藏股 |
| 手動 | treasury | 庫藏股歷史回補約 6 個月（每次 20 分鐘、可續跑） |
- workflow checkout 用 `ref: main`（排隊的工作也拿最新資料，避免存回衝突）。concurrency group `update-data`。
- **稀疏 checkout**：history 以外的工作不下載 `data/archive/{quotes,inst,margin}`（只寫當天新檔，`git add --sparse`）。要讀這些舊檔的程式只能放在 history 工作。
- 部署前 `python -m pipeline.spark` 產生 `site/data/spark.json`（不進 git，每次部署從 data/history 產生）。
- `data/history` 只留 260 個交易日（store.prune，daily 時執行）；更舊的看 data/archive。

## 機密與費用
- `ANTHROPIC_API_KEY` 在 GitHub Secrets（workspace 金鑰，Default workspace）；使用者已設每月上限、關閉自動儲值。**絕不要請使用者把金鑰貼到對話。**
- 模型 `claude-haiku-5-5`（變數 AI_MODEL）。AI 用於：族群分類（themes.json 優先→關鍵字→AI，AI 新增寫回 themes.json）、漲停原因、自結/季報/營收評分（-9~+9）、盤後短評。**歷史回補不得呼叫 AI。**
- `data/state/ai_status.json` 記最近 20 次 AI 呼叫。

## 資料來源重點
- 上市分點：bsr.twse.com.tw（驗證碼用 ddddocr），只有當天；報表沒日期→用價格範圍與量驗證。
- 上櫃分點：Cloudflare 真人驗證，**不繞過**。可選付費：FinMind 贊助或向櫃買購買（未決定）。
- 櫃買 OpenAPI 前綴是 `mopsfin_`；公司資料有 `IssueShares`、`Paidin.Capital.NTDollars`。
- 重大訊息：MOPS `t05st02`（逐日全部公告）；季報：`ajax_t163sb04`。
- 融資融券：TWSE `MI_MARGN?selectType=ALL`（資、券兩段同名欄位，用位置判斷）、TPEX `margin/balance`。

## 長期資料庫 `data/archive/`（pipeline/archive.py）
- 每類一資料夾、每日一個 gzip CSV（固定時間戳）：quotes、inst、margin、limitup、notices、punish；`adjust.csv.gz` 除權息／減資還原因子（參考價≠前一交易日收盤）；`progress.json` 回補進度。
- 2026-10-25 起分階段回補：先 10 年、再到 2004-02（archive.target_start / stage1_done）。舊年份查無法人／融資券的日子試 2 次後記在 progress.json `gave_up`，只缺上櫃的日子記在 `no_tpex`，每年各類天數在 `by_year`。每年約 20MB。上市注意／處置股 5 年已補；**上櫃注意／處置股只能從 2026-10 起累積**。
- 每日 daily/disposal 會自動寫入。

## 庫藏股（pipeline/announce.py）
- `data/state/treasury_raw.json`：庫藏股相關原始公告（主旨含「買回／庫藏」），保留 190 天；`_days` 記已回補日期、`_bf` 記最近回補結果。
- 每次 announce 會把 material_db（45 天）的庫藏公告複製進 raw；買回計畫每次從 raw＋material 重建（treasury_db 只是輸出快取），決議晚於執行結果補進來也不會重複。
- 回補不呼叫 AI；觀測站連續拒絕 3 次就停，下次續跑。舊公告不標「新」。

## 基本面與族群資料（2026-10-25 起回補）
- `data/archive/val/`（每日本益比/淨值比/殖利率，上市 2005 起）、`revenue/YYYY-MM`（月營收，2013 起，觀測站 nas/t21 靜態頁 cp950）、`fin/YYYYQn`（季報累計數，2013 起，ajax_t163sb04）。進度在 progress.json `fund`、`fund_run`。
- 三大法人 2012-05-02 前查無（archive.INST_START 前不查）。櫃買舊行情端點對太早日期會回最新一天 → `_resp_date` 核對日期。
- 族群：themes.json 有約 1,069 檔 AI 只給官方產業別（當初缺業務資料）。夜間 history 補抓全部公司『主要經營業務』（business.json）；補齊後手動跑一次 job `retheme`（會用 AI，約 20 次 haiku 呼叫）重分類並重建歷史漲停/隔日/統計。
- 探測資料源：workflow `probe.yml`（結果推到 `probe` 分支，`git fetch origin +probe:refs/remotes/origin/probe`）。artifact 下載被這個環境擋。

## 小走勢圖（pipeline/spark.py、app.js 的 spk*）
- 每檔 160 日還原收盤，64 階一字元編碼；漲停日紅點；外框＝圖中最大波動：最大漲幅 ×2/×5/×10 淡黃/黃/紅框，最大跌幅 −30/−60/−80% 淺綠/深綠/墨綠，漲跌都有取對數幅度大的一邊，框內小字標倍數或跌幅。
- 表格有「名稱」欄就自動在右邊加「走勢」欄（table → withSpark），所有圖對齊，可依最大漲幅排序；每日漲停檔、隔日檔內嵌 `spark`（只畫到那一天），其他頁用 spark.json（最新）。滑鼠移上或手機點一下浮出大圖；個股頁直接顯示大圖。

## 已驗證和原網站一致的規則
- 隔日標籤：續漲停／強續漲／弱續漲／開高走低／直接跌；加權 = (2×開盤報酬 + 均價報酬)/3；族群勝率 = 加權>0 比例。
- 當沖損益 = 已實現 + 未實現(收盤) − 手續費(0.1425%×0.14) − 稅(當沖 0.15%／其他 0.3%)。
- 處置：第 1、2、3、4、6、7 款依交易所／櫃買「異常標準之詳細數據」（config.DISPOSAL_RULES，TWSE_X / TPEX_X）；第 5 款無法（需全市場分點）。
- 處置同類股（2026-10-25 完成）：第 1、2、3、4、7 款價格條件同時和全體平均、同類股平均（同市場同產業別，companies.industry）比；同類未達 5 家、本益比空白（虧損）或 ≥60 倍（上櫃 65）不比同類（disposal.Peers）。量放大、週轉率只和全體比（依法規）。
- 量比（2026-10-25 已改）：隔日頁「量比」＝**隔日成交量 ÷ 漲停日成交量**（同原網站，24/24 檔吻合，nextday JSON `vol_ratio`；舊定義留在 `avg5_ratio`）；當日頁改名「均量比」＝漲停日量 ÷ 前 5 日均量（daily JSON 欄位名仍是 `vol_ratio`）。

## 尚未完成（依優先）
0. 已完成：簡單密碼頁（使用者選的方案）。GitHub Secret `SITE_PASSWORD` → 部署時產生 `site/gate.json`（只有雜湊，不進 git）；沒設就不鎖。只擋一般訪客，repo 仍公開。
2. 主動 ETF 持股（各投信格式不同，需逐家寫抓取）。
3. ~~庫藏股歷史回補~~（2026-10-25 完成，job treasury）。
4. ~~處置「同類股平均」條件~~（2026-10-25 完成）。
5. ~~量比~~（2026-10-25 完成）。
6. 回測功能本身（資料庫已備好）。待辦：基本面補齊後，測「缺貨漲價型」財報訊號（營收年增加速、毛利率跳升、轉虧為盈，公布後進場）——前段找、後段驗證、和大盤比。工具已有：`pipeline/backtest.py`（讀資料庫、漲停事件表、超額報酬、分組勝率、月 IC），研究腳本與結論在 `research/`（README 有摘要）。需 `requirements-backtest.txt`（pandas、scipy），排程不會裝。使用者想要的方向：找「勝率與漲幅都贏大盤」的訊號，一律和大盤比（超額報酬），用前段找、後段驗證。
7. 上櫃分點、處置第 5 款：需付費資料源。

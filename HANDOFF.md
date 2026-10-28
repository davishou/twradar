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
| 週六日 08:00／13:00／18:00（GitHub cron） | history | 週末加跑回補（每次最多 5×45 分；行情分到 80% 時間） |
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
- 族群：themes.json 有約 1,069 檔 AI 只給官方產業別（當初缺業務資料）。夜間 history 補抓全部公司『主要經營業務』（business.json）；2026-10-28 已跑 job `retheme`（每批 20 檔，約 60 次 haiku）：1,059 檔改分到細族群（CCL→PCB基板、MLCC→被動元件），官方產業別族群已清空；歷史漲停/隔日/統計已重建。
- 探測資料源：workflow `probe.yml`（結果推到 `probe` 分支，`git fetch origin +probe:refs/remotes/origin/probe`）。artifact 下載被這個環境擋。

## 可轉債（pipeline/cb.py、頁面 #/cb）
- 來源（櫃買，全公開）：每日行情 `storage/bond_zone/tradeinfo/cb/Y/YM/RSta0113.YYYYMMDD-C.csv`（2007 起）、資訊看板 `RSdrs001`（實際 2017-01 起，欄位依年代不同，用欄名解析）、OpenAPI `bond_ISSBD5_data`（發行資料，只有最新）。CSV 是 cp950。
- daily（17:05）與 disposal（21:45，若還沒今天）都會跑 job_cb；手動 job `cb`。history 工作回補 `data/archive/cbq|cbb`（稀疏 checkout 排除），並用它重建 `data/cb_history/`（每日快照，留 260 日）。部署時 `python -m pipeline.cb hist` 產生 `site/data/cb_hist.json`（不進 git）。
- 頁面：統計卡、快速篩選（仿主力藏寶圖：剩餘比率<30/>80、CB≤106、深度價內、股債連動±3%、折價、新發行/快到期 90 天）、區間篩選、剩餘比率、展開看標的均線均量法人、K 線／溢價率／張數三層圖（`site/data/cbh/代號.json`，部署時產生）、近幾週餘額、轉換比例、可轉股數與稀釋比例。
- CB IPO（pipeline/cbipo.py、#/cbipo）：公會 web.twsa.org.tw/edoc2 承銷公告（GET）與詢圈公告（ASP.NET POST rblReportType=BookBuilding）、證交所 `announcement/auction?date=YYYY`（含 CB 競拍、得標價、撥券日）、ISSBD5。公司全名→代號用 companies.json 的 `full`（啓/啟、（第五次）、-創新版 會正規化）。TCRI、申報生效日、公告轉換價不是公開資料。
- `site/data/cb_index.json`：{股票: {cb: 檔數, ipo: 狀態}}，全站表格有可轉債的列淡黃、即將發行名稱旁 IPO 標籤（app.js CBIDX）。
- 理論權利金用固定 3% 折現到下次賣回日（沒有賣回用到期面額 100），和投資少數派／券商 CBAS 報價不同。cyclesinvest.com 對我們的瀏覽器回 403，還沒看到內容。
- probe workflow 可帶 `cmd` 輸入跑任意指令，結果寫 probe/ 推到 probe 分支（不受 update-data 排隊影響）。

## 鄭詩翰（鄭大）可轉債研究（2026-10-26~27）
- 使用者指定只認三個來源：個人頁 facebook.com/zheng.shi.han.14954、粉專「鄭大的投資日記」facebook.com/trender888（userID 100063717079492）、私人社團「年輕人的投資夢」facebook.com/groups/warrent.trender。**網路上有冒名詐騙頁（例如 profile.php?id=100085827672531、「鄭詩翰的投資日記」），不要抓**。FB 由使用者自己登入內建瀏覽器，不輸入密碼。社團內容是私人的：只放私人 Artifact 與 scratchpad 筆記，不進公開 repo／網站。
- CB 溫度計（pipeline/cbtemp.py、可轉債頁卡片）：全市場平均轉換價值換算成他的「CB 委買均價」= 0.655×conv+49.3（他 8 個公布值擬合，r=0.97）。區間 <105 極端恐慌、105–110 恐慌、110–113 低迷、113–121 正常、≥121 偏熱；回測在 research/cb_market.py。
- CB 訊號（pipeline/cbsig.py：SIGNALS、detect、NOTES 分組回測補充；每日在 job_cb 標記 → site/data/cb_sig.json）；回測 research/cb_signals.py（判定看 60 日 CB 超額＋大賺／大賠機率，2022/7 前後兩段都成立才通過；另算 1/5/10/20/60 天）；條件分組探索 research/cb_signals_horizon.py。頁面：可轉債頁名稱下標籤＋「鄭大訊號」篩選列；#/cbsig「CB 策略」頁。
- 結論（2026-10）：只有「站上轉換價」通過；使用者對週期的假設（CB 過高股未過高＝短線、爆量要低檔、股崩 CB 撐＝會反彈）回測都不支持，細節在 NOTES。
- 回測的 CB 報酬：持有期內提前下市（強制贖回、轉換完、到期、賣回）用下市前最後價出場，不丟掉（約 8% 的 CB-日會遇到；已下市 872 檔中 38% 最後價 ≥130、50% <105）。cbq 是每天的全市場檔，下市的 CB 也在，沒有倖存者偏差。
- history 工作每週六（台北）少補一輪，裝 requirements-backtest.txt 重跑 research.cb_market 與 research.cb_signals，結果自動上網站。
- 部署時 index.html 的 app.js／style.css 會加 ?v=版本號，避免瀏覽器用舊檔。

## 國際行情（pipeline/markets.py、頁面 #/mkt，2026-10-27）
- 共 116 個（2026-10-27 擴充）：貴金屬、能源、工業金屬（含熱軋鋼捲）、農產品、畜產林產、美國／美洲／東亞／南亞東南亞大洋洲／歐洲／中東非洲股市、25 種匯率、美債 13 週～30 年殖利率與 VIX／黃金／原油波動率、比特幣以太幣。清單在 markets.GROUPS（加代號只改這裡；先用 probe 確認 Yahoo 有歷史）。Yahoo 沒有的改用鉅亨網圖表介面 `ws.api.cnyes.com/ws/api/v1/charting/history?resolution=D&symbol=<代號>&from=<新>&to=0`（新到舊，每頁約 1,250 天，往前翻頁；清單裡代號前綴 `cnyes:`）：台灣櫃買 TWS:OTC01:INDEX（1999 起，每晚和櫃買中心官方 indexInfo/inx 本月資料核對）、滬深300 GI:CSI300、泰國 GI:SET、菲律賓 GI:PCOMP、波蘭 GI:WIG（WIG20 沒有）；沙烏地指數沒有免費歷史（交易所網站擋程式），使用者同意改用 Yahoo 的 iShares MSCI 沙烏地 ETF（KSA，2015 起）代替。其他專用來源：俄羅斯用莫斯科交易所官方 ISS `iss.moex.com/iss/history/engines/stock/markets/index/securities/{IMOEX,RTSI}.json`（每頁 100 筆，1997／1995 起，前綴 moex:）；越南 VN-Index 用 DNSE `services.entrade.com.vn/chart-api/v2/ohlcs/index`、失敗改 SSI `iboard-api.ssi.com.vn/statistics/charts/history`（2000 起，前綴 vn:）；挪威 OSEBX 用 Euronext 官方 CSV `live.euronext.com/en/ajax/AwlHistoricalPrice/getFullDownloadAjax/NO0007035327-XOSL`（只提供近 2 年，2024-10 起，之後每天累積；前綴 euronext:）。這三個盤中不重抓，只在每晚／手動 markets 更新。FRED 沒有這些國家的每日指數（只有 OECD 月資料），所以不用。智利、埃及 Yahoo／鉅亨都沒有。
- 歷史水位：site 輸出 lv.all／lv.y10（最低、最高、日期、百分位＝多少 % 交易日收盤低於現價）；前端用現價算位置 0~100%，每 10% 一色（藍低紅高），可切全部歷史／近 10 年。總表模式（一次看全部，可排序；欄位順序：分類、名稱、現價、漲跌、歷史走勢、起始、水位、百分位、距史高、各期報酬；分類名稱欄窄、太長截斷滑鼠看全名；手機只留名稱／現價／1 年／水位）。網頁大分類 6 個（markets.COARSE：金屬、能源、農畜產、全球股市、匯率、利率・波動率・加密）；卡片在水位條下方顯示最低／最高（隨全部歷史／近 10 年切換），細分類（貴金屬、歐洲…）在卡片模式是小標題、總表是分類欄。明細圖標出區間最高最低，若剛好是歷史最高最低就寫「歷史」。
- 小走勢圖（卡片與總表）＝全部歷史：site 輸出 spark_all（160 點、保留最高最低、y＝每個新年份第一點的位置、d0/d1 起訖日；漲超過 8 倍前端用對數刻度）。外觀比照股票小走勢圖：外框固定顏色（不隨漲跌變色、不標倍數）、直線固定每 5 年一條（逢 5 年淡細、逢 10 年稍深，使用者要求間隔固定好閱讀）、虛線＝期初價位、線色紅漲綠跌（和期初比）、紅點史高綠點史低。
- 特殊狀況標記 markets.NOTES：ksa＝「ETF 代替」、osebx＝「僅近 2 年」；卡片／總表顯示黃色 ⚠ 標記（滑鼠看說明），明細頁有說明框。
- 來源：Yahoo 圖表介面 `query1/2.finance.yahoo.com/v8/finance/chart/<代號>`，GitHub runner 直接用 requests 可抓（不需 yfinance、不需金鑰）。第一次抓某代號自動抓全部歷史（period1=1900），之後只補最近 14 天。商品是期貨連續近月、延遲 10~20 分。
- 存放 `data/archive/mkt/<id>/<年>.csv`（純文字、每年一檔，只有今年的檔變動）；沒有被稀疏 checkout 排除。部署時 `python -m pipeline.markets site` 產生 `site/data/mkt.json`、`site/data/mkt/<id>.json`（不進 git）。
- 排程：announce 每 30 分鐘一次快速更新現價（range=5d）；history（每晚 00:30，週末也跑）補收盤並做 FRED 核對；手動 job `markets`（`markets full` 重抓全部歷史）。
- FRED_API_KEY 已設（2026-10-27）。首次核對：美股指數、美債、VIX、匯率共 15 項全部通過；WTI 差 5.7%、布蘭特差 13.5%（FRED 是現貨、Yahoo 是近月期貨，供給緊張時差很多），頁面顯示黃色「差 x%」。手動重抓指定代號全部歷史：dispatch job `markets full <id> <id>`。
- 選用 GitHub Secret `FRED_API_KEY`：有設就和 FRED 官方資料核對原油、美債、美股指數、匯率（容許誤差在 markets.FRED），結果在 `data/state/markets.json` 的 fred，頁面顯示「已核對」。
- 單日大跳又彈回的可疑報價只標示不刪（避免刪掉 2020/4 油價負值這種真實行情）。
- 本機預覽：`python -m pipeline.markets mock`（模擬資料，**預覽完要刪 data/archive/mkt 與 data/state/markets.json，不要提交**）。

## 外觀（2026-10-27）
- 版面寬度 1400；可轉債、CB 策略、CB IPO、國際行情加 body.wide（最寬 1800、欄距縮小、表頭可換行），1280 寬螢幕以上沒有橫向捲軸。
- 淺色模式標題欄＝黑金（深底＋金屬漸層金字＋底部金線），選中頁籤金色按鈕。
- 深色模式（使用者 2026-10-27 選定）：橫幅底色金箔漸層（--top-bg），金蔥＝兩層 SVG feTurbulence 雜訊（--top-glitter）由 .top::before 鋪上、透明度 .5、mask 讓左右兩端漸變回素金；字近黑 #140c00 粗體＋淡金光暈；選中頁籤黑底金字；整頁背景純黑 #0b0b0c、卡片 #151517。CSS 在 style.css「深色模式：金蔥細點」區塊。
- 每頁 h1 下方金線和標題文字一樣長（main h1 display:table）。國際行情卡片金框。漲跌一律紅漲綠跌。變數在 style.css 開頭 top bar 區（--gold*、--top-*）。

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

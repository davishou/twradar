# 盤後雷達：台股盤後資料儀表板

把漲停族群、隔日表現、處置預測、公告偵測、券差借券費率與主動 ETF 持股異動整理成一個網站，
每個交易日自動更新。後端是 Python 資料流程，前端是純靜態網頁，可以免費放在 GitHub Pages。

## 功能

| 頁面 | 內容 | 更新時間（台灣） |
|---|---|---|
| 首頁 | 今日漲停族群熱度帶、盤面主軸評論、盤前 LINE 轉貼文字 | 17:05 |
| 氣氛 | 每日盤後評論（有 AI 金鑰用 AI 寫，否則用規則產生） | 17:05 |
| 當日 | 漲停股、族群分類、三大法人、漲停原因；點個股看券商分點買賣超 Top15、分點泡泡圖、當沖 Top10 | 17:05（分點 18:40 補抓失敗的） |
| 隔日 | 前一日漲停股今天的開盤／均價／收盤／加權報酬、勝率、走勢標籤、族群比較；點個股看漲停日前 15 大買超券商隔日動向、隔日泡泡圖、當沖 Top10 | 17:05 |
| 統計 | 近 60 個交易日漲停家數、族群排行與隔日勝率 | 17:05 |
| 自結／季報／營收／庫藏／事件 | 公告偵測，標示本次新增，以及公告後是否已經歷過收盤（股價是否已反應） | 每 5 分鐘 |
| 券差 | 應付現股當日沖銷券差借券費率，每檔彙總與原始明細 | 20:08 |
| 處置 | 差 1 次／差 2 次就處置、明日第一款與第二款觸發價、處置中與出關日、LINE 轉貼 | 19:30 |
| 主動 ETF | 各基金持股與前次比較的加減碼、估計金額、股票總表 | 22:30 |
| 個股 | 某檔股票的漲停履歷、處置預測與近期公告 | — |

## 先看示範（不需網路）

```bash
pip install -r requirements.txt
python -m pipeline.run mock      # 產生模擬資料（公司名稱皆為虛構）
python -m pipeline.run serve     # 開啟 http://localhost:8000
```

壓縮檔裡已經附了一份模擬資料，直接 `serve` 也能看。第一次執行真實資料流程時，模擬資料會自動清除。

## 部署（GitHub Pages，免費）

1. 在 GitHub 建一個新 repository，把這個資料夾全部推上去。
2. Settings → Pages → Source 選 **GitHub Actions**。
3. （選用）Settings → Secrets and variables → Actions：
   - Secret `ANTHROPIC_API_KEY`：啟用 AI 族群分類、公告評分、盤後評論。
   - Variable `SITE_URL`：你的網站網址（出現在 LINE 轉貼文字），`SITE_NAME`：網站名稱。
4. Actions → update-data → Run workflow，job 填 `backfill`。這會補抓最近 120 個交易日行情
   （處置的 30/60/90 日門檻、量比、連板都需要歷史），然後跑一次全部流程。
5. 之後就照 `.github/workflows/update.yml` 的排程自動更新。

注意：GitHub 的排程可能延遲 5～15 分鐘；公告每 5 分鐘會產生一次 commit。若想要準時或不想讓 repo 變大，
改用下面的自架方式。

## 自架（VPS、NAS、常開的電腦）

```bash
pip install -r requirements.txt
python -m pipeline.run backfill 120
python -m pipeline.run all
python -m pipeline.scheduler          # 常駐排程
```

把 `site/` 資料夾交給任何靜態網頁伺服器（nginx、Caddy）即可。

## 各指令

```
python -m pipeline.run daily | disposal | borrow | etf | announce | all
python -m pipeline.run backfill 120
python -m pipeline.run mock | serve [port] | reset
python -m unittest tests.test_core
```

## 自訂

- **族群分類**：編輯 `themes.json`。`codes` 填股票代號就固定歸到該族群；`keywords` 會比對公司名稱與近期公告主旨。
  沒對到的股票，有 AI 金鑰時由 AI 判斷（結果會快取），否則用官方產業別。
- **主動 ETF**：各投信網站格式不同，提供兩種方式
  1. 把投信下載的持股檔存成 `data/etf_inbox/00981A_20261016.csv`（欄位含代號、名稱、股數、權重即可，UTF-8 或 Big5 都行）；
  2. 在 `pipeline/active_etf.py` 的 `ADAPTERS` 加一個抓取函式（檔內有範本）。
  要追蹤的基金清單在 `pipeline/config.py` 的 `ACTIVE_ETFS`。
- **處置門檻**：`pipeline/config.py` 的 `DISPOSAL_RULES`，交易所修改規定時改這裡。
- **資料源網址**：全部集中在 `pipeline/config.py` 的 `URLS`。

## 資料與限制

- 資料來自臺灣證券交易所、證券櫃檯買賣中心的公開資料與 OpenAPI，以及公開資訊觀測站。交易所偶爾改版欄位或網址，
  解析程式已盡量容錯（`pipeline/sources.py`），若某一區突然沒資料，先看執行紀錄的「抓取失敗」訊息，再對照官方頁面調整 `URLS`。
  **這份程式是在無法連線交易所的環境寫成的**：解析邏輯用公開格式的樣本測過，但第一次部署時請實際跑 `backfill` 與 `all`，
  確認各頁都有資料。券差費率的兩個端點（`twse_borrow_fee`、`tpex_borrow_fee`）最可能需要依官網實際 API 調整。
- 證交所網站對過於頻繁的請求會暫時封鎖，`HTTP_DELAY` 預設每次間隔 1.2 秒，請不要調低。
- 處置預測只估算第一款（6 日累積漲跌）與第二款（30/60/90 日），第三～八款需要成交量倍數、單一券商占比、融資券等資料，只顯示條件說明。
  所有預測都是程式估算，不是交易所預告。
- 公開資訊觀測站的 OpenAPI 重大訊息以「當日」為主，盤中即時性取決於官方更新頻率；本程式自己保留最近 10 天的紀錄。
- 本專案僅供研究，不構成投資建議。

## 結構

```
pipeline/
  config.py      網址、門檻、設定
  sources.py     各資料源 → 統一欄位
  mock.py        模擬資料源（介面同 sources）
  store.py       每日行情歷史、狀態檔
  limitup.py     漲停、族群、隔日、統計、個股履歷
  themes.py      族群分類（themes.json → 關鍵字 → AI → 產業別）
  disposal.py    處置預測
  announce.py    自結／季報／營收／庫藏／事件
  borrow.py      券差借券費率
  active_etf.py  主動 ETF
  brief.py       盤後評論、LINE 轉貼、meta
  ai.py          Claude API（選用）
  run.py         指令入口
  scheduler.py   自架常駐排程
site/            靜態網站（index.html、assets/、data/）
data/            歷史行情與狀態（網站不會讀取）
```

## 券商分點（當日頁）

- 來源：證交所「券商買賣證券日報表」（bsr.twse.com.tw）。網站只保留最近一個交易日，每檔查詢都要輸入驗證碼，
  程式用 `ddddocr` 自動辨識，失敗會換一張重試（`config.BROKER_RETRIES`）。所以分點只能在收盤當天抓，舊日期沒有。
- 上櫃：櫃買中心的查詢頁可能使用 Google reCAPTCHA，目前還不支援；第一次執行會把查詢頁存到
  `data/state/brokers_debug/` 供調整。
- 每天抓兩批：當日漲停股（看誰在買）＋昨日漲停股（隔日頁看誰在賣）。隔日頁要等兩天都有分點資料才會顯示。
- 每檔結果記在 `site/data/brokers/日期/_status.json`；失敗的會在 18:40 自動重抓，也可以手動跑 job `brokers`。
- 「當沖 Top10」的總損益以收盤價計算：賣出金額 − 買進金額 ＋ 未沖銷張數 × 收盤價，未扣手續費與證交稅。

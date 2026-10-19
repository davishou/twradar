"""全站設定。資料源網址、門檻、排程都集中在這裡，交易所改版時只需改這個檔。"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"            # 原始資料與歷史（不公開）
HISTORY_DIR = DATA_DIR / "history"  # 每日全市場行情快照
STATE_DIR = DATA_DIR / "state"      # 去重用的已見公告、注意股紀錄等
ETF_INBOX = DATA_DIR / "etf_inbox"  # 主動 ETF 手動匯入 CSV
SITE_DIR = ROOT / "site"
OUT_DIR = SITE_DIR / "data"         # 前端讀取的 JSON

SITE_NAME = os.getenv("SITE_NAME", "盤後雷達")
SITE_URL = os.getenv("SITE_URL", "https://example.github.io/twradar/")

# ---- AI（選用）：設定 ANTHROPIC_API_KEY 即啟用 AI 族群分類、公告評分、盤後氣氛 ----
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
AI_MODEL = os.getenv("AI_MODEL", "claude-haiku-5-5")  # 便宜快速；想要更好的文字品質可設 claude-sonnet-5-5

# ---- 資料源 ----
URLS = {
    # 全市場收盤行情（最新交易日）
    "twse_quotes": "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL",
    "tpex_quotes": "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes",
    # 指定日期行情（補歷史用）
    "twse_quotes_by_date": "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={yyyymmdd}&type=ALLBUT0999&response=json",
    "tpex_quotes_by_date": "https://www.tpex.org.tw/www/zh-tw/afterTrading/otc?date={yyyy}/{mm}/{dd}&type=EW&response=json",
    # 上市櫃公司基本資料（產業別、實收資本額）
    "twse_company": "https://openapi.twse.com.tw/v1/opendata/t187ap03_L",
    "tpex_company": "https://www.tpex.org.tw/openapi/v1/mopsfe_t187ap03_O",
    # 本益比、殖利率、淨值比
    "twse_pe": "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL",
    "tpex_pe": "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_analysis",
    # 注意股、處置股
    "twse_notice": "https://www.twse.com.tw/rwd/zh/announcement/notice?startDate={start}&endDate={end}&response=json",
    "twse_punish": "https://www.twse.com.tw/rwd/zh/announcement/punish?startDate={start}&endDate={end}&response=json",
    "tpex_notice": "https://www.tpex.org.tw/openapi/v1/tpex_trading_warning_information",
    "tpex_punish": "https://www.tpex.org.tw/openapi/v1/tpex_disposal_information",
    # 重大訊息（自結、庫藏股、事件）
    "twse_material": "https://openapi.twse.com.tw/v1/opendata/t187ap04_L",
    "tpex_material": "https://www.tpex.org.tw/openapi/v1/mopsfe_t187ap04_O",
    # 月營收
    "twse_revenue": "https://openapi.twse.com.tw/v1/opendata/t187ap05_L",
    "tpex_revenue": "https://www.tpex.org.tw/openapi/v1/mopsfe_t187ap05_O",
    # 季報 EPS
    "twse_eps": "https://openapi.twse.com.tw/v1/opendata/t187ap14_L",
    "tpex_eps": "https://www.tpex.org.tw/openapi/v1/mopsfe_t187ap14_O",
    # 休市日
    "holidays": "https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule",
    # 櫃買舊版依日期行情（新版失敗時備援）
    "tpex_quotes_by_date_legacy": "https://www.tpex.org.tw/web/stock/aftertrading/otc_quotes_no1430/stk_wn1430_result.php?l=zh-tw&d={roc}&se=EW",
    # 應付現股當日沖銷券差借券費率
    "twse_borrow_fee": "https://www.twse.com.tw/rwd/zh/dayTrading/BFIF8U?date={yyyymmdd}&response=json",
    "tpex_borrow_fee": "https://www.tpex.org.tw/www/zh-tw/dayTrading/fee?date={yyyy}/{mm}/{dd}&response=json",
    # 三大法人買賣超（個股）
    "twse_inst": "https://www.twse.com.tw/rwd/zh/fund/T86?date={yyyymmdd}&selectType=ALLBUT0999&response=json",
    "tpex_inst": "https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade?type=Daily&sect=EW&date={yyyy}/{mm}/{dd}&response=json",
    # 券商買賣證券日報表（分點進出）。證交所版只提供最近一個交易日，且每次查詢要輸入驗證碼
    "twse_bsr_menu": "https://bsr.twse.com.tw/bshtm/bsMenu.aspx",
    "tpex_bsr_menu": "https://www.tpex.org.tw/web/stock/aftertrading/broker_trading/brokerBS.php?l=zh-tw",
    # 證交所 ISIN 一覽表（上櫃），櫃買公司資料抓不到時用來補產業別
    "isin_tpex": "https://isin.twse.com.tw/isin/C_public.jsp?strMode=4",
    # 公司基本資料（主要經營業務），給 AI 判斷族群用
    "mops_profile": "https://mopsov.twse.com.tw/mops/web/ajax_t05st03",
}

# ---- 券商分點 ----
BROKER_RETRIES = 6          # 每檔驗證碼最多嘗試次數
BROKER_DELAY = 1.5          # 每次查詢間隔（秒）
BROKER_DEBUG = True         # 失敗時把網頁存到 data/state/brokers_debug，方便調整解析

# ---- 處置規則參數（依交易所現行規定，可自行調整）----
# 第一款：最近六個營業日累積收盤漲跌幅，且與全體平均差幅 ≥ diff
DISPOSAL_RULES = {
    "TWSE": {
        "c1_small": 0.32, "c1_big": 0.25, "c1_big_price": 50,   # 價差 <50 元用 32%，≥50 元用 25%
        "c2": [(30, 1.00, 0.85), (60, 1.30, 1.10), (90, 1.60, 1.35)],
    },
    "TPEX": {
        "c1_small": 0.30, "c1_big": 0.23, "c1_big_price": 40,
        "c2": [(30, 1.00, 0.80), (60, 1.40, 0.80), (90, 1.60, 0.80)],
    },
    "c1_diff": 0.20,
    # 處置條件（次數）
    "consec_c1": 3,      # 連續 3 日第一款
    "consec_any": 5,     # 連續 5 日第 1~7 款
    "within10": 6,       # 10 日內 6 次
    "within30": 12,      # 30 日內 12 次
}

# 主動式 ETF：在 data/etf_inbox 放入 {代號}_{YYYYMMDD}.csv（欄位：代號,名稱,股數,權重）即可，
# 或於此註冊自動抓取的轉接器（見 pipeline/active_etf.py）
# 名稱留空時會自動從行情資料帶入
ACTIVE_ETFS = {
    "00980A": "",
    "00981A": "",
    "00982A": "",
    "00985A": "",
    "00991A": "",
}

HTTP_TIMEOUT = 30
HTTP_DELAY = 1.2   # 對交易所網站的禮貌間隔（秒）

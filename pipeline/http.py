"""HTTP 連線：重試、禮貌延遲、相容交易所憑證。"""
from __future__ import annotations

import logging
import ssl
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from . import config

log = logging.getLogger(__name__)


class _TLSAdapter(HTTPAdapter):
    """Python 3.13 起預設啟用 VERIFY_X509_STRICT，部分交易所憑證缺少 SKI 會驗證失敗。
    這裡仍完整驗證憑證鏈與主機名，只關閉該嚴格旗標。"""

    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        if hasattr(ssl, "VERIFY_X509_STRICT"):
            ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


_session: requests.Session | None = None
_last = 0.0


def session() -> requests.Session:
    global _session
    if _session is None:
        s = requests.Session()
        retry = Retry(total=3, backoff_factor=2, status_forcelist=(429, 500, 502, 503, 504))
        ad = _TLSAdapter(max_retries=retry)
        s.mount("https://", ad)
        s.mount("http://", ad)
        s.headers.update({
            "User-Agent": "Mozilla/5.0 (compatible; twradar/1.0; +https://github.com/)",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-TW,zh;q=0.9",
        })
        _session = s
    return _session


def get_json(url: str, **kw):
    """取 JSON；失敗回 None 並記錄，讓單一資料源掛掉不影響其他模組。"""
    global _last
    wait = config.HTTP_DELAY - (time.time() - _last)
    if wait > 0:
        time.sleep(wait)
    try:
        r = session().get(url, timeout=config.HTTP_TIMEOUT, **kw)
        _last = time.time()
        r.raise_for_status()
        r.encoding = r.encoding or "utf-8"
        return r.json()
    except Exception as e:  # noqa: BLE001
        log.warning("抓取失敗 %s：%s", url, e)
        return None


def get_bytes(url: str) -> bytes | None:
    try:
        r = session().get(url, timeout=config.HTTP_TIMEOUT)
        r.raise_for_status()
        return r.content
    except Exception as e:  # noqa: BLE001
        log.warning("抓取失敗 %s：%s", url, e)
        return None

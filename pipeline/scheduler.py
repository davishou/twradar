"""在自己的主機（VPS、NAS、常開的電腦）上常駐排程，取代 GitHub Actions。

  python -m pipeline.scheduler

以台灣時間判斷，週一到週五執行；公告偵測每 5 分鐘一次（08:00~23:55）。
"""
from __future__ import annotations

import logging
import time
import traceback

from . import run, sources
from .util import now_tw

FIXED = {"17:05": "daily", "19:30": "disposal", "20:08": "borrow", "22:30": "etf"}
log = logging.getLogger("scheduler")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    done: set[str] = set()
    log.info("排程啟動")
    while True:
        t = now_tw()
        hm = t.strftime("%H:%M")
        key = t.strftime("%Y-%m-%d ") + hm
        if t.weekday() < 5 and key not in done:
            jobs = []
            if hm in FIXED:
                jobs.append(FIXED[hm])
            if 8 <= t.hour <= 23 and t.minute % 5 == 0:
                jobs.append("announce")
            for j in jobs:
                try:
                    log.info("執行 %s", j)
                    getattr(run, f"job_{j}")(sources)
                except Exception:  # noqa: BLE001
                    log.error("%s 失敗\n%s", j, traceback.format_exc())
            done.add(key)
            if len(done) > 5000:
                done.clear()
        time.sleep(20)


if __name__ == "__main__":
    main()

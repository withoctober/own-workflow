from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


RUNTIME_TIMEZONE = ZoneInfo("Asia/Shanghai")


def now_in_runtime_timezone() -> datetime:
    return datetime.now(RUNTIME_TIMEZONE)


def new_batch_id() -> str:
    return now_in_runtime_timezone().strftime("%Y%m%d%H%M%S")

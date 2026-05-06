"""Date helpers for user-facing Korean calendar features."""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo('Asia/Seoul')


def kst_today() -> date:
    return datetime.now(KST).date()


def kst_today_iso() -> str:
    return kst_today().isoformat()

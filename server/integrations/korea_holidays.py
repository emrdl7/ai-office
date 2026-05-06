"""Korea public holiday lookup via data.go.kr KASI special-day API."""
from __future__ import annotations

import logging
import os
import time
import xml.etree.ElementTree as ET
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_REST_HOLIDAY_URL = 'https://apis.data.go.kr/B090041/openapi/service/SpcdeInfoService/getRestDeInfo'
_CACHE_TTL_SECONDS = 12 * 60 * 60
_CACHE: dict[str, tuple[float, list[dict[str, str]]]] = {}


def _service_key() -> str:
    for name in ('KOREA_HOLIDAY_API_KEY', 'PUBLIC_DATA_SERVICE_KEY', 'DATA_GO_KR_SERVICE_KEY'):
        value = os.environ.get(name, '').strip()
        if value:
            return value
    return ''


def get_public_holidays(month: str) -> list[dict[str, str]]:
    """Return public holidays for a YYYY-MM month.

    Missing credentials or upstream failures deliberately return an empty list so
    the work-report calendar remains usable offline.
    """
    if len(month) != 7 or month[4] != '-':
        return []

    cached = _CACHE.get(month)
    now = time.time()
    if cached and now - cached[0] < _CACHE_TTL_SECONDS:
        return [dict(item) for item in cached[1]]

    key = _service_key()
    if not key:
        return []

    try:
        response = httpx.get(
            _REST_HOLIDAY_URL,
            params={
                'serviceKey': key,
                'solYear': month[:4],
                'solMonth': month[5:7],
                'numOfRows': '100',
                '_type': 'json',
            },
            timeout=6.0,
        )
        response.raise_for_status()
        holidays = _parse_holiday_response(response)
    except Exception:
        logger.exception('Korea public holiday lookup failed for %s', month)
        holidays = []

    _CACHE[month] = (now, holidays)
    return [dict(item) for item in holidays]


def _parse_holiday_response(response: httpx.Response) -> list[dict[str, str]]:
    content_type = response.headers.get('content-type', '')
    if 'json' in content_type.lower() or response.text.lstrip().startswith('{'):
        return _parse_json_payload(response.json())
    return _parse_xml_payload(response.text)


def _parse_json_payload(payload: dict[str, Any]) -> list[dict[str, str]]:
    body = payload.get('response', {}).get('body', {})
    items = body.get('items', {})
    raw_items = items.get('item', []) if isinstance(items, dict) else []
    if isinstance(raw_items, dict):
        raw_items = [raw_items]
    holidays = [_normalize_item(item) for item in raw_items if isinstance(item, dict)]
    return [item for item in holidays if item]


def _parse_xml_payload(text: str) -> list[dict[str, str]]:
    root = ET.fromstring(text)
    holidays: list[dict[str, str]] = []
    for item in root.findall('.//item'):
        raw = {child.tag: child.text or '' for child in item}
        normalized = _normalize_item(raw)
        if normalized:
            holidays.append(normalized)
    return holidays


def _normalize_item(item: dict[str, Any]) -> dict[str, str]:
    if str(item.get('isHoliday', '')).upper() != 'Y':
        return {}
    locdate = str(item.get('locdate', ''))
    if len(locdate) != 8:
        return {}
    return {
        'date': f'{locdate[:4]}-{locdate[4:6]}-{locdate[6:8]}',
        'name': str(item.get('dateName', '')).strip() or '공휴일',
        'kind': str(item.get('dateKind', '')).strip(),
        'sequence': str(item.get('seq', '')).strip(),
    }

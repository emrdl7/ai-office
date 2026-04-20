"""색상 유틸 — HEX 추출, 팔레트 SVG 생성, WCAG 대비 경고."""
from __future__ import annotations

import re
from typing import Any

_HEX_RE = re.compile(r'#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b')


def extract_hex_colors(text: str) -> list[str]:
    """텍스트에서 HEX 색상 코드 추출 (#fff, #ffffff 모두 지원). 6자리 정규화."""
    seen: list[str] = []
    for m in _HEX_RE.findall(text or ''):
        hx = m.lower()
        if len(hx) == 4:  # #abc → #aabbcc
            hx = '#' + hx[1] * 2 + hx[2] * 2 + hx[3] * 2
        if hx not in seen:
            seen.append(hx)
    return seen


def _hex_to_rgb(hx: str) -> tuple[int, int, int]:
    hx = hx.lstrip('#')
    if len(hx) == 3:
        hx = ''.join(c * 2 for c in hx)
    return int(hx[0:2], 16), int(hx[2:4], 16), int(hx[4:6], 16)


def _luminance(rgb: tuple[int, int, int]) -> float:
    """WCAG 상대 휘도 (0~1)."""
    def chan(v: int) -> float:
        c = v / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)


def contrast_ratio(a: str, b: str) -> float:
    """두 HEX 색상의 WCAG 대비 비율 (1.0 ~ 21.0)."""
    try:
        la = _luminance(_hex_to_rgb(a))
        lb = _luminance(_hex_to_rgb(b))
    except Exception:
        return 1.0
    hi, lo = max(la, lb), min(la, lb)
    return round((hi + 0.05) / (lo + 0.05), 2)


def collect_wcag_warnings(colors: list[str]) -> list[str]:
    """팔레트 내 인접 색상 쌍 중 4.5 미만 대비(AA 본문 기준)를 경고로."""
    warnings: list[str] = []
    for i, a in enumerate(colors):
        for b in colors[i + 1:]:
            r = contrast_ratio(a, b)
            if r < 4.5:
                warnings.append(f'{a} vs {b}: 대비 {r} (AA 본문 기준 4.5 미달)')
    return warnings


def generate_palette_svg(colors: list[str], title: str = '색상 팔레트') -> str:
    """색상 목록을 가로 띠 SVG로 렌더."""
    if not colors:
        return ''
    swatch_w = 120
    swatch_h = 160
    pad = 16
    title_h = 44
    width = pad * 2 + swatch_w * len(colors) + (len(colors) - 1) * 8
    height = pad * 2 + title_h + swatch_h + 24  # label line
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">',
        f'  <rect width="100%" height="100%" fill="#ffffff"/>',
        f'  <text x="{pad}" y="{pad + 28}" font-family="sans-serif" font-size="20" font-weight="600" fill="#111">{_escape(title)}</text>',
    ]
    x = pad
    y = pad + title_h
    for hx in colors:
        try:
            rgb = _hex_to_rgb(hx)
        except Exception:
            continue
        lum = _luminance(rgb)
        text_color = '#111' if lum > 0.5 else '#fff'
        parts.append(
            f'  <rect x="{x}" y="{y}" width="{swatch_w}" height="{swatch_h}" fill="{hx}" rx="8" ry="8"/>'
        )
        parts.append(
            f'  <text x="{x + swatch_w / 2}" y="{y + swatch_h / 2 + 6}" '
            f'font-family="monospace" font-size="14" fill="{text_color}" text-anchor="middle">{hx}</text>'
        )
        x += swatch_w + 8
    parts.append('</svg>')
    return '\n'.join(parts)


def _escape(s: str) -> str:
    return (
        s.replace('&', '&amp;')
         .replace('<', '&lt;')
         .replace('>', '&gt;')
         .replace('"', '&quot;')
    )

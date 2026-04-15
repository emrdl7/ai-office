#!/usr/bin/env python3
"""agents/*.md 페르소나 스키마 린트 — P5-1

검사 항목:
  1. h1 형식: `# {이름} ({역할})`
  2. 필수 섹션 존재: 성격, 판단력, 대화 스타일, 역할, 품질 기준
  3. 필수 섹션 순서 보존
  4. 각 필수 섹션 내 최소 1개 비어있지 않은 내용 행 (빈 섹션 금지)
  5. 각 필수 섹션 내 최소 1개 bullet(- 또는 *) 또는 numbered item(숫자.)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

AGENTS_DIR = Path(__file__).parent.parent / "agents"
REQUIRED_SECTIONS = ["성격", "판단력", "대화 스타일", "역할", "품질 기준"]
H1_PATTERN = re.compile(r"^# \S.+\s\(.+\)$")

errors: list[str] = []
warnings: list[str] = []


def _parse_sections(text: str) -> dict[str, list[str]]:
    """h2 섹션별 body line 파싱. key = 섹션명, value = 이후 lines (다음 h2 전까지)."""
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    return sections


def _has_content(lines: list[str]) -> bool:
    return any(l.strip() for l in lines)


def _has_bullet_or_list(lines: list[str]) -> bool:
    """- / * bullet 또는 숫자. numbered list item이 1개 이상."""
    for l in lines:
        s = l.strip()
        if s.startswith("- ") or s.startswith("* "):
            return True
        if re.match(r"^\d+\.", s):
            return True
    return False


def lint_file(md_path: Path) -> None:
    name = md_path.name
    text = md_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    # 1. h1 형식
    h1_lines = [l for l in lines if l.startswith("# ")]
    if not h1_lines:
        errors.append(f"{name}: h1 헤더 없음")
    elif not H1_PATTERN.match(h1_lines[0]):
        errors.append(f"{name}: h1 형식 불일치 — \"{h1_lines[0]}\" (기대: # 이름 (역할))")

    sections = _parse_sections(text)
    section_keys = list(sections.keys())

    # 2. 필수 섹션 존재
    for req in REQUIRED_SECTIONS:
        if req not in sections:
            errors.append(f"{name}: 필수 섹션 '## {req}' 없음")

    # 3. 필수 섹션 순서 (존재하는 것들끼리만 비교)
    present_required = [s for s in section_keys if s in REQUIRED_SECTIONS]
    expected_order = [s for s in REQUIRED_SECTIONS if s in present_required]
    if present_required != expected_order:
        errors.append(
            f"{name}: 필수 섹션 순서 오류 — 실제: {present_required} | 기대: {expected_order}"
        )

    # 4. 빈 섹션 금지 / 5. bullet 검사 (필수 섹션만)
    for req in REQUIRED_SECTIONS:
        if req not in sections:
            continue  # 이미 에러 기록됨
        body = sections[req]
        if not _has_content(body):
            errors.append(f"{name}: '## {req}' 섹션이 비어 있음")
        elif not _has_bullet_or_list(body):
            errors.append(f"{name}: '## {req}' 섹션에 bullet/list 항목 없음 (최소 1개 필요)")


def main() -> int:
    md_files = sorted(AGENTS_DIR.glob("*.md"))
    if not md_files:
        print(f"persona lint: agents 디렉토리에 md 파일 없음 ({AGENTS_DIR})")
        return 1

    for md in md_files:
        lint_file(md)

    if errors:
        print(f"persona lint FAIL: {len(errors)}개 오류 ({len(md_files)}개 파일 검사)")
        for e in errors:
            print(f"  ✗ {e}")
        if warnings:
            for w in warnings:
                print(f"  ⚠ {w}")
        return 1

    msg = f"persona lint OK: {len(md_files)}개 파일 통과"
    if warnings:
        msg += f", {len(warnings)}개 경고"
        for w in warnings:
            print(f"  ⚠ {w}")
    print(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())

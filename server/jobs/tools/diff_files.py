"""diff_files — 두 텍스트 파일의 unified diff를 반환."""
from __future__ import annotations

import difflib
from pathlib import Path

from jobs.tool_registry import ToolSpec

TOOL_SPEC = ToolSpec(
    id='diff_files',
    name='파일 비교(diff)',
    description='context의 file_a, file_b 키에 지정된 두 파일의 diff를 반환한다. 코드 리뷰 시 변경사항 파악에 유용.',
    category='file',
    params=['file_a', 'file_b'],
)


def execute(context: dict[str, str]) -> str:
    file_a = context.get('file_a', '')
    file_b = context.get('file_b', '')
    if not file_a or not file_b:
        return '[diff_files: file_a, file_b 모두 필요]'
    try:
        a_lines = Path(file_a).read_text(encoding='utf-8').splitlines(keepends=True)
        b_lines = Path(file_b).read_text(encoding='utf-8').splitlines(keepends=True)
        diff = list(difflib.unified_diff(a_lines, b_lines, fromfile=file_a, tofile=file_b))
        if not diff:
            return '[두 파일이 동일합니다]'
        result = ''.join(diff)
        return result[:8000] + ('\n[이후 생략]' if len(result) > 8000 else '')
    except Exception as exc:
        return f'[diff_files 실패: {exc}]'

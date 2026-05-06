"""read_file — 텍스트 파일 내용을 안전한 길이로 반환."""
from __future__ import annotations

from pathlib import Path

from jobs.tool_registry import ToolSpec

TOOL_SPEC = ToolSpec(
    id='read_file',
    name='파일 읽기',
    description='context의 file_path 키에 지정된 파일을 읽는다.',
    category='file',
    params=['file_path'],
)


def execute(context: dict[str, str]) -> str:
    file_path = context.get('file_path', '')
    if not file_path:
        return '[read_file: file_path 없음]'
    try:
        path = Path(file_path)
        if not path.exists():
            return f'[파일 없음: {file_path}]'
        content = path.read_text(encoding='utf-8')
        if len(content) > 20000:
            content = content[:20000] + f'\n\n[이후 {len(content) - 20000}자 생략]'
        return content
    except Exception as exc:
        return f'[파일 읽기 실패: {exc}]'

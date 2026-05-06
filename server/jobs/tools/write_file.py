"""write_file — 지정 경로에 텍스트 산출물을 저장."""
from __future__ import annotations

from pathlib import Path

from jobs.tool_registry import ToolSpec

TOOL_SPEC = ToolSpec(
    id='write_file',
    name='파일 저장',
    description='context의 file_path와 content 키를 사용해 파일을 저장한다. 산출물을 직접 파일로 출력할 때 사용.',
    category='file',
    params=['file_path', 'content'],
)


def execute(context: dict[str, str]) -> str:
    file_path = context.get('file_path', '')
    content = context.get('content', '')
    if not file_path:
        return '[write_file: file_path 없음]'
    try:
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        return f'[파일 저장 완료: {file_path} ({len(content)}자)]'
    except Exception as exc:
        return f'[write_file 실패: {exc}]'

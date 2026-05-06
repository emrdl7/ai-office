"""list_files — 디렉터리의 파일 목록을 반환."""
from __future__ import annotations

from pathlib import Path

from jobs.tool_registry import ToolSpec

TOOL_SPEC = ToolSpec(
    id='list_files',
    name='파일 목록',
    description='context의 dir_path 키에 지정된 디렉토리의 파일 목록을 가져온다.',
    category='file',
    params=['dir_path'],
)


def execute(context: dict[str, str]) -> str:
    dir_path = context.get('dir_path', '.')
    try:
        path = Path(dir_path)
        if not path.is_dir():
            return f'[디렉토리 없음: {dir_path}]'
        files = [str(item.relative_to(path)) for item in sorted(path.rglob('*')) if item.is_file()][:100]
        return '\n'.join(files)
    except Exception as exc:
        return f'[목록 실패: {exc}]'

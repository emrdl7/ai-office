"""notion_write — Notion 페이지에 Markdown 내용을 블록으로 추가."""
from __future__ import annotations

import json
import urllib.request

from jobs.tool_registry import ToolSpec
from jobs.tools._common import resolve_token

TOOL_SPEC = ToolSpec(
    id='notion_write',
    name='Notion 페이지 작성',
    description='context의 page_id와 content를 Notion 페이지에 추가한다.',
    category='integration',
    params=['page_id', 'content'],
    env_var='NOTION_TOKEN',
)


def _rich_text(text: str) -> list[dict[str, object]]:
    return [{'type': 'text', 'text': {'content': text[:2000]}}]


def _markdown_blocks(content: str) -> list[dict[str, object]]:
    blocks: list[dict[str, object]] = []
    code_buf: list[str] = []
    in_code = False
    for line in content.splitlines():
        if line.startswith('```'):
            if in_code:
                blocks.append({
                    'object': 'block',
                    'type': 'code',
                    'code': {'rich_text': _rich_text('\n'.join(code_buf)), 'language': 'plain text'},
                })
                code_buf = []
                in_code = False
            else:
                in_code = True
            continue
        if in_code:
            code_buf.append(line)
            continue
        stripped = line.strip()
        if stripped.startswith('# '):
            blocks.append({'object': 'block', 'type': 'heading_1', 'heading_1': {'rich_text': _rich_text(stripped[2:])}})
        elif stripped.startswith('## '):
            blocks.append({'object': 'block', 'type': 'heading_2', 'heading_2': {'rich_text': _rich_text(stripped[3:])}})
        elif stripped.startswith('### '):
            blocks.append({'object': 'block', 'type': 'heading_3', 'heading_3': {'rich_text': _rich_text(stripped[4:])}})
        elif stripped.startswith('- ') or stripped.startswith('* '):
            blocks.append({'object': 'block', 'type': 'bulleted_list_item', 'bulleted_list_item': {'rich_text': _rich_text(stripped[2:])}})
        elif stripped.startswith('> '):
            blocks.append({'object': 'block', 'type': 'quote', 'quote': {'rich_text': _rich_text(stripped[2:])}})
        elif stripped:
            blocks.append({'object': 'block', 'type': 'paragraph', 'paragraph': {'rich_text': _rich_text(stripped)}})
    return blocks


def execute(context: dict[str, str]) -> str:
    token = resolve_token('NOTION_TOKEN')
    if not token:
        return '[notion_write: NOTION_TOKEN 미설정 — 컴포넌트 라이브러리에서 토큰을 등록하세요]'
    page_id = context.get('page_id', '')
    content = context.get('content', '')
    if not page_id or not content:
        return '[notion_write: page_id, content 필요]'

    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
        'Notion-Version': '2022-06-28',
    }
    blocks = _markdown_blocks(content)
    total = 0
    try:
        for i in range(0, len(blocks), 100):
            payload = json.dumps({'children': blocks[i:i + 100]}).encode()
            req = urllib.request.Request(
                f'https://api.notion.com/v1/blocks/{page_id}/children',
                data=payload,
                headers=headers,
            )
            with urllib.request.urlopen(req, timeout=10):
                pass
            total += len(blocks[i:i + 100])
        return f'[Notion 작성 완료: {page_id} — {total}개 블록]'
    except Exception as exc:
        return f'[notion_write 실패: {exc}]'

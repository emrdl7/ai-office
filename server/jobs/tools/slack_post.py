"""slack_post — Slack 메시지 전송."""
from __future__ import annotations

import json
import urllib.request

from jobs.tool_registry import ToolSpec
from jobs.tools._common import resolve_token

TOOL_SPEC = ToolSpec(
    id='slack_post',
    name='Slack 메시지 전송',
    description='context의 channel과 message를 Slack에 전송한다.',
    category='integration',
    params=['channel', 'message'],
    env_var='SLACK_BOT_TOKEN',
)


def execute(context: dict[str, str]) -> str:
    token = resolve_token('SLACK_BOT_TOKEN')
    if not token:
        return '[slack_post: SLACK_BOT_TOKEN 미설정 — 컴포넌트 라이브러리에서 토큰을 등록하세요]'
    channel = context.get('channel', '')
    message = context.get('message', '')
    if not channel or not message:
        return '[slack_post: channel, message 필요]'
    try:
        payload = json.dumps({'channel': channel, 'text': message}).encode()
        req = urllib.request.Request(
            'https://slack.com/api/chat.postMessage',
            data=payload,
            headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        if data.get('ok'):
            return f'[Slack 전송 완료: #{channel}]'
        return f'[slack_post 실패: {data.get("error", "unknown")}]'
    except Exception as exc:
        return f'[slack_post 실패: {exc}]'

# Gemini REST API 러너 (OAuth credentials 기반)
import asyncio
import json
import os
from pathlib import Path

import httpx
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleAuthRequest

LOG = Path('data/debug.log')

# Gemini CLI 인증 파일 경로
_OAUTH_CREDS_PATH = Path.home() / '.gemini' / 'oauth_creds.json'

# Gemini REST API
_GEMINI_BASE = 'https://generativelanguage.googleapis.com/v1beta'
_DEFAULT_MODEL = os.environ.get('GEMINI_MODEL', 'gemini-2.5-flash')
_FALLBACK_MODEL = 'gemini-2.0-flash'

# Client ID (Gemini CLI 공식 클라이언트)
_CLIENT_ID = '681255809395-oo8ft2oprdrnp9e3aqf6av3hmdib135j.apps.googleusercontent.com'
_TOKEN_URI = 'https://oauth2.googleapis.com/token'

_SCOPES = [
    'https://www.googleapis.com/auth/cloud-platform',
    'https://www.googleapis.com/auth/userinfo.profile',
    'https://www.googleapis.com/auth/userinfo.email',
    'openid',
]

# 응답이 잘렸는지 판단하는 패턴
_CUT_INDICATORS = ['###', '## ', '**', '- **', '---', '|']


class GeminiRunnerError(Exception):
    pass


def _looks_truncated(text: str) -> bool:
    '''응답이 중간에 잘린 것처럼 보이는지 판단한다.'''
    if not text:
        return False
    last_line = text.rstrip().split('\n')[-1].strip()
    if any(last_line.endswith(ind) for ind in _CUT_INDICATORS):
        return True
    if last_line and last_line[-1] not in '.!?。\n```':
        if len(text) > 1500:
            return True
    return False


def _load_credentials() -> Credentials:
    '''~/.gemini/oauth_creds.json 에서 OAuth credentials 로드 및 갱신.'''
    if not _OAUTH_CREDS_PATH.exists():
        raise GeminiRunnerError('Gemini OAuth creds 없음: ~/.gemini/oauth_creds.json')

    raw = json.loads(_OAUTH_CREDS_PATH.read_text())

    # google-auth Credentials 객체 생성
    creds = Credentials(
        token=raw.get('access_token'),
        refresh_token=raw.get('refresh_token'),
        token_uri=_TOKEN_URI,
        client_id=_CLIENT_ID,
        client_secret=raw.get('client_secret', ''),
        scopes=_SCOPES,
    )

    # 만료됐으면 갱신
    if not creds.valid:
        creds.refresh(GoogleAuthRequest())
        raw['access_token'] = creds.token
        # atomic write: tmp → rename
        tmp = _OAUTH_CREDS_PATH.with_suffix('.tmp')
        tmp.write_text(json.dumps(raw, indent=2))
        tmp.replace(_OAUTH_CREDS_PATH)

    return creds


async def _call_gemini_model(full_prompt: str, timeout: float, model: str, system: str = '') -> str:
    '''지정 모델로 Gemini REST API 단일 호출.'''
    api_key = os.environ.get('GOOGLE_API_KEY', '')
    if api_key:
        headers = {'Content-Type': 'application/json'}
        url = f'{_GEMINI_BASE}/models/{model}:generateContent?key={api_key}'
    else:
        try:
            creds = _load_credentials()
        except Exception as e:
            raise GeminiRunnerError(f'Gemini 인증 실패: {e}')
        headers = {
            'Authorization': f'Bearer {creds.token}',
            'Content-Type': 'application/json',
        }
        url = f'{_GEMINI_BASE}/models/{model}:generateContent'

    payload: dict = {
        'contents': [{'role': 'user', 'parts': [{'text': full_prompt}]}],
        'generationConfig': {'temperature': 0.7, 'maxOutputTokens': 8192},
    }
    if system:
        payload['systemInstruction'] = {'parts': [{'text': system}]}

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, headers=headers, json=payload)
    except httpx.TimeoutException:
        raise GeminiRunnerError(f'Gemini REST API 타임아웃 ({timeout}초)')
    except Exception as e:
        raise GeminiRunnerError(f'Gemini REST API 호출 실패: {e}')

    if resp.status_code in (429, 503):
        raise GeminiRunnerError(f'Gemini 일시 불가 ({resp.status_code})')
    if resp.status_code == 401:
        raise GeminiRunnerError(f'Gemini 인증 오류 (401)')
    if resp.status_code != 200:
        raise GeminiRunnerError(f'Gemini API 오류 ({resp.status_code}): {resp.text[:200]}')

    data = resp.json()
    try:
        text = data['candidates'][0]['content']['parts'][0]['text']
    except (KeyError, IndexError) as e:
        raise GeminiRunnerError(f'Gemini 응답 파싱 실패: {e}')

    try:
        LOG.open('a').write(f'[GEMINI:{model}] len={len(text)}\n')
    except Exception:
        pass
    return text.strip()


async def _call_gemini(full_prompt: str, timeout: float, system: str = '') -> str:
    '''2.5-flash 우선, 503/429 시 2.0-flash 폴백. 429면 5초 대기 후 재시도.'''
    import logging as _log  # noqa: PLC0415
    _logger = _log.getLogger(__name__)

    for model in (_DEFAULT_MODEL, _FALLBACK_MODEL):
        for attempt in range(2):
            try:
                return await _call_gemini_model(full_prompt, timeout, model, system=system)
            except GeminiRunnerError as e:
                if '일시 불가' in str(e):
                    if attempt == 0:
                        _logger.warning('[gemini] %s 일시 불가, 15초 후 재시도', model)
                        await asyncio.sleep(15)
                        continue
                    _logger.warning('[gemini] %s 실패 → 다음 모델', model)
                    break  # 다음 모델로
                raise
    raise GeminiRunnerError('Gemini 모든 모델 일시 불가 (429/503)')


async def run_gemini(prompt: str, system: str = '', timeout: float = 600.0) -> str:
    '''Gemini REST API를 실행하고, 응답이 잘리면 이어서 작성하도록 재호출한다.'''
    rules = (
        '[필수 규칙]\n'
        '- 반드시 한국어로만 응답하세요. 영어를 사용하지 마세요.\n'
        '- 파일을 생성하거나 도구를 호출하지 마세요. 텍스트로만 응답하세요.\n'
        '- 코드를 작성해야 할 경우 마크다운 코드블록(```)으로 감싸서 텍스트로 출력하세요.\n'
    )
    # system이 있으면 rules를 systemInstruction에 합쳐서 전달, 없으면 user content에 포함
    if system:
        system_with_rules = rules + '---\n\n' + system
        full_prompt = prompt
    else:
        system_with_rules = ''
        full_prompt = rules + '---\n\n' + prompt

    result = await _call_gemini(full_prompt, timeout, system=system_with_rules)

    # 응답이 잘린 것 같으면 최대 2회 이어쓰기
    for _ in range(2):
        if not _looks_truncated(result):
            break
        continue_prompt = (
            f'{full_prompt}\n\n'
            f'[이전 응답]\n{result}\n\n'
            f'위 응답이 중간에 끊겼습니다. 끊긴 부분부터 이어서 작성하세요. '
            f'이전 내용을 반복하지 말고, 끊긴 지점부터 바로 이어서 작성하세요.'
        )
        continuation = await _call_gemini(continue_prompt, timeout, system=system_with_rules)
        result += '\n' + continuation

    try:
        from runners.cost_tracker import record_call
        record_call(runner='gemini', model=_DEFAULT_MODEL, prompt=full_prompt, response=result)
    except Exception:
        pass
    return result

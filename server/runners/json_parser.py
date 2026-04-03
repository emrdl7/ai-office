# Gemma4 구조화 JSON 출력 파싱+복구 전략 (INFR-05)
# Gemma4는 format:json 파라미터를 사용해도 응답에 후행 텍스트,
# 마크다운 코드 펜스, 후행 쉼표 등을 포함하는 경우가 있다.
# 2-pass 전략: strict 파싱 실패 시 repair 시도
import json
import re
from typing import Any


def parse_json(text: str) -> Any | None:
    '''Gemma4 JSON 출력 파싱 (2-pass: strict → repair).

    Pass 1: 표준 json.loads 시도
    Pass 2:
      a) 마크다운 코드 펜스(```json...```) 내용 추출
      b) 첫 번째 { 또는 [ 부터 마지막 } 또는 ] 까지 추출
      c) 후행 쉼표 제거 후 재시도

    Returns:
        파싱된 Python 객체, 복구 불가능하면 None
    '''
    if not text or not text.strip():
        return None

    # Pass 1: 표준 파싱
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Pass 2a: 마크다운 코드 펜스 추출
    fence_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Pass 2b: 첫 번째 { 또는 [ 부터 마지막 } 또는 ] 추출
    extracted = _extract_json_block(text)
    if extracted:
        try:
            return json.loads(extracted)
        except json.JSONDecodeError:
            # Pass 2c: 후행 쉼표 제거 후 재시도
            repaired = _remove_trailing_commas(extracted)
            try:
                return json.loads(repaired)
            except json.JSONDecodeError:
                pass

    return None


def _extract_json_block(text: str) -> str | None:
    '''텍스트에서 첫 번째 JSON 블록({...} 또는 [...]) 추출'''
    # 객체 시도
    start_obj = text.find('{')
    if start_obj != -1:
        end_obj = text.rfind('}')
        if end_obj > start_obj:
            return text[start_obj:end_obj + 1]
    # 배열 시도
    start_arr = text.find('[')
    if start_arr != -1:
        end_arr = text.rfind(']')
        if end_arr > start_arr:
            return text[start_arr:end_arr + 1]
    return None


def _remove_trailing_commas(text: str) -> str:
    '''JSON의 후행 쉼표 제거 (,} 또는 ,])'''
    # ,} 또는 ,] 패턴에서 쉼표 제거 (공백 포함)
    text = re.sub(r',\s*}', '}', text)
    text = re.sub(r',\s*]', ']', text)
    return text

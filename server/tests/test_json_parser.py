# INFR-05: Gemma4 JSON 파싱+복구 전략 테스트
import pytest
from runners.json_parser import parse_json


def test_strict_json_parse_valid():
    '''유효한 JSON 문자열이 파싱됨 (pass 1)'''
    result = parse_json('{"task": "design", "priority": 1}')
    assert result == {'task': 'design', 'priority': 1}


def test_parse_json_array():
    '''JSON 배열도 파싱됨'''
    result = parse_json('[1, 2, 3]')
    assert result == [1, 2, 3]


def test_repair_json_with_trailing_text():
    '''후행 텍스트가 있는 JSON이 복구됨 (pass 2b)'''
    result = parse_json('{"status": "done"} 이 결과를 확인해주세요.')
    assert result == {'status': 'done'}


def test_repair_json_with_leading_text():
    '''전치 텍스트가 있는 JSON이 복구됨 (pass 2b)'''
    result = parse_json('결과는 다음과 같습니다: {"status": "done"}')
    assert result == {'status': 'done'}


def test_repair_markdown_code_fence():
    '''마크다운 코드 펜스로 감싸진 JSON이 복구됨 (pass 2a)'''
    text = '```json\n{"key": "value"}\n```'
    result = parse_json(text)
    assert result == {'key': 'value'}


def test_repair_trailing_comma():
    '''후행 쉼표가 있는 JSON이 복구됨 (pass 2c)'''
    result = parse_json('{"a": 1, "b": 2,}')
    assert result == {'a': 1, 'b': 2}


def test_repair_returns_none_on_unrecoverable():
    '''복구 불가능한 출력에서 None 반환'''
    result = parse_json('이것은 JSON이 아닙니다. 완전히 다른 텍스트.')
    assert result is None


def test_empty_string_returns_none():
    '''빈 문자열에서 None 반환'''
    assert parse_json('') is None
    assert parse_json('   ') is None

# INFR-05: Gemma4 JSON 파싱+복구 전략 테스트
# 실제 테스트: 01-05-PLAN에서 구현
import pytest

@pytest.mark.xfail(reason='01-05-PLAN에서 구현 예정', strict=False)
def test_strict_json_parse_valid():
    '''유효한 JSON 문자열이 파싱됨'''
    pass

@pytest.mark.xfail(reason='01-05-PLAN에서 구현 예정', strict=False)
def test_repair_json_with_trailing_text():
    '''후행 텍스트가 있는 JSON이 복구됨'''
    pass

@pytest.mark.xfail(reason='01-05-PLAN에서 구현 예정', strict=False)
def test_repair_returns_none_on_unrecoverable():
    '''복구 불가능한 출력에서 None 반환'''
    pass

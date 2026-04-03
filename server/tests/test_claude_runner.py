# INFR-02: Claude CLI subprocess 러너 테스트
# 실제 테스트: 01-04-PLAN에서 구현
import pytest

@pytest.mark.xfail(reason='01-04-PLAN에서 구현 예정', strict=False)
async def test_run_claude_returns_text():
    '''Claude subprocess가 텍스트 응답을 반환'''
    pass

@pytest.mark.xfail(reason='01-04-PLAN에서 구현 예정', strict=False)
async def test_bare_flag_token_isolation():
    '''--bare 플래그로 CLAUDE.md 주입이 차단됨'''
    pass

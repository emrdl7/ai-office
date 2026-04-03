# INFR-03: Ollama 러너 단일 큐 테스트
# 실제 테스트: 01-05-PLAN에서 구현
import pytest

@pytest.mark.xfail(reason='01-05-PLAN에서 구현 예정', strict=False)
async def test_sequential_queue_ordering():
    '''동시 요청이 순차적으로 처리됨을 확인'''
    pass

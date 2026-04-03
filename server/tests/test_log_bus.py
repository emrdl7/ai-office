# INFR-04: asyncio.Queue 이벤트 버스 테스트
# 실제 테스트: 01-06-PLAN에서 구현
import pytest

@pytest.mark.xfail(reason='01-06-PLAN에서 구현 예정', strict=False)
async def test_publish_reaches_subscriber():
    '''발행된 이벤트가 구독자 큐에 도달함'''
    pass

@pytest.mark.xfail(reason='01-06-PLAN에서 구현 예정', strict=False)
async def test_unsubscribe_stops_delivery():
    '''unsubscribe 후 이벤트가 전달되지 않음'''
    pass

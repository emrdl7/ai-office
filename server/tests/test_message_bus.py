# INFR-01: SQLite WAL 메시지 버스 테스트
# 실제 테스트: 01-02-PLAN에서 구현
import pytest

@pytest.mark.xfail(reason='01-02-PLAN에서 구현 예정', strict=False)
def test_publish_and_consume(in_memory_db):
    '''메시지 발행 후 소비 왕복 테스트'''
    pass

@pytest.mark.xfail(reason='01-02-PLAN에서 구현 예정', strict=False)
def test_ack_removes_from_pending(in_memory_db):
    '''ACK 후 메시지가 pending에서 제거됨을 확인'''
    pass

@pytest.mark.xfail(reason='01-02-PLAN에서 구현 예정', strict=False)
def test_atomic_write_pattern(in_memory_db):
    '''tmp+rename atomic write 패턴 적용 확인'''
    pass

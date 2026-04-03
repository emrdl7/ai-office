# ARTF-01, ARTF-02: workspace 파일시스템 테스트
# 실제 테스트: 01-03-PLAN에서 구현
import pytest

@pytest.mark.xfail(reason='01-03-PLAN에서 구현 예정', strict=False)
def test_write_artifact_creates_file(tmp_workspace):
    '''write_artifact가 실제 파일을 생성함'''
    pass

@pytest.mark.xfail(reason='01-03-PLAN에서 구현 예정', strict=False)
def test_atomic_write_no_partial_file(tmp_workspace):
    '''쓰기 중단 시 부분 파일이 남지 않음'''
    pass

@pytest.mark.xfail(reason='01-03-PLAN에서 구현 예정', strict=False)
def test_path_traversal_blocked(tmp_workspace):
    '''경로 순회 공격(../etc/passwd)이 차단됨'''
    pass

@pytest.mark.xfail(reason='01-03-PLAN에서 구현 예정', strict=False)
def test_multiple_artifact_types_supported(tmp_workspace):
    '''.py, .md, .json 등 다양한 파일 형식 저장 가능'''
    pass

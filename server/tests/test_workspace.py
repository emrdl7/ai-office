# ARTF-01, ARTF-02: WorkspaceManager 테스트
import os
import pytest
from pathlib import Path
from workspace.manager import WorkspaceManager


@pytest.fixture
def mgr(tmp_workspace):
    '''임시 workspace 루트를 사용하는 WorkspaceManager'''
    return WorkspaceManager(task_id='task-001', workspace_root=tmp_workspace)


def test_write_artifact_creates_file(mgr, tmp_workspace):
    '''write_artifact가 실제 파일을 생성함 (ARTF-01)'''
    result = mgr.write_artifact('output.py', 'print("hello")')

    assert result.exists()
    assert result.read_text() == 'print("hello")'


def test_task_isolation_directory(mgr, tmp_workspace):
    '''산출물이 workspace/<task-id>/ 하위에 저장됨 (ARTF-01)'''
    result = mgr.write_artifact('result.md', '# Report')

    assert str(result).startswith(str(tmp_workspace / 'task-001'))


def test_atomic_write_no_partial_file(mgr, tmp_workspace):
    '''정상 쓰기 후 .tmp 파일이 남지 않음 (atomic write 패턴)'''
    import glob
    mgr.write_artifact('code.py', 'x = 1')

    tmp_files = list(tmp_workspace.rglob('*.tmp.*'))
    assert len(tmp_files) == 0, f'임시 파일 잔존: {tmp_files}'


def test_path_traversal_blocked(mgr):
    '''경로 순회 공격이 ValueError로 차단됨 (보안)'''
    with pytest.raises(ValueError, match='경로 순회 감지'):
        mgr.safe_path('../../../etc/passwd')


def test_multiple_artifact_types_supported(mgr):
    '''다양한 파일 형식 저장 가능 (ARTF-02)'''
    artifacts = [
        ('main.py', 'print("code")'),
        ('README.md', '# Docs'),
        ('schema.json', '{"version": 1}'),
        ('styles.css', 'body { margin: 0 }'),
        ('config.yaml', 'key: value'),
        ('component.tsx', 'export default () => <div/>'),
    ]
    for path, content in artifacts:
        result = mgr.write_artifact(path, content)
        assert result.exists(), f'{path} 저장 실패'
        assert result.read_text() == content


def test_write_creates_subdirectory(mgr):
    '''중첩 디렉토리 자동 생성'''
    result = mgr.write_artifact('src/components/Button.tsx', 'export const Button = () => null')

    assert result.exists()
    assert result.parent.name == 'components'


def test_artifact_type_classification(mgr):
    '''파일 확장자로 타입 분류'''
    assert mgr.artifact_type('main.py') == 'code'
    assert mgr.artifact_type('README.md') == 'doc'
    assert mgr.artifact_type('schema.json') == 'design'
    assert mgr.artifact_type('unknown.xyz') == 'unknown'

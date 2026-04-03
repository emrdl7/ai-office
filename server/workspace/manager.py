# 태스크별 격리 디렉토리 + atomic write (ARTF-01, ARTF-02)
# 실제 구현: 01-03-PLAN
from pathlib import Path

class WorkspaceManager:
    def __init__(self, task_id: str):
        raise NotImplementedError('01-03-PLAN에서 구현 예정')

    def safe_path(self, relative_path: str) -> Path:
        raise NotImplementedError

    def write_artifact(self, relative_path: str, content: str | bytes) -> Path:
        raise NotImplementedError

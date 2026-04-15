# 프로젝트 경로 상수 — 테스트에서 env로 격리 가능.
import os
from pathlib import Path

# server/ 디렉토리의 부모 = 프로젝트 루트
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _resolve_workspace_root() -> Path:
  env = os.environ.get('AI_OFFICE_WORKSPACE', '').strip()
  if env:
    return Path(env)
  return _PROJECT_ROOT / 'workspace'


WORKSPACE_ROOT: Path = _resolve_workspace_root()

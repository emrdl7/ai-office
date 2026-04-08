# 태스크별 격리 디렉토리 + atomic write (ARTF-01, ARTF-02)
import os
from pathlib import Path


# 지원하는 산출물 파일 형식 레지스트리 (ARTF-02)
SUPPORTED_EXTENSIONS: dict[str, list[str]] = {
    'code': ['.py', '.ts', '.js', '.tsx', '.jsx', '.html', '.css', '.scss', '.sh'],
    'doc': ['.md', '.txt', '.rst', '.pdf'],
    'design': ['.json', '.yaml', '.yml'],
    'data': ['.csv', '.xml'],
}

# 역방향 조회: 확장자 → 타입
_EXT_TO_TYPE: dict[str, str] = {
    ext: category
    for category, exts in SUPPORTED_EXTENSIONS.items()
    for ext in exts
}


class WorkspaceManager:
    '''태스크별 격리 workspace 관리자.

    모든 파일 쓰기는 tmp+rename atomic write 패턴으로 처리된다.
    경로 순회 공격은 safe_path()에서 차단된다.
    '''

    def __init__(self, task_id: str, workspace_root: str | Path = 'workspace'):
        self.task_id = task_id
        self.task_dir = Path(workspace_root) / task_id
        self.task_dir.mkdir(parents=True, exist_ok=True)

    def safe_path(self, relative_path: str) -> Path:
        '''경로 순회 공격 방지 — workspace/<task-id>/ 외부 접근 차단.

        Raises:
            ValueError: relative_path가 task_dir 외부를 가리키면 발생
        '''
        target = (self.task_dir / relative_path).resolve()
        task_dir_resolved = self.task_dir.resolve()
        if not str(target).startswith(str(task_dir_resolved)):
            raise ValueError(
                f'경로 순회 감지: {relative_path!r} → {target} '
                f'(허용 범위: {task_dir_resolved})'
            )
        return target

    def write_artifact(self, relative_path: str, content: str | bytes) -> Path:
        '''산출물 파일을 atomic write로 저장.

        1. tmp 파일에 쓴다
        2. os.rename으로 대상 경로로 이동 (원자적 교체)
        3. 실패 시 tmp 파일 삭제

        Returns:
            저장된 파일의 절대 경로
        '''
        target = self.safe_path(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)

        tmp_path = target.with_suffix(target.suffix + f'.tmp.{os.getpid()}')
        try:
            if isinstance(content, bytes):
                with open(tmp_path, 'wb') as f:
                    f.write(content)
            else:
                with open(tmp_path, 'w', encoding='utf-8') as f:
                    f.write(content)
            os.rename(tmp_path, target)  # macOS APFS에서 원자적
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise
        return target

    def artifact_type(self, relative_path: str) -> str:
        '''파일 확장자로 산출물 타입 반환 (code/doc/design/data/unknown)'''
        ext = Path(relative_path).suffix.lower()
        return _EXT_TO_TYPE.get(ext, 'unknown')

    def list_artifacts(self) -> list[Path]:
        '''task_dir 내 모든 파일 목록 (재귀)'''
        return [p for p in self.task_dir.rglob('*') if p.is_file()]

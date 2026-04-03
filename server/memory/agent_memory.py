# 에이전트 경험 메모리 핵심 모듈 (AMEM-01~03)
# 에이전트별 JSON 파일로 경험을 저장하고, 작업 시작 시 관련 경험을 조회한다.
import json
import os
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class MemoryRecord:
    '''에이전트 경험 레코드 스키마 (D-02)

    Attributes:
        task_id: 태스크 고유 식별자
        task_type: 태스크 유형 ('planning' | 'design' | 'development' | 'qa' | 기타)
        success: 성공 여부
        feedback: QA 불합격 사유 또는 Claude 보완 지시
        tags: 패턴 태그 (예: ['json_parse_error', 'missing_field'])
        timestamp: ISO 8601 타임스탬프
    '''
    task_id: str
    task_type: str
    success: bool
    feedback: str
    tags: list[str]
    timestamp: str


class AgentMemory:
    '''에이전트별 경험 메모리 관리자 (D-01, D-07, D-08)

    data/memory/{agent_name}_memory.json에 경험 레코드를 저장하고,
    lazy compaction으로 파일 크기를 관리한다.

    사용 예시:
        memory = AgentMemory('planner')
        memory.record(MemoryRecord(...))
        experiences = memory.load_relevant(task_type='planning', limit=5)
    '''

    # 상세 경험 최대 보관 수 (D-07 재량)
    MAX_DETAIL_COUNT = 20

    def __init__(
        self,
        agent_name: str,
        memory_root: str | Path = 'data/memory',
    ) -> None:
        '''AgentMemory 초기화

        Args:
            agent_name: 에이전트 이름 (예: 'planner', 'designer')
            memory_root: 메모리 파일 저장 루트 디렉토리 (테스트 격리용 주입 가능)
        '''
        self._file = Path(memory_root) / f'{agent_name}_memory.json'
        self._file.parent.mkdir(parents=True, exist_ok=True)

    def record(self, record: MemoryRecord) -> None:
        '''경험 레코드를 파일에 추가 (atomic write)

        Args:
            record: 저장할 경험 레코드
        '''
        data = self._load_raw()
        if 'records' not in data:
            data['records'] = []
        data['records'].append(asdict(record))
        self._atomic_write(data)

    def load_relevant(
        self,
        task_type: str | None = None,
        limit: int = 5,
    ) -> list[MemoryRecord]:
        '''관련 경험 조회 (lazy compaction 포함)

        Args:
            task_type: 필터할 태스크 유형. None이면 전체 반환
            limit: 반환할 최대 건수

        Returns:
            최신 순으로 정렬된 MemoryRecord 리스트
        '''
        if not self._file.exists():
            return []

        data = self._load_raw()

        # lazy compaction (D-08): 레코드 수가 MAX_DETAIL_COUNT 초과 시 압축
        compacted = self._maybe_compact(data)
        if compacted:
            self._atomic_write(data)

        records: list[dict[str, Any]] = data.get('records', [])

        # task_type 필터
        if task_type is not None:
            records = [r for r in records if r.get('task_type') == task_type]

        # timestamp 기준 내림차순 정렬 (최신이 먼저)
        records_sorted = sorted(
            records,
            key=lambda r: r.get('timestamp', ''),
            reverse=True,
        )

        return [
            MemoryRecord(**r)
            for r in records_sorted[:limit]
        ]

    def _maybe_compact(self, data: dict[str, Any]) -> bool:
        '''레코드 수가 MAX_DETAIL_COUNT 초과 시 오래된 항목 압축

        Args:
            data: 로드된 메모리 데이터 dict (인플레이스 수정)

        Returns:
            True: 압축 발생, False: 압축 불필요
        '''
        records: list[dict[str, Any]] = data.get('records', [])

        if len(records) <= self.MAX_DETAIL_COUNT:
            return False

        # timestamp 기준 정렬 (오래된 순)
        sorted_records = sorted(
            records,
            key=lambda r: r.get('timestamp', ''),
        )

        keep_count = self.MAX_DETAIL_COUNT // 2
        old_records = sorted_records[:-keep_count]
        new_records = sorted_records[-keep_count:]

        # 오래된 레코드를 규칙 기반 요약으로 압축
        n_success = sum(1 for r in old_records if r.get('success'))
        n_fail = len(old_records) - n_success

        all_tags: list[str] = []
        for r in old_records:
            all_tags.extend(r.get('tags', []))
        tag_counts = Counter(all_tags)
        top_tags = [tag for tag, _ in tag_counts.most_common(3)]

        summary_text = (
            f'[압축] {len(old_records)}건: '
            f'성공={n_success}, 실패={n_fail}, '
            f'주요태그={top_tags}'
        )

        # 기존 summary에 누적
        existing_summary = data.get('summary', '')
        if existing_summary:
            data['summary'] = existing_summary + '\n' + summary_text
        else:
            data['summary'] = summary_text

        data['records'] = new_records
        return True

    def _load_raw(self) -> dict[str, Any]:
        '''메모리 파일을 로드하여 raw dict 반환 (파일 없으면 빈 dict)'''
        if not self._file.exists():
            return {}
        try:
            with open(self._file, encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}

    def _atomic_write(self, data: dict[str, Any]) -> None:
        '''data를 JSON으로 atomic write (tmp + os.rename 패턴)'''
        tmp_path = self._file.with_suffix(
            self._file.suffix + f'.tmp.{os.getpid()}'
        )
        try:
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.rename(tmp_path, self._file)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise

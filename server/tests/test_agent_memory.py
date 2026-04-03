# AgentMemory 단위 테스트 (TDD RED → GREEN)
# 테스트 격리: 모든 테스트는 tmp_path 기반 memory_root 사용
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from memory.agent_memory import AgentMemory, MemoryRecord


def _make_record(task_type: str = 'planning', success: bool = True) -> MemoryRecord:
    '''테스트용 MemoryRecord 생성 헬퍼'''
    return MemoryRecord(
        task_id=f'task-{task_type}-{success}',
        task_type=task_type,
        success=success,
        feedback='테스트 피드백',
        tags=['test_tag'],
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


def test_record_creates_file(tmp_path: Path) -> None:
    '''record() 호출 후 에이전트 메모리 파일이 생성되는지 확인'''
    memory_root = tmp_path / 'memory'
    am = AgentMemory(agent_name='planner', memory_root=memory_root)
    record = _make_record(task_type='planning')

    am.record(record)

    assert (memory_root / 'planner_memory.json').exists()


def test_record_accumulates(tmp_path: Path) -> None:
    '''record() 두 번 호출 후 load_relevant()가 2건을 반환하는지 확인'''
    memory_root = tmp_path / 'memory'
    am = AgentMemory(agent_name='planner', memory_root=memory_root)

    am.record(_make_record(task_type='planning', success=True))
    am.record(_make_record(task_type='planning', success=False))

    results = am.load_relevant()
    assert len(results) == 2


def test_load_relevant_filters_by_task_type(tmp_path: Path) -> None:
    '''task_type 필터가 정확히 동작하는지 확인'''
    memory_root = tmp_path / 'memory'
    am = AgentMemory(agent_name='planner', memory_root=memory_root)

    am.record(_make_record(task_type='design'))
    am.record(_make_record(task_type='development'))

    results = am.load_relevant(task_type='design')
    assert len(results) == 1
    assert results[0].task_type == 'design'


def test_load_relevant_empty_when_no_file(tmp_path: Path) -> None:
    '''파일이 없으면 load_relevant()가 빈 리스트를 반환하는지 확인'''
    memory_root = tmp_path / 'memory'
    am = AgentMemory(agent_name='planner', memory_root=memory_root)

    results = am.load_relevant()
    assert results == []


def test_lazy_compaction_triggers(tmp_path: Path) -> None:
    '''MAX_DETAIL_COUNT + 1건 삽입 후 load_relevant() 호출 시 압축이 실행되는지 확인'''
    memory_root = tmp_path / 'memory'
    am = AgentMemory(agent_name='planner', memory_root=memory_root)
    total = AgentMemory.MAX_DETAIL_COUNT + 1

    for i in range(total):
        am.record(MemoryRecord(
            task_id=f'task-{i}',
            task_type='planning',
            success=True,
            feedback='피드백',
            tags=[],
            timestamp=datetime.now(timezone.utc).isoformat(),
        ))

    # load_relevant() 호출 시 lazy compaction이 실행됨
    am.load_relevant()

    # 압축 후 파일의 records 수가 MAX_DETAIL_COUNT + 1 미만이어야 함
    import json
    with open(memory_root / 'planner_memory.json', encoding='utf-8') as f:
        data = json.load(f)
    assert len(data['records']) < total


def test_atomic_write_no_partial_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    '''record() 중 os.rename이 실패해도 기존 파일 손상 없음 + tmp 파일 미잔류 확인'''
    import json

    memory_root = tmp_path / 'memory'
    am = AgentMemory(agent_name='planner', memory_root=memory_root)

    # 초기 레코드를 정상 저장
    first_record = _make_record(task_type='planning', success=True)
    am.record(first_record)

    memory_file = memory_root / 'planner_memory.json'
    with open(memory_file, encoding='utf-8') as f:
        original_content = f.read()

    # os.rename을 예외 발생으로 교체
    import memory.agent_memory as am_module

    def broken_rename(src: str, dst: str) -> None:
        raise OSError('강제 실패')

    monkeypatch.setattr(am_module.os, 'rename', broken_rename)

    # record() 호출 시 예외 발생 확인
    with pytest.raises(OSError):
        am.record(_make_record(task_type='qa', success=False))

    # 기존 파일 내용이 그대로인지 확인
    with open(memory_file, encoding='utf-8') as f:
        current_content = f.read()
    assert current_content == original_content

    # tmp 파일이 남아 있지 않은지 확인
    tmp_files = list(memory_root.glob('*.tmp.*'))
    assert tmp_files == [], f'tmp 파일 잔류: {tmp_files}'

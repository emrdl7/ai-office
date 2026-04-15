#!/usr/bin/env python3
"""능력 키워드 감사 — P5-4

각 에이전트의 agents/*.md '역할' 섹션에서 능력 키워드를 추출하고
실제 chat_logs + artifacts와 교차 검증해 '사용되지 않은 능력'과
'코드에 없는 암묵적 능력'을 리포트한다.

출력:
  - 콘솔 리포트 (스크립트 직접 실행 시)
  - 팀장 건의게시판 등록 (--register 플래그)

실행 예시:
  python3 scripts/capability_audit.py
  python3 scripts/capability_audit.py --register
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
AGENTS_DIR = REPO_ROOT / 'agents'
SERVER_DIR = REPO_ROOT / 'server'
DATA_DIR = REPO_ROOT / 'data'

AUDIT_AGENTS = ['designer', 'developer', 'planner', 'qa']

# 역할 섹션에서 기술/능력 키워드로 간주하는 패턴
CAPABILITY_RE = re.compile(
    r'(?:'
    r'[A-Za-z][A-Za-z0-9_-]{2,}'   # 영문 식별자 (CSS, WCAG, KPI…)
    r'|[가-힣]+\s(?:작성|분석|검수|설계|구현|수립|정의|조사|추출|통합)'  # 한국어 동작 명사구
    r'|[가-힣]{2,6}(?:서|안|도|명세|보고서|전략|계획|기준|가이드)'  # 한국어 산출물 명사
    r')'
)


def _parse_role_lines(md_path: Path) -> list[str]:
    """agents/*.md '역할' 섹션의 body 라인 반환."""
    text = md_path.read_text(encoding='utf-8')
    lines: list[str] = []
    in_role = False
    for line in text.splitlines():
        if line.startswith('## '):
            section = line[3:].strip()
            in_role = section == '역할'
        elif in_role:
            lines.append(line)
    return lines


def _extract_capabilities(lines: list[str]) -> list[str]:
    """역할 body에서 능력 키워드 목록 추출."""
    caps: list[str] = []
    for line in lines:
        for m in CAPABILITY_RE.finditer(line):
            kw = m.group().strip()
            if len(kw) >= 3:
                caps.append(kw)
    return list(dict.fromkeys(caps))  # dedup, 순서 유지


def _load_recent_messages(limit: int = 2000) -> list[str]:
    """data/chat_logs.db 에서 최근 N건의 message 텍스트 로드."""
    try:
        import sqlite3
        db_path = DATA_DIR / 'chat_logs.db'
        if not db_path.exists():
            return []
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            'SELECT message FROM chat_logs ORDER BY timestamp DESC LIMIT ?', (limit,)
        ).fetchall()
        conn.close()
        return [r['message'] or '' for r in rows]
    except Exception:
        return []


def _load_artifacts_text(limit: int = 200) -> list[str]:
    """artifacts 테이블에서 content 샘플 로드."""
    try:
        import sqlite3
        db_path = DATA_DIR / 'chat_logs.db'
        if not db_path.exists():
            return []
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT content FROM artifacts ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        conn.close()
        return [r['content'] or '' for r in rows]
    except Exception:
        return []


def audit_agent(agent_name: str, corpus: list[str]) -> dict:
    """에이전트 1명의 능력 키워드 사용 현황 감사."""
    md_path = AGENTS_DIR / f'{agent_name}.md'
    if not md_path.exists():
        return {'agent': agent_name, 'error': 'md 없음'}

    role_lines = _parse_role_lines(md_path)
    capabilities = _extract_capabilities(role_lines)

    corpus_text = ' '.join(corpus)

    used: list[str] = []
    unused: list[str] = []
    for cap in capabilities:
        if cap.lower() in corpus_text.lower():
            used.append(cap)
        else:
            unused.append(cap)

    return {
        'agent': agent_name,
        'total_capabilities': len(capabilities),
        'used': used,
        'unused': unused,
        'unused_count': len(unused),
        'usage_rate': round(len(used) / len(capabilities), 2) if capabilities else 0.0,
    }


def main(register: bool = False) -> int:
    messages = _load_recent_messages()
    artifacts = _load_artifacts_text()
    corpus = messages + artifacts

    if not corpus:
        print('⚠ chat_logs.db 없음 또는 비어 있음 — 오프라인 모드로 능력 목록만 출력')

    results: list[dict] = []
    for agent in AUDIT_AGENTS:
        r = audit_agent(agent, corpus)
        results.append(r)

    # 콘솔 출력
    total_unused = 0
    report_lines: list[str] = []
    for r in results:
        if 'error' in r:
            report_lines.append(f'  {r["agent"]}: {r["error"]}')
            continue
        pct = int(r['usage_rate'] * 100)
        status = '✅' if pct >= 70 else ('⚠' if pct >= 40 else '❌')
        line = (
            f'  {status} {r["agent"]}: 능력 {r["total_capabilities"]}개 중 '
            f'{len(r["used"])}개 사용 ({pct}%)'
        )
        if r['unused']:
            line += f'\n     미사용: {", ".join(r["unused"][:8])}'
        report_lines.append(line)
        total_unused += r['unused_count']

    print(f'capability_audit — 에이전트 {len(results)}명, 미사용 능력 합계 {total_unused}개')
    for line in report_lines:
        print(line)

    if total_unused == 0:
        print('능력 감사 OK: 모든 에이전트 능력이 최근 로그에서 사용됨')
        return 0

    # --register: 팀장 건의게시판에 등록
    if register and total_unused > 0:
        _register_suggestion(results)

    return 0


def _register_suggestion(results: list[dict]) -> None:
    """unused 능력 요약을 teamlead 건의게시판에 등록."""
    try:
        sys.path.insert(0, str(SERVER_DIR))
        from db.suggestion_store import create_suggestion

        lines: list[str] = []
        for r in results:
            if r.get('unused'):
                lines.append(
                    f'- {r["agent"]}: {", ".join(r["unused"][:5])}'
                    + (f' 외 {len(r["unused"]) - 5}개' if len(r["unused"]) > 5 else '')
                )

        if not lines:
            return

        body = (
            '능력 감사 결과 최근 로그에서 사용되지 않은 선언 능력이 발견되었습니다.\n\n'
            + '\n'.join(lines)
            + '\n\n에이전트 역할 정의와 실제 사용 패턴의 정합성을 검토하세요.'
        )
        create_suggestion(
            agent_id='system',
            title=f'[능력 감사] 미사용 능력 {sum(r.get("unused_count", 0) for r in results)}개 발견',
            content=body,
            category='프로세스 개선',
            target_agent='teamlead',
        )
        print('✅ 팀장 건의게시판 등록 완료')
    except Exception as e:
        print(f'⚠ 건의 등록 실패: {e}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='에이전트 능력 키워드 감사')
    parser.add_argument('--register', action='store_true', help='결과를 팀장 건의게시판에 등록')
    args = parser.parse_args()
    sys.exit(main(register=args.register))

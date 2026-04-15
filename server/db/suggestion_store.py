# 건의게시판 저장소 — SQLite 기반
import sqlite3
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / 'data' / 'suggestions.db'


def _conn() -> sqlite3.Connection:
  DB_PATH.parent.mkdir(parents=True, exist_ok=True)
  conn = sqlite3.connect(str(DB_PATH))
  conn.row_factory = sqlite3.Row
  conn.execute('PRAGMA journal_mode=WAL')
  conn.execute('''
    CREATE TABLE IF NOT EXISTS suggestions (
      id TEXT PRIMARY KEY,
      agent_id TEXT NOT NULL,
      category TEXT NOT NULL DEFAULT 'general',
      title TEXT NOT NULL,
      content TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'pending',
      response TEXT DEFAULT '',
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    )
  ''')
  # suggestion_type 컬럼 추가 마이그레이션 (prompt/code)
  try:
    conn.execute('ALTER TABLE suggestions ADD COLUMN suggestion_type TEXT DEFAULT "prompt"')
    conn.commit()
  except sqlite3.OperationalError:
    pass  # 이미 존재
  # target_agent — 건의가 적용될 대상 에이전트 (빈 값이면 제안자 본인)
  try:
    conn.execute('ALTER TABLE suggestions ADD COLUMN target_agent TEXT DEFAULT ""')
    conn.commit()
  except sqlite3.OperationalError:
    pass
  # auto_applied — 자동 반영 여부 (0/1), auto_applied_at — 반영 시각 ISO
  try:
    conn.execute('ALTER TABLE suggestions ADD COLUMN auto_applied INTEGER DEFAULT 0')
    conn.commit()
  except sqlite3.OperationalError:
    pass
  try:
    conn.execute('ALTER TABLE suggestions ADD COLUMN auto_applied_at TEXT DEFAULT ""')
    conn.commit()
  except sqlite3.OperationalError:
    pass
  # source_log_id — 건의를 트리거한 원본 message 로그 ID (대시보드에서 발화 추적용)
  try:
    conn.execute('ALTER TABLE suggestions ADD COLUMN source_log_id TEXT DEFAULT ""')
    conn.commit()
  except sqlite3.OperationalError:
    pass
  # 건의 감사 로그 — kind 예: auto_filed/dedup_skipped/review_promoted/auto_applied/
  # rollback/approved/rejected/branch_created/branch_merged/branch_discarded/test_failed
  conn.execute('''
    CREATE TABLE IF NOT EXISTS suggestion_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      suggestion_id TEXT NOT NULL,
      ts TEXT NOT NULL,
      kind TEXT NOT NULL,
      payload TEXT DEFAULT '{}'
    )
  ''')
  conn.execute('CREATE INDEX IF NOT EXISTS idx_events_sid ON suggestion_events(suggestion_id)')
  conn.execute('CREATE INDEX IF NOT EXISTS idx_events_kind ON suggestion_events(kind, ts)')
  conn.commit()
  return conn


def log_event(suggestion_id: str, kind: str, payload: dict | None = None) -> None:
  '''건의 감사 이벤트 기록.'''
  import json as _json
  c = _conn()
  c.execute(
    'INSERT INTO suggestion_events (suggestion_id, ts, kind, payload) VALUES (?, ?, ?, ?)',
    (
      suggestion_id,
      datetime.now(timezone.utc).isoformat(),
      kind,
      _json.dumps(payload or {}, ensure_ascii=False),
    ),
  )
  c.commit()
  c.close()


def list_events(suggestion_id: str = '', limit: int = 200) -> list[dict]:
  '''건의 이벤트 목록 (시계열, 최신순).'''
  import json as _json
  c = _conn()
  if suggestion_id:
    rows = c.execute(
      'SELECT * FROM suggestion_events WHERE suggestion_id=? ORDER BY ts DESC LIMIT ?',
      (suggestion_id, limit),
    ).fetchall()
  else:
    rows = c.execute(
      'SELECT * FROM suggestion_events ORDER BY ts DESC LIMIT ?', (limit,),
    ).fetchall()
  c.close()
  out = []
  for r in rows:
    d = dict(r)
    try:
      d['payload'] = _json.loads(d.get('payload') or '{}')
    except Exception:
      d['payload'] = {}
    out.append(d)
  return out


def count_rollbacks_since(hours: int = 168, target_agent: str | None = None) -> int:
  '''최근 N시간 내 rollback 이벤트 수. target 필터 옵션.'''
  import json as _json
  from datetime import timedelta
  cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
  c = _conn()
  rows = c.execute(
    'SELECT payload FROM suggestion_events WHERE kind=? AND ts>=?',
    ('rollback', cutoff),
  ).fetchall()
  c.close()
  if target_agent is None:
    return len(rows)
  n = 0
  for r in rows:
    try:
      p = _json.loads(r['payload'] or '{}')
      if p.get('target_agent') == target_agent:
        n += 1
    except Exception:
      pass
  return n


# 발언에서 언급된 대상 에이전트를 감지하는 heuristic
_TARGET_PATTERNS: list[tuple[str, list[str]]] = [
  ('planner', ['planner.md', '@기획', '@planner', '기획자', '기획 에이전트', '기획 단계', '기획에서',
               '드러커', '플래너']),
  ('designer', ['designer.md', '@디자인', '@designer', '디자이너', '디자인 에이전트',
                '아이브', 'UX', 'UI 가이드']),
  ('developer', ['developer.md', '@개발', '@developer', '개발자', '개발 에이전트',
                 '튜링', '개발팀']),
  ('qa', ['qa.md', 'QA.md', '@qa', '@QA', 'QA가', 'QA는', 'QA팀', 'QA 기준', 'QA 단계',
          '데밍', '검수자']),
  ('teamlead', ['@팀장', '팀장이', '팀장은', '잡스가', '잡스는']),
]


_DEDUP_STOPWORDS = {
  '건의', '제안', '도입', '적용', '기반', '관련', '활용', '개선', '자동화', '통합',
  '연계', '구축', '시스템', '파일럿', '워크플로우', '워크플로', '방식', '방안', '검수',
  '명세', '기준', '규약', '가이드', '가이드라인', '규칙', '원칙', '표준', '프로세스',
  '관리', '강화', '고도화', '통합', '정의', '추가', '확장', '필요', '수립', '처리',
  '업무', '작업', '산출', '산출물', '체계', '고려', '생각', '논의',
}


def _kw_set(s: str) -> set[str]:
  '''의미 키워드 set — stop word 제외.'''
  import re as _re
  toks = set(_re.findall(r'[A-Za-z][A-Za-z0-9]{2,}|[가-힣]{2,}', s or ''))
  return {t for t in toks if t.lower() not in {x.lower() for x in _DEDUP_STOPWORDS}}


def is_duplicate(title: str, content: str, scope: str = 'all') -> tuple[bool, str]:
  '''새 건의가 기존 건의와 의미상 중복인지 판정.

  scope: 'pending' | 'all' (done/rejected까지 포함).
  반환: (중복여부, 사유 또는 매칭된 기존 id).
  '''
  c = _conn()
  if scope == 'pending':
    rows = c.execute(
      "SELECT id, title, content, status FROM suggestions WHERE status='pending' ORDER BY created_at DESC LIMIT 80"
    ).fetchall()
  else:
    rows = c.execute(
      "SELECT id, title, content, status FROM suggestions ORDER BY created_at DESC LIMIT 80"
    ).fetchall()
  c.close()
  new_kws = _kw_set(f'{title} {content}')
  new_title_kws = _kw_set(title)
  if not new_kws:
    return (False, '')
  for r in rows:
    prev_title = r['title'] or ''
    prev_content = r['content'] or ''
    prev_kws = _kw_set(f'{prev_title} {prev_content}')
    if not prev_kws:
      continue
    overlap = new_kws & prev_kws
    smaller = min(len(new_kws), len(prev_kws))
    ratio = len(overlap) / smaller if smaller else 0
    # 전체 키워드 겹침이 0.45 이상 또는 제목 키워드가 2개 이상 겹치면 중복
    title_overlap = len(new_title_kws & _kw_set(prev_title))
    if len(overlap) >= 3 and ratio >= 0.45:
      return (True, f'{r["id"]}({r["status"]}) keyword_overlap={ratio:.2f}')
    if title_overlap >= 2 and len(new_title_kws) >= 3:
      return (True, f'{r["id"]}({r["status"]}) title_overlap={title_overlap}')
  return (False, '')


_ATTRIBUTION_VERBS = (
  '해라', '해야', '하자', '합시다', '바꿔', '바꾸', '추가', '반영', '도입',
  '적용', '정의', '수정', '개선', '명세', '규칙', '프롬프트', '규약', '기준',
  '의 역할', '에게 적용', '이 적용',
)


def detect_target_agent(message: str, speaker: str = '') -> str:
  '''발언 텍스트에서 적용 대상 에이전트를 추론. 자기 자신/미발견/단순 언급은 빈 문자열.

  단순히 "QA가 지적한대로" 같은 인용 언급은 제외하고, 매치 주변 20자 윈도 안에
  귀속 동사(해라/바꿔/적용/명세 등)가 있을 때만 target으로 확정한다.
  '''
  text = message
  for agent, patterns in _TARGET_PATTERNS:
    if agent == speaker:
      continue
    for p in patterns:
      idx = text.find(p)
      if idx < 0:
        continue
      # 매치 주변 ±20자 윈도
      start = max(0, idx - 20)
      end = min(len(text), idx + len(p) + 20)
      window = text[start:end]
      if any(v in window for v in _ATTRIBUTION_VERBS):
        return agent
      # 귀속 동사 없으면 단순 인용으로 간주, 다음 패턴/에이전트 계속
  return ''


def classify_suggestion_type(title: str, content: str, category: str = 'general') -> str:
  '''건의 내용을 3가지로 분류: 'prompt' | 'rule' | 'code'.

  - prompt: 에이전트 태도/관점 조정 (PromptEvolver 규칙)
  - rule: 프로세스/규약/명세 기준 수립 (PromptEvolver 규칙 — high priority 메타 규칙)
  - code: 실제 Python/TS/yml 파일을 만들거나 고쳐야 함
  '''
  text = f'{title} {content}'.lower()

  # 강한 code 시그널 — 실제 파일 작성·수정·설치가 필수인 경우
  strong_code = [
    '.yml', '.yaml', '.github/workflows', 'github actions',
    '.tsx', '.ts ', '.js ', '.py ', '.mjs',
    'npm install', 'pip install', 'yarn add', '라이브러리 설치',
    '버튼 추가', '페이지 추가', '화면 추가', '컴포넌트 추가',
    '엔드포인트 추가', 'api 구현', 'endpoint 구현',
    '스크립트 작성', '스크립트 추가', 'workflow 파일',
    'websocket', 'webhook', 'sse 구현',
    '데이터베이스 마이그레이션', '스키마 변경',
    '크롤링', '스크래핑', 'mcp 서버 구현',
  ]
  if any(kw in text for kw in strong_code):
    return 'code'

  # rule 시그널 — 규칙/기준/명세/규약 수립 (md 편집 수준)
  rule_keywords = [
    '규칙', '원칙', '가이드라인', '규약', '표준', '기준 정의', '기준 수립',
    '명세화', '명세 작성', '명세 기준', '검수 기준', '평가 기준', '작성 규칙',
    '작성 원칙', '문서화 방식', 'bdd', 'spec-first', 'gherkin 문법',
    '인수 조건', '인수조건', 'acceptance criteria', '완료 기준', '합격 기준',
    '산출물 포맷', '보고서 포맷', '템플릿 정의',
    '프로세스 정의', '프로세스 개선', '워크플로우 정의',
    '사용자 관점', '시나리오 작성',
  ]
  if any(kw in text for kw in rule_keywords):
    return 'rule'

  # 약한 code 시그널 — 파이프라인/자동화 등 인프라 작업
  weak_code = [
    'api', 'endpoint', 'mcp', '도구 추가', '기능 추가', '기능 개발',
    '자동화 도구', '자동 저장', '자동 백업',
    'ci/cd', '파이프라인', 'pipeline', '배포',
    '외부 접근', '파일 시스템', '인증', 'auth', 'oauth',
  ]
  if category in ('도구 부족', '데이터 부족'):
    return 'code'
  if any(kw in text for kw in weak_code):
    return 'code'

  # 기본값: 프롬프트
  return 'prompt'


async def classify_suggestion_type_2stage(title: str, content: str, category: str = 'general') -> str:
  '''2단계 분류: 키워드 결과가 rule이면서 강한 code 시그널도 공존하는 경계 케이스만
  Haiku에 한 번 물어 보수적으로 확정. 호출측은 비동기 문맥일 때 이 함수를 쓴다.'''
  base = classify_suggestion_type(title, content, category)
  text = f'{title} {content}'.lower()
  # 경계: rule + strong_code 잠복 (예: "규칙으로 정하자: 웹훅 엔드포인트 추가")
  suspicious = False
  if base == 'rule':
    borderline = [
      'endpoint', 'webhook', '엔드포인트', 'api 엔드포인트', '라이브러리', '.py', '.ts', '.tsx',
      '워크플로 파일', 'workflow 파일', 'github actions', 'yml',
      '설치', 'install', '구현', '빌드',
    ]
    if any(b in text for b in borderline):
      suspicious = True
  # 경계: code로 분류됐지만 내용이 "규칙"/"명세" 중심이라 rule일 가능성
  elif base == 'code':
    rule_markers = ['규칙', '원칙', '기준', '명세 작성', '인수 조건', '합격 기준', 'acceptance criteria']
    if any(m in text for m in rule_markers) and len(text) < 600:
      suspicious = True
  if not suspicious:
    return base
  try:
    from runners.claude_runner import run_claude_isolated
    prompt = (
      f'건의를 정확히 하나로 분류: prompt | rule | code.\n'
      f'- prompt: 에이전트 태도/관점 변화 (프롬프트 편집)\n'
      f'- rule: 규약·기준·명세 추가 (md 편집 수준)\n'
      f'- code: 실제 파일 생성·수정·라이브러리 설치\n\n'
      f'[제목]\n{title}\n\n[내용]\n{content[:800]}\n\n'
      f'JSON만 출력: {{"type":"prompt|rule|code","reason":"1문장"}}'
    )
    raw = await run_claude_isolated(prompt, model='claude-haiku-4-5-20251001', timeout=15.0)
    import re as _re, json as _json
    m = _re.search(r'\{[\s\S]*?\}', raw)
    if m:
      d = _json.loads(m.group())
      t = (d.get('type') or '').strip()
      if t in ('prompt', 'rule', 'code'):
        return t
  except Exception:
    pass
  # 실패 시 안전한 기본값 — 자동 반영 가능한 prompt로 떨어뜨리지 않고 원 분류 유지
  return base


def create_suggestion(
  agent_id: str,
  title: str,
  content: str,
  category: str = 'general',
  suggestion_type: str | None = None,
  target_agent: str = '',
  status: str = 'pending',
  source_log_id: str = '',
) -> dict:
  '''건의를 등록한다. suggestion_type 미지정 시 자동 분류.
  target_agent가 지정되면 승인 시 해당 에이전트의 PromptEvolver 규칙으로 반영.

  status='draft'면 auto_triage 대상에서 제외 (말로만 한 다짐 완충용).
  source_log_id는 트리거 발화 추적용 (선택).
  '''
  c = _conn()
  suggestion_id = str(uuid.uuid4())[:8]
  now = datetime.now(timezone.utc).isoformat()
  if not suggestion_type:
    suggestion_type = classify_suggestion_type(title, content, category)
  c.execute(
    'INSERT INTO suggestions (id, agent_id, category, title, content, status, created_at, updated_at, suggestion_type, target_agent, source_log_id) '
    'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
    (suggestion_id, agent_id, category, title, content, status, now, now, suggestion_type, target_agent, source_log_id),
  )
  c.commit()
  c.close()
  return {
    'id': suggestion_id, 'agent_id': agent_id, 'category': category,
    'title': title, 'content': content, 'status': status,
    'response': '', 'created_at': now, 'updated_at': now,
    'suggestion_type': suggestion_type, 'target_agent': target_agent,
    'source_log_id': source_log_id,
  }


def promote_draft(suggestion_id: str) -> bool:
  '''draft 상태 건의를 pending으로 승격. 이미 pending이거나 없으면 False.'''
  c = _conn()
  cur = c.execute(
    'UPDATE suggestions SET status="pending", updated_at=? WHERE id=? AND status="draft"',
    (datetime.now(timezone.utc).isoformat(), suggestion_id),
  )
  c.commit()
  ok = cur.rowcount > 0
  c.close()
  return ok


def auto_promote_drafts(stale_hours: int = 24) -> int:
  '''24h 경과한 draft를 pending으로 자동 승격. 승격 건수 반환.'''
  cutoff = (datetime.now(timezone.utc) - timedelta(hours=stale_hours)).isoformat()
  c = _conn()
  cur = c.execute(
    'UPDATE suggestions SET status="pending", updated_at=? WHERE status="draft" AND created_at < ?',
    (datetime.now(timezone.utc).isoformat(), cutoff),
  )
  c.commit()
  n = cur.rowcount
  c.close()
  return n


def get_suggestion(suggestion_id: str) -> dict | None:
  '''건의 단건을 반환한다.'''
  c = _conn()
  row = c.execute('SELECT * FROM suggestions WHERE id = ?', (suggestion_id,)).fetchone()
  c.close()
  return dict(row) if row else None


def list_suggestions(status: str = '') -> list[dict]:
  '''건의 목록을 반환한다.'''
  c = _conn()
  if status:
    rows = c.execute(
      'SELECT * FROM suggestions WHERE status = ? ORDER BY created_at DESC', (status,)
    ).fetchall()
  else:
    rows = c.execute('SELECT * FROM suggestions ORDER BY created_at DESC').fetchall()
  c.close()
  return [dict(r) for r in rows]


def update_suggestion(suggestion_id: str, status: str = '', response: str = '') -> bool:
  '''건의 상태/답변을 업데이트한다.'''
  c = _conn()
  now = datetime.now(timezone.utc).isoformat()
  updates = []
  params = []
  if status:
    updates.append('status = ?')
    params.append(status)
  if response:
    updates.append('response = ?')
    params.append(response)
  if not updates:
    c.close()
    return False
  updates.append('updated_at = ?')
  params.append(now)
  params.append(suggestion_id)
  c.execute(f'UPDATE suggestions SET {", ".join(updates)} WHERE id = ?', params)
  changed = c.total_changes > 0
  c.commit()
  c.close()
  return changed


def delete_suggestion(suggestion_id: str) -> bool:
  '''건의를 삭제한다.'''
  c = _conn()
  c.execute('DELETE FROM suggestions WHERE id = ?', (suggestion_id,))
  changed = c.total_changes > 0
  c.commit()
  c.close()
  return changed

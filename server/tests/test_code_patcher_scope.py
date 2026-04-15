# _check_scope / _parse_declared_files 스코프 가드 테스트
# 자가개선 루프의 유일한 신뢰 경계이므로 우회 경로를 회귀 테스트로 잠근다.

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from improvement.code_patcher import _check_scope, _parse_declared_files


DIFF_SMALL = '1 file changed, 10 insertions(+), 2 deletions(-)'


def test_parse_structured_files_block():
  content = '''요청 내용.
FILES:
  - server/main.py
  - dashboard/src/App.tsx
'''
  assert _parse_declared_files(content) == {'server/main.py', 'dashboard/src/App.tsx'}


def test_parse_korean_header_and_asterisk_bullets():
  content = '''설명
수정 파일:
- server/orchestration/office.py
* package.json
'''
  assert _parse_declared_files(content) == {
    'server/orchestration/office.py', 'package.json',
  }


def test_parse_rejects_inline_mention():
  # 본문에 파일명만 언급돼도 블록이 없으면 선언된 것이 아님
  assert _parse_declared_files('main.py의 로직을 고쳐주세요') == set()


def test_parse_ignores_trailing_comments():
  content = '''FILES:
- server/main.py   # 라우터 개선
- package.json  설명 텍스트
'''
  assert _parse_declared_files(content) == {'server/main.py', 'package.json'}


def test_scope_blocks_forbidden_without_declaration():
  ok, reason = _check_scope(
    {'content': 'main.py 개선해주세요'},
    ['server/main.py'],
    DIFF_SMALL,
  )
  assert ok is False
  assert 'FILES 블록에 미선언' in reason


def test_scope_allows_forbidden_with_explicit_declaration():
  ok, reason = _check_scope(
    {'content': 'FILES:\n- server/main.py\n'},
    ['server/main.py'],
    DIFF_SMALL,
  )
  assert ok is True
  assert reason == ''


def test_scope_allows_non_forbidden_without_declaration():
  ok, _ = _check_scope(
    {'content': '로깅 개선'},
    ['server/log_bus/event_bus.py'],
    DIFF_SMALL,
  )
  assert ok is True


def test_scope_rejects_too_many_files():
  ok, reason = _check_scope(
    {'content': 'x'},
    [f'f{i}.py' for i in range(20)],
    DIFF_SMALL,
  )
  assert ok is False
  assert '한도' in reason


def test_scope_rejects_too_many_lines():
  ok, reason = _check_scope(
    {'content': 'x'},
    ['server/log_bus/event_bus.py'],
    '1 file changed, 600 insertions(+), 10 deletions(-)',
  )
  assert ok is False
  assert '한도' in reason


def test_scope_substring_bypass_no_longer_works():
  # 과거 구현(substring 매칭)에서 통과했을 우회 케이스가 이제 차단되는지 회귀 테스트
  # "main.py"라는 단어가 본문에 있어도 구조화된 FILES 블록이 없으면 차단
  content = '메인 엔트리(main.py)의 라우터 동작을 자연스럽게 개선하는 게 좋겠습니다'
  ok, _ = _check_scope(
    {'content': content},
    ['server/main.py'],
    DIFF_SMALL,
  )
  assert ok is False

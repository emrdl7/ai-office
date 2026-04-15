# _is_stop_command 단어 경계 가드 회귀 테스트.
from orchestration.user_input import _is_stop_command


def test_positive_stop_commands():
  assert _is_stop_command('중단')
  assert _is_stop_command('중단해줘')
  assert _is_stop_command('지금 그만')
  assert _is_stop_command('취소')
  assert _is_stop_command('stop')
  assert _is_stop_command('멈춰')


def test_negated_stop_not_triggered():
  # 부정형은 중단 명령이 아님
  assert not _is_stop_command('중단하지마')
  assert not _is_stop_command('중단하지 마세요')
  assert not _is_stop_command('중단 아님')
  assert not _is_stop_command('취소하지 마')
  assert not _is_stop_command('그만하지 마')
  assert not _is_stop_command("don't stop")


def test_unrelated_message():
  assert not _is_stop_command('진행 상황 공유해줘')
  assert not _is_stop_command('이거 반영해주세요')

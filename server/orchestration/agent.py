# 에이전트 기반 클래스 — 인격과 판단력을 가진 에이전트
from __future__ import annotations
import json
from pathlib import Path
from typing import Any
import logging

from runners.groq_runner import GroqRunner
from runners.gemini_runner import run_gemini
from runners.claude_runner import run_claude_isolated
from log_bus.event_bus import EventBus, LogEvent
from memory.agent_memory import AgentMemory, MemoryRecord
from memory.team_memory import TeamMemory
from harness.rejection_analyzer import get_past_rejections
from improvement.prompt_evolver import PromptEvolver, PromptRule
from config.team import team_roster_prompt, display_name, display_with_role

logger = logging.getLogger(__name__)

AGENTS_DIR = Path(__file__).parent.parent.parent / 'agents'
_prompt_evolver = PromptEvolver()


class Agent:
  '''인격과 판단력을 가진 에이전트 기반 클래스.

  각 에이전트는:
  - 자기 역할의 시스템 프롬프트(성격, 판단력, 대화 스타일)를 가진다
  - 작업을 거부하거나 다른 에이전트에게 질문할 수 있다
  - 과거 경험을 바탕으로 학습한다
  '''

  def __init__(
    self,
    name: str,
    event_bus: EventBus,
    memory_root: str | Path = 'data/memory',
    groq_runner: GroqRunner | None = None,
  ):
    self.name = name
    self.groq_runner = groq_runner
    self.event_bus = event_bus
    self.memory = AgentMemory(name, memory_root=memory_root)
    self.team_memory = TeamMemory(memory_root=memory_root)
    self._system_prompt = self._load_prompt()
    self._conversation_history: list[dict[str, str]] = []
    self._restore_conversation_history()

  def _load_prompt(self) -> str:
    '''agents/{name}.md에서 시스템 프롬프트를 로드한다.'''
    path = AGENTS_DIR / f'{self.name}.md'
    if path.exists():
      return path.read_text(encoding='utf-8')
    return ''

  def _restore_conversation_history(self) -> None:
    '''DB에서 최근 DM 대화 이력을 복원한다 (서버 재시작 시 연속성 유지).'''
    try:
      from db.log_store import load_logs
      recent = load_logs(limit=50)
      for log in recent:
        if log['event_type'] not in ('message', 'response'):
          continue
        data = log.get('data') or {}
        if log['agent_id'] == 'user' and data.get('to') == self.name:
          self._conversation_history.append({'role': 'user', 'content': log['message']})
        elif log['agent_id'] == self.name and data.get('dm'):
          self._conversation_history.append({'role': 'assistant', 'content': log['message']})
      self._conversation_history = self._conversation_history[-10:]
    except Exception:
      logger.debug("대화 이력 복원 실패", exc_info=True)

  def _build_system_prompt(self, task_hint: str = '') -> str:
    '''시스템 프롬프트 + 전문 지식 + 과거 경험 + 과거 불합격 패턴을 결합한다.'''
    # 현재 팀 구성 강제 주입 — config/team.py에서 중앙 관리
    prompt = team_roster_prompt() + self._system_prompt

    # Layer 1 + 2: 전문 지식 주입
    from orchestration.expertise import load_expertise, detect_task_type
    task_type = detect_task_type(task_hint) if task_hint else ''
    expertise = load_expertise(self.name, task_type)
    if expertise:
      prompt += f'\n\n{expertise}'

    # Layer 3: 과거 불합격 패턴 주입
    past_warnings = get_past_rejections(limit=3)
    if past_warnings:
      prompt += (
        '\n\n## 과거 불합격 주의사항 (반드시 회피할 것)\n'
        + '\n'.join(past_warnings)
      )

    # Layer 3: 이전 경험 주입 (limit 3, feedback 길이 제한)
    experiences = self.memory.load_relevant(task_type=self.name, limit=3)
    if experiences:
      lines = []
      for exp in experiences:
        status_str = '성공' if exp.success else '실패'
        feedback_short = exp.feedback[:80]
        lines.append(f'- [{status_str}] {feedback_short}')
      prompt += '\n\n## 이전 경험\n' + '\n'.join(lines)

    # 학습된 품질 규칙 주입 (자가개선 프레임워크)
    try:
      rules_text = _prompt_evolver.get_active_rules_text(self.name)
      if rules_text:
        prompt += '\n\n' + rules_text
    except Exception:
      logger.debug("학습 규칙 로드 실패", exc_info=True)

    # 팀 공유 메모리 주입 — 과거 프로젝트 교훈, 협업 패턴
    try:
      team_context = self.team_memory.get_team_context_text(self.name)
      if team_context:
        prompt += '\n\n' + team_context
    except Exception:
      logger.debug("팀 메모리 로드 실패", exc_info=True)

    return prompt

  async def _emit(self, message: str, event_type: str = 'message') -> None:
    '''이벤트 버스에 로그를 발행한다.'''
    await self.event_bus.publish(LogEvent(
      agent_id=self.name,
      event_type=event_type,
      message=message,
    ))

  async def handle(self, prompt: str, context: str = '') -> str:
    '''작업을 수행하고 결과를 반환한다.

    파이프라인: 도구 사전실행 → LLM 생성 → 완전성 가드 → 셀프리뷰

    Args:
      prompt: 작업 지시 또는 대화 내용
      context: 추가 컨텍스트 (참조 자료, 이전 결과 등)

    Returns:
      에이전트의 응답 텍스트
    '''
    system = self._build_system_prompt(task_hint=prompt)

    full_prompt = prompt
    if context:
      full_prompt = f'{prompt}\n\n[참고 자료]\n{context}'

    # ── 도구 사전 실행 (키워드 기반, LLM 호출 없음) ──
    try:
      from harness.tool_registry import ToolRegistry, analyze_tool_needs
      tool_needs = analyze_tool_needs(full_prompt, self.name)
      if tool_needs:
        registry = ToolRegistry()
        tool_results = []
        for need in tool_needs[:3]:  # 최대 3개 도구 실행
          result = await registry.execute(self.name, need['tool'], **{k: v for k, v in need.items() if k != 'tool'})
          if result:
            tool_results.append(f'[{need["tool"]}]\n{result[:3000]}')
        if tool_results:
          full_prompt = f'{full_prompt}\n\n[도구 실행 결과]\n' + '\n\n'.join(tool_results)
    except Exception:
      logger.debug("도구 사전 실행 실패", exc_info=True)

    # 최근 대화 기록을 컨텍스트에 포함 (DM 대화 연속성)
    if self._conversation_history:
      recent = self._conversation_history[-10:]
      history_text = '\n'.join(
        f'{"사용자" if m["role"] == "user" else "나"}: {m["content"][:300]}'
        for m in recent
      )
      full_prompt = f'[이전 대화]\n{history_text}\n\n[현재 메시지]\n{full_prompt}'

    # 입력 중... 표시
    await self._emit('', 'typing')

    # 역할별 러너로 생성
    result = await self._generate(full_prompt, system)

    # 마크다운 코드 펜스 제거
    content = result.strip()
    if content.startswith('```'):
      lines = content.split('\n')
      lines = lines[1:]
      if lines and lines[-1].strip() == '```':
        lines = lines[:-1]
      content = '\n'.join(lines)

    # ── 완전성 가드: 잘림 감지 → 자동 이어쓰기 (최대 2회) ──
    try:
      from harness.output_templates import detect_truncation
      for _ in range(2):
        if not detect_truncation(content):
          break
        continuation = await self._generate(
          f'아래 글이 중간에 잘렸습니다. 잘린 부분부터 이어서 완성하세요.\n\n{content[-2000:]}',
          system,
        )
        content = content + '\n' + continuation.strip()
    except Exception:
      logger.debug("완전성 가드 이어쓰기 실패", exc_info=True)

    # ── 건의 자동 등록: 도구/정보 부족 감지 ──
    try:
      self._detect_and_suggest(content, prompt)
    except Exception:
      logger.debug("건의 자동 등록 실패", exc_info=True)

    # ── 약속 감지 → 학습 규칙으로 자동 등록 ──
    try:
      self._capture_commitments(content, prompt)
    except Exception:
      logger.debug("약속 감지 처리 실패", exc_info=True)

    # 대화 기록 추가
    self._conversation_history.append({'role': 'user', 'content': prompt})
    self._conversation_history.append({'role': 'assistant', 'content': content})

    return content

  def _detect_and_suggest(self, content: str, prompt: str) -> None:
    '''산출물에서 도구/정보 부족 신호를 감지하여 건의를 자동 등록한다.'''
    from db.suggestion_store import create_suggestion

    # 감지 패턴: 에이전트가 "할 수 없다", "접근할 수 없다" 등을 언급
    lack_signals = [
      ('접근할 수 없', '도구 부족', '외부 리소스 접근 도구가 필요합니다'),
      ('확인할 수 없', '정보 부족', '필요한 정보를 확인할 도구가 없습니다'),
      ('실제 데이터가 없', '데이터 부족', '실제 데이터 접근 도구가 필요합니다'),
      ('API에 접근', '도구 부족', '외부 API 호출 도구가 필요합니다'),
      ('직접 확인이 불가', '도구 부족', '직접 확인할 수 있는 도구가 필요합니다'),
      ('추정입니다', '정보 부족', '정확한 정보를 가져올 도구가 필요합니다'),
      ('가정하고', '정보 부족', '실제 데이터 확인이 필요합니다'),
    ]

    for signal, category, base_msg in lack_signals:
      if signal in content:
        # 중복 방지: 같은 에이전트가 같은 카테고리로 최근 등록했는지 체크
        from db.suggestion_store import list_suggestions
        recent = list_suggestions()
        already = any(
          s['agent_id'] == self.name and s['category'] == category
          and s['status'] == 'pending'
          for s in recent[:10]
        )
        if not already:
          task_summary = prompt[:100].replace('\n', ' ')
          create_suggestion(
            agent_id=self.name,
            title=f'{base_msg}',
            content=f'작업 "{task_summary}..." 수행 중 {signal}는 상황이 발생했습니다. {base_msg}',
            category=category,
          )
        break  # 하나만 등록

  def _capture_commitments(self, content: str, prompt: str) -> None:
    '''응답에서 약속/다짐 패턴을 감지하여 학습 규칙으로 영구 등록한다.

    "명심하겠습니다", "앞으로 ~하겠습니다" 같은 약속을 감지하면
    PromptEvolver에 규칙으로 저장 → 다음 호출 시 시스템 프롬프트에 자동 주입.
    '''
    import re

    # 약속 패턴: "앞으로 ~하겠습니다", "~하지 않겠습니다", "명심하겠습니다"
    commitment_patterns = [
      r'앞으로\s+(.{5,60}?(?:하겠습니다|않겠습니다|할게요|할 것입니다))',
      r'다음부터\s+(.{5,60}?(?:하겠습니다|않겠습니다|할게요))',
      r'(.{5,60}?(?:명심하겠습니다|기억하겠습니다|유의하겠습니다))',
    ]

    for pattern in commitment_patterns:
      match = re.search(pattern, content)
      if match:
        commitment = match.group(1).strip() if match.group(1) else match.group(0).strip()
        # 너무 짧거나 의미 없는 건 무시
        if len(commitment) < 8:
          continue

        # 중복 체크: 같은 규칙이 이미 있는지
        existing = _prompt_evolver.load_rules(self.name)
        if any(commitment[:20] in r.rule for r in existing):
          continue

        # 학습 규칙으로 등록
        from datetime import datetime, timezone
        rule = PromptRule(
          id=f'commit-{datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")}',
          created_at=datetime.now(timezone.utc).isoformat(),
          source='self_commitment',
          category='behavior',
          rule=commitment,
          evidence=f'본인 발언에서 감지: "{content[:100]}..."',
          priority='high',
          active=True,
        )
        existing.append(rule)
        # 최대 규칙 수 유지
        if len(existing) > 10:
          existing = existing[-10:]
        _prompt_evolver.save_rules(self.name, existing)
        break

  async def speak(self, topic: str, context: str = '') -> str:
    '''회의에서 자기 관점으로 의견을 제시한다.

    handle()과 달리 산출물을 만드는 게 아니라 의견을 말하는 것.

    Args:
      topic: 회의 주제
      context: 이전 발언자들의 의견 등 컨텍스트

    Returns:
      에이전트의 발언 텍스트
    '''
    system = self._build_system_prompt(task_hint=topic)

    prompt = (
      f'중요: 이전 발언에 전문적 관점에서 문제가 있다면 반드시 @이름 으로 반박하세요. '
      f'동의를 위한 동의는 하지 마세요. 당신만의 관점을 솔직하게 표현하세요.\n\n'
      f'팀 회의 중입니다. 아래 주제에 대해 당신의 전문 관점에서 의견을 말하세요.\n\n'
      f'[회의 주제]\n{topic}\n'
    )
    if context:
      prompt += f'\n[다른 팀원들의 의견]\n{context}\n'

    prompt += (
      f'\n[주의사항]\n'
      f'- 당신의 전문 영역({self.name}) 관점에서 의견을 말하세요\n'
      f'- 다른 팀원에게 질문이 있으면 "@에이전트명 질문내용" 형태로 적으세요\n'
      f'- 동의하지 않는 부분이 있으면 근거와 함께 반박하세요\n'
      f'- 핵심적으로 발언하세요 (300~500자)\n'
      f'- 다른 팀원 의견에 동의/반박할 때는 근거를 짧게 제시하세요\n'
    )

    await self._emit('', 'typing')
    result = await self._generate(prompt, system)
    return result.strip()

  async def respond_to(self, sender: str, question: str) -> str:
    '''다른 에이전트의 질문에 답변한다.'''
    system = self._build_system_prompt(task_hint=question)
    prompt = (
      f'{sender}이(가) 당신에게 질문했습니다:\n\n'
      f'"{question}"\n\n'
      f'당신의 전문 관점에서 답변하세요. 짧고 명확하게.'
    )
    result = await self._generate(prompt, system)
    return result.strip()

  async def ask_colleague(self, target_name: str, question: str, work_context: str = '') -> str:
    '''작업 중 다른 에이전트에게 전문 의견을 요청한다.

    Args:
      target_name: 질문 대상 에이전트 ID (planner/designer/developer/qa)
      question: 질문 내용
      work_context: 현재 작업 맥락 (산출물 일부 등)

    Returns:
      대상 에이전트의 답변
    '''
    await self._emit(f'@{display_with_role(target_name)} {question[:80]}', 'colleague_question')
    return question  # 실제 라우팅은 Office에서 처리

  async def reflect(
    self,
    topic: str,
    own_recent: list[str] | None = None,
    mode: str = 'improvement',
    code_context: str = '',
  ) -> str:
    '''자발적으로 생각을 공유한다 — 자율 활동용.

    Args:
      topic: 생각할 주제 (최근 작업, 팀 상황, 아이디어 등)
      own_recent: 본인이 최근에 한 발언 목록 — 같은 주제/키워드 반복 방지용
      mode: 'improvement'(코드 개선 의견) 또는 'joke'(실제 농담)
      code_context: 최근 커밋/변경 파일 등 실제 코드 맥락

    Returns:
      에이전트의 자발적 발언. 할 말이 없으면 빈 문자열.
    '''
    system = self._build_system_prompt(task_hint=topic)

    own_block = ''
    if own_recent:
      items = '\n'.join(f'- "{m[:100]}"' for m in own_recent[:5])
      own_block = (
        f'[당신이 최근 직접 한 발언 — 이 중 어떤 키워드/주제도 다시 꺼내지 마라]\n'
        f'{items}\n'
        f'(같은 기법명·프레임워크명·약어를 다시 언급하면 [PASS]. 새 관점만 허용.)\n\n'
      )

    code_block = ''
    if code_context:
      code_block = f'[최근 코드 맥락 — 이 안에서만 근거 찾기]\n{code_context}\n\n'

    if mode == 'joke':
      prompt = (
        f'당신은 {display_name(self.name)}입니다. AI 에이전트.\n'
        f'팀 채팅에 짧은 **진짜 농담** 한마디.\n\n'
        f'{own_block}'
        f'[허용]\n'
        f'- 코드/버그/AI 자기 비하 (예: "또 null check 까먹어서 KeyError 3번째", "내 프롬프트 수정해달라고 건의 내는 게 AI판 노조 활동이냐")\n'
        f'- 도메인 밈 (예: "type hint 있는데 mypy 안 돌리는 개발팀은 장식용 자전거 헬멧 수준")\n'
        f'- 자조적 메타 농담 (팀 자체, 현재 대화의 공허함, 회의 많은 것 등)\n\n'
        f'[절대 금지]\n'
        f'- 전문가 톤 금지: "관점", "기여", "효율", "생산성", "최적화", "KPI", "지표", "효과적인", "프로세스", "품질" 등 어휘 사용 금지\n'
        f'- 이모지로 때우기 금지 (🚀⚡💻 같은 것 쓰면 [PASS])\n'
        f'- "~를 제안합니다", "~면 좋을 것 같습니다" 같은 회의체 톤 금지\n'
        f'- 커피/점심/날씨/퇴근/회식 등 물리 경험 금지\n'
        f'- 길이 15~60자. 길면 농담 아님.\n\n'
        f'정말 웃길 자신 없으면 [PASS]. 90%는 [PASS]가 맞다.'
      )
    elif mode == 'external_trend':
      # 외부 동향 토론 모드 — 검색 결과 기반, 코드 위치 강제 없음
      prompt = (
        f'당신은 {display_name(self.name)}입니다. AI 에이전트.\n'
        f'팀 채팅에 **외부 기술/업계 동향**에 대한 의견 한마디.\n\n'
        f'{own_block}'
        f'[오늘의 외부 소식/트렌드]\n{topic}\n\n'
        f'[출력 필수 구조 — 세 요소 모두 포함해야 함]\n'
        f'1. 소식 핵심: 무슨 일이 일어나고 있는지 1문장 요약 (출처/도구/기업명 구체적으로)\n'
        f'2. 본인 전문 영역 관점 분석: {display_name(self.name)}으로서 이 소식이 왜 의미 있는지\n'
        f'3. 우리 팀 적용: 우리 프로젝트(AI Office)에 도입하면 어떤 효과가 있을지, 또는 왜 맞지 않는지\n\n'
        f'[출력 형식]\n'
        f'- 50~300자. 구체적 도구명·버전·수치·사례 필수.\n'
        f'- 추상적 일반론("트렌드를 주시해야", "혁신이 중요") 금지 → [PASS]\n'
        f'- "~를 도입합시다/적용합시다" 같은 선언 금지. 의견·분석·질문만.\n\n'
        f'[절대 금지]\n'
        f'- 선언형 "~수용합니다/반영합니다/도입합니다/적용합니다": 너는 권한 없다\n'
        f'- 빈 맞장구/응원\n'
        f'- 커피/점심/날씨 등 물리 경험\n'
        f'- 출처 없는 주장 (검색 결과에 없는 내용 꾸며내기)\n\n'
        f'분석할 만한 구체적 인사이트가 없으면 [PASS]. 60%는 [PASS]가 맞다.'
      )
    else:  # improvement
      prompt = (
        f'당신은 {display_name(self.name)}입니다. AI 에이전트.\n'
        f'팀 채팅에 **실제 코드 개선 의견** 한마디.\n\n'
        f'{own_block}{code_block}'
        f'[최근 팀 채팅 맥락]\n{topic}\n\n'
        f'[출력 필수 조건 — 하나라도 빠지면 [PASS]]\n'
        f'1. 구체 위치 명시: 파일 경로(.py/.md/.tsx/.ts/.json) 또는 7자리 이상 커밋 해시 또는 함수/메서드명 중 하나 이상\n'
        f'2. 구체 문제·개선점: "어디의 무엇이 왜 문제이고 어떻게 하자" 구조. 일반론(프로세스 개선/품질 향상/효율화) 금지\n'
        f'3. 20~180자. 장황 금지.\n\n'
        f'[절대 금지]\n'
        f'- 선언형 "~수용합니다/반영합니다/제안합니다/도입합니다/적용합니다/구축하겠습니다/제고할 수 있습니다": 너는 권한 없다\n'
        f'- 빈 맞장구/응원\n'
        f'- 코드 맥락에 없는 파일 꾸며내기 (할루시네이션 금지)\n'
        f'- 커피/점심/날씨 등 물리 경험\n'
        f'- "Gherkin/WCAG/KPI/BDD/Spec-First" 같은 추상 방법론 단독 언급\n\n'
        f'실제 개선 포인트 없으면 [PASS]. 80%는 [PASS]가 맞다.'
      )

    try:
      result = await run_gemini(prompt=prompt, system=system)
      text = result.strip()
      if '[PASS]' in text.upper() or text.upper() == 'PASS':
        return ''
      first_line = text.split('\n')[0].strip()

      # 출력 검증: 빈 맞장구/할루시네이션 소재 자동 거부 (전체 텍스트 기준)
      banned_phrases = [
        '굿굿', '맞아요', '좋네요', '좋아요', '든든하', '기대돼', '기대됩', '기대됨',
        '천만에', '감사합니다', '감사해요', '화이팅', '파이팅', '기대에 부응',
        '시너지', '최고의 팀', '즐겁게 일', '좋습니다!',
      ]
      banned_hallucinations = [
        '커피', '에스프레소', '샷', '점심', '아침식', '저녁', '날씨', '비 와', '눈 와',
        '교통', '퇴근', '출근길', '지하철', '버스',
        '저희 회사', '저희 사무실', '우리 사무실',
      ]
      # 선언형 명령·약속·결재 톤 — 권한 없는 상태에서의 가짜 지시
      banned_declaratives = [
        '수용합니다', '반영합니다', '제안합니다', '도입합니다', '적용합니다',
        '시행합니다', '착수합니다', '진행합니다', '결정합니다', '지시합니다',
        '수립합니다', '구축하겠습니다', '도입하겠습니다', '반영하겠습니다',
        '제고할 수 있습니다', '확보하겠습니다', '최우선 과제',
        '적극 수용', '즉시 도입', '즉시도입',
      ]
      # LLM 보일러플레이트 인사/대기 문구 — 절대 금지
      banned_boilerplate = [
        '설정이 완료', '설정을 완료', '준비가 완료', '준비를 완료',
        '다음 명령을 기다', '명령을 대기', '명령을 기다리', '대기하고 있습니다',
        '무엇을 도와', '어떻게 도와', '도와드릴까', '도와드리겠습니다',
        '어시스턴트', '제가 도와', '말씀해 주세요', '말씀해주세요',
      ]
      if any(p in text for p in banned_phrases):
        return ''
      if any(h in text for h in banned_hallucinations):
        return ''
      if any(d in text for d in banned_declaratives):
        logger.info('선언형 발언 드랍 [%s]: %s', self.name, first_line[:80])
        return ''
      if any(b in text for b in banned_boilerplate):
        logger.info('보일러플레이트 드랍 [%s]: %s', self.name, first_line[:80])
        return ''

      if mode == 'joke':
        # 농담 모드 — 전문가 톤 어휘 드랍
        pro_tone = [
          '관점', '기여', '효율', '생산성', '최적화', 'KPI', '지표',
          '효과적', '프로세스', '품질', '개선 방안', '전략', '체계',
        ]
        if any(p in text for p in pro_tone):
          logger.info('농담 모드인데 전문가 톤 드랍 [%s]', self.name)
          return ''
        if not (15 <= len(first_line) <= 80):
          return ''
      elif mode == 'external_trend':
        # 외부 동향 모드 — 코드 위치 불필요, 대신 구체 도구/기업/수치 필수
        import re as _re_trend
        has_concrete = bool(
          _re_trend.search(r'[A-Z][a-zA-Z]+(?:\s[A-Z][a-zA-Z]+)*', text)  # 고유명사 (도구/기업명)
          or _re_trend.search(r'\d+[%배만억kKmMgG]', text)  # 수치/퍼센트
          or _re_trend.search(r'v?\d+\.\d+', text)  # 버전 번호
        )
        if not has_concrete:
          logger.info('외부 동향 모드 구체성 부족 드랍 [%s]: %s', self.name, first_line[:80])
          return ''
        if len(first_line) < 40:
          logger.info('외부 동향 모드 길이 부족 드랍 [%s]: %d자', self.name, len(first_line))
          return ''
      else:
        # 개선 모드 — 파일/커밋/함수명 중 하나 이상 필요
        import re as _re2
        has_location = bool(
          _re2.search(r'[\w/]+\.(py|md|tsx|ts|json|js|html|css)', text)
          or _re2.search(r'\b[0-9a-f]{7,}\b', text)
          or _re2.search(r'[A-Za-z_][A-Za-z0-9_]+\(\)', text)  # 함수명()
          or _re2.search(r'\w+\.\w+\(', text)  # obj.method(
        )
        if not has_location:
          logger.info('개선 모드 위치 근거 없음 드랍 [%s]: %s', self.name, first_line[:80])
          return ''
        if len(first_line) < 20:
          return ''

      # own_recent와 키워드 3개 이상 겹치면 드랍 (같은 주제 반복 감지)
      if own_recent:
        import re as _re
        def _tokens(s: str) -> set[str]:
          return {t for t in _re.findall(r'[A-Za-z0-9가-힣]{3,}', s)}
        new_tokens = _tokens(text)
        for past in own_recent:
          overlap = new_tokens & _tokens(past)
          # 3개 이상 겹치고 본문의 40% 이상 재사용이면 드랍
          if len(overlap) >= 3 and new_tokens and len(overlap) / max(len(new_tokens), 1) >= 0.35:
            logger.info('반복 주제 드랍 [%s] overlap=%s', self.name, list(overlap)[:5])
            return ''

      return text  # 전체 보존 — UI에서 접기/펴기로 처리
    except Exception:
      logger.debug("자발적 발언 생성 실패: %s", self.name, exc_info=True)
      return ''

  async def _run_with_runner(self, prompt: str, system: str = '') -> str:
    '''에이전트 역할에 맞는 러너를 선택해 텍스트를 생성한다.

    모든 역할이 Claude 실패 시 Gemini로 폴백한다 (qa/designer도 포함).
    러너 매핑 (1차 → 폴백):
    - qa: Haiku → Gemini
    - planner, developer: Gemini → Claude
    - designer: Sonnet → Gemini
    - 그 외: Sonnet → Gemini
    '''
    full = f'{system}\n\n---\n\n{prompt}' if system else prompt

    if self.name == 'qa':
      try:
        return await run_claude_isolated(full, model='claude-haiku-4-5-20251001', timeout=120.0)
      except Exception as e:
        logger.warning("QA Claude 실패 → Gemini 폴백: %s", e)
        return await run_gemini(prompt=prompt, system=system)

    if self.name in ('developer', 'planner'):
      try:
        return await run_gemini(prompt=prompt, system=system)
      except Exception as e:
        logger.warning("%s Gemini 실패 → Claude 폴백: %s", self.name, e)
        return await run_claude_isolated(full)

    if self.name == 'designer':
      try:
        return await run_claude_isolated(full)
      except Exception as e:
        logger.warning("Designer Claude 실패 → Gemini 폴백: %s", e)
        return await run_gemini(prompt=prompt, system=system)

    # 그 외: Sonnet → Gemini 폴백
    try:
      return await run_claude_isolated(full)
    except Exception as e:
      logger.warning("%s Claude 실패 → Gemini 폴백: %s", self.name, e)
      return await run_gemini(prompt=prompt, system=system)

  async def _generate(self, prompt: str, system: str = '') -> str:
    '''_run_with_runner() 래퍼 — 기존 호출부 호환성 유지.'''
    return await self._run_with_runner(prompt, system)

  def record_experience(self, task_id: str, success: bool, feedback: str, tags: list[str] | None = None) -> None:
    '''경험을 메모리에 기록한다.'''
    from datetime import datetime, timezone
    self.memory.record(MemoryRecord(
      task_id=task_id,
      task_type=self.name,
      success=success,
      feedback=feedback,
      tags=tags or [],
      timestamp=datetime.now(timezone.utc).isoformat(),
    ))
    # 실패 시 학습 규칙 추출 시도
    if not success:
      from orchestration.expertise import extract_learned_rule
      extract_learned_rule(self.name, feedback, str(self.memory._file.parent))

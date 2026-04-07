# 오케스트레이션 루프 — 전체 워크플로우 상태 머신 (ORCH-01, ORCH-04, WKFL-02)
from __future__ import annotations
# Claude 분석 → 기획자 → 작업자 → QA → Claude 최종검증 → 보완 루프
import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from orchestration.task_graph import TaskGraph, TaskNode, TaskStatus
from orchestration.router import MessageRouter
from runners.claude_runner import run_claude_isolated
from runners.opencode_runner import run_opencode
from bus.message_bus import MessageBus
from bus.schemas import AgentMessage
from bus.payloads import TaskRequestPayload, TaskResultPayload
from log_bus.event_bus import EventBus, LogEvent
from workspace.manager import WorkspaceManager
from memory.agent_memory import AgentMemory, MemoryRecord
from harness.file_reader import resolve_references
from harness.code_runner import run_code
from harness.rejection_analyzer import record_rejection, get_past_rejections
from harness.stitch_client import designer_generate_with_context

# 에이전트 시스템 프롬프트 파일 디렉토리 (프로젝트 루트 agents/)
AGENTS_DIR = Path(__file__).parent.parent.parent / "agents"


class WorkflowState(str, Enum):
    """오케스트레이션 워크플로우 상태 열거형"""

    IDLE = "idle"  # 초기 대기 상태
    CLAUDE_ANALYZING = "claude_analyzing"  # Claude 사용자 지시 분석 중
    PLANNER_PLANNING = "planner_planning"  # 기획자 태스크 분해 중
    WORKER_EXECUTING = "worker_executing"  # 작업자 태스크 실행 중
    QA_REVIEWING = "qa_reviewing"  # QA 게이트 검수 중
    CLAUDE_FINAL_VERIFYING = "claude_final_verifying"  # Claude 최종 검증 중
    REVISION_LOOPING = "revision_looping"  # 보완 루프 — 재기획 진입 전
    COMPLETED = "completed"  # 워크플로우 완료
    ESCALATED = "escalated"  # 최대 반복 횟수 초과 에스컬레이션


class OrchestrationLoop:
    """전체 워크플로우 상태 머신.

    Claude 분석 → 기획자 → 작업자 → QA → Claude 최종검증 → 보완 루프의
    전체 흐름을 상태 머신으로 관리한다.

    MAX_REVISION_ROUNDS 초과 시 ESCALATED 상태로 전환하여 루프를 종료한다 (D-11, D-12).
    """

    MAX_REVISION_ROUNDS = 3  # 최대 보완 반복 횟수 (D-11, D-12)

    def __init__(
        self,
        bus: MessageBus,
        event_bus: EventBus,
        workspace: WorkspaceManager,
        router: MessageRouter,
        memory_root: str | Path = "data/memory",
    ):
        self.bus = bus
        self.event_bus = event_bus
        self.workspace = workspace
        self.router = router
        self._state = WorkflowState.IDLE
        self._revision_count = 0
        self._task_graph: TaskGraph | None = None
        self._memory_root = Path(memory_root)
        self._last_verify_feedback = ""
        self._reference_context = ""

    async def _emit_status(self, state: WorkflowState) -> None:
        """상태 변경 이벤트를 이벤트 버스에 발행한다"""
        await self.event_bus.publish(
            LogEvent(
                agent_id="orchestrator",
                event_type="status_change",
                message=f"상태: {state.value}",
                data={"state": state.value},
            )
        )

    async def _emit_log(
        self, agent_id: str, message: str, event_type: str = "message"
    ) -> None:
        """작업 진행 로그를 이벤트 버스에 발행한다"""
        await self.event_bus.publish(
            LogEvent(
                agent_id=agent_id,
                event_type=event_type,
                message=message,
            )
        )

    def _load_agent_prompt(self, agent_name: str) -> str:
        """agents/{agent_name}.md 파일을 읽어 시스템 프롬프트를 반환한다.

        파일이 없을 경우 빈 문자열을 반환한다.
        """
        prompt_path = AGENTS_DIR / f"{agent_name}.md"
        if prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8")
        return ""

    async def run(self, user_instruction: str) -> WorkflowState:
        """전체 오케스트레이션 루프를 실행한다.

        상태 전이 순서:
        1. IDLE → CLAUDE_ANALYZING: Claude 지시 분석
        2. CLAUDE_ANALYZING → PLANNER_PLANNING: 기획자 태스크 분해
        3. PLANNER_PLANNING → WORKER_EXECUTING: 작업자 태스크 실행
        4. WORKER_EXECUTING → QA_REVIEWING: QA 게이트 검수
        5. QA_REVIEWING → CLAUDE_FINAL_VERIFYING (all_done()) 또는 재작업
        6. CLAUDE_FINAL_VERIFYING → COMPLETED | REVISION_LOOPING
        7. REVISION_LOOPING: MAX 초과 시 ESCALATED, 아니면 PLANNER_PLANNING 재진입

        Returns:
            최종 WorkflowState (COMPLETED 또는 ESCALATED)
        """
        self._task_graph = TaskGraph()
        self._user_instruction = user_instruction

        # 0. 파일 참조 해석 — 경로가 있으면 파일 내용을 읽어옴
        self._reference_context = resolve_references(user_instruction)
        if self._reference_context:
            await self._emit_log(
                "system",
                f"참조 파일을 읽었습니다. ({len(self._reference_context)}자)",
                "message",
            )

        # 1. IDLE → CLAUDE_ANALYZING
        self._state = WorkflowState.CLAUDE_ANALYZING
        await self._emit_status(self._state)
        await self._emit_log(
            "claude", f"팀장이 지시를 분석합니다: {user_instruction}", "task_start"
        )
        self._claude_analysis = await self.analyze_instruction(user_instruction)
        await self._emit_log(
            "claude", "지시 분석 완료. 기획자에게 방향을 전달합니다.", "task_end"
        )

        # 2. 기획자 태스크 분배
        self._state = WorkflowState.PLANNER_PLANNING
        await self._emit_status(self._state)
        await self._emit_log("planner", "기획자가 태스크를 분해합니다...", "task_start")
        await self._run_planner()
        task_count = len(self._task_graph._nodes)
        await self._emit_log("planner", f"태스크 {task_count}개 생성 완료.", "task_end")

        # 3. 작업자 실행 + QA 중간검수
        self._state = WorkflowState.WORKER_EXECUTING
        await self._emit_status(self._state)

        worker_results: dict[str, str] = {}

        while True:
            ready = self._task_graph.ready_tasks()
            if not ready:
                break
            for node in ready:
                self._task_graph.update_status(node.task_id, TaskStatus.PROCESSING)
                await self._emit_log(
                    node.assigned_to,
                    f"[{node.assigned_to}] 작업 시작: {node.description}",
                    "task_start",
                )
                result = await self._run_agent(node)
                summary = result.summary if result else "응답 없음"
                await self._emit_log(
                    node.assigned_to,
                    f"[{node.assigned_to}] 작업 완료: {summary}",
                    "task_end",
                )

                # 작업자 결과 수집
                if result and result.status == "success":
                    worker_results[node.task_id] = (
                        f"[{node.assigned_to}] {node.description}\n결과: {result.summary}\n"
                    )
                    for fpath in result.artifact_paths:
                        try:
                            full = (
                                self.workspace.task_dir / fpath.split("/", 1)[-1]
                                if "/" in fpath
                                else self.workspace.task_dir / fpath
                            )
                            if full.exists():
                                worker_results[node.task_id] += (
                                    f"\n--- {fpath} ---\n{full.read_text(errors='replace')[:2000]}\n"
                                )
                        except Exception:
                            pass

                # 4. QA 중간검수 + 보완 루프
                self._state = WorkflowState.QA_REVIEWING
                await self._emit_status(self._state)
                await self._emit_log(
                    "qa", f"[QA] {node.task_id} 검수 시작", "task_start"
                )
                qa_passed = await self._run_qa_gate(node)
                await self._emit_log(
                    "qa",
                    f"[QA] {node.task_id} 검수: {'합격' if qa_passed else '불합격'}",
                    "task_end",
                )

                if not qa_passed:
                    # 보완 요청 (최대 2회)
                    for retry in range(1, 3):
                        await self._emit_log(
                            node.assigned_to,
                            f"[{node.assigned_to}] 보완 시도 {retry}/2: {node.failure_reason}",
                            "task_start",
                        )
                        # 이전 산출물 내용을 읽어서 "이걸 이렇게 수정하라"고 구체적으로 전달
                        prev_content = ""
                        for fpath in node.artifact_paths:
                            try:
                                full = (
                                    self.workspace.task_dir / fpath.split("/", 1)[-1]
                                    if "/" in fpath
                                    else self.workspace.task_dir / fpath
                                )
                                if full.exists():
                                    prev_content = full.read_text(errors="replace")[
                                        :3000
                                    ]
                            except Exception:
                                pass
                        node.description = (
                            f"{node.requirements}\n\n"
                            f"[이전 제출물]\n{prev_content[:2000]}\n\n"
                            f"[QA 불합격 사유]\n{node.failure_reason}\n\n"
                            f"위 불합격 사유를 반영하여 이전 제출물을 수정·보완하세요. 요약하지 말고 상세하게 작성하세요."
                        )
                        self._state = WorkflowState.WORKER_EXECUTING
                        result = await self._run_agent(node)
                        if result and result.status == "success":
                            worker_results[node.task_id] = (
                                f"[{node.assigned_to}] 보완완료: {result.summary}\n"
                            )
                        await self._emit_log(
                            node.assigned_to,
                            f"[{node.assigned_to}] 보완 완료",
                            "task_end",
                        )
                        self._state = WorkflowState.QA_REVIEWING
                        qa_passed = await self._run_qa_gate(node)
                        await self._emit_log(
                            "qa",
                            f"[QA] 재검수: {'합격' if qa_passed else '불합격'}",
                            "message",
                        )
                        if qa_passed:
                            break

                if qa_passed:
                    self._task_graph.update_status(node.task_id, TaskStatus.DONE)
                else:
                    self._task_graph.update_status(
                        node.task_id,
                        TaskStatus.FAILED,
                        failure_reason=node.failure_reason,
                    )

                self._state = WorkflowState.WORKER_EXECUTING

        # 5. 기획자 취합 → 최종 산출물
        if worker_results:
            self._state = WorkflowState.PLANNER_PLANNING
            await self._emit_status(self._state)
            await self._emit_log(
                "planner",
                f"기획자가 {len(worker_results)}개 결과를 취합합니다...",
                "task_start",
            )
            await self._run_planner_synthesize(worker_results)
            await self._emit_log("planner", "최종 산출물 작성 완료.", "task_end")

        # 6. Claude 최종검증 (1회만 — 취합 결과물만 검수)
        self._state = WorkflowState.CLAUDE_FINAL_VERIFYING
        await self._emit_status(self._state)
        await self._emit_log(
            "claude", "팀장이 최종 산출물을 검수합니다...", "task_start"
        )
        passed = await self._claude_final_verify(self._task_graph)
        await self._emit_log(
            "claude",
            f"최종 검수: {'합격 — 완료' if passed else '불합격 — 보완 지시'}",
            "task_end",
        )

        if not passed and self._state != WorkflowState.ESCALATED:
            # 보완 루프: Claude 불합격 사유를 기획자에게 전달 → 재취합 → Claude 재검증
            while self._revision_count < self.MAX_REVISION_ROUNDS:
                feedback = self._last_verify_feedback or "품질 미달"
                await self._emit_log("claude", f"보완 지시: {feedback}", "message")
                await self._emit_log(
                    "planner",
                    f"팀장 보완 지시에 따라 재작성 (라운드 {self._revision_count}/{self.MAX_REVISION_ROUNDS})",
                    "task_start",
                )
                self._state = WorkflowState.PLANNER_PLANNING
                # 보완 사유를 기획자에게 전달
                await self._run_planner_synthesize(
                    worker_results, revision_feedback=feedback
                )
                await self._emit_log("planner", "보완 산출물 작성 완료.", "task_end")

                self._state = WorkflowState.CLAUDE_FINAL_VERIFYING
                await self._emit_log(
                    "claude", "팀장이 보완된 산출물을 재검수합니다...", "task_start"
                )
                passed = await self._claude_final_verify(self._task_graph)
                await self._emit_log(
                    "claude", f"재검수: {'합격' if passed else '불합격'}", "task_end"
                )
                if passed or self._state == WorkflowState.ESCALATED:
                    break

        return self._state

    async def _run_planner(self) -> None:
        """기획자 에이전트를 실행하여 태스크를 분해하고 task_graph에 추가한다.

        사용자 지시와 Claude 분석을 전달하여 구체적 태스크 목록을 생성한다.
        """
        system_prompt = self._load_agent_prompt("planner")

        # 전문 지식 주입
        from orchestration.expertise import load_expertise, detect_task_type
        task_type = detect_task_type(self._user_instruction)
        expertise = load_expertise("planner", task_type)
        if expertise:
            system_prompt += f"\n\n{expertise}"

        # 기획자 회고 메모리 — 과거 불합격 시 태스크 분배 방식 반성
        past_warnings = get_past_rejections(limit=3)
        if past_warnings:
            system_prompt += (
                "\n\n## 과거 불합격 패턴 (태스크 분배 시 반영할 것)\n"
                + "\n".join(past_warnings)
            )
            system_prompt += "\n위 패턴을 참고하여 각 구성원에게 더 구체적이고 상세한 지시를 내리세요."

        # Claude 분석 결과에서 payload 추출
        analysis_text = ""
        if self._claude_analysis:
            payload = self._claude_analysis.payload or {}
            analysis_text = payload.get("claude_analysis", "")

        ref_section = ""
        if self._reference_context:
            ref_section = f"[참조 자료]\n{self._reference_context[:4000]}\n\n"

        prompt = (
            f"[사용자 지시]\n{self._user_instruction}\n\n"
            f"[팀장(Claude) 분석]\n{analysis_text}\n\n"
            f"{ref_section}"
            f"[응답 형식]\n"
            f"반드시 아래 JSON 형식으로 응답하세요:\n"
            f"{{\n"
            f'  "tasks": [\n'
            f"    {{\n"
            f'      "task_id": "task-1",\n'
            f'      "description": "구체적 작업 내용",\n'
            f'      "requirements": "완료 기준",\n'
            f'      "assigned_to": "developer",\n'
            f'      "depends_on": []\n'
            f"    }}\n"
            f"  ]\n"
            f"}}\n"
            f"assigned_to는 planner, designer, developer, qa 중 하나."
        )

        result = await self.runner.generate_json(prompt, system=system_prompt)
        Path("data/debug.log").open("a").write(f"[PLANNER] result={result}\n")

        if result and isinstance(result, dict) and "tasks" in result:
            for task_data in result["tasks"]:
                task_id = task_data.get("task_id", f"task-{id(task_data)}")
                # depends_on 안전 변환
                deps = task_data.get("depends_on", [])
                if isinstance(deps, str):
                    deps = [deps] if deps else []
                elif not isinstance(deps, list):
                    deps = []
                try:
                    payload = TaskRequestPayload(
                        task_id=task_id,
                        description=task_data.get("description", ""),
                        requirements=task_data.get("requirements", ""),
                        assigned_to=task_data.get("assigned_to", "developer"),
                        depends_on=deps,
                    )
                    self._task_graph.add_task(payload)
                except Exception as e:
                    Path("data/debug.log").open("a").write(
                        f"[PLANNER] 태스크 파싱 실패: {e}\n"
                    )
                    continue
        else:
            # 기획자 응답 파싱 실패 시 기본 태스크 생성
            fallback = TaskRequestPayload(
                task_id="task-fallback",
                description=self._user_instruction,
                requirements=self._user_instruction,
                assigned_to="developer",
                depends_on=[],
            )
            self._task_graph.add_task(fallback)

    async def _run_planner_synthesize(
        self, worker_results: dict[str, str], revision_feedback: str = ""
    ) -> None:
        """기획자가 작업자들의 결과를 취합하여 최종 산출물을 작성한다.

        revision_feedback가 있으면 Claude 팀장의 보완 지시를 반영하여 재작성한다.
        """
        system_prompt = self._load_agent_prompt("planner")

        results_text = "\n\n".join(worker_results.values())

        revision_section = ""
        if revision_feedback:
            revision_section = (
                f"[팀장 보완 지시 — 반드시 반영할 것]\n{revision_feedback}\n\n"
            )

        prompt = (
            f"[사용자 원본 지시]\n{self._user_instruction}\n\n"
            f"{revision_section}"
            f"[각 구성원의 작업 결과]\n{results_text}\n\n"
            f"[지시사항 — 절대 규칙]\n"
            f"1. 절대로 요약하지 마라. 각 구성원의 분석 내용을 한 글자도 줄이지 마라.\n"
            f"2. 각 구성원의 작업 결과를 섹션별로 전문(全文) 포함하라.\n"
            f"3. 기획자로서 추가할 것: 프로젝트 개요(앞), 섹션 간 연결(중간), 실행 로드맵(끝)\n"
            f"4. 최소 3000자 이상 작성하라. 짧으면 불합격이다.\n"
            f"{('5. 팀장 보완 지시 반드시 반영: ' + revision_feedback[:300] if revision_feedback else '')}\n\n"
            f"마크다운 형식으로 직접 작성하세요. JSON으로 감싸지 마세요."
        )

        raw = await self.runner.generate(prompt, system=system_prompt)
        content = raw.strip()
        # 마크다운 펜스 제거
        if content.startswith("```"):
            lines = content.split("\n")
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            content = "\n".join(lines)

        Path("data/debug.log").open("a").write(f"[PLANNER_SYNTH] len={len(content)}\n")

        try:
            self.workspace.write_artifact("final/result.md", content)
            Path("data/debug.log").open("a").write(
                f"[PLANNER_SYNTH] final/result.md 저장 ({len(content)}bytes)\n"
            )
        except Exception as e:
            Path("data/debug.log").open("a").write(f"[PLANNER_SYNTH] 저장 실패: {e}\n")

    async def _run_agent(self, node: TaskNode) -> TaskResultPayload | None:
        """에이전트를 실행하여 태스크를 처리하고 결과를 workspace에 저장한다.

        Args:
            node: 실행할 TaskNode

        Returns:
            TaskResultPayload 또는 실패 시 None
        """
        system_prompt = self._load_agent_prompt(node.assigned_to)

        # 전문 지식 주입
        from orchestration.expertise import load_expertise, detect_task_type
        task_type = detect_task_type(self._user_instruction)
        expertise = load_expertise(node.assigned_to, task_type)
        if expertise:
            system_prompt += f"\n\n{expertise}"

        # 과거 불합격 패턴 주입 — 같은 실수 반복 방지
        past_warnings = get_past_rejections(limit=3)
        if past_warnings:
            system_prompt += (
                "\n\n## 과거 불합격 주의사항 (반드시 회피할 것)\n"
                + "\n".join(past_warnings)
            )

        # 이전 경험 주입 (AMEM-02)
        memory = AgentMemory(node.assigned_to, memory_root=self._memory_root)
        task_type = node.assigned_to
        experiences = memory.load_relevant(task_type=task_type, limit=5)
        if experiences:
            lines = []
            for exp in experiences:
                status_str = "성공" if exp.success else "실패"
                lines.append(
                    f"- [{status_str}] {exp.feedback} (태그: {', '.join(exp.tags)})"
                )
            system_prompt += "\n\n## 이전 경험\n" + "\n".join(lines)

        # 참조 자료가 있으면 에이전트에게도 전달
        ref_section = ""
        if self._reference_context:
            ref_section = f"[참조 자료]\n{self._reference_context[:4000]}\n\n"

        prompt = (
            f"[작업 지시]\n{node.description}\n\n"
            f"[원본 요구사항]\n{node.requirements}\n\n"
            f"{ref_section}"
            f"위 지시에 따라 실무에서 바로 활용할 수 있는 수준으로 상세하게 작성하세요.\n"
            f"마크다운 형식으로 작성하세요. JSON으로 감싸지 마세요."
        )

        # developer 작업은 opencode(클라우드), 나머지는 Gemma(로컬)
        if node.assigned_to == "developer":
            await self._emit_log(
                "developer", "[opencode] 클라우드 모델로 작업 실행 중...", "task_start"
            )
            raw_content = await run_opencode(
                prompt=prompt,
                system=system_prompt,
                workspace_dir=str(self.workspace.task_dir),
            )
            Path("data/debug.log").open("a").write(
                f"[AGENT {node.task_id}][opencode] len={len(raw_content)}\n"
            )
        else:
            raw_content = await self.runner.generate(prompt, system=system_prompt)
            Path("data/debug.log").open("a").write(
                f"[AGENT {node.task_id}][gemma] len={len(raw_content)}\n"
            )

        # 마크다운 코드 펜스 제거
        content = raw_content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            content = "\n".join(lines)

        # 파일 확장자 결정: 코드 작업이면 .py/.js 등, 문서 작업이면 .md
        is_code = node.assigned_to == "developer" and any(
            kw in node.description.lower()
            for kw in [
                "스크립트",
                "코드",
                "구현",
                "개발",
                "html",
                "css",
                "python",
                "javascript",
            ]
        )
        if is_code and not content.startswith("#"):
            ext = ".py"  # 기본 코드 확장자
            for lang_ext in [
                (".html", "html"),
                (".css", "css"),
                (".js", "javascript"),
                (".ts", "typescript"),
            ]:
                if lang_ext[1] in node.description.lower():
                    ext = lang_ext[0]
                    break
            filename = f"{node.task_id}{ext}"
        else:
            filename = f"{node.task_id}.md"

        file_path = f"{node.task_id}/{filename}"
        saved_paths: list[str] = []
        try:
            self.workspace.write_artifact(file_path, content)
            saved_paths.append(file_path)
            Path("data/debug.log").open("a").write(
                f"[AGENT {node.task_id}] 저장: {file_path} ({len(content)}bytes)\n"
            )
        except Exception as e:
            Path("data/debug.log").open("a").write(
                f"[AGENT {node.task_id}] 저장 실패: {e}\n"
            )

        # 디자이너 작업이고 디자인 파일이 필요한 경우 Stitch로 UI 생성
        needs_design_file = node.assigned_to == "designer" and any(
            kw in node.description.lower()
            for kw in [
                "와이어프레임",
                "ui",
                "ux",
                "페이지",
                "화면",
                "레이아웃",
                "디자인 파일",
                "프로토타입",
            ]
        )
        if needs_design_file and saved_paths:
            await self._emit_log(
                "designer", "[designer] Stitch로 디자인 파일 생성 중...", "task_start"
            )
            try:
                # 참조 자료(사용자 첨부 원본)가 있으면 Gemma 재작성 대신 원본을 Stitch에 전달
                stitch_context = (
                    self._reference_context if self._reference_context else content
                )
                stitch_result = await designer_generate_with_context(
                    design_context=stitch_context,
                    task_id=node.task_id,
                    workspace_root=str(self.workspace.task_dir),
                )
                if stitch_result.get("success"):
                    if stitch_result.get("html_path"):
                        saved_paths.append(f"{node.task_id}/stitch/design.html")
                    if stitch_result.get("image_path"):
                        saved_paths.append(f"{node.task_id}/stitch/design.png")
                    await self._emit_log(
                        "designer",
                        "[designer] Stitch 디자인 파일 생성 완료",
                        "task_end",
                    )
                else:
                    await self._emit_log(
                        "designer",
                        f"[designer] Stitch 생성 실패: {stitch_result.get('error', '')}",
                        "error",
                    )
            except Exception as e:
                Path("data/debug.log").open("a").write(f"[STITCH] 에러: {e}\n")
                await self._emit_log(
                    "designer",
                    f"[designer] Stitch 연동 실패 (산출물은 마크다운으로 유지)",
                    "error",
                )

        summary = content.replace("\n", " ")
        result = TaskResultPayload(
            task_id=node.task_id,
            status="success" if saved_paths else "fail",
            artifact_paths=saved_paths,
            summary=summary,
            failure_reason=None if saved_paths else "파일 저장 실패",
        )

        # result.json 메타데이터도 저장
        try:
            self.workspace.write_artifact(
                f"{node.task_id}/result.json",
                json.dumps(result.model_dump(), ensure_ascii=False, indent=2),
            )
        except Exception:
            pass

        # task_graph 업데이트
        if result.status == "success":
            self._task_graph.update_status(
                node.task_id,
                TaskStatus.DONE,
                artifact_paths=result.artifact_paths,
            )
            # 성공 경험 기록 (AMEM-01: 성공 패턴도 저장)
            success_memory = AgentMemory(
                node.assigned_to, memory_root=self._memory_root
            )
            success_memory.record(
                MemoryRecord(
                    task_id=node.task_id,
                    task_type=node.assigned_to,
                    success=True,
                    feedback=result.summary,
                    tags=["success"],
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )
            )
        else:
            self._task_graph.update_status(
                node.task_id,
                TaskStatus.FAILED,
                failure_reason=result.failure_reason,
            )

        return result

    async def _run_qa_gate(self, node: TaskNode) -> bool:
        """QA 게이트 — 원본 요구사항 대비 작업 결과물을 검수한다 (D-08, Pattern 4).

        확증편향 방지: QA는 결과물만 보지 않고 반드시 원본 요구사항 대비 검증한다.

        Args:
            node: 검수할 TaskNode

        Returns:
            QA 통과 시 True, 불합격 시 False (node.failure_reason에 이유 설정)
        """
        system_prompt = self._load_agent_prompt("qa")

        # 산출물 내용 수집 — QA가 직접 읽을 수 없으므로 내용을 전달
        artifact_content = ""
        for fpath in node.artifact_paths:
            try:
                full = (
                    self.workspace.task_dir / fpath.split("/", 1)[-1]
                    if "/" in fpath
                    else self.workspace.task_dir / fpath
                )
                if full.exists():
                    artifact_content += f"\n--- {fpath} ---\n{full.read_text(errors='replace')[:3000]}\n"
            except Exception:
                pass
        if not artifact_content:
            artifact_content = f"(산출물 요약: {node.description[:200]})"

        # 코드 파일이면 실행 결과도 첨부
        code_result_text = ""
        for fpath in node.artifact_paths:
            full = (
                self.workspace.task_dir / fpath.split("/", 1)[-1]
                if "/" in fpath
                else self.workspace.task_dir / fpath
            )
            if full.exists() and full.suffix in (".py", ".js", ".ts", ".sh"):
                result = await run_code(str(full))
                status = "성공" if result["success"] else "실패"
                code_result_text += (
                    f"\n[코드 실행 결과: {full.name}] {status}\n"
                    f"stdout: {result['stdout'][:500]}\n"
                    f"stderr: {result['stderr'][:500]}\n"
                )

        prompt = (
            f"[원본 요구사항]\n{node.requirements}\n\n"
            f"[작업 결과물]\n{artifact_content}\n\n"
            f"{code_result_text}"
            f"[검수 기준]\n"
            f"1. 산출물의 내용이 충분히 구체적이고 상세한가?\n"
            f"2. 해당 구성원의 전문 관점(디자인/개발/기획)이 반영되어 있는가?\n"
            f"3. 실무에서 바로 활용할 수 있는 수준인가?\n"
            f"4. 논리적 구조와 일관성이 있는가?\n"
            f"참고: 외부 파일 직접 참조 여부는 검수 대상이 아님. 산출물 내용 자체의 품질만 평가하라.\n\n"
            f"반드시 아래 JSON으로 응답:\n"
            f'{{"status":"success","summary":"합격 근거","failure_reason":null}}\n'
            f"또는\n"
            f'{{"status":"fail","summary":"검수 요약","failure_reason":"구체적 문제점"}}'
        )

        result_data = await self.runner.generate_json(prompt, system=system_prompt)

        if result_data and isinstance(result_data, dict):
            if result_data.get("status") == "success":
                return True
            else:
                # 불합격 — failure_reason을 노드에 기록
                node.failure_reason = result_data.get("failure_reason", "QA 불합격")
                # QA 불합격 즉시 경험 기록 (AMEM-03, D-05)
                memory = AgentMemory(node.assigned_to, memory_root=self._memory_root)
                memory.record(
                    MemoryRecord(
                        task_id=node.task_id,
                        task_type=node.assigned_to,
                        success=False,
                        feedback=node.failure_reason,
                        tags=["qa_fail"],
                        timestamp=datetime.now(timezone.utc).isoformat(),
                    )
                )
                return False

        # 응답 없음 — 안전하게 실패 처리
        node.failure_reason = "QA 응답 없음"
        return False

    async def _claude_final_verify(self, task_graph: TaskGraph) -> bool:
        """Claude 최종 검증 — 산출물을 직접 읽고 품질을 판단한다.

        Claude가 팀장으로서:
        1. 실제 산출물 파일을 읽는다
        2. 사용자 원본 지시 대비 충족도를 평가한다
        3. 부족하면 구체적으로 뭘 보완해야 하는지 명시한다
        """
        # 산출물 파일 내용 수집
        artifact_contents = []
        for node in task_graph._nodes.values():
            if node.status == TaskStatus.DONE:
                for fpath in node.artifact_paths:
                    try:
                        full_path = self.workspace.task_dir / fpath
                        if full_path.exists():
                            content = full_path.read_text(errors="replace")[:3000]
                            artifact_contents.append(f"--- {fpath} ---\n{content}\n")
                    except Exception:
                        pass

        # final/ 폴더의 산출물도 포함
        final_dir = self.workspace.task_dir / "final"
        if final_dir.exists():
            for f in final_dir.rglob("*"):
                if f.is_file():
                    try:
                        content = f.read_text(errors="replace")[:5000]
                        rel = f.relative_to(self.workspace.task_dir)
                        artifact_contents.append(f"--- {rel} ---\n{content}\n")
                    except Exception:
                        pass

        artifacts_text = (
            "\n".join(artifact_contents) if artifact_contents else "(산출물 없음)"
        )

        # Claude가 처음 분석한 내용 (팀장의 지시 기억)
        analysis_text = ""
        if self._claude_analysis:
            payload = self._claude_analysis.payload or {}
            analysis_text = payload.get("claude_analysis", "")

        prompt = (
            f"너는 AI Office의 팀장이다. 최종 산출물을 검수하라.\n\n"
            f"[사용자 원본 지시]\n{self._user_instruction}\n\n"
            f"[내가 처음에 내린 지시 (팀장 분석)]\n{analysis_text}\n\n"
            f"[최종 산출물]\n{artifacts_text}\n\n"
            f"[검수 기준]\n"
            f"1. 내가 처음에 분석한 방향대로 작업이 수행되었는가?\n"
            f"2. 사용자 지시를 충족하는가? 빠진 내용은 없는가?\n"
            f"3. 실무에서 바로 활용할 수 있는 수준인가? (피상적이면 FAIL)\n"
            f"4. 각 구성원(기획/디자인/개발/QA)의 관점이 충분히 반영되었는가?\n"
            f"5. 논리적 일관성과 구체성이 있는가?\n\n"
            f"판정: 반드시 첫 줄에 PASS 또는 FAIL을 명시하라.\n"
            f"FAIL인 경우 구체적으로 어떤 부분을 어떻게 보완해야 하는지 상세히 기술하라.\n"
            f"주의: .venv/ node_modules/ __pycache__/ 디렉토리는 절대 탐색하지 마라."
        )

        response = await run_claude_isolated(prompt, timeout=180.0)
        Path("data/debug.log").open("a").write(
            f"[CLAUDE_VERIFY] response_len={len(response)} first_200={response[:200]}\n"
        )

        # 불합격 사유 저장 (보완 루프에서 기획자에게 전달용)
        self._last_verify_feedback = response

        # 대소문자 무관 PASS/FAIL 확인
        response_upper = response.upper()
        if "PASS" in response_upper:
            self._state = WorkflowState.COMPLETED
            await self._emit_status(self._state)
            return True
        else:
            # FAIL — 불합격 분석기로 에이전트별 책임 분석 + 메모리 기록
            blamed = record_rejection(
                response, task_type="general", memory_root=str(self._memory_root)
            )
            blamed_summary = ", ".join(
                f"{a}: {len(issues)}건" for a, issues in blamed.items()
            )
            Path("data/debug.log").open("a").write(
                f"[REJECTION] blamed={blamed_summary}\n"
            )
            await self._emit_log(
                "system", f"불합격 원인 분석: {blamed_summary}", "error"
            )
            self._revision_count += 1
            if self._revision_count >= self.MAX_REVISION_ROUNDS:
                # 최대 반복 횟수 초과 → 에스컬레이션 (D-12)
                self._state = WorkflowState.ESCALATED
                await self._emit_status(self._state)
            else:
                # 보완 루프 재진입 (D-10)
                self._state = WorkflowState.REVISION_LOOPING
                await self._emit_status(self._state)
            return False

    async def analyze_instruction(self, instruction: str) -> AgentMessage:
        """사용자 지시를 심층 분석하여 기획자에게 구체적 방향을 제시한다.

        Claude가 팀장으로서:
        1. 작업 유형을 파악 (문서작성/코드생성/사이트구축/분석 등)
        2. 어떤 구성원이 어떤 관점에서 작업해야 하는지 구체적으로 지시
        3. 각 구성원에게 기대하는 산출물의 수준과 형태를 명시
        4. 최종 산출물의 완성도 기준을 제시
        """
        ref_section = ""
        if self._reference_context:
            ref_section = f"[참조 자료]\n{self._reference_context}\n\n"

        prompt = (
            f"너는 AI Office의 팀장이다. 사용자의 지시를 심층 분석하여 기획자에게 전달할 구체적 작업 방향을 수립하라.\n\n"
            f"[사용자 지시]\n{instruction}\n\n"
            f"{ref_section}"
            f"[분석 항목]\n"
            f"1. 작업 유형 판별: 문서작성 / 코드생성 / 사이트구축 / 분석보고서 / 복합프로젝트 중 어느 유형인가?\n"
            f"2. 필요한 구성원과 역할:\n"
            f"   - 기획자(planner): 어떤 관점에서 분석/기획해야 하는가?\n"
            f"   - 디자이너(designer): 디자인 관점에서 어떤 분석/작업이 필요한가?\n"
            f"   - 개발자(developer): 기술 관점에서 어떤 분석/작업이 필요한가?\n"
            f"   - QA: 어떤 기준으로 검수해야 하는가?\n"
            f"3. 각 구성원에게 기대하는 산출물의 구체적 형태와 분량\n"
            f"4. 최종 산출물의 완성도 기준 — 실무에서 바로 활용할 수 있는 수준이어야 함\n"
            f"5. 구성원 간 협업 순서 — 누가 먼저 작업하고 누구의 결과를 참고해야 하는지\n\n"
            f"심층적으로 분석하라. 피상적인 분석은 거부한다.\n"
            f"주의: .venv/ node_modules/ __pycache__/ 디렉토리는 절대 탐색하지 마라."
        )

        response = await run_claude_isolated(prompt, timeout=180.0)
        Path("data/debug.log").open("a").write(
            f"[CLAUDE_ANALYZE] len={len(response)}\n"
        )

        msg = AgentMessage(
            type="task_request",
            **{"from": "claude", "to": "planner"},
            payload={"claude_analysis": response, "original_instruction": instruction},
        )

        await self.router.route(msg)
        return msg

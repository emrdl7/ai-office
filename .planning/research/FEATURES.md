# Feature Research

**Domain:** AI multi-agent collaboration system with web dashboard
**Researched:** 2026-04-03
**Confidence:** MEDIUM (ecosystem patterns verified across multiple sources; specific Ollama+Claude CLI combination is novel)

## Feature Landscape

### Table Stakes (Users Expect These)

Features users assume exist. Missing these = product feels incomplete.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Agent role assignment | Every multi-agent system defines distinct agent roles with bounded responsibilities — without this, agents collide | LOW | Planner, Designer, Developer, QA roles defined at system init |
| Task dispatch (orchestrator → worker) | Users expect a leader agent to break work down and assign it — this is the definition of the system | MEDIUM | Claude CLI → Gemma4 workers via local message queue |
| Inter-agent messaging | Workers must request help from each other (Developer → Designer, etc.) — siloed agents cannot collaborate | MEDIUM | File-based or in-process queue; needs schema definition |
| Structured message schema | Unschemed messages cause role violations and lost context — the #1 failure root cause per MAST 2025 research | LOW | JSON schema per message type: task_request, task_result, status_update |
| Task status tracking | Users and the PM agent both need to know what's in-progress, done, or blocked — without this there is no workflow | MEDIUM | Planner/PM maintains a canonical task state store |
| Artifact output to files | The core value proposition is producing real files — if outputs exist only in memory the product is useless | LOW | All agent outputs written to project folder immediately |
| Web dashboard: task instruction input | Users must be able to give a project directive from the dashboard — equivalent to the CLI entry point | MEDIUM | Text input + submit → dispatched to Claude team lead |
| Web dashboard: agent status board | Users need to see at a glance which agents are working, idle, or errored | LOW | Polling or WebSocket-fed status panel |
| Web dashboard: real-time log stream | Agents emit events as they work; users expect to watch it live — a static log page breaks trust | HIGH | WebSocket or SSE from a log aggregator; all agents write to shared log bus |
| Web dashboard: artifact viewer | Files produced are the deliverable — users must be able to view code, documents, and designs inside the dashboard | MEDIUM | File tree + content preview (syntax highlighted code, markdown render) |
| Final verification by Claude | Claude's quality judgment is the team lead's core value — skipping final review makes Claude a routing proxy only | MEDIUM | Claude receives completed artifact set, returns pass/fail + revision notes |
| QA step-by-step review | QA agent catching intermediate errors before they propagate is expected in any team workflow | MEDIUM | QA invoked at configurable checkpoints, writes structured review results |

### Differentiators (Competitive Advantage)

Features that set the product apart. Not required, but valued.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Free-form inter-agent work requests | Agents autonomously deciding to request help from another agent (Developer → Designer) rather than only following top-down orders shows genuine emergent collaboration | HIGH | Requires agents to parse their own output, detect a gap, and emit a request event |
| Revision loop: Claude → workers | Claude can reject final output and re-dispatch with specific revision instructions — closed-loop quality control | HIGH | State machine: PENDING → IN_PROGRESS → QA_REVIEW → FINAL_REVIEW → [APPROVED|REVISION] |
| Planner PM role: workflow ownership | Planner tracks the entire workflow and can detect stalls or missing steps — single source of truth for project state | MEDIUM | Planner owns task graph; workers notify planner on completion |
| Dashboard workflow graph visualization | Showing a live DAG of agent tasks with status colors (pending/active/done/error) communicates system health far better than a log list | HIGH | Requires task dependency data from Planner; rendered as directed graph (e.g., vis.js or d3) |
| CLI + dashboard dual entry points | Power users want CLI speed; managers want dashboard visibility — supporting both avoids forcing a choice | MEDIUM | Both entry points dispatch to same orchestration layer |
| Per-agent log filtering | With 4+ agents emitting concurrent logs, being able to filter to a single agent's stream dramatically reduces noise | LOW | Tag each log event with agent_id; dashboard filter control |
| Artifact diff/version view | When Claude requests revisions and a new version is produced, showing a diff between v1 and v2 makes the improvement visible | HIGH | Requires artifact versioning (e.g., append timestamp to filename or git-tracked folder) |

### Anti-Features (Commonly Requested, Often Problematic)

Features that seem good but create problems.

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Automatic deployment of agent outputs | "The AI should just ship it" sounds like full automation | Deployment requires human judgment about environment, credentials, and risk — automating it at v1 creates unrecoverable errors with no rollback | Artifacts are written to disk; user triggers deployment manually with a separate CLI command |
| External API/cloud agent calls | Connecting agents to external services (Slack, GitHub, cloud LLMs) seems powerful | Contradicts the all-local constraint; introduces auth complexity, rate limits, and cost unpredictability | Keep Claude on CLI and Gemma4 on Ollama; external integrations are v2+ |
| Agent memory across projects (persistent cross-project state) | "The agents should remember what they did last time" | Cross-project shared state creates unpredictable context bleed, hard debugging, and privacy issues between unrelated projects | Scope memory to current project session; clean-slate each new project |
| More than 5-6 concurrent agent types | "Let's add a Security Agent, Data Agent, DevOps Agent..." | Research (MAST 2025) shows coordination benefits plateau beyond 4 agents; above that, overhead exceeds gains and failure rates increase sharply | Keep the 4 core roles (Planner, Designer, Developer, QA) and let Claude serve as the fifth as team lead |
| Fully autonomous infinite loop operation | "Agents should keep working until the project is perfect" | Without human checkpoints, error cascades compound — an early planning mistake gets implemented and QA'd before anyone can intervene | Human approves phase transitions; Claude escalates blockers to user rather than looping indefinitely |
| Real-time collaborative editing between agents | Multiple agents writing to the same file simultaneously seems efficient | Race conditions and merge conflicts corrupt output; this is the "unsynchronized shared state" anti-pattern | Each agent owns its output file(s) exclusively; coordination happens through task messages, not shared file writes |

## Feature Dependencies

```
[Task Instruction Input (CLI or Dashboard)]
    └──requires──> [Claude Team Lead: Task Analysis & Dispatch]
                       └──requires──> [Inter-Agent Message Queue]
                                          └──requires──> [Structured Message Schema]
                                          └──requires──> [Task Status Tracker (Planner/PM)]

[Gemma4 Worker Agents: Planner, Designer, Developer, QA]
    └──requires──> [Inter-Agent Message Queue]
    └──requires──> [Artifact Output to Files]

[QA Step-by-Step Review]
    └──requires──> [Task Status Tracker]
    └──requires──> [Artifact Output to Files]

[Claude Final Verification]
    └──requires──> [QA Step-by-Step Review]
    └──requires──> [Artifact Output to Files]

[Revision Loop: Claude → Workers]
    └──requires──> [Claude Final Verification]
    └──requires──> [Inter-Agent Message Queue]

[Web Dashboard: Real-time Log Stream]
    └──requires──> [Log Bus / Event Emitter from all agents]
    └──requires──> [WebSocket or SSE server]

[Web Dashboard: Artifact Viewer]
    └──requires──> [Artifact Output to Files]
    └──requires──> [File watcher / API endpoint]

[Web Dashboard: Agent Status Board]
    └──requires──> [Task Status Tracker]
    └──requires──> [WebSocket or SSE server]

[Dashboard Workflow Graph]
    └──requires──> [Task Status Tracker (Planner owns task graph)]
    └──requires──> [Web Dashboard: Agent Status Board]

[Free-form Inter-Agent Work Requests]
    └──enhances──> [Inter-Agent Message Queue]
    └──requires──> [Structured Message Schema]

[Artifact Diff/Version View]
    └──requires──> [Artifact Output to Files]
    └──requires──> [Revision Loop: Claude → Workers]
```

### Dependency Notes

- **Inter-Agent Message Queue requires Structured Message Schema:** Unschemed messages are the #1 cause of role violations per MAST 2025 research (coordination failures = 36.9% of all multi-agent failures). The schema must be defined before any agent sends a message.
- **Claude Final Verification requires QA:** Claude's judgment is wasted if it receives unreviewed intermediate work. QA reduces noise before the highest-cost agent step.
- **Dashboard Log Stream requires Log Bus:** Each agent process must write to a shared event bus (not its own log file) for the dashboard to aggregate. This architectural decision must be made early or retrofitting is painful.
- **Workflow Graph conflicts with Simple Status Board:** Build status board first (simpler), graph visualization layer on top once task dependency data exists.

## MVP Definition

### Launch With (v1)

Minimum viable product — what's needed to validate the concept.

- [ ] Claude CLI dispatches project directive to Planner (Gemma4) with task breakdown
- [ ] Inter-agent message queue with structured schema (file-based queue acceptable for v1)
- [ ] Planner tracks task state; Designer/Developer/QA execute their roles
- [ ] QA performs step-by-step review at defined checkpoints
- [ ] Claude receives final artifact set and performs verification pass; re-dispatches if revision needed
- [ ] All artifacts written as real files to project output folder
- [ ] Web dashboard: task instruction input, agent status board, real-time log stream, artifact viewer

### Add After Validation (v1.x)

Features to add once core is working.

- [ ] Free-form inter-agent work requests (Developer → Designer autonomously) — trigger: v1 reveals agents hitting gaps that require cross-role help
- [ ] CLI entry point alongside dashboard — trigger: power users request it or dashboard proves too slow for iteration
- [ ] Per-agent log filtering in dashboard — trigger: logs become too noisy to read during real projects
- [ ] Dashboard workflow graph (DAG visualization) — trigger: users report difficulty understanding which step is blocking progress

### Future Consideration (v2+)

Features to defer until product-market fit is established.

- [ ] Artifact diff/version view — depends on revision loop working well and users wanting audit trail
- [ ] Additional agent roles (Security, DevOps, Data) — only if user projects consistently demand them
- [ ] External API integrations (GitHub, Slack) — requires moving off all-local constraint, out of scope for v1

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Claude dispatches task to Planner | HIGH | MEDIUM | P1 |
| Inter-agent message queue + schema | HIGH | MEDIUM | P1 |
| Task status tracking (Planner/PM) | HIGH | LOW | P1 |
| Artifact output to files | HIGH | LOW | P1 |
| QA step-by-step review | HIGH | MEDIUM | P1 |
| Claude final verification + revision loop | HIGH | MEDIUM | P1 |
| Dashboard: task instruction input | HIGH | LOW | P1 |
| Dashboard: agent status board | HIGH | LOW | P1 |
| Dashboard: real-time log stream | HIGH | HIGH | P1 |
| Dashboard: artifact viewer | HIGH | MEDIUM | P1 |
| Per-agent log filtering | MEDIUM | LOW | P2 |
| Free-form inter-agent requests | HIGH | HIGH | P2 |
| Workflow graph visualization | MEDIUM | HIGH | P2 |
| CLI entry point (dual mode) | MEDIUM | LOW | P2 |
| Artifact diff/version view | MEDIUM | HIGH | P3 |
| Additional agent roles | LOW | MEDIUM | P3 |

**Priority key:**
- P1: Must have for launch
- P2: Should have, add when possible
- P3: Nice to have, future consideration

## Competitor Feature Analysis

| Feature | CrewAI | LangGraph | Our Approach |
|---------|--------|-----------|--------------|
| Agent roles | Named roles with goal/backstory | Nodes in state graph | Fixed 4 roles + Claude lead; simpler but explicit |
| Workflow orchestration | Sequential/hierarchical/parallel crew modes | State machine with conditional routing | Planner-owned task graph; Planner is PM |
| Monitoring/observability | CrewAI dashboard (cloud product) | LangSmith (separate service) | Built-in local dashboard; no external service |
| Human-in-the-loop | Supported via callbacks | Supported via interrupt nodes | Claude escalates blockers to user; no mid-step pause UI in v1 |
| Local execution | Partial (cloud-oriented) | Partial (cloud-oriented) | Fully local (Ollama + Claude CLI); no API keys needed |
| Artifact management | In-memory state | In-memory state | Explicit file output; artifacts are first-class |
| Entry point | Python API | Python API | CLI + web dashboard |

**Key differentiator vs existing frameworks:** All-local execution with no external service dependency, and treating file artifacts as a first-class output (not just in-memory state) is a gap in existing frameworks.

## Sources

- [How to Build Multi-Agent Systems: Complete 2026 Guide](https://dev.to/eira-wexford/how-to-build-multi-agent-systems-complete-2026-guide-1io6) — MEDIUM confidence
- [Multi-Agent Systems & AI Orchestration Guide 2026](https://www.codebridge.tech/articles/mastering-multi-agent-orchestration-coordination-is-the-new-scale-frontier) — MEDIUM confidence
- [Build Multi-Agent Dashboards in 2026](https://letsblogitup.dev/articles/building-multi-agent-dashboards-for-2026-a-develop/) — MEDIUM confidence
- [Why Do Multi-Agent LLM Systems Fail? (MAST 2025 research)](https://arxiv.org/html/2503.13657v1) — HIGH confidence (peer-reviewed, ICLR 2025)
- [AI Agent Orchestration Patterns - Azure Architecture Center](https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/ai-agent-design-patterns) — HIGH confidence (official Microsoft docs)
- [Top 5 AI Agent Frameworks 2026: LangGraph, CrewAI & More](https://www.intuz.com/blog/top-5-ai-agent-frameworks-2025) — MEDIUM confidence
- [15 AI Agent Observability Tools in 2026](https://research.aimultiple.com/agentic-monitoring/) — MEDIUM confidence

---
*Feature research for: AI multi-agent collaboration system (ai-office)*
*Researched: 2026-04-03*

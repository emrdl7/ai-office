# Pitfalls Research

**Domain:** AI multi-agent collaboration system — local-only, Claude CLI orchestrator + Gemma4/Ollama workers
**Researched:** 2026-04-03
**Confidence:** HIGH (multiple independent sources, verified against official docs and production post-mortems)

---

## Critical Pitfalls

### Pitfall 1: Claude CLI Subprocess Token Explosion

**What goes wrong:**
Every Claude CLI subprocess spawned for orchestration re-injects the full global configuration on each turn — CLAUDE.md files, all MCP tool descriptions, enabled plugins. A single subprocess turn consumes ~50,000 tokens before any actual work begins. In a multi-agent setup running 4+ workers, this burns through token quotas in minutes.

**Why it happens:**
The CLI was designed for interactive single-session use. It assumes each process inherits user context. When repurposed as an orchestration backend, this "helpful" context injection becomes a cost and latency catastrophe. Developers don't discover the scale of waste until the first production run.

**How to avoid:**
Isolate each Claude CLI subprocess from global configuration using four techniques together:
1. Scoped working directory — prevents `~/CLAUDE.md` auto-loading
2. Git boundary (`.git/HEAD` presence) — blocks upward traversal for parent CLAUDE.md files
3. Empty plugin directory — pass `--plugin-dir` pointing to an empty path
4. Setting source filtering — use `--setting-sources project,local` to exclude user-level settings

Prefer a long-lived subprocess in `stream-json` mode over repeatedly spawning new processes. Send the system prompt once, then pass subsequent messages via stdin.

**Warning signs:**
- Orchestrator runs consume far more tokens than individual manual Claude sessions
- Response latency per subprocess is 10-30 seconds even for trivial tasks
- Token counters spike on first message before any agent output appears

**Phase to address:**
Phase 1 (foundation/infrastructure) — must be solved before building any workflow on top of Claude CLI.

---

### Pitfall 2: Ollama Single-Instance Serialization Under Load

**What goes wrong:**
When multiple Gemma4 worker agents send concurrent requests to Ollama, requests queue rather than execute in parallel. Ollama's default `OLLAMA_NUM_PARALLEL=1` means agents that appear to run concurrently actually serialize. A 4-agent system theoretically completing in 30 seconds takes 2+ minutes.

**Why it happens:**
Ollama loads one model instance and handles parallel requests by expanding context size (each parallel slot multiplies the context window by the number of parallel requests). On an M-series Mac with constrained unified memory, this means true parallelism is often memory-limited even if you increase `OLLAMA_NUM_PARALLEL`.

**How to avoid:**
Measure actual concurrency limits for your specific Mac hardware before designing the agent communication model. Configure:
```
OLLAMA_NUM_PARALLEL=2  # safe starting point for 16GB RAM
OLLAMA_MAX_LOADED_MODELS=1  # Gemma4 is large; don't try to load multiple models
```
Design agent workflows to minimize simultaneous blocking waits on Ollama. Use sequential agent handoff patterns (pipeline) rather than fan-out/fan-in where all agents wait for parallel completion.

**Warning signs:**
- Dashboard shows multiple agents "in progress" but only one advances at a time
- Ollama logs show a growing request queue
- `ollama ps` shows model thrashing (unload/reload cycles)

**Phase to address:**
Phase 1 (infrastructure setup) — benchmark Ollama concurrency on target hardware before designing any workflow topology.

---

### Pitfall 3: Error Accumulation Across Multi-Step Agent Chains

**What goes wrong:**
A small error in step 1 of an agent pipeline mutates into a catastrophic failure by step 8. An LLM agent anchors to its first interpretation and fails to correct course when subsequent information contradicts it. In a 10-step workflow where each agent achieves 90% accuracy, the compounded success probability is only 35%.

**Why it happens:**
Each agent in the chain receives the output of the previous agent as its context. LLMs have strong anchoring bias — they reason forward from what they've been given rather than questioning the premise. Without explicit validation gates, errors propagate silently.

**How to avoid:**
Insert explicit QA checkpoints at phase transitions rather than only at the end. Define what "correct output" looks like for each agent role with a structured schema. Make the QA agent compare against the original user requirement, not just the previous agent's output. Fail fast and re-route rather than continuing with degraded output.

**Warning signs:**
- Final output is coherent-sounding but diverges substantially from the original requirement
- QA agent finds no issues but Claude final verification rejects the output
- Agent logs show agents referencing "the plan" but the plan has quietly shifted from what was originally specified

**Phase to address:**
Phase 2 (agent role definition) — define validation schemas and QA checkpoints per agent role before connecting agents into a chain.

---

### Pitfall 4: Infinite Loop / Agent Deadlock (the "Mirror Mirror" failure)

**What goes wrong:**
Two agents with slightly conflicting instructions bounce the same task back and forth indefinitely — neither can accept the other's output because each interprets its role as requiring the other to change. The orchestration system consumes CPU and produces no output, and there is no automatic termination.

**Why it happens:**
Directive misalignment between roles (e.g., a QA agent that rejects any output it didn't validate, and a developer agent that won't submit to QA until development is "done") creates a circular dependency. Without iteration limits and escalation logic, the loop runs until killed by the user.

**How to avoid:**
Every agent task must carry a maximum iteration counter. Implement at the orchestration layer:
- Max 3 retries per agent per task before escalating to human review or Claude re-evaluation
- Timeout at the task level (e.g., 5 minutes per agent step) independent of retry count
- Circular dependency detection: if the same task ID appears in more than one agent's inbox simultaneously, flag it
- Explicit conflict resolution hierarchy: Claude CLI has final authority; no peer-agent disagreement can block indefinitely

**Warning signs:**
- Dashboard shows the same task in "in progress" state across multiple agents
- Log timestamps show the same task bouncing between agents with no state change
- Ollama request count climbs steadily without any file output being produced

**Phase to address:**
Phase 2 (orchestration logic) — build timeouts, max-retry limits, and escalation paths before any agent-to-agent task routing is enabled.

---

### Pitfall 5: Gemma4 Structured Output Unreliability

**What goes wrong:**
The orchestration system depends on Gemma4 agents returning well-formed JSON (or another structured format) to communicate task results, status, and handoff data. Smaller Gemma variants and base models produce valid intent but in inconsistent formats — sometimes JSON, sometimes XML, sometimes plain prose with the JSON embedded in a markdown code block. Parsers break, silent data loss occurs.

**Why it happens:**
Gemma models do not have a dedicated tool-use token. The 4B variant has a documented tool-call format bias regardless of prompt — it tends to emit tool calls even in purely conversational contexts. The 12B and 27B variants are significantly more reliable but still require explicit format enforcement.

**How to avoid:**
Never parse agent output with a strict parser that throws on malformed input. Use a two-pass approach:
1. Attempt strict parse (JSON.parse / Pydantic)
2. On failure, run a lightweight repair pass (extract JSON from markdown blocks, fix trailing commas)
3. Log every repair and monitor repair rate — if it exceeds 5%, tighten the prompt or use Ollama's `format: json` parameter

Use `format: json` in all Ollama API calls to enable constrained decoding where Gemma4 supports it. Provide a one-shot example in the system prompt showing exactly the expected output shape.

**Warning signs:**
- Agent handoff logs contain "parse error" or "unexpected token" entries
- Tasks stall at inter-agent boundaries but individual agents appear to complete
- Agent outputs are valid prose that describes what the JSON should look like rather than being actual JSON

**Phase to address:**
Phase 2 (agent role definition) — define and test structured output contracts for each agent role before wiring communication.

---

### Pitfall 6: File-Based Message Queue Race Conditions

**What goes wrong:**
Multiple agents write to the same shared message directory simultaneously. One agent reads a half-written JSON file from another agent. The reader gets a parse error or a partial message. The writing agent believes delivery succeeded. The task is silently dropped.

**Why it happens:**
File writes are not atomic by default. `open(path, 'w')` followed by `write()` creates a window where the file exists but contains incomplete data. Any concurrent reader polling the directory during this window sees a corrupt file.

**How to avoid:**
Implement the `tmp + rename` pattern exclusively for all inter-agent message writes:
```python
# atomic write
tmp_path = f'{message_path}.tmp.{os.getpid()}'
with open(tmp_path, 'w') as f:
    json.dump(message, f)
os.rename(tmp_path, message_path)  # atomic on macOS/APFS
```
Use a file lock (via `fcntl.flock`) for any directory-level index or queue manifest file. Never write directly to the final destination path. Prefix files being written with `.draft.` and rename on completion.

**Warning signs:**
- Intermittent JSON parse errors in agent logs that don't reproduce on retry
- Agents occasionally report "no messages found" when the sender's log shows messages sent
- Message count in the queue directory doesn't match the count agents report receiving

**Phase to address:**
Phase 1 (infrastructure) — implement the atomic write protocol from the first message-passing commit. Do not prototype with simple file writes and plan to "fix later."

---

### Pitfall 7: Context Rot in Long-Running Agent Sessions

**What goes wrong:**
Gemma4 agents running multi-turn tasks degrade in reasoning quality as their context window fills. The model continues to produce output with full confidence but the quality measurably drops. Research across 18 frontier models confirms every model exhibits context rot at every context length increment — it is not a threshold effect, it is a continuous degradation.

**Why it happens:**
"Lost in the middle" — LLMs attend poorly to information in the middle of long contexts. As task history accumulates, earlier decisions (constraints, requirements, agreed conventions) slide into the middle of the context window and stop influencing generation.

**How to avoid:**
Design agents with bounded context sessions. Each agent role should maintain only a rolling window of recent messages plus a distilled summary of earlier decisions. When a task requires more than ~10 back-and-forth turns with a single agent, break it into sub-tasks with fresh sessions that inherit only the structured summary.

Use the Planner/Executor pattern: the PM agent (기획자) maintains a structured task state file on disk, not in LLM context. Each agent reads current state from the file rather than relying on conversation history.

**Warning signs:**
- Agent output late in a long task contradicts a constraint it acknowledged early in the same task
- Agents start producing generic outputs that match the role description rather than the specific task
- QA agent acceptance rate drops as the session progresses even though requirements haven't changed

**Phase to address:**
Phase 2-3 — architect agent session management with context limits from the start. Do not defer to "optimize later."

---

### Pitfall 8: Hallucinated Consensus (QA Rubber-Stamping)

**What goes wrong:**
The QA agent validates developer or designer outputs as correct when they contain fundamental errors. This is not a simple miss — it is a systematic failure where the QA LLM inherits the same misunderstanding as the generator. Multiple agents converge on a shared fabrication and reinforce it.

**Why it happens:**
When the QA agent receives the developer's output in its context, it anchors to that output as the reference truth. LLM-as-judge systems have documented confirmation bias: the verifier reproduces the errors of the original generation because it reasons from the same (flawed) premises. The QA agent is essentially asked "is this right?" by someone who is confident it is right.

**How to avoid:**
The QA agent must receive the original user requirement independently — never only the agent's output. Structure QA prompts as: "Given this original requirement [X], does this deliverable [Y] satisfy it?" rather than "Is this deliverable correct?"

For code outputs specifically, run actual execution/compilation checks rather than asking the LLM to evaluate correctness. Linting and test execution are more reliable than LLM QA for code artifacts.

Claude's final verification has higher authority precisely because it has no exposure to the chain's intermediate outputs — preserve that independence by not feeding Claude the entire agent conversation history.

**Warning signs:**
- QA passes everything on the first attempt — this is suspicious, not good
- Claude final verification consistently rejects outputs that QA approved
- QA agent explanations repeat the same language as the developer agent's output

**Phase to address:**
Phase 2 (QA agent design) — define what artifacts and context the QA agent receives. This is as important as what it is asked to verify.

---

### Pitfall 9: WebSocket State Management and Update Flooding

**What goes wrong:**
The real-time dashboard floods React state with raw WebSocket messages — every agent log line triggers a `setState` call, every token triggers a re-render. The dashboard becomes unresponsive at exactly the moment when most events are happening (during active agent execution).

**Why it happens:**
The developer implements WebSocket message handling by pushing each message directly to React state. This works perfectly during testing with a single slow agent. Under load with 4 concurrent agents generating interleaved log events, React processes hundreds of state updates per second.

**How to avoid:**
Batch incoming WebSocket messages. Accumulate messages over a 100-150ms window, then flush to state in a single update. Use `useReducer` instead of `useState` for complex agent state to avoid derived-state inconsistency. Virtualize log lists (react-window or similar) — never render all historical log entries as DOM nodes.

Separate agent status state (low frequency, needs to be current) from log stream state (high frequency, displayable with slight lag) and update them on different intervals.

**Warning signs:**
- Dashboard works fine with 1 agent, becomes sluggish with 3-4
- Browser profiler shows React render consuming >50ms of main thread repeatedly
- Scrolling the log panel stutters during active execution

**Phase to address:**
Phase 3 (dashboard development) — implement batched update architecture from the start, before the log volume problem becomes visible.

---

### Pitfall 10: Claude CLI Cannot Spawn Sub-Agents

**What goes wrong:**
The architecture assumes Claude CLI can act as orchestrator and dynamically dispatch sub-agents. In fact, Claude CLI subagents cannot spawn further subagents — this is a hard architectural constraint, not a configuration issue. Designs that rely on Claude spinning up Gemma4 workers dynamically will not work.

**Why it happens:**
Developers assume Claude CLI's subprocess model mirrors API capabilities. The constraint exists by design (to limit resource usage). It is not documented prominently and is discovered mid-implementation.

**How to avoid:**
Separate the orchestration control plane from Claude CLI. Claude CLI provides the judgment layer (analysis, direction-setting, final verification). A separate orchestrator process (Python/Node.js) manages actual agent lifecycle — spawning Ollama API calls, managing message queues, routing tasks. Claude CLI communicates with this orchestrator via its tool/file interface, not by directly spawning processes.

**Warning signs:**
- Initial design diagrams show Claude CLI at the center of a hub-and-spoke with arrows pointing to each worker
- Implementation attempts to call subprocess from within a Claude CLI session
- Unexpected permission errors or silent failures when Claude tries to initiate Ollama sessions

**Phase to address:**
Phase 1 (architecture design) — define the separation between Claude CLI (judgment) and the orchestration runtime (process management) before any code is written.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Simple file writes without atomic rename | Faster to implement | Silent message loss under concurrent writes | Never — implement atomic writes from day one |
| Polling-based agent status checks | No WebSocket complexity | 100ms-1s status lag, unnecessary I/O load | Only during initial prototyping, remove before any multi-agent test |
| Plain text inter-agent messages (no schema) | No schema design overhead | Parsing failures cascade into agent confusion | Only in single-agent smoke test, never cross-agent |
| Single Ollama session for all agents | Simpler setup | Serialized execution, all agents blocked by one slow task | Never if any form of concurrency is needed |
| Keeping full conversation history in agent context | Simpler state management | Context rot, performance degradation on long tasks | Prototype only, max 5-turn tasks |
| No max-retry/timeout on agent tasks | Simpler orchestration | Infinite loops consume all resources with no output | Never — always set hard limits |
| Claude receives full agent chain history for final verification | More context seems better | Claude's independent judgment polluted by chain's biases | Never — Claude should receive requirement + deliverable only |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Claude CLI as subprocess | Spawning new process per task | Long-lived process in `stream-json` mode, one process per workflow |
| Claude CLI subprocess | Inheriting global ~/.claude config | Explicitly set `--setting-sources project,local`, empty `--plugin-dir` |
| Ollama API | Assuming parallel requests run concurrently | Check `OLLAMA_NUM_PARALLEL` setting, benchmark actual throughput on target hardware |
| Ollama concurrent models | Loading multiple Gemma4 variants simultaneously | Set `OLLAMA_MAX_LOADED_MODELS=1` on memory-constrained Macs, use single model variant |
| Gemma4 structured output | Using strict JSON parser on raw output | Two-pass parse with repair; use Ollama `format: json` parameter |
| File-based message queue | Writing files in-place | Always use tmp-file + atomic rename pattern |
| WebSocket to React dashboard | setState on every message | Batch updates in 100-150ms windows before flushing to state |

---

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Re-injecting full Claude config every subprocess turn | 10-30s latency before any real work, rapid token depletion | Long-lived subprocess, config isolation | Immediately on first multi-step task |
| Ollama request queue buildup | Agents appear active but no output; Ollama CPU pegged | Configure `OLLAMA_NUM_PARALLEL`, use sequential handoff not fan-out | When 3+ agents submit requests within 60 seconds |
| Unbounded agent log accumulation in dashboard state | Dashboard slows and eventually freezes during active runs | Virtualized lists, log pagination/truncation, separate log store | When cumulative log entries exceed ~1000 in a session |
| Full agent chain history passed to each new agent | Context window exhausted mid-task; agent reasoning degrades | Structured state files on disk; agents read current state, not full history | After ~5 agent handoffs in a single workflow |
| Polling shared message directory at high frequency | macOS filesystem I/O load spikes; battery drain on MacBook | Use `fs.watch` / `watchdog` for change events instead of polling intervals | When >3 agents poll simultaneously at <500ms intervals |

---

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Agents writing output files with no path validation | Agent writes to arbitrary filesystem path (path traversal via LLM hallucination) | Validate all output paths are within the designated project output directory before writing |
| Forwarding raw user input directly to agent system prompt | Prompt injection — user instruction hijacks agent role | Sanitize and structure user input; keep user instruction in a clearly-bounded section of the prompt |
| Sharing a single Ollama endpoint between orchestrator and agents with no authentication | Any local process can submit requests and manipulate agent state | Not critical for local-only dev setup, but log all Ollama requests for audit |
| Storing full Claude session including user data in accessible log files | Sensitive project content exposed in plaintext logs | Define what gets logged; exclude raw content, log only metadata (task IDs, status, timestamps) |

---

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| No intermediate progress indication during long agent tasks | User sees spinner for 3-5 minutes, no indication of whether system is working | Stream agent status changes in real-time; show which agent is active, what subtask it is on |
| Showing raw LLM output in dashboard | Confusing internal reasoning, incomplete JSON, error traces visible to user | Show only structured task status and final deliverable links; put raw logs in collapsible debug section |
| Silent failure when an agent task exceeds timeout | User waits indefinitely, no feedback | Surface timeout and failure events prominently; show retry count, provide manual re-trigger option |
| No way to inspect why Claude rejected an output and re-triggered work | User sees task loop without understanding why | Expose Claude's final verification reasoning as a visible "review note" on the dashboard |
| Dashboard does not survive page refresh (ephemeral WebSocket state only) | Reload loses all agent history for the current session | Persist task state and log history to disk/DB; dashboard is a view over persisted state, not the source of truth |

---

## "Looks Done But Isn't" Checklist

- [ ] **Agent communication:** Messages appear to send and receive — verify atomic write is implemented, check for any race condition with concurrent writers
- [ ] **Ollama concurrency:** Multiple agents appear to run — verify they are actually executing in parallel, not serializing through a single Ollama slot (check `ollama ps` during load)
- [ ] **Claude CLI subprocess isolation:** Orchestrator runs without errors — verify token consumption per turn is not including global config re-injection (measure tokens on first turn vs. fifth turn of same subprocess)
- [ ] **QA agent:** QA approves all test runs — verify QA is receiving original requirements, not only developer output; check if QA passes deliberately introduced errors
- [ ] **Dashboard real-time updates:** Dashboard shows updates during single-agent test — verify performance under 4 concurrent agents with high log volume; profile React render frequency
- [ ] **File output:** Agents produce files in the correct location — verify paths are validated against the output directory; test with a hallucinated path and confirm it is rejected
- [ ] **Timeout/retry logic:** Tasks complete successfully — verify tasks that never complete actually terminate within the defined timeout and escalate correctly
- [ ] **Context management:** Agents complete 5-turn tasks correctly — verify agents complete 15+ turn tasks without contradicting earlier decisions (context rot test)

---

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Claude config re-injection token explosion discovered late | MEDIUM | Implement subprocess isolation protocol; requires refactoring launch code but not architecture |
| Race conditions in file queue corrupted task state | HIGH | Halt all agents, audit message queue for partial files, replay from last confirmed checkpoint |
| Infinite agent loop consumed all Ollama capacity | LOW | Kill all Ollama processes, restart Ollama server, re-queue the stalled task with iteration limit set |
| Context rot caused agent to produce incorrect output that QA approved | MEDIUM | Re-run the specific agent task in a fresh session with distilled context; Claude re-verification catches the error |
| Claude CLI architectural constraint discovered after designing agent-spawning orchestration | HIGH | Redesign the control plane to separate Claude CLI (judgment) from external orchestrator (process management); this is a structural change |
| Dashboard state desync from actual agent state after page reload | LOW | Source of truth is always on-disk state; dashboard reconnects and replays from persisted state |

---

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Claude CLI token explosion (subprocess config inheritance) | Phase 1: Infrastructure | Measure tokens consumed on first turn of isolated subprocess vs. naive subprocess |
| Ollama serialization under concurrent load | Phase 1: Infrastructure | Benchmark 4 simultaneous Ollama requests on target Mac; record actual throughput |
| Claude CLI cannot spawn sub-agents | Phase 1: Architecture design | Architecture diagram must show external orchestrator separate from Claude CLI |
| File queue race conditions | Phase 1: Infrastructure | Concurrent write stress test — 4 agents writing to queue simultaneously for 60 seconds, verify zero parse errors |
| Structured output unreliability (Gemma4) | Phase 2: Agent role definition | Each agent role contract has a defined output schema; parse failure rate test before integration |
| Error accumulation across agent chains | Phase 2: Orchestration logic | End-to-end test with deliberate 10% error introduced at step 1; verify error is caught at next QA gate |
| Infinite loop / deadlock | Phase 2: Orchestration logic | Test: create two agents with conflicting instructions; verify task escalates and terminates within timeout |
| Context rot in long sessions | Phase 2-3: Agent session design | Test: 20-turn task where step 1 establishes a constraint; verify step 20 output still respects that constraint |
| QA rubber-stamping / hallucinated consensus | Phase 2: QA agent design | Test: submit deliberately incorrect output to QA agent; verify rejection rate >90% |
| WebSocket update flooding | Phase 3: Dashboard | Profile React renders during 4-agent concurrent run; require <50ms render budget |
| Dashboard ephemeral state | Phase 3: Dashboard | Reload page mid-run; verify all agent state and logs are restored from persisted store |

---

## Sources

- [Building a 24/7 Claude Code Wrapper? Here's Why Each Subprocess Burns 50K Tokens](https://dev.to/jungjaehoon/why-claude-code-subagents-waste-50k-tokens-per-turn-and-how-to-fix-it-41ma) — Claude CLI subprocess token overhead (HIGH confidence, specific measurements)
- [When AI Agents Collide: Multi-Agent Orchestration Failure Playbook for 2026](https://cogentinfo.com/resources/when-ai-agents-collide-multi-agent-orchestration-failure-playbook-for-2026) — infinite loops, hallucinated consensus, resource deadlocks (HIGH confidence)
- [Why Your Multi-Agent System is Failing: Escaping the 17x Error Trap](https://towardsdatascience.com/why-your-multi-agent-system-is-failing-escaping-the-17x-error-trap-of-the-bag-of-agents/) — error accumulation, coordination tax (HIGH confidence)
- [Ollama FAQ — Concurrency and Parallel Requests](https://docs.ollama.com/faq) — official Ollama concurrency limits and configuration (HIGH confidence)
- [How Ollama Handles Parallel Requests](https://www.glukhov.org/post/2025/05/how-ollama-handles-parallel-requests/) — memory expansion under parallel load (MEDIUM confidence)
- [Ollama Does Not Utilize Multiple Instances for Parallel Processing (GitHub Issue #9054)](https://github.com/ollama/ollama/issues/9054) — confirmed serialization behavior (HIGH confidence)
- [Agent-to-Agent Communication: Shared File Protocols Guide](https://fast.io/resources/agent-to-agent-file-communication-protocols/) — atomic write requirements (MEDIUM confidence)
- [Why Do Multi-Agent LLM Systems Fail?](https://arxiv.org/html/2503.13657v1) — systematic analysis, coordination tax at 36.9% (HIGH confidence, peer-reviewed)
- [Context Window Overflow in 2026: Fix LLM Errors Fast](https://redis.io/blog/context-window-overflow/) — context rot patterns (MEDIUM confidence)
- [Context Rot: Why LLMs Degrade as Context Grows](https://www.morphllm.com/context-rot) — performance degradation mechanics (MEDIUM confidence)
- [google/gemma-3-27b-it Tool Usage Discussion](https://huggingface.co/google/gemma-3-27b-it/discussions/8) — Gemma tool use format reliability (MEDIUM confidence)
- [The JSON Parsing Problem That's Killing Your AI Agent Reliability](https://dev.to/the_bookmaster/the-json-parsing-problem-thats-killing-your-ai-agent-reliability-4gjg) — structured output failure modes (MEDIUM confidence)
- [Multi-Agent Communication Patterns That Actually Work](https://dev.to/aureus_c_b3ba7f87cc34d74d49/multi-agent-communication-patterns-that-actually-work-50kp) — file-based queue patterns (MEDIUM confidence)
- [Multi-Agent Orchestration: Running 10+ Claude Instances in Parallel (Part 3)](https://dev.to/bredmond1019/multi-agent-orchestration-running-10-claude-instances-in-parallel-part-3-29da) — Claude CLI orchestration architecture lessons (MEDIUM confidence)
- [Mitigating LLM Hallucinations Using a Multi-Agent Framework](https://www.mdpi.com/2078-2489/16/7/517) — QA agent confirmation bias (HIGH confidence, peer-reviewed)

---

*Pitfalls research for: AI multi-agent collaboration system (Claude CLI orchestrator + Gemma4/Ollama workers, local macOS)*
*Researched: 2026-04-03*

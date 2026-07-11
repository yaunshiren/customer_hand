---
name: agent-architecture-review
description: Use when reviewing or changing the FastAPI + LangGraph Agent architecture, routing, state, memory, RAG, tools, Reviewer, HumanGate, trace flow, tenant boundaries, or when preparing an evidence-based architecture explanation. Do not edit files unless explicitly asked.
---

# Agent Architecture Review Skill

Use this skill to review the architecture of the FastAPI + LangGraph vertical customer-service Agent.

The goal is to keep the system explainable, testable, traceable, secure, bounded, and suitable for an enterprise pilot MVP.

## Repository instructions

- Follow all applicable `AGENTS.md` files before using this skill.
- This skill may add stricter task-specific rules, but must not weaken repository security, testing, command, or Git restrictions.
- When rules conflict, follow the stricter rule.
- Do not modify files unless the user explicitly authorizes implementation.
- Work on one independently testable and reversible task at a time.

## When to use

Use this skill when the task involves:

- Agent architecture selection
- LangGraph versus handwritten orchestration
- workflow versus supervisor / master-subAgent
- single Agent versus multi-Agent
- routing and state transitions
- initial request versus multi-turn continuation
- ProductContext or DiagnosticContext
- RAG and tool-calling boundaries
- Reviewer or HumanGate
- trace / eval integration points
- dependency degradation behavior
- tenant-aware state, memory, ticket, tracker, or trace design
- architecture documentation or interview explanations

## Read first

Inspect the relevant files before making conclusions:

- `app/agent/graph/builder.py`
- `app/agent/graph/state.py`
- `app/agent/graph/node_*.py`
- `app/entry/guard.py`
- `app/entry/models.py`
- `app/entry/auth.py`
- `app/entry/authorization.py`, if present
- `app/tools/`
- `app/skills/`
- `app/rag/`
- `app/memory/`
- `app/tickets/`
- `app/persistence/`
- related tests and architecture documents

If a listed file does not exist, report that fact and inspect the closest existing implementation instead.

## Review steps

### 1. Identify the current architecture

Determine:

- Whether the graph is workflow-style, supervisor-style, or multi-Agent
- The main nodes and state transitions
- Which component resolves intent and route
- Which component calls RAG
- Which component calls tools
- Where memory is loaded and saved
- Where traces are recorded
- Where write actions leave the planning loop
- Whether the graph is bounded and recoverable

### 2. Evaluate the architecture choice

Explain:

- Why LangGraph is or is not justified
- Why a bounded workflow is or is not appropriate
- Whether a supervisor or multi-Agent design is actually necessary
- Whether module boundaries are clear
- Whether the graph can be tested node-by-node and transition-by-transition
- Whether failure paths are explicit and observable

Do not recommend multi-Agent architecture only for terminology or novelty.

### 3. Evaluate enterprise MVP boundaries

Check:

- Where authenticated `Principal`, tenant, owner, and authorization context enter the flow
- Whether client-provided sender, tenant, owner, role, or scope are treated as untrusted
- Whether `ProductContext` is strongly typed
- Whether `DiagnosticContext` has legal, bounded transitions
- Whether product-model-specific RAG filtering is enforced
- Whether Planner actions are constrained
- Whether Reviewer blocks unsupported, wrong-model, unsafe, or unconfirmed output
- Whether HumanGate handles dangerous symptoms, repeated failure, evidence conflict, and user-requested escalation
- Whether write actions require deterministic authorization, confirmation, and idempotency
- Whether Memory, Ticket, Tracker, and Trace are tenant-aware
- Whether dependency failures become explicit degraded or fail-safe states
- Whether high-risk paths fail closed

### 4. Check architecture risks

Look for:

- Hidden mutable state outside graph state
- Client-provided identity or tenant data treated as trusted
- LLM decisions used as authorization
- Writes executed directly from Planner output
- Unbounded diagnostic loops
- Reviewer failure defaulting to allow
- HumanGate state stored only in process memory
- Cross-model RAG retrieval
- Tool handlers containing domain logic
- Missing tests for transitions and rejection paths
- Missing trace on error and degraded paths
- Raw PII stored in logs or traces
- Memory-only state unsuitable for multi-instance deployment
- `main.py` containing orchestration or domain logic
- Resource access without tenant and owner scope

### 5. Separate fact from plan

Classify findings as:

- Implemented
- Partially implemented
- Planned but not implemented
- Not found
- Requires external verification

Do not treat design documents as implementation evidence.

## Output format

Return:

1. Architecture summary
2. Current mode: workflow / supervisor / multi-Agent
3. Evidence and files inspected
4. Why the current mode fits or does not fit the business
5. Major strengths
6. Enterprise MVP gaps
7. Security and reliability risks
8. Recommended incremental refactor plan
9. Files likely affected
10. Tests and acceptance criteria
11. Rollback considerations
12. Optional interview explanation, only when requested

## Do not

- Do not rewrite the graph unless explicitly asked.
- Do not introduce multi-Agent only for buzzwords.
- Do not remove tests or weaken assertions.
- Do not claim production-readiness without evidence for identity, tenant isolation, idempotency, PII handling, observability, deployment, and recovery.
- Do not describe planned ProductContext, Reviewer, HumanGate, or tenant isolation as implemented.
- Do not allow the LLM to decide authorization or write permission.

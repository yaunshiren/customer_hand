---
name: agent-architecture-review
description: Use when reviewing or changing the LangGraph Agent architecture, routing, memory, RAG, tool calling, state transitions, trace flow, or when preparing interview-ready architecture explanations. Do not edit files unless explicitly asked.
---

# Agent Architecture Review Skill

You are reviewing a FastAPI + LangGraph vertical customer service Agent project. The goal is to keep the project explainable, testable, traceable, and suitable for production-like backend engineering.

## When to use

Use this skill when the user asks about:

- Agent architecture selection
- LangGraph vs self-built framework
- workflow vs supervisor / master-subAgent
- single Agent vs multi-Agent
- routing mechanism
- initial request vs multi-turn continuation
- state management
- RAG and tool calling boundaries
- trace / eval integration points

## Review steps

1. Read these files first:
   - `app/agent/graph/builder.py`
   - `app/agent/graph/state.py`
   - `app/agent/graph/node_*.py`
   - `app/entry/guard.py`
   - `app/entry/models.py`
   - `app/tools/`
   - `app/rag/`
   - `app/memory/`
   - `app/persistence/`

2. Identify the current architecture:
   - Is it workflow-style, supervisor-style, or multi-Agent?
   - What are the main nodes?
   - Which node decides route?
   - Which node calls RAG?
   - Which node calls tools?
   - Where are traces recorded?
   - Where is memory loaded and saved?

3. Evaluate architecture decisions:
   - Why LangGraph is used instead of handwritten if-else orchestration.
   - Why workflow is preferred for bounded customer service tasks.
   - When supervisor + subAgent would become necessary.
   - Whether module boundaries are clear.
   - Whether the current graph is easy to test and debug.

4. Check risks:
   - Hidden state outside graph state.
   - `main.py` containing too much orchestration logic.
   - Tool handler directly containing domain logic.
   - Missing tests for route transitions.
   - Missing trace on error paths.
   - Memory-only state not suitable for multi-instance deployment.

## Output format

Return:

1. Architecture summary
2. Current mode: workflow / supervisor / multi-Agent
3. Why this mode fits or does not fit the business scenario
4. Major strengths
5. Risks and production gaps
6. Recommended refactor plan
7. Files likely affected
8. Interview explanation draft

## Do not

- Do not rewrite the graph unless explicitly asked.
- Do not introduce multi-Agent only for buzzwords.
- Do not remove existing tests.
- Do not claim production-readiness unless state, auth, idempotency, observability, and deployment are actually production-like.

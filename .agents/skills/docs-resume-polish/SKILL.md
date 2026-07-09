---
name: docs-resume-polish
description: Use when updating README, architecture docs, interview notes, project descriptions, resume bullets, or when converting implementation details into interview-ready engineering explanations.
---

# Docs and Resume Polish Skill

This skill helps turn code implementation into clear engineering documentation and resume language.

## When to use

Use this skill when:

- Updating README.
- Writing `docs/*.md`.
- Writing interview Q&A.
- Summarizing architecture decisions.
- Writing resume bullet points.
- Explaining trade-offs and production gaps.

## Documentation principles

1. Be specific. Avoid vague phrases like “optimized the system” without explaining how.
2. Separate facts, design choices, and future improvements.
3. Do not overclaim production-readiness.
4. Use architecture diagrams or text flows where helpful.
5. Include key paths and commands.
6. Include limitations and next steps.
7. Tie implementation to interview keywords:
   - LangGraph
   - RAG
   - Tool Calling
   - Tool Schema
   - Entry Guard
   - Trace
   - Eval
   - Badcase
   - Idempotency
   - Rate limit
   - Prompt Injection

## Resume writing rules

Use this structure:

- Action + technical object + business purpose + measurable/observable result.

Good example:

“基于 LangGraph 将上下文加载、意图理解、路由决策、RAG 检索、工具调用和响应生成拆分为独立节点，提升复杂任务链路的可维护性与可追踪性。”

Avoid:

“使用 LangGraph 实现智能客服。”

## Output format

When polishing a section, provide:

1. Current weakness
2. Improved version
3. Why it is stronger
4. Possible interview follow-up questions
5. Honest limitations

## Do not

- Do not fabricate metrics.
- Do not claim “production-grade” unless the implementation supports multi-instance state, secure auth, observability, and deployment controls.
- Do not hide the fact that some services are mock if they are still mock.

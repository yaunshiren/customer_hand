---
name: docs-resume-polish
description: Use when updating README, architecture docs, interview notes, project descriptions, resume bullets, or converting implementation details into evidence-based engineering explanations.
---

# Docs and Resume Polish Skill

Use this skill to turn implementation details into clear, accurate engineering documentation and interview-ready language.

## Repository instructions

- Follow all applicable `AGENTS.md` files before using this skill.
- This skill may add stricter task-specific rules, but must not weaken repository security, testing, command, or Git restrictions.
- Do not modify files unless the user explicitly authorizes implementation.
- Never include real credentials, tokens, customer PII, or identifiable production traces.

## Learning and interview ownership

When Learning Mode is active:

1. Ask the user for a first draft before rewriting it.
2. Improve the user's explanation without replacing their understanding.
3. Map every important claim to code, tests, commands, or reports.
4. Remove claims the user cannot defend with evidence.
5. Generate likely interview follow-up questions.
6. Ask the user to answer those questions before providing a model answer.
7. Prefer a clear, defensible explanation over polished but vague wording.

## When to use

Use this skill when:

- Updating `README.md`
- Writing `docs/*.md`
- Writing architecture or security documents
- Writing interview Q&A
- Summarizing design decisions and trade-offs
- Writing project descriptions or resume bullets
- Explaining production gaps and enterprise MVP readiness
- Converting code evidence into a review or handoff document

## Documentation principles

1. Be specific and evidence-based.
2. Separate:
   - implemented
   - partially implemented
   - planned
   - externally provided but not verified
3. Do not overclaim production-readiness.
4. Reference concrete code paths, tests, commands, or reports when making technical claims.
5. Use architecture diagrams or text flows where they improve clarity.
6. Include limitations, assumptions, migration risks, and next steps.
7. Do not hide that a provider, integration, or workflow is mock or sandbox.
8. Do not call a design “enterprise-grade” only because it uses common enterprise technologies.
9. Security and reliability claims require implementation and verification evidence.
10. Generated metrics must come from actual scripts, tests, or reports.

## Enterprise MVP documentation rules

Do not describe the following as complete without code and test evidence:

- tenant and owner isolation
- resource-level authorization
- sender and Principal binding
- PII classification, retention, export, and deletion
- durable write idempotency
- confirmation and HumanGate
- readiness and dependency health
- metrics and alerts
- backup, restore, rollback, and release gates
- approved index manifest and rollback
- real business-provider integration

Prefer:

- “enterprise pilot MVP”
- “production-like”
- “implemented foundation”
- “partially implemented”
- “planned next phase”

Avoid “production-grade” unless release gates and recovery controls have actually been verified.

## Eval and report traceability

Evaluation and audit documents should include, when available:

- Git commit
- dataset name and version
- index manifest or collection version
- model and embedding configuration
- relevant feature flags
- execution time
- exact commands
- pass/fail/skip counts
- known environment limitations

Do not fabricate missing metadata.

## Resume writing rules

Use:

> Action + technical object + business purpose + measurable or observable result.

Good example:

> 基于 LangGraph 将上下文加载、意图理解、路由、RAG、工具调用与响应生成拆分为独立节点，使客服任务链路可测试、可追踪并支持受控降级。

Avoid:

> 使用 LangGraph 实现智能客服。

When no numerical metric exists, use an observable engineering result rather than inventing a number.

## Output format

When polishing content, provide:

1. Current weakness
2. Improved version
3. Evidence supporting the wording
4. Why the revision is stronger
5. Honest limitations
6. Possible interview follow-up questions
7. Claims that still require verification

## Do not

- Do not fabricate metrics.
- Do not claim tenant isolation, PII lifecycle, backup, recovery, or production-readiness without evidence.
- Do not conceal mock or sandbox services.
- Do not present a roadmap item as an implemented feature.
- Do not include real customer data, credentials, or raw sensitive trace samples.

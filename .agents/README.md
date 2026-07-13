# Repository Agent Skills

`AGENTS.md` contains repository-wide rules. Files under `.agents/skills/` contain task-specific workflows.

## Skill map

- `learning-pair-programming`: teaching, step-by-step implementation, interview preparation, and independent reproduction
- `agent-architecture-review`: LangGraph architecture, state, routing, Reviewer, HumanGate, and tenant-aware flow reviews
- `entry-guard-productionize`: authentication, authorization, sender binding, tenant context, rate limiting, idempotency, and entry security
- `tool-skill-development`: governed business Tool and Agent Skill design
- `eval-badcase-loop`: trace-driven eval, badcase classification, regression datasets, and handoff reports
- `docs-resume-polish`: evidence-based documentation, project explanations, and interview or resume wording

## Mode composition

Learning Mode can be combined with any task-specific skill.

Example:

```text
Use Learning Mode together with agent-architecture-review.
Do not modify files.
Guide me to trace the current graph and ask me to classify the architecture before giving your conclusion.
```

When rules conflict, follow the stricter rule. No skill may weaken the security, testing, command, or Git restrictions in the root `AGENTS.md`.

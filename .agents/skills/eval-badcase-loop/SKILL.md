---
name: eval-badcase-loop
description: Use when creating eval cases, running isolated evals, analyzing agent_trace/retrieval_trace/tool_trace, classifying badcases, generating reports, or producing reports/codex_handoff.md for the next improvement pass.
---

# Eval + Badcase Improvement Loop Skill

Use this skill to make Agent improvement repeatable and evidence-based:

`trace → badcase → eval case → diagnosis → Codex handoff → fix → rerun eval`

## Repository instructions

- Follow all applicable `AGENTS.md` files before using this skill.
- This skill may add stricter task-specific rules, but must not weaken repository security, testing, command, or Git restrictions.
- Do not modify files or run state-changing commands unless explicitly authorized.
- Work on one independently testable and reversible issue at a time.

## When to use

Use this skill when:

- Creating eval JSONL files
- Running Agent evaluation
- Exporting or classifying badcases
- Analyzing Agent, retrieval, or tool traces
- Generating a Markdown report
- Preparing a Codex handoff
- Checking prompt, tool, RAG, policy, or workflow regressions
- Evaluating authorization, confirmation, tenant isolation, Reviewer, HumanGate, or degradation behavior

## Required badcase taxonomy

Use the project taxonomy when it is stricter. Otherwise use:

### Agent and RAG

- `INTENT_ERROR`
- `ROUTE_ERROR`
- `RAG_MISS`
- `MODEL_SCOPE_MISMATCH`
- `ANSWER_UNGROUNDED`
- `CONTEXT_LOST`
- `FORMAT_ERROR`

### Tool and workflow

- `TOOL_SELECTION_ERROR`
- `TOOL_ARGUMENT_ERROR`
- `TOOL_FAILURE`
- `CONFIRMATION_BYPASS`
- `DUPLICATE_WRITE`
- `HUMAN_HANDOFF_MISS`
- `REVIEWER_MISS`
- `DEPENDENCY_DEGRADATION_ERROR`

### Security and privacy

- `AUTHENTICATION_ERROR`
- `AUTHORIZATION_ERROR`
- `SENDER_SPOOFING`
- `CROSS_TENANT_ACCESS`
- `UNSAFE_ACTION`
- `PII_LEAK`
- `PROMPT_INJECTION_RISK`

### Fallback

- `UNKNOWN`

Use `UNKNOWN` only when trace evidence is insufficient.

## Eval case format

Prefer one JSON object per line.

Example:

```json
{
  "case_id": "tool_001",
  "dataset_version": "cleaning_mvp_v1",
  "tenant_id": "eval_tenant_a",
  "principal_id": "eval_user_a",
  "user_input": "帮我查一下订单 O123 的物流",
  "expected_intent": "query_logistics",
  "expected_route": "tool",
  "expected_tool": "query_logistics",
  "expected_args": {"order_id": "O123"},
  "expected_doc_ids": [],
  "expected_authorization": "allow",
  "expected_confirmation": false,
  "expected_handoff": false,
  "expected_risk_level": "low",
  "expected_behavior": "调用物流查询工具并返回物流状态"
}
```

Use synthetic or approved test identities. Do not use real customer tenants, users, conversations, tokens, or PII.

## Loop steps

1. Collect evidence:
   - eval output
   - `agent_trace`
   - `retrieval_trace`
   - `tool_trace`
   - structured logs
   - exact commit, dataset, index, and configuration when available

2. Classify each failure:
   - What was expected?
   - What happened?
   - Which component failed?
   - What evidence supports the classification?
   - Is the issue deterministic, model-sensitive, environment-sensitive, or data-sensitive?

3. Add or update a regression eval case.

4. Implement one focused fix.

5. Run the smallest relevant isolated test and eval subset.

6. Compare with the previous baseline.

7. Produce or update:
   - `reports/eval_report.md`
   - `reports/badcases.jsonl`
   - `reports/codex_handoff.md`

8. The Codex handoff must include:
   - ranked issues
   - code and trace evidence
   - files likely affected
   - tests or eval cases to add
   - explicit acceptance criteria
   - known environment limitations
   - rollback considerations

## Report traceability

Reports should include, when available:

- Git commit
- dataset name and version
- index manifest or collection version
- model and embedding configuration
- feature flags
- execution timestamp
- exact commands
- exit codes
- pass/fail/skip counts
- previous baseline
- known unverified dependencies

Do not fabricate missing values.

## Acceptance criteria for any fix

- Tests directly related to the task pass in an isolated test environment.
- Exact commands, exit codes, and pass/fail/skip counts are reported.
- Full `pytest -q` is run only when explicitly authorized and confirmed not to access real services.
- Relevant existing eval metrics do not regress without explanation.
- Every new badcase has a regression test or eval case.
- Trace still contains enough PII-safe evidence for diagnosis.
- No write path bypasses authorization, confirmation, or durable idempotency.
- No security regression is hidden by lowering thresholds or changing expected output.
- Metrics are computed from actual outputs.

## Do not

- Do not tune a prompt based on one badcase without regression evaluation.
- Do not change multiple unrelated components in one repair pass.
- Do not invent metrics.
- Do not mark a case fixed without a test or eval case.
- Do not change expected results merely to match current behavior.
- Do not run full test, migration, indexing, Docker, or external-provider commands without authorization.
- Do not store raw customer data in eval files or reports.

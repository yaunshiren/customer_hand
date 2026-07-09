---
name: eval-badcase-loop
description: Use when creating eval cases, running evals, analyzing agent_trace/retrieval_trace/tool_trace, classifying badcases, generating reports, or producing reports/codex_handoff.md for the next improvement pass.
---

# Eval + Badcase Improvement Loop Skill

This skill turns Agent improvement into a repeatable loop:

`trace → badcase → eval case → diagnosis → Codex handoff → fix → rerun eval`

## When to use

Use this skill when:

- Creating eval JSONL files.
- Running Agent evaluation.
- Exporting badcases.
- Classifying failures.
- Generating a markdown report.
- Preparing a Codex handoff for the next repair task.
- Checking whether a prompt/tool/RAG change regressed other scenarios.

## Required badcase taxonomy

Use these categories unless the project defines a stricter set:

- `INTENT_ERROR`: intent classification is wrong.
- `ROUTE_ERROR`: route decision is wrong.
- `RAG_MISS`: relevant document was not retrieved.
- `ANSWER_UNGROUNDED`: answer is not supported by retrieved context.
- `TOOL_SELECTION_ERROR`: wrong tool selected.
- `TOOL_ARGUMENT_ERROR`: selected tool is right but arguments are missing or wrong.
- `TOOL_FAILURE`: tool handler failed or timed out.
- `CONTEXT_LOST`: multi-turn state or slot was lost.
- `UNSAFE_ACTION`: unsafe / unauthorized operation was attempted.
- `PROMPT_INJECTION_RISK`: prompt injection or jailbreak was not handled correctly.
- `FORMAT_ERROR`: model output format violates schema.
- `UNKNOWN`: insufficient evidence.

## Eval case format

Prefer JSONL with one object per case:

```json
{
  "case_id": "tool_001",
  "user_input": "帮我查一下订单 O123 的物流",
  "expected_intent": "query_logistics",
  "expected_route": "tool",
  "expected_tool": "query_logistics",
  "expected_args": {"order_id": "O123"},
  "expected_doc_ids": [],
  "expected_behavior": "调用物流查询工具并返回物流状态"
}
```

## Loop steps

1. Collect evidence:
   - eval output
   - `agent_trace`
   - `retrieval_trace`
   - `tool_trace`
   - logs

2. Classify each failure:
   - What was expected?
   - What happened?
   - Which component failed?
   - What trace evidence supports the classification?

3. Generate or update eval cases.

4. Run eval again.

5. Produce or update:
   - `reports/eval_report.md`
   - `reports/badcases.jsonl`
   - `reports/codex_handoff.md`

6. For Codex repair, always provide:
   - ranked issues
   - evidence
   - files likely affected
   - tests to add
   - acceptance criteria

## Acceptance criteria for any fix

- `pytest -q` passes.
- Existing eval metrics do not regress without explanation.
- New badcase has a regression test or eval case.
- Trace still contains enough evidence for diagnosis.
- No high-risk tool path bypasses confirmation or idempotency.

## Do not

- Do not tune prompt based on one badcase without running regression eval.
- Do not change multiple unrelated components in one repair pass.
- Do not invent metrics; compute them from eval output.
- Do not mark a case fixed without a test or eval case.

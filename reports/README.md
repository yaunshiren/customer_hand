# Eval Reports

`python scripts/run_agent_eval.py` writes the following runtime artifacts here:

- `eval_report.md`
- `eval_report.json`
- `badcases.jsonl`
- `codex_handoff.md`

Generated reports are intentionally ignored by Git because a real run can contain
trace-linked operational evidence. Only this README is committed. Before sharing a
report, review it for tenant data and other sensitive information even though the
runner removes raw user input, full answers, authorization data, API keys, common PII,
and raw tool parameters from report payloads.

The handoff is review input for a later repair round. It does not authorize Codex or
another agent to modify code automatically.

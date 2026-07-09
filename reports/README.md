# Reports

This directory stores generated evaluation artifacts.

Recommended files:

- `eval_report.md`: human-readable eval report.
- `eval_report.json`: machine-readable eval metrics.
- `badcases.jsonl`: failed eval cases with error_type and trace evidence.
- `codex_handoff.md`: focused handoff for Codex repair loop.

Typical loop:

```bash
python scripts/run_agent_eval.py
python scripts/export_badcases.py
python scripts/generate_codex_handoff.py --badcases reports/badcases.jsonl --output reports/codex_handoff.md
```

Then ask Codex:

```text
请使用 eval-badcase-loop skill，阅读 reports/codex_handoff.md。
先给修改计划，不要直接改代码。
```

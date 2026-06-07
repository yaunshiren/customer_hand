from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any


def default_badcase_report_path(project_root: str | Path | None = None, *, now: datetime | None = None) -> Path:
    base = Path(project_root) if project_root is not None else Path.cwd()
    stamp = (now or datetime.now()).strftime("%Y%m%d")
    return base / "docs" / f"badcase_report_{stamp}.md"


def write_badcase_report(
    records: Sequence[Any],
    output_path: str | Path,
    *,
    run_id: str | None = None,
    source_jsonl: str | Path | None = None,
    generated_at: datetime | None = None,
) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        render_badcase_markdown(
            records,
            run_id=run_id,
            source_jsonl=source_jsonl,
            generated_at=generated_at,
        ),
        encoding="utf-8",
    )
    return path


def render_badcase_markdown(
    records: Sequence[Any],
    *,
    run_id: str | None = None,
    source_jsonl: str | Path | None = None,
    generated_at: datetime | None = None,
) -> str:
    generated = generated_at or datetime.now()
    rows = list(records)
    error_counts = Counter(_field(row, "error_type") or "UNCLASSIFIED" for row in rows)
    hit_counts = Counter("hit" if _field(row, "is_hit") is True else "badcase" for row in rows)

    lines: list[str] = [
        f"# Badcase Report {generated.strftime('%Y-%m-%d')}",
        "",
        "## Summary",
        "",
        "| Item | Value |",
        "|---|---:|",
        f"| Run ID | `{_md(run_id or 'ALL')}` |",
        f"| Source JSONL | `{_md(str(source_jsonl))}` |" if source_jsonl else "| Source JSONL | `-` |",
        f"| Badcase rows | {len(rows)} |",
        f"| Rows with error_type | {sum(1 for row in rows if _field(row, 'error_type'))} |",
        f"| Rows marked miss | {hit_counts.get('badcase', 0)} |",
        "",
    ]

    lines.extend(
        [
            "## Error Type Distribution",
            "",
            "| Error Type | Count |",
            "|---|---:|",
        ]
    )
    if error_counts:
        for error_type, count in sorted(error_counts.items()):
            lines.append(f"| `{_md(error_type)}` | {count} |")
    else:
        lines.append("| `-` | 0 |")

    lines.extend(
        [
            "",
            "## Badcases",
            "",
        ]
    )

    if not rows:
        lines.append("No badcases matched the current filters.")
        lines.append("")
        return "\n".join(lines)

    by_error: dict[str, list[Any]] = defaultdict(list)
    for row in rows:
        by_error[_field(row, "error_type") or "UNCLASSIFIED"].append(row)

    for error_type in sorted(by_error):
        lines.extend(
            [
                f"### {error_type}",
                "",
                "| Case | Hit | Route | Trace | Expected Intent | Predicted Intent | Expected Docs | Retrieved Docs |",
                "|---|---|---|---|---|---|---|---|",
            ]
        )
        group = sorted(by_error[error_type], key=lambda item: str(_field(item, "case_id") or ""))
        for row in group:
            lines.append(
                "| "
                + " | ".join(
                    [
                        _md_cell(_field(row, "case_id")),
                        _md_cell(_hit_label(_field(row, "is_hit"))),
                        _md_cell(_field(row, "system_route")),
                        _md_cell(_field(row, "trace_id")),
                        _md_cell(_field(row, "expected_intent")),
                        _md_cell(_field(row, "predicted_intent")),
                        _md_cell(_join_list(_field(row, "expected_doc_ids"))),
                        _md_cell(_join_list(_field(row, "retrieved_doc_ids"))),
                    ]
                )
                + " |"
            )
        lines.append("")

        for row in group:
            case_id = _field(row, "case_id") or "-"
            lines.extend(
                [
                    f"#### Case `{_md(str(case_id))}`",
                    "",
                    f"- Question: {_md_inline(_field(row, 'question'))}",
                    f"- Answer: {_md_inline(_truncate(_field(row, 'answer'), 420))}",
                    "",
                ]
            )

    return "\n".join(lines)


def _field(row: Any, name: str) -> Any:
    if isinstance(row, dict):
        return row.get(name)
    return getattr(row, name, None)


def _hit_label(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    return "-"


def _join_list(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(item) for item in value) or "-"
    return str(value) or "-"


def _truncate(value: Any, limit: int) -> str:
    text = "" if value is None else str(value).strip()
    if not text:
        return "-"
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _md(value: Any) -> str:
    return str(value).replace("`", "'")


def _md_cell(value: Any) -> str:
    text = _truncate(value, 180)
    return _md(text).replace("|", "/").replace("\n", " ")


def _md_inline(value: Any) -> str:
    text = _truncate(value, 420)
    return _md(text).replace("\n", " ")

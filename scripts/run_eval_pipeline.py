from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAGENTEVAL_ROOT = PROJECT_ROOT.parent / "ragenteval-main"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(RAGENTEVAL_ROOT) not in sys.path:
    sys.path.insert(0, str(RAGENTEVAL_ROOT))

from app.persistence.eval_recorder import persist_eval_jsonl  # noqa: E402
from app.persistence.eval_report import default_badcase_report_path, write_badcase_report  # noqa: E402
from app.persistence.repositories import EvalRepository  # noqa: E402
from app.persistence.db import trace_db_session  # noqa: E402

KEY_METRICS = [
    "intent_top1",
    "hit@1",
    "hit@3",
    "hit@5",
    "recall@3",
    "recall@5",
    "mrr@10",
    "over_retrieval_rate",
    "ttft_p50_ms",
    "ttft_p95_ms",
    "total_p95_ms",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run customer_hand eval end-to-end: run, score, report, persist eval_record, export badcases.",
    )
    parser.add_argument(
        "--mode",
        default="system",
        choices=["combined", "rag", "system"],
        help="customer_hand eval mode. system tests /api/messages; rag tests /api/eval/rag; combined runs both.",
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="customer_hand service base URL.")
    parser.add_argument("--limit", type=int, default=20, help="Number of eval cases for a smoke run.")
    parser.add_argument("--all", action="store_true", help="Run all available cases after filters.")
    parser.add_argument("--start", type=int, default=0, help="Skip the first N cases.")
    parser.add_argument("--filter-intent", default=None, help="Only run one intent_l2.")
    parser.add_argument(
        "--runs-file",
        type=Path,
        default=None,
        help="Reuse an existing eval/runs/*.jsonl and skip calling the API.",
    )
    parser.add_argument("--with-ragas", action="store_true", help="Also run LLM-as-judge metrics.")
    parser.add_argument("--ragas-limit", type=int, default=None, help="Only judge first N records for RAGAS.")
    parser.add_argument("--ragas-n", type=int, default=1, help="Run RAGAS N times and average.")
    parser.add_argument("--no-report", action="store_true", help="Skip ragenteval report.md/csv/slides generation.")
    parser.add_argument("--theme", default="swiss", choices=["swiss", "magazine"], help="Report slide theme.")
    parser.add_argument("--no-badcases", action="store_true", help="Skip eval_record persistence and badcase report.")
    parser.add_argument("--badcase-limit", type=int, default=100, help="Maximum badcases exported to markdown.")
    parser.add_argument("--badcase-output", type=Path, default=None, help="Output path for docs/badcase_report_*.md.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _ensure_ragenteval_available()

    runs_file = _resolve_runs_file(args.runs_file) if args.runs_file else None
    if runs_file is None:
        runs_file = _run_customer_hand_eval(args)
    else:
        print(f"[1/4] reuse runs file: {_display_path(runs_file)}")
    _assert_system_eval_contexts(runs_file)

    print("[2/4] score metrics")
    from eval.rag.pipeline.score import score

    scored_runs_file, metrics = score(
        runs_file=runs_file,
        skip_ragas=not args.with_ragas,
        ragas_limit=args.ragas_limit,
        ragas_n=args.ragas_n,
    )
    runs_file = scored_runs_file
    scores_path = _scores_path_for(runs_file)

    report_dir = _report_dir_for(runs_file)
    if args.no_report:
        print("[3/4] skip ragenteval report")
    else:
        print("[3/4] generate ragenteval report")
        _generate_ragenteval_report(runs_file, theme=args.theme)

    badcase_report_path: Path | None = None
    if args.no_badcases:
        print("[4/4] skip eval_record and badcase report")
    else:
        print("[4/4] persist eval_record and export badcases")
        badcase_report_path = _persist_and_export_badcases(
            runs_file,
            limit=args.badcase_limit,
            output_path=args.badcase_output,
        )

    _print_final_summary(
        runs_file=runs_file,
        scores_path=scores_path,
        report_dir=report_dir,
        badcase_report_path=badcase_report_path,
        metrics=metrics,
    )
    return 0


def _ensure_ragenteval_available() -> None:
    if not RAGENTEVAL_ROOT.exists():
        raise RuntimeError(f"ragenteval-main not found: {RAGENTEVAL_ROOT}")


def _run_customer_hand_eval(args: argparse.Namespace) -> Path:
    from eval.common.schemas import load_samples
    from eval.rag.pipeline.customer_hand_runner import EVAL_SET_PATH, run

    os.environ["CUSTOMER_HAND_BASE_URL"] = args.base_url.rstrip("/")
    limit = args.limit
    if args.all:
        samples = load_samples(EVAL_SET_PATH)
        if args.filter_intent:
            samples = [sample for sample in samples if sample.intent_l2 == args.filter_intent]
        if args.mode == "rag":
            samples = [sample for sample in samples if sample.requires_rag]
        limit = max(1, len(samples) - args.start)

    print(
        "[1/4] run eval "
        f"mode={args.mode} limit={limit} start={args.start} base_url={args.base_url.rstrip('/')}"
    )
    return run(
        limit=limit,
        start=args.start,
        filter_intent=args.filter_intent,
        mode=args.mode,
    )


def _generate_ragenteval_report(runs_file: Path, *, theme: str) -> None:
    from argparse import Namespace
    from eval.common.cli import cmd_report

    result = cmd_report(Namespace(runs_file=runs_file, theme=theme, only_slides=False))
    if result != 0:
        raise RuntimeError("ragenteval report generation failed")


def _persist_and_export_badcases(runs_file: Path, *, limit: int, output_path: Path | None) -> Path:
    summary = persist_eval_jsonl(runs_file, run_id=runs_file.stem)
    out_path = output_path or default_badcase_report_path(PROJECT_ROOT)

    with trace_db_session() as session:
        records = EvalRepository(session).list_badcases(run_id=summary.run_id, limit=limit)
        _assert_badcases_attributed(records)
        write_badcase_report(
            records,
            out_path,
            run_id=summary.run_id,
            source_jsonl=runs_file,
        )

    print(
        "  eval_record: "
        f"run_id={summary.run_id} total={summary.total} saved={summary.saved} badcases={summary.badcases}"
    )
    print(f"  badcases:    {_display_path(out_path)}")
    return out_path


def _assert_system_eval_contexts(runs_file: Path) -> None:
    missing: list[str] = []
    with runs_file.open("r", encoding="utf-8") as file:
        for line in file:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("eval_mode") != "system":
                continue
            retrieved_doc_ids = row.get("retrieved_doc_ids") or []
            retrieved_contexts = row.get("retrieved_contexts") or []
            if retrieved_doc_ids and not retrieved_contexts:
                missing.append(str(row.get("query_id") or row.get("case_id") or "?"))
    if missing:
        preview = ", ".join(missing[:10])
        raise RuntimeError(
            "system eval JSONL has retrieved_doc_ids but missing retrieved_contexts for "
            f"{len(missing)} case(s): {preview}"
        )


def _assert_badcases_attributed(records: Sequence[Any]) -> None:
    missing = [
        str(getattr(record, "case_id", "?"))
        for record in records
        if not getattr(record, "error_type", None)
    ]
    if missing:
        preview = ", ".join(missing[:10])
        raise RuntimeError(f"badcases missing error_type attribution: {preview}")


def _resolve_runs_file(raw: Path) -> Path:
    from eval.rag.pipeline.score import RUNS_DIR

    candidates = [
        raw,
        RAGENTEVAL_ROOT / raw,
        RUNS_DIR / raw.name,
        RUNS_DIR / f"{raw.name}.jsonl" if raw.suffix == "" else RUNS_DIR / raw.name,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    raise FileNotFoundError(f"runs file not found: {raw}")


def _scores_path_for(runs_file: Path) -> Path:
    from eval.rag.pipeline.score import REPORTS_DIR

    return REPORTS_DIR / runs_file.stem / "_scores.json"


def _report_dir_for(runs_file: Path) -> Path:
    from eval.rag.pipeline.score import REPORTS_DIR

    return REPORTS_DIR / runs_file.stem


def _print_final_summary(
    *,
    runs_file: Path,
    scores_path: Path,
    report_dir: Path,
    badcase_report_path: Path | None,
    metrics: Sequence[Any],
) -> None:
    by_name = {getattr(metric, "name", ""): metric for metric in metrics}
    print("")
    print("=== Eval Summary ===")
    print(f"runs_file:   {_display_path(runs_file)}")
    print(f"scores_json: {_display_path(scores_path)}")
    print(f"report_dir:  {_display_path(report_dir)}")
    if badcase_report_path is not None:
        print(f"badcases:    {_display_path(badcase_report_path)}")
    print("")
    print("metric                  value")
    print("----------------------  -------")
    for name in KEY_METRICS:
        metric = by_name.get(name)
        if metric is None:
            continue
        print(f"{name:<22}  {_format_metric(metric)}")


def _format_metric(metric: Any) -> str:
    value = getattr(metric, "overall", None)
    if value is None:
        return "-"
    if str(getattr(metric, "name", "")).endswith("_ms"):
        return f"{int(value)} ms"
    if getattr(metric, "is_pct", False):
        return f"{value * 100:.1f}%"
    return f"{float(value):.3f}"


def _display_path(path: Path) -> str:
    resolved = Path(path).resolve()
    for root in (PROJECT_ROOT, RAGENTEVAL_ROOT):
        try:
            return str(resolved.relative_to(root))
        except ValueError:
            pass
    return str(resolved)


if __name__ == "__main__":
    raise SystemExit(main())

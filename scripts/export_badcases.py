from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.persistence.db import trace_db_session  # noqa: E402
from app.persistence.eval_recorder import infer_run_id_from_path, persist_eval_jsonl  # noqa: E402
from app.persistence.eval_report import default_badcase_report_path, write_badcase_report  # noqa: E402
from app.persistence.repositories import EVAL_ERROR_TYPES, EvalRepository  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Persist eval JSONL records and export eval_record badcases as a markdown report.",
    )
    parser.add_argument(
        "--input-jsonl",
        "--jsonl",
        dest="input_jsonl",
        type=Path,
        help="Optional eval runs JSONL. When provided, records are upserted into eval_record first.",
    )
    parser.add_argument(
        "--run-id",
        help="Eval run id. Defaults to input JSONL filename stem when --input-jsonl is provided.",
    )
    parser.add_argument(
        "--error-type",
        choices=sorted(EVAL_ERROR_TYPES),
        help="Only export one error type.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum badcase rows to export.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Markdown output path. Defaults to docs/badcase_report_YYYYMMDD.md.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output_path = args.output or default_badcase_report_path(PROJECT_ROOT)
    run_id = args.run_id.strip() if args.run_id else None

    if args.input_jsonl is not None:
        source_path = args.input_jsonl
        run_id = run_id or infer_run_id_from_path(source_path)
        summary = persist_eval_jsonl(source_path, run_id=run_id)
        print(
            "persisted eval jsonl: "
            f"run_id={summary.run_id} total={summary.total} saved={summary.saved} badcases={summary.badcases}"
        )

    with trace_db_session() as session:
        repo = EvalRepository(session)
        records = repo.list_badcases(run_id=run_id, error_type=args.error_type, limit=args.limit)
        write_badcase_report(
            records,
            output_path,
            run_id=run_id,
            source_jsonl=args.input_jsonl,
        )

    print(f"badcase report exported: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

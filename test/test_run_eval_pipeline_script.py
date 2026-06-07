from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

import pytest

from scripts import run_eval_pipeline


@dataclass
class Metric:
    name: str
    overall: float | None
    is_pct: bool = True


def test_run_eval_pipeline_parser_defaults() -> None:
    args = run_eval_pipeline.build_parser().parse_args([])

    assert args.mode == "system"
    assert args.base_url == "http://127.0.0.1:8000"
    assert args.limit == 20
    assert args.with_ragas is False
    assert args.no_report is False
    assert args.no_badcases is False


def test_run_eval_pipeline_formats_metric_values() -> None:
    assert run_eval_pipeline._format_metric(Metric("hit@1", 0.875)) == "87.5%"
    assert run_eval_pipeline._format_metric(Metric("ttft_p95_ms", 146.9, is_pct=False)) == "146 ms"
    assert run_eval_pipeline._format_metric(Metric("intent_top1", None)) == "-"


def test_run_eval_pipeline_rejects_system_jsonl_without_contexts(tmp_path: Path) -> None:
    runs_file = tmp_path / "system.jsonl"
    runs_file.write_text(
        json.dumps(
            {
                "query_id": "S9-01",
                "eval_mode": "system",
                "retrieved_doc_ids": ["NET_GUIDE_001"],
                "retrieved_contexts": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="missing retrieved_contexts"):
        run_eval_pipeline._assert_system_eval_contexts(runs_file)


def test_run_eval_pipeline_rejects_unattributed_badcases() -> None:
    class Badcase:
        case_id = "CASE-001"
        error_type = None

    with pytest.raises(RuntimeError, match="missing error_type"):
        run_eval_pipeline._assert_badcases_attributed([Badcase()])

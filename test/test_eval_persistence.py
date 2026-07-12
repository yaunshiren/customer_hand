from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import delete, select

from app.persistence.db import ping_trace_db, trace_db_session
from app.persistence.eval_recorder import normalize_eval_record, persist_eval_jsonl
from app.persistence.eval_report import render_badcase_markdown
from app.persistence.models import EvalRecord, ToolTrace


def test_normalize_ragenteval_record_infers_rerank_error() -> None:
    record = normalize_eval_record(
        {
            "query_id": "S14-01",
            "user_input": "How long is the warranty?",
            "intent_l2": "S14_AFTERSALE_POLICY",
            "intent_pred": "S14_AFTERSALE_POLICY",
            "reference_doc_ids": ["POLICY_WAR_001", "POLICY_WAR_002"],
            "retrieved_doc_ids": ["PROD_PHONE_004", "POLICY_WAR_002"],
            "response": "Warranty answer",
        },
        default_run_id="run_001",
    )

    assert record.run_id == "run_001"
    assert record.case_id == "S14-01"
    assert record.question == "How long is the warranty?"
    assert record.expected_intent == "S14_AFTERSALE_POLICY"
    assert record.predicted_intent == "S14_AFTERSALE_POLICY"
    assert record.expected_doc_ids == ["POLICY_WAR_001", "POLICY_WAR_002"]
    assert record.retrieved_doc_ids == ["PROD_PHONE_004", "POLICY_WAR_002"]
    assert record.is_hit is True
    assert record.error_type == "RERANK_ERROR"


def test_normalize_ragenteval_record_keeps_trace_link_fields() -> None:
    record = normalize_eval_record(
        {
            "query_id": "S9-01",
            "user_input": "Wifi setup failed",
            "intent_l2": "S9_NETWORK",
            "reference_doc_ids": ["NET_GUIDE_001"],
            "retrieved_doc_ids": [],
            "trace_id": "trace_001",
            "system_route": "chitchat",
            "eval_mode": "system",
        },
        default_run_id="run_trace",
    )

    assert record.trace_id == "trace_001"
    assert record.system_route == "chitchat"
    assert record.eval_mode == "system"
    assert record.error_type == "ROUTE_ERROR"


def test_normalize_eval_rag_envelope_prioritizes_intent_error() -> None:
    record = normalize_eval_record(
        {
            "case_id": "RET-01",
            "question": "Can I return an opened product?",
            "expected_intent": "S14_AFTERSALE_POLICY",
            "expected_doc_ids": ["POLICY_RET_001"],
            "data": {
                "retrievedDocIds": ["POLICY_LOG_001"],
                "intentLeafIds": ["S5_LOGISTICS"],
            },
            "answer": "Logistics answer",
        },
        default_run_id="run_002",
    )

    assert record.case_id == "RET-01"
    assert record.predicted_intent == "S5_LOGISTICS"
    assert record.retrieved_doc_ids == ["POLICY_LOG_001"]
    assert record.is_hit is False
    assert record.error_type == "INTENT_ERROR"


def test_render_badcase_markdown_groups_by_error_type() -> None:
    markdown = render_badcase_markdown(
        [
            {
                "case_id": "RET-01",
                "question": "Can I return it?",
                "expected_intent": "S14",
                "predicted_intent": "S5",
                "expected_doc_ids": ["POLICY_RET_001"],
                "retrieved_doc_ids": ["POLICY_LOG_001"],
                "answer": "Wrong answer",
                "is_hit": False,
                "error_type": "INTENT_ERROR",
            }
        ],
        run_id="run_report",
        generated_at=datetime(2026, 6, 6),
    )

    assert "# Badcase Report 2026-06-06" in markdown
    assert "`run_report`" in markdown
    assert "### INTENT_ERROR" in markdown
    assert "RET-01" in markdown
    assert "POLICY_RET_001" in markdown


@pytest.mark.integration
@pytest.mark.mysql
def test_persist_eval_jsonl_to_mysql_when_available(tmp_path: Path) -> None:
    try:
        ping_trace_db()
    except Exception as exc:  # pragma: no cover - depends on local MySQL.
        pytest.skip(f"trace database is not available: {exc}")

    run_id = f"eval_run_{uuid.uuid4().hex}"
    jsonl_path = tmp_path / "eval_records.jsonl"
    rows = [
        {
            "query_id": "CASE-001",
            "user_input": "Return policy",
            "intent_l2": "S14_AFTERSALE_POLICY",
            "intent_pred": "S14_AFTERSALE_POLICY",
            "reference_doc_ids": ["POLICY_RET_001"],
            "retrieved_doc_ids": ["POLICY_LOG_001"],
            "response": "Wrong context answer",
        },
        {
            "query_id": "CASE-002",
            "user_input": "Where is my order?",
            "intent_l2": "S5_LOGISTICS",
            "intent_pred": "S14_AFTERSALE_POLICY",
            "reference_doc_ids": ["POLICY_LOG_001"],
            "retrieved_doc_ids": ["POLICY_LOG_001"],
            "response": "Right document, wrong intent",
        },
    ]
    jsonl_path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")

    try:
        summary = persist_eval_jsonl(jsonl_path, run_id=run_id)
        assert summary.total == 2
        assert summary.saved == 2
        assert summary.badcases == 2

        with trace_db_session() as session:
            persisted = list(
                session.execute(
                    select(
                        EvalRecord.case_id,
                        EvalRecord.expected_intent,
                        EvalRecord.predicted_intent,
                        EvalRecord.expected_doc_ids,
                        EvalRecord.retrieved_doc_ids,
                        EvalRecord.is_hit,
                        EvalRecord.error_type,
                        EvalRecord.trace_id,
                        EvalRecord.system_route,
                        EvalRecord.eval_mode,
                    )
                    .where(EvalRecord.run_id == run_id)
                    .order_by(EvalRecord.case_id)
                ).all()
            )

        assert persisted == [
            (
                "CASE-001",
                "S14_AFTERSALE_POLICY",
                "S14_AFTERSALE_POLICY",
                ["POLICY_RET_001"],
                ["POLICY_LOG_001"],
                False,
                "RETRIEVAL_MISS",
                None,
                None,
                None,
            ),
            (
                "CASE-002",
                "S5_LOGISTICS",
                "S14_AFTERSALE_POLICY",
                ["POLICY_LOG_001"],
                ["POLICY_LOG_001"],
                True,
                "INTENT_ERROR",
                None,
                None,
                None,
            ),
        ]
    finally:
        with trace_db_session() as session:
            session.execute(delete(EvalRecord).where(EvalRecord.run_id == run_id))


@pytest.mark.integration
@pytest.mark.mysql
def test_persist_eval_jsonl_uses_failed_tool_trace_for_attribution(tmp_path: Path) -> None:
    try:
        ping_trace_db()
    except Exception as exc:  # pragma: no cover - depends on local MySQL.
        pytest.skip(f"trace database is not available: {exc}")

    run_id = f"eval_run_{uuid.uuid4().hex}"
    trace_id = f"trace_{uuid.uuid4().hex}"
    jsonl_path = tmp_path / "eval_tool_records.jsonl"
    jsonl_path.write_text(
        json.dumps(
            {
                "query_id": "CASE-TOOL",
                "user_input": "Create a ticket",
                "intent_l2": "F3_COMPLAINT",
                "reference_doc_ids": [],
                "retrieved_doc_ids": [],
                "trace_id": trace_id,
                "system_route": "ticket",
                "eval_mode": "system",
                "is_hit": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    try:
        with trace_db_session() as session:
            session.add(
                ToolTrace(
                    trace_id=trace_id,
                    tool_name="ticket_create",
                    arguments_json={"sender_id": "eval_user"},
                    result_json={"failure_type": "TOOL_FAILURE", "error": "ticket service down"},
                    status="failed",
                    latency_ms=12,
                )
            )

        summary = persist_eval_jsonl(jsonl_path, run_id=run_id)
        assert summary.badcases == 1

        with trace_db_session() as session:
            row = session.execute(select(EvalRecord).where(EvalRecord.run_id == run_id)).scalar_one()
            assert row.case_id == "CASE-TOOL"
            assert row.trace_id == trace_id
            assert row.system_route == "ticket"
            assert row.eval_mode == "system"
            assert row.error_type == "TOOL_FAILURE"
    finally:
        with trace_db_session() as session:
            session.execute(delete(EvalRecord).where(EvalRecord.run_id == run_id))
            session.execute(delete(ToolTrace).where(ToolTrace.trace_id == trace_id))

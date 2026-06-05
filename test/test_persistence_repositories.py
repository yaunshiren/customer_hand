from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.persistence.db import get_session_factory, ping_trace_db
from app.persistence.models import EvalRecord
from app.persistence.repositories import (
    AgentTraceCreate,
    EvalRecordUpsert,
    EvalRepository,
    RepositoryError,
    RetrievalTraceCreate,
    ToolTraceCreate,
    TraceRepository,
)


@pytest.fixture()
def db_session() -> Session:
    try:
        ping_trace_db()
    except Exception as exc:  # pragma: no cover - depends on local MySQL.
        pytest.skip(f"trace database is not available: {exc}")

    session = get_session_factory()()
    transaction = session.begin()
    try:
        yield session
    finally:
        transaction.rollback()
        session.close()


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def test_trace_repository_writes_agent_retrieval_and_tool_records(db_session: Session) -> None:
    trace_id = _id("trace")
    repo = TraceRepository(db_session)

    trace = repo.create_agent_trace(
        AgentTraceCreate(
            id=trace_id,
            sender_id="user_001",
            conversation_id="conv_001",
            user_text="Where is my order?",
        )
    )
    assert trace.id == trace_id

    updated = repo.update_agent_trace(
        trace_id,
        rewritten_query="order logistics query",
        intent_id="logistics.query",
        intent_confidence=0.91,
        route="tool",
        final_answer="Your order is in transit.",
        latency_ms=123,
    )
    assert updated is not None
    assert updated.route == "tool"
    assert updated.latency_ms == 123

    retrieval_rows = repo.add_retrieval_traces(
        trace_id,
        [
            RetrievalTraceCreate(
                query="order logistics query",
                channel="keyword",
                doc_id="POLICY_LOG_001",
                chunk_id="POLICY_LOG_001-0",
                score=0.72,
                rerank_score=1.34,
                content="Shipping policy context",
            )
        ],
    )
    assert len(retrieval_rows) == 1
    assert retrieval_rows[0].trace_id == trace_id
    assert retrieval_rows[0].doc_id == "POLICY_LOG_001"

    tool_row = repo.add_tool_trace(
        ToolTraceCreate(
            trace_id=trace_id,
            tool_name="get_logistics_info",
            arguments_json={"order_id": "A10001"},
            result_json={"status": "in_transit"},
            status="success",
            latency_ms=45,
        )
    )
    assert tool_row.tool_name == "get_logistics_info"
    assert tool_row.result_json == {"status": "in_transit"}


def test_eval_repository_upserts_and_lists_badcases(db_session: Session) -> None:
    run_id = _id("run")
    case_id = _id("case")
    repo = EvalRepository(db_session)

    first = repo.save_eval_record(
        EvalRecordUpsert(
            run_id=run_id,
            case_id=case_id,
            question="What is the return policy?",
            expected_intent="return.policy",
            predicted_intent="logistics.query",
            expected_doc_ids=["POLICY_RET_001"],
            retrieved_doc_ids=["POLICY_LOG_001"],
            answer="Incorrect logistics answer",
            is_hit=False,
            error_type="INTENT_ERROR",
        )
    )
    first_id = first.id

    second = repo.save_eval_record(
        {
            "run_id": run_id,
            "case_id": case_id,
            "question": "What is the return policy?",
            "expected_intent": "return.policy",
            "predicted_intent": "return.policy",
            "expected_doc_ids": ["POLICY_RET_001"],
            "retrieved_doc_ids": ["POLICY_RET_001"],
            "answer": "Correct return answer",
            "is_hit": True,
            "error_type": None,
        }
    )
    assert second.id == first_id
    assert second.answer == "Correct return answer"

    count = db_session.execute(
        select(func.count()).select_from(EvalRecord).where(EvalRecord.run_id == run_id)
    ).scalar_one()
    assert count == 1

    bad = repo.save_eval_record(
        EvalRecordUpsert(
            run_id=run_id,
            case_id=_id("case"),
            question="Which warranty doc applies?",
            expected_doc_ids=["POLICY_WAR_001"],
            retrieved_doc_ids=["POLICY_RET_001"],
            answer="Wrong context",
            is_hit=False,
            error_type="RETRIEVAL_MISS",
        )
    )

    badcases = repo.list_badcases(run_id=run_id)
    assert [item.id for item in badcases] == [bad.id]


def test_repositories_validate_status_error_type_and_update_fields(db_session: Session) -> None:
    trace_repo = TraceRepository(db_session)
    eval_repo = EvalRepository(db_session)
    trace_id = _id("trace")

    trace_repo.create_agent_trace({"id": trace_id, "sender_id": "user_001", "user_text": "hello"})

    with pytest.raises(RepositoryError):
        trace_repo.update_agent_trace(trace_id, unknown_field="nope")

    with pytest.raises(RepositoryError):
        trace_repo.add_tool_trace(
            {"trace_id": trace_id, "tool_name": "demo_tool", "status": "pending"}
        )

    with pytest.raises(RepositoryError):
        eval_repo.save_eval_record(
            {
                "run_id": _id("run"),
                "case_id": _id("case"),
                "question": "hello",
                "error_type": "UNKNOWN_ERROR",
            }
        )

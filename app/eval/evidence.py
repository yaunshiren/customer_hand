from __future__ import annotations

import time
from typing import Protocol

from sqlalchemy import select

from app.persistence.db import ping_trace_db, trace_db_session
from app.persistence.models import AgentTrace, RetrievalTrace, ToolTrace

from .models import (
    AgentTraceEvidence,
    EvalInfrastructureError,
    RetrievalTraceEvidence,
    ToolTraceEvidence,
)


class EvidenceProvider(Protocol):
    def preflight(self) -> None: ...

    def fetch(
        self,
        trace_id: str,
        *,
        require_agent: bool,
        require_retrieval: bool,
        require_tool: bool,
    ) -> tuple[AgentTraceEvidence | None, list[RetrievalTraceEvidence], list[ToolTraceEvidence]]: ...


class MySQLEvidenceProvider:
    def __init__(
        self,
        *,
        wait_timeout_seconds: float = 5.0,
        poll_interval_seconds: float = 0.1,
    ) -> None:
        self.wait_timeout_seconds = max(0.1, float(wait_timeout_seconds))
        self.poll_interval_seconds = max(0.01, float(poll_interval_seconds))

    def preflight(self) -> None:
        try:
            ping_trace_db()
        except Exception as exc:
            raise EvalInfrastructureError(
                "trace MySQL is unavailable; start/configure the trace database before running eval"
            ) from exc

    def fetch(
        self,
        trace_id: str,
        *,
        require_agent: bool = True,
        require_retrieval: bool,
        require_tool: bool,
    ) -> tuple[AgentTraceEvidence | None, list[RetrievalTraceEvidence], list[ToolTraceEvidence]]:
        clean_trace_id = str(trace_id or "").strip()
        if not clean_trace_id:
            raise EvalInfrastructureError("X-Trace-Id is empty; trace evidence cannot be correlated")

        deadline = time.monotonic() + self.wait_timeout_seconds
        last_state = "agent_trace=missing retrieval_trace=0 tool_trace=0"
        while True:
            try:
                bundle = _read_trace_bundle(clean_trace_id)
            except Exception as exc:
                raise EvalInfrastructureError(
                    f"failed to query trace MySQL for trace_id={clean_trace_id}"
                ) from exc

            agent, retrieval, tools = bundle
            last_state = (
                f"agent_trace={'present' if agent else 'missing'} "
                f"retrieval_trace={len(retrieval)} tool_trace={len(tools)}"
            )
            complete = (
                (not require_agent or agent is not None)
                and (not require_retrieval or bool(retrieval))
                and (not require_tool or bool(tools))
            )
            if complete:
                return agent, retrieval, tools
            if time.monotonic() >= deadline:
                requirements: list[str] = []
                if require_agent:
                    requirements.append("agent_trace")
                if require_retrieval:
                    requirements.append("retrieval_trace")
                if require_tool:
                    requirements.append("tool_trace")
                raise EvalInfrastructureError(
                    "incomplete trace evidence for "
                    f"trace_id={clean_trace_id}; required={','.join(requirements)}; observed={last_state}"
                )
            time.sleep(self.poll_interval_seconds)


def _read_trace_bundle(
    trace_id: str,
) -> tuple[
    AgentTraceEvidence | None,
    list[RetrievalTraceEvidence],
    list[ToolTraceEvidence],
]:
    with trace_db_session() as session:
        agent_row = session.get(AgentTrace, trace_id)
        retrieval_rows = list(
            session.scalars(
                select(RetrievalTrace)
                .where(RetrievalTrace.trace_id == trace_id)
                .order_by(RetrievalTrace.id.asc())
            )
        )
        tool_rows = list(
            session.scalars(
                select(ToolTrace)
                .where(ToolTrace.trace_id == trace_id)
                .order_by(ToolTrace.id.asc())
            )
        )

        agent = None
        if agent_row is not None:
            agent = AgentTraceEvidence(
                trace_id=agent_row.id,
                intent_id=agent_row.intent_id,
                route=agent_row.route,
                rewritten_query=agent_row.rewritten_query,
                final_answer=agent_row.final_answer,
                memory_snapshot=(
                    dict(agent_row.memory_snapshot)
                    if isinstance(agent_row.memory_snapshot, dict)
                    else None
                ),
                latency_ms=agent_row.latency_ms,
            )
        retrieval = [
            RetrievalTraceEvidence(
                channel=row.channel,
                doc_id=row.doc_id,
                chunk_id=row.chunk_id,
                score=row.score,
                rerank_score=row.rerank_score,
                content=row.content,
            )
            for row in retrieval_rows
        ]
        tools = [
            ToolTraceEvidence(
                tool_name=row.tool_name,
                arguments=_dict_or_empty(row.arguments_json),
                result=_dict_or_empty(row.result_json),
                status=row.status,
                latency_ms=row.latency_ms,
            )
            for row in tool_rows
        ]
    return agent, retrieval, tools


def _dict_or_empty(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}

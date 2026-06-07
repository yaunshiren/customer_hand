from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAGENTEVAL_ROOT = PROJECT_ROOT.parent / "ragenteval-main"
for path in (PROJECT_ROOT, RAGENTEVAL_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from eval.common.schemas import EvalSample  # noqa: E402
from eval.rag.pipeline import customer_hand_runner  # noqa: E402


def _sample() -> EvalSample:
    return EvalSample(
        query_id="S9-01",
        query="How do I reconnect wifi?",
        intent_l1="SUPPORT",
        intent_l2="S9_NETWORK",
        difficulty="medium",
        requires_rag=True,
        expected_doc_ids=["NET_GUIDE_001"],
    )


def test_system_eval_payload_uses_real_contexts_and_trace_id_from_message_metadata() -> None:
    payload = customer_hand_runner._message_metadata_eval_payload(
        _sample(),
        [
            {
                "text": "answer",
                "metadata": {
                    "rag_doc_ids": ["NET_GUIDE_001"],
                    "rag_chunk_ids": ["NET_GUIDE_001-0"],
                    "rag_context_doc_ids": ["NET_GUIDE_001"],
                    "retrieved_contexts": ["[source]\ndoc_id: NET_GUIDE_001\ncontent: wifi setup"],
                    "intentLeafIds": ["S9_NETWORK"],
                    "intentSource": "classifier",
                    "trace_id": "trace_system_001",
                    "route": "rag",
                },
            }
        ],
    )

    data = payload["data"]
    assert data["retrievedDocIds"] == ["NET_GUIDE_001"]
    assert data["retrievedChunkIds"] == ["NET_GUIDE_001-0"]
    assert data["retrievedContexts"] == ["[source]\ndoc_id: NET_GUIDE_001\ncontent: wifi setup"]
    assert data["retrievedContextDocIds"] == ["NET_GUIDE_001"]
    assert data["intentLeafIds"] == ["S9_NETWORK"]
    assert data["traceId"] == "trace_system_001"
    assert data["systemRoute"] == "rag"


def test_post_message_injects_trace_header_into_response_metadata(monkeypatch) -> None:
    class FakeResponse:
        status_code = 200
        text = "ok"
        headers = {"X-Trace-Id": "trace_header_001"}

        def json(self) -> list[dict[str, Any]]:
            return [{"text": "answer", "metadata": {"route": "rag"}}]

    def fake_post(*args: Any, **kwargs: Any) -> FakeResponse:
        return FakeResponse()

    monkeypatch.setattr(customer_hand_runner.requests, "post", fake_post)

    responses, latency_ms, error = customer_hand_runner._post_message(
        "http://127.0.0.1:8000",
        _sample(),
        "eval_sender",
    )

    assert error is None
    assert latency_ms >= 0
    assert responses[0]["metadata"]["trace_id"] == "trace_header_001"

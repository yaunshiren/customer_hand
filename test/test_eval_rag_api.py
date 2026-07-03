from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fastapi.testclient import TestClient

from app.rag.documents import KnowledgeChunk
from app.rag.indexer import RetrievalMatch
from app.rag.retriever import RetrievalResult
from main import app


client = TestClient(app)
AUTH_EVALUATOR = {"Authorization": "Bearer dev:evaluator_001:tenant_demo:evaluator"}


@dataclass
class FakeRetriever:
    matches: list[RetrievalMatch]
    last_top_k: int | None = None
    called: bool = False

    def retrieve(self, query: str, top_k: int = 3) -> RetrievalResult:
        self.called = True
        self.last_top_k = top_k
        return RetrievalResult(query=query, matches=self.matches)


def _match(doc_id: str, chunk_id: str, text: str = "测试内容") -> RetrievalMatch:
    return RetrievalMatch(
        chunk=KnowledgeChunk(
            chunk_id=chunk_id,
            source=str(Path("knowledge") / f"{doc_id}.md"),
            text=text,
            metadata={"doc_id": doc_id, "title": f"{doc_id} 标题"},
        ),
        score=0.9,
    )


def test_eval_rag_response_shape_and_doc_id_alignment(monkeypatch) -> None:
    retriever = FakeRetriever(
        matches=[
            _match("DOC_A", "DOC_A-0", "第一段"),
            _match("DOC_A", "DOC_A-1", "第二段"),
            _match("DOC_B", "DOC_B-0", "第三段"),
        ]
    )
    monkeypatch.setattr(app.state, "kb_retriever", retriever)

    response = client.get(
        "/api/eval/rag",
        headers=AUTH_EVALUATOR,
        params={"question": "小米 14 Pro 屏幕尺寸", "top_k": 99},
    )

    assert response.status_code == 200
    payload = response.json()
    data = payload["data"]
    assert payload["success"] is True
    assert retriever.called is True
    assert retriever.last_top_k == 20
    assert data["retrievedDocIds"] == ["DOC_A", "DOC_B"]
    assert data["retrievedChunkIds"] == ["DOC_A-0", "DOC_A-1", "DOC_B-0"]
    assert data["retrievedContextDocIds"] == ["DOC_A", "DOC_A", "DOC_B"]
    assert len(data["retrievedContexts"]) == 3
    assert data["retrievedContexts"][0].startswith("[来源 1]\ndoc_id: DOC_A\n")
    assert data["intentLeafIds"] == []
    assert data["intentSource"] == "not_exposed"
    assert data["hasKb"] is True
    assert data["hasMcp"] is False
    assert data["traceId"]


def test_eval_rag_does_not_skip_retrieval_for_feedback(monkeypatch) -> None:
    retriever = FakeRetriever(matches=[_match("DOC_FEEDBACK", "DOC_FEEDBACK-0")])
    monkeypatch.setattr(app.state, "kb_retriever", retriever)

    response = client.get(
        "/api/eval/rag",
        headers=AUTH_EVALUATOR,
        params={"question": "希望 APP 能加个深色模式"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert retriever.called is True
    assert data["intentLeafIds"] == []
    assert data["retrievedDocIds"] == ["DOC_FEEDBACK"]
    assert len(data["retrievedContexts"]) == 1
    assert data["hasKb"] is True


def test_eval_rag_rejects_empty_question() -> None:
    response = client.get("/api/eval/rag", headers=AUTH_EVALUATOR, params={"question": "   "})

    assert response.status_code == 400

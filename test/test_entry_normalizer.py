from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.api.schemas import MessageRequest
from app.entry.normalizer import normalize_message_request


def test_normalize_message_request_builds_entry_task() -> None:
    app = FastAPI()

    @app.middleware("http")
    async def trace_header_middleware(request: Request, call_next):
        request.state.trace_id = request.headers.get("x-trace-id") or "trace-test"
        return await call_next(request)

    @app.post("/probe")
    async def probe(req: MessageRequest, request: Request):
        task = normalize_message_request(req, request)
        return task.model_dump(mode="json")

    client = TestClient(app)
    response = client.post(
        "/probe",
        headers={"X-Trace-Id": "trace-entry-1", "Idempotency-Key": "idem-1"},
        json={
            "sender_id": "u1",
            "message": "  hello  ",
            "conversation_id": "c1",
            "source": "web",
            "scenario": "chat",
            "metadata": {"channel": "browser"},
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["trace_id"] == "trace-entry-1"
    assert data["sender_id"] == "u1"
    assert data["conversation_id"] == "c1"
    assert data["source"] == "web"
    assert data["normalized_text"] == "hello"
    assert data["idempotency_key"] == "idem-1"
    assert data["metadata"]["channel"] == "browser"

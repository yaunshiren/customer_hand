from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.agent.agent import Agent
from app.core.tracker_store import InMemoryTrackerStore
from app.entry.models import Principal
from app.settings import settings


DEFAULT_MESSAGES = [
    "你好",
    "我要退货",
    "有什么手机",
    "有什么商品",
    "还有其他的吗",
    "小米 14 Pro 512G 蓝色现在缺货吗？",
    "新款手表什么时候上市？",
    "扫地机的边刷哪几个型号是通用的？",
    "扫地机能扫地毯吗？",
    "智能门锁停电了能用吗？",
    "详细介绍小米 14 Pro的信息",
    "我们之前聊了什么",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a multi-turn customer-service dialogue locally.")
    parser.add_argument(
        "--message",
        action="append",
        dest="messages",
        help="Add one user message. Repeat this option for a custom dialogue.",
    )
    parser.add_argument(
        "--sender-id",
        default=f"dialogue_demo_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        help="Conversation sender id. The same id is reused for all turns.",
    )
    parser.add_argument(
        "--tenant-id",
        required=True,
        help="Explicit trusted tenant scope for this local system-principal run.",
    )
    parser.add_argument(
        "--llm-mode",
        choices=["env", "disabled"],
        default="env",
        help="env uses .env LLM settings; disabled turns off chat LLM calls after agent init.",
    )
    parser.add_argument(
        "--rag-backend",
        choices=["env", "keyword", "hybrid", "chroma"],
        default="env",
        help="env follows .env RAG_BACKEND; keyword avoids embedding/vector dependencies.",
    )
    parser.add_argument("--knowledge-dir", type=Path, default=settings.knowledge_dir)
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="JSONL output path. Defaults to runs/dialogue_demo_<timestamp>.jsonl.",
    )
    parser.add_argument(
        "--hide-metadata",
        action="store_true",
        help="Only print user/assistant text in terminal. JSONL still contains metadata.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    messages = args.messages or DEFAULT_MESSAGES
    output_path = _resolve_output_path(args.output)

    if args.rag_backend != "env":
        settings.rag_backend = args.rag_backend

    agent = Agent(
        tracker_store=InMemoryTrackerStore(),
        flows={},
        knowledge_dir=args.knowledge_dir,
    )
    if args.llm_mode == "disabled":
        _disable_llm(agent)

    principal = Principal(
        principal_id=args.sender_id,
        user_id=args.sender_id,
        tenant_id=args.tenant_id,
        roles=["user"],
        source="dialogue_demo",
        auth_type="system",
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"sender_id={args.sender_id}")
    print(f"llm_mode={args.llm_mode}")
    print(f"rag_backend={settings.rag_backend}")
    print(f"knowledge_dir={args.knowledge_dir}")
    print(f"output={output_path}")
    print()

    with output_path.open("w", encoding="utf-8") as writer:
        for index, message in enumerate(messages, start=1):
            started_at = time.perf_counter()
            responses = agent.handle_message(
                message,
                args.sender_id,
                principal=principal,
            )
            latency_ms = int((time.perf_counter() - started_at) * 1000)

            assistant_text = _join_response_text(responses)
            metadata = _first_metadata(responses)
            record = {
                "turn": index,
                "sender_id": args.sender_id,
                "user": message,
                "assistant": assistant_text,
                "latency_ms": latency_ms,
                "responses": responses,
                "metadata": metadata,
            }
            writer.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            writer.flush()

            _print_turn(
                turn=index,
                user_text=message,
                assistant_text=assistant_text,
                latency_ms=latency_ms,
                metadata=metadata,
                hide_metadata=args.hide_metadata,
            )

    print(f"\ncompleted_turns={len(messages)}")
    print(f"result_jsonl={output_path}")
    return 0


def _resolve_output_path(path: Path | None) -> Path:
    if path is None:
        name = f"dialogue_demo_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
        return PROJECT_ROOT / "runs" / name
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def _disable_llm(agent: Agent) -> None:
    agent.llm_generator.client.enabled = False
    answerer_llm = getattr(agent.knowledge_answerer, "llm", None)
    if answerer_llm is not None:
        answerer_llm.enabled = False


def _join_response_text(responses: list[dict[str, Any]]) -> str:
    texts = [str(item.get("text") or "").strip() for item in responses if isinstance(item, dict)]
    return "\n".join(text for text in texts if text)


def _first_metadata(responses: list[dict[str, Any]]) -> dict[str, Any]:
    for response in responses:
        if not isinstance(response, dict):
            continue
        metadata = response.get("metadata")
        if isinstance(metadata, dict):
            return metadata
    return {}


def _print_turn(
    *,
    turn: int,
    user_text: str,
    assistant_text: str,
    latency_ms: int,
    metadata: dict[str, Any],
    hide_metadata: bool,
) -> None:
    print(f"[{turn}] 用户：{user_text}")
    print(f"[{turn}] 助手：{assistant_text or '<empty>'}")
    if not hide_metadata:
        summary = {
            "route": metadata.get("route"),
            "system_route": metadata.get("system_route"),
            "intentLeafIds": metadata.get("intentLeafIds"),
            "intentConfidence": metadata.get("intentConfidence"),
            "intentSource": metadata.get("intentSource"),
            "needsClarification": metadata.get("needsClarification"),
            "clarifyReason": metadata.get("clarifyReason"),
            "rag_match_count": metadata.get("rag_match_count"),
            "used_llm": metadata.get("used_llm"),
        }
        compact = {key: value for key, value in summary.items() if value not in (None, [], "")}
        print(f"[{turn}] 摘要：{json.dumps(compact, ensure_ascii=False, default=str)} latency_ms={latency_ms}")
    print()


if __name__ == "__main__":
    raise SystemExit(main())

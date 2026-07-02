from __future__ import annotations

import json
import logging
import re
from concurrent.futures import Executor, ThreadPoolExecutor
from threading import Lock
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.llm.client import LLMClient
from app.memory.store import ConversationMemoryStore
from app.persistence.models import ConversationMessage
from app.settings import settings

logger = logging.getLogger(__name__)

_DEFAULT_SUMMARY_EXECUTOR = ThreadPoolExecutor(
    max_workers=2,
    thread_name_prefix="memory-summary",
)


class MemorySummaryPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    summary: str = Field(default="")


class MemorySummaryService:
    def __init__(
        self,
        *,
        store: ConversationMemoryStore | None = None,
        llm_client: LLMClient | None = None,
        executor: Executor | None = None,
    ) -> None:
        self.store = store or ConversationMemoryStore()
        self.llm_client = llm_client or LLMClient.from_env()
        self.executor = executor or _DEFAULT_SUMMARY_EXECUTOR
        self._locks: dict[str, Lock] = {}
        self._locks_guard = Lock()

    def compress_if_needed(
        self,
        *,
        sender_id: str,
        conversation_id: str | None = None,
    ) -> bool:
        """Schedule a background summary task.

        Returns True when a task is accepted by the local executor. The actual
        compression decision still happens inside the background task.
        """
        if not settings.memory_summary_enabled:
            return False
        if not self.llm_client.enabled:
            return False

        lock_key = conversation_id or sender_id
        lock = self._lock_for(lock_key)
        if not lock.acquire(blocking=False):
            return False

        try:
            self.executor.submit(
                self._run_compress_task,
                lock,
                sender_id=sender_id,
                conversation_id=conversation_id,
            )
            return True
        except Exception:
            lock.release()
            logger.exception(
                "memory.summary.schedule_failed sender_id=%s conversation_id=%s",
                sender_id,
                conversation_id,
            )
            return False

    def _lock_for(self, lock_key: str) -> Lock:
        with self._locks_guard:
            return self._locks.setdefault(lock_key, Lock())

    def _run_compress_task(
        self,
        lock: Lock,
        *,
        sender_id: str,
        conversation_id: str | None,
    ) -> bool:
        try:
            return self._compress(sender_id=sender_id, conversation_id=conversation_id)
        except Exception:
            logger.exception("memory.summary.failed sender_id=%s conversation_id=%s", sender_id, conversation_id)
            return False
        finally:
            lock.release()

    def _compress(
        self,
        *,
        sender_id: str,
        conversation_id: str | None,
    ) -> bool:
        user_turns = self.store.count_user_messages(
            sender_id=sender_id,
            conversation_id=conversation_id,
        )
        if user_turns < settings.memory_summary_start_turns:
            return False

        latest_user_turns = self.store.load_latest_user_messages(
            sender_id=sender_id,
            conversation_id=conversation_id,
            limit=settings.memory_recent_turn_limit,
        )
        if len(latest_user_turns) < settings.memory_recent_turn_limit:
            return False

        oldest_kept_user = latest_user_turns[-1]
        before_id = int(oldest_kept_user.id)

        latest_summary = self.store.find_latest_summary(
            sender_id=sender_id,
            conversation_id=conversation_id,
        )
        after_id = int(latest_summary.last_message_id) if latest_summary else 0

        if after_id >= before_id:
            return False

        messages_to_summarize = self.store.list_messages_between(
            sender_id=sender_id,
            conversation_id=conversation_id,
            after_id=after_id,
            before_id=before_id,
        )
        if not messages_to_summarize:
            return False

        stale_user_turns = sum(1 for item in messages_to_summarize if item.role == "user")
        if stale_user_turns < settings.memory_summary_batch_turns:
            return False
        
        summary = self._generate_summary(
            previous_summary=latest_summary.content if latest_summary else "",
            messages=messages_to_summarize,
        )
        if not summary:
            return False

        self.store.create_summary(
            sender_id=sender_id,
            conversation_id=conversation_id,
            last_message_id=int(messages_to_summarize[-1].id),
            content=summary,
        )
        return True

    def _generate_summary(
        self,
        *,
        previous_summary: str,
        messages: list[ConversationMessage],
    ) -> str:
        system_prompt = (
            "你是客服系统的会话记忆压缩器。"
            "你的任务是把历史对话压缩成可长期保存的客服记忆。"
            "只保留事实，不要编造，不要输出 Markdown。"
            "必须输出 JSON。"
        )
        user_prompt = self._build_user_prompt(
            previous_summary=previous_summary,
            messages=messages,
        )

        result = self.llm_client.generate_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.0,
            response_format={"type": "json_object"},
            response_model=MemorySummaryPayload,
        )
        if not result.get("success"):
            logger.info("memory.summary.llm_failed error=%s", result.get("error"))
            return ""

        payload = result.get("json_output")
        if not isinstance(payload, dict):
            payload = _extract_json_object(str(result.get("raw_output") or ""))
        summary = str(payload.get("summary") or "").strip()
        if not summary:
            return ""

        max_chars = settings.memory_summary_max_chars
        return summary[:max_chars]

    def _build_user_prompt(
        self,
        *,
        previous_summary: str,
        messages: list[ConversationMessage],
    ) -> str:
        lines = []
        for message in messages:
            role = "用户" if message.role == "user" else "客服"
            lines.append(f"{role}: {message.content}")

        return f"""
请压缩以下客服历史对话。

要求：
- 保留用户诉求、商品、订单号、售后/物流/发票等关键信息
- 保留已确认事实、已执行动作、未解决问题
- 删除寒暄、重复表达和无业务价值内容
- 不要编造
- summary 控制在 {settings.memory_summary_max_chars} 字以内
- 只输出 JSON：{{"summary":"..."}}

已有长期摘要：
{previous_summary or "无"}

待压缩对话：
{chr(10).join(lines)}
""".strip()


def _extract_json_object(raw_output: str) -> dict[str, Any]:
    text = raw_output.strip()
    if not text:
        return {}

    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", text, flags=re.S)
    if not match:
        return {}

    try:
        value = json.loads(match.group(0))
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}

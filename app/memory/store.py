from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import Select, func, select

from app.persistence.db import trace_db_session
from app.persistence.models import ConversationMessage, ConversationSummary

VALID_ROLES = {"user", "assistant"}


class ConversationMemoryStore:
    def append_message(
        self,
        *,
        sender_id: str,
        role: str,
        content: str,
        conversation_id: str | None = None,
    ) -> ConversationMessage:
        role = role.strip()
        if role not in VALID_ROLES:
            raise ValueError(f"Unsupported message role: {role}")

        message = ConversationMessage(
            sender_id=sender_id,
            conversation_id=conversation_id,
            role=role,
            content=content,
        )
        with trace_db_session() as session: ## 这段在干嘛
            session.add(message)
            session.flush()
            session.refresh(message)
            session.expunge(message)
        return message

    def load_recent_messages(
        self,
        *,
        sender_id: str,
        conversation_id: str | None = None,
        limit: int,
    ) -> list[ConversationMessage]:
        stmt = self._message_scope(sender_id=sender_id, conversation_id=conversation_id)
        stmt = stmt.order_by(ConversationMessage.id.desc()).limit(max(1, limit))

        with trace_db_session() as session:
            rows = list(session.scalars(stmt).all())
            for row in rows:
                session.expunge(row)

        return list(reversed(rows))

    def count_user_messages(
        self,
        *,
        sender_id: str,
        conversation_id: str | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(ConversationMessage).where(
            ConversationMessage.sender_id == sender_id,
            ConversationMessage.role == "user",
        )
        if conversation_id:
            stmt = stmt.where(ConversationMessage.conversation_id == conversation_id)

        with trace_db_session() as session:
            return int(session.scalar(stmt) or 0)

    def find_latest_summary(
        self,
        *,
        sender_id: str,
        conversation_id: str | None = None,
    ) -> ConversationSummary | None:
        stmt = select(ConversationSummary).where(ConversationSummary.sender_id == sender_id)
        if conversation_id:
            stmt = stmt.where(ConversationSummary.conversation_id == conversation_id)
        stmt = stmt.order_by(ConversationSummary.last_message_id.desc(), ConversationSummary.id.desc()).limit(1)

        with trace_db_session() as session:
            summary = session.scalar(stmt)
            if summary is not None:
                session.expunge(summary)
            return summary

    def list_messages_between(
        self,
        *,
        sender_id: str,
        conversation_id: str | None = None,
        after_id: int = 0,
        before_id: int | None = None,
    ) -> list[ConversationMessage]:
        stmt = self._message_scope(sender_id=sender_id, conversation_id=conversation_id)
        stmt = stmt.where(ConversationMessage.id > after_id)
        if before_id is not None:
            stmt = stmt.where(ConversationMessage.id < before_id)
        stmt = stmt.order_by(ConversationMessage.id.asc())

        with trace_db_session() as session:
            rows = list(session.scalars(stmt).all())
            for row in rows:
                session.expunge(row)
            return rows

    def create_summary(
        self,
        *,
        sender_id: str,
        last_message_id: int,
        content: str,
        conversation_id: str | None = None,
    ) -> ConversationSummary:
        summary = ConversationSummary(
            sender_id=sender_id,
            conversation_id=conversation_id,
            last_message_id=last_message_id,
            content=content,
        )
        with trace_db_session() as session:
            session.add(summary)
            session.flush()
            session.refresh(summary)
            session.expunge(summary)
        return summary

    def _message_scope(
        self,
        *,
        sender_id: str,
        conversation_id: str | None,
    ) -> Select[tuple[ConversationMessage]]:
        stmt = select(ConversationMessage).where(ConversationMessage.sender_id == sender_id)
        if conversation_id:
            stmt = stmt.where(ConversationMessage.conversation_id == conversation_id)
        return stmt
    
    def load_latest_user_messages(
        self,
        *,
        sender_id: str,
        conversation_id: str | None = None,
        limit: int,
    ) -> list[ConversationMessage]:
        stmt = self._message_scope(sender_id=sender_id, conversation_id=conversation_id)
        stmt = (
            stmt.where(ConversationMessage.role == "user")
            .order_by(ConversationMessage.id.desc())
            .limit(max(1, limit))
        )

        with trace_db_session() as session:
            rows = list(session.scalars(stmt).all())
            for row in rows:
                session.expunge(row)
            return rows
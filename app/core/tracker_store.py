from __future__ import annotations

from typing import Any

from app.core.exceptions import ForbiddenError
from app.core.tracker import DialogueStateTracker
from app.entry.authorization import AuthorizedContext
from app.memory import DEFAULT_RECENT_TURN_LIMIT, ConversationMemory


TrackerKey = tuple[str, str]


class _StoreTracker(DialogueStateTracker):
    """Temporary dict-compatible tracker for the current Agent implementation."""

    def __init__(
        self,
        sender_id: str,
        *,
        tenant_id: str,
        owner_user_id: str,
        memory_turn_limit: int = DEFAULT_RECENT_TURN_LIMIT,
    ):
        super().__init__(
            sender_id,
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            memory_turn_limit=memory_turn_limit,
        )

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def __setitem__(self, key: str, value: Any) -> None:
        setattr(self, key, value)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def setdefault(self, key: str, default: Any = None) -> Any:
        if not hasattr(self, key):
            setattr(self, key, default)
        return getattr(self, key)

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
        *,
        memory_turn_limit: int = DEFAULT_RECENT_TURN_LIMIT,
    ) -> "_StoreTracker":
        tracker = cls(
            sender_id=str(data.get("sender_id") or ""),
            tenant_id=str(data.get("tenant_id") or ""),
            owner_user_id=str(data.get("owner_user_id") or ""),
            memory_turn_limit=memory_turn_limit,
        )
        tracker.slots = dict(data.get("slots") or {})
        tracker.events = list(data.get("events") or [])
        if isinstance(data.get("memory"), dict):
            tracker.memory = ConversationMemory.from_dict(
                data.get("memory"),
                recent_turn_limit=memory_turn_limit,
            )
        else:
            tracker.memory = ConversationMemory.from_events(
                tracker.events,
                recent_turn_limit=memory_turn_limit,
            )
        tracker.latest_message = data.get("latest_message")
        tracker.latest_bot_message = data.get("latest_bot_message")
        tracker.active_flow = data.get("active_flow")
        tracker.flow_status = str(data.get("flow_status") or "idle")
        tracker.flow_step_index = int(data.get("flow_step_index") or 0)
        tracker.slot_to_collect = data.get("slot_to_collect")
        tracker.flow_history = list(data.get("flow_history") or [])
        tracker.latest_action_name = data.get("latest_action_name")
        tracker.created_at = data.get("created_at") or tracker.created_at
        tracker.updated_at = data.get("updated_at") or tracker.updated_at
        return tracker


class InMemoryTrackerStore:
    """Tenant-scoped Tracker storage for the phase-0 in-memory runtime.

    Tracker keys are always ``(tenant_id, owner_user_id)``. Legacy sender-only
    entries may remain in ``_data`` during an in-process upgrade, but normal
    methods never search, adopt, migrate, or delete them.
    """

    def __init__(self, *, memory_turn_limit: int = DEFAULT_RECENT_TURN_LIMIT):
        self.memory_turn_limit = memory_turn_limit
        self._data: dict[TrackerKey | str, DialogueStateTracker | dict[str, Any]] = {}

    def get_or_create(self, context: AuthorizedContext) -> DialogueStateTracker:
        context = self._require_context(context)
        tracker = self.retrieve(context)
        if tracker is None:
            tracker = _StoreTracker(
                context.owner_user_id,
                tenant_id=context.tenant_id,
                owner_user_id=context.owner_user_id,
                memory_turn_limit=self.memory_turn_limit,
            )
            self._data[self._key(context, context.owner_user_id)] = tracker
        return tracker

    def save(
        self,
        context: AuthorizedContext,
        tracker: DialogueStateTracker,
    ) -> None:
        context = self._require_context(context)
        owner_user_id = self._verified_tracker_owner(
            tracker,
            expected_tenant_id=context.tenant_id,
        )
        self._authorize_owner(context, owner_user_id)
        self._data[self._key(context, owner_user_id)] = tracker

    def retrieve(
        self,
        context: AuthorizedContext,
        *,
        owner_user_id: str | None = None,
    ) -> DialogueStateTracker | None:
        context = self._require_context(context)
        target_owner = self._target_owner(context, owner_user_id)
        tracker = self._data.get(self._key(context, target_owner))
        if tracker is None:
            return None

        if isinstance(tracker, dict):
            self._verify_serialized_scope(
                tracker,
                tenant_id=context.tenant_id,
                owner_user_id=target_owner,
            )
            tracker = _StoreTracker.from_dict(
                tracker,
                memory_turn_limit=self.memory_turn_limit,
            )
            self._data[self._key(context, target_owner)] = tracker

        self._verify_tracker_scope(
            tracker,
            tenant_id=context.tenant_id,
            owner_user_id=target_owner,
        )
        return tracker

    def delete(
        self,
        context: AuthorizedContext,
        *,
        owner_user_id: str | None = None,
    ) -> bool:
        context = self._require_context(context)
        target_owner = self._target_owner(context, owner_user_id)
        tracker = self.retrieve(context, owner_user_id=target_owner)
        if tracker is None:
            return False
        del self._data[self._key(context, target_owner)]
        return True

    @staticmethod
    def _require_context(context: AuthorizedContext) -> AuthorizedContext:
        if not isinstance(context, AuthorizedContext):
            raise ForbiddenError("permission denied")
        return context

    @staticmethod
    def _key(context: AuthorizedContext, owner_user_id: str) -> TrackerKey:
        return context.tenant_id, owner_user_id

    def _target_owner(
        self,
        context: AuthorizedContext,
        owner_user_id: str | None,
    ) -> str:
        target_owner = (
            context.owner_user_id
            if owner_user_id is None
            else str(owner_user_id).strip()
        )
        if not target_owner:
            raise ForbiddenError("permission denied")
        self._authorize_owner(context, target_owner)
        return target_owner

    @staticmethod
    def _authorize_owner(context: AuthorizedContext, owner_user_id: str) -> None:
        if owner_user_id == context.owner_user_id or context.is_tenant_admin:
            return
        raise ForbiddenError("permission denied")

    @staticmethod
    def _verified_tracker_owner(
        tracker: DialogueStateTracker,
        *,
        expected_tenant_id: str,
    ) -> str:
        tenant_id = str(getattr(tracker, "tenant_id", None) or "").strip()
        owner_user_id = str(getattr(tracker, "owner_user_id", None) or "").strip()
        sender_id = str(getattr(tracker, "sender_id", None) or "").strip()
        if (
            not tenant_id
            or tenant_id != expected_tenant_id
            or not owner_user_id
            or owner_user_id != sender_id
        ):
            raise ForbiddenError("permission denied")
        return owner_user_id

    @classmethod
    def _verify_tracker_scope(
        cls,
        tracker: DialogueStateTracker,
        *,
        tenant_id: str,
        owner_user_id: str,
    ) -> None:
        actual_owner = cls._verified_tracker_owner(
            tracker,
            expected_tenant_id=tenant_id,
        )
        if actual_owner != owner_user_id:
            raise ForbiddenError("permission denied")

    @staticmethod
    def _verify_serialized_scope(
        tracker: dict[str, Any],
        *,
        tenant_id: str,
        owner_user_id: str,
    ) -> None:
        actual_tenant = str(tracker.get("tenant_id") or "").strip()
        actual_owner = str(tracker.get("owner_user_id") or "").strip()
        sender_id = str(tracker.get("sender_id") or "").strip()
        if (
            actual_tenant != tenant_id
            or actual_owner != owner_user_id
            or sender_id != owner_user_id
        ):
            raise ForbiddenError("permission denied")

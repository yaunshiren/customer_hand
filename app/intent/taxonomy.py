from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from .schema import ClarificationConfig, IntentDefinition, IntentGroup


def _normalize_alias(value: str) -> str:
    return value.strip().casefold()


class IntentTaxonomy:
    def __init__(
        self,
        intents: list[IntentDefinition],
        *,
        groups: list[IntentGroup] | None = None,
        clarification: ClarificationConfig | None = None,
        version: str = "v1",
    ) -> None:
        self.version = version
        self.clarification = clarification or ClarificationConfig()

        self._groups = groups or []
        self._intents = intents

        self._group_by_id = {item.id: item for item in self._groups}
        self._by_id = {item.id: item for item in self._intents}

        self._dump_by_id = {item.id: item.model_dump() for item in self._intents}
        self._group_dump_by_id = {item.id: item.model_dump() for item in self._groups}

        self._alias_to_id: dict[str, str] = {}
        for item in self._intents:
            for alias in item.aliases:
                normalized = _normalize_alias(alias)
                if not normalized:
                    continue
                if normalized in self._alias_to_id:
                    raise ValueError(f"duplicate intent alias: {alias.strip()}")
                self._alias_to_id[normalized] = item.id

        self._validate_tree()

    @classmethod
    def load(cls, path: str | Path) -> "IntentTaxonomy":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ValueError("intent taxonomy file must be a mapping")

        version = str(data.get("version") or "v1")

        raw_groups = data.get("groups") or []
        if not isinstance(raw_groups, list):
            raise ValueError("intent taxonomy field 'groups' must be a list")

        raw_intents = data.get("intents") or []
        if not isinstance(raw_intents, list):
            raise ValueError("intent taxonomy field 'intents' must be a list")

        raw_clarification = data.get("clarification") or {}
        if not isinstance(raw_clarification, dict):
            raise ValueError("intent taxonomy field 'clarification' must be a mapping")

        groups: list[IntentGroup] = []
        seen_groups: set[str] = set()
        for raw in raw_groups:
            if not isinstance(raw, dict):
                raise ValueError("each group item must be a mapping")
            item = IntentGroup.model_validate(raw)
            if item.id in seen_groups:
                raise ValueError(f"duplicate intent group id: {item.id}")
            seen_groups.add(item.id)
            groups.append(item)

        intents: list[IntentDefinition] = []
        seen_intents: set[str] = set()
        for raw in raw_intents:
            if not isinstance(raw, dict):
                raise ValueError("each intent item must be a mapping")
            item = IntentDefinition.model_validate(raw)
            if item.id in seen_intents:
                raise ValueError(f"duplicate intent id: {item.id}")
            seen_intents.add(item.id)
            intents.append(item)

        clarification = ClarificationConfig.model_validate(raw_clarification)

        return cls(
            intents,
            groups=groups,
            clarification=clarification,
            version=version,
        )

    @property
    def groups(self) -> list[dict[str, Any]]:
        return [item.model_dump() for item in self._groups]

    @property
    def group_definitions(self) -> list[IntentGroup]:
        return list(self._groups)

    @property
    def intents(self) -> list[dict[str, Any]]:
        return [item.model_dump() for item in self._intents]

    @property
    def definitions(self) -> list[IntentDefinition]:
        return list(self._intents)

    @property
    def enabled_definitions(self) -> list[IntentDefinition]:
        return [item for item in self._intents if item.enabled]

    @property
    def eval_definitions(self) -> list[IntentDefinition]:
        return [item for item in self._intents if item.eval_enabled]

    @property
    def leaf_definitions(self) -> list[IntentDefinition]:
        return [
            item
            for item in self._intents
            if item.level == "intent" and item.id != "UNKNOWN"
        ]

    @property
    def enabled_leaf_definitions(self) -> list[IntentDefinition]:
        return [item for item in self.leaf_definitions if item.enabled]

    def get(self, intent_id: str) -> dict[str, Any] | None:
        item = self._dump_by_id.get(intent_id)
        return deepcopy(item) if item is not None else None

    def get_definition(self, intent_id: str) -> IntentDefinition | None:
        return self._by_id.get(intent_id)

    def get_group(self, group_id: str) -> dict[str, Any] | None:
        item = self._group_dump_by_id.get(group_id)
        return deepcopy(item) if item is not None else None

    def get_group_definition(self, group_id: str) -> IntentGroup | None:
        return self._group_by_id.get(group_id)

    def has(self, intent_id: str) -> bool:
        return intent_id in self._by_id

    def has_group(self, group_id: str) -> bool:
        return group_id in self._group_by_id

    def intent_ids(self, *, enabled_only: bool = False) -> list[str]:
        if enabled_only:
            return [item.id for item in self._intents if item.enabled]
        return list(self._by_id.keys())

    def resolve_id(self, intent_id_or_alias: str) -> str | None:
        normalized_id = intent_id_or_alias.strip()
        if normalized_id in self._by_id:
            return normalized_id
        return self._alias_to_id.get(_normalize_alias(intent_id_or_alias))

    def by_type(self, intent_type: str) -> list[dict[str, Any]]:
        return [
            item.model_dump()
            for item in self._intents
            if item.type == intent_type
        ]

    def by_kind(self, kind: str) -> list[dict[str, Any]]:
        return [
            item.model_dump()
            for item in self._intents
            if item.kind == kind
        ]

    def children_of(self, parent_id: str) -> list[dict[str, Any]]:
        children: list[dict[str, Any]] = []

        for group in self._groups:
            if group.parent_id == parent_id:
                children.append(group.model_dump())

        for intent in self._intents:
            if intent.parent_id == parent_id:
                children.append(intent.model_dump())

        return children

    def full_path(self, intent: IntentDefinition) -> str:
        names = [intent.name]
        parent_id = intent.parent_id

        while parent_id:
            group = self._group_by_id.get(parent_id)
            if group is None:
                break
            names.append(group.name)
            parent_id = group.parent_id

        return " > ".join(reversed(names))

    def to_prompt_items(self, *, enabled_only: bool = True) -> list[dict[str, Any]]:
        definitions = self.enabled_leaf_definitions if enabled_only else self.leaf_definitions

        return [
            {
                "id": item.id,
                "name": item.name,
                "path": self.full_path(item),
                "type": item.type,
                "kind": item.kind or item.type,
                "route": item.route,
                "description": item.description,
                "examples": item.examples[:3],
            }
            for item in definitions
        ]

    def to_prompt_tree(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "clarification": self.clarification.model_dump(),
            "intent_leaf_nodes": self.to_prompt_items(enabled_only=True),
        }

    def _validate_tree(self) -> None:
        node_ids = set(self._group_by_id) | set(self._by_id)

        for group in self._groups:
            if group.parent_id and group.parent_id not in node_ids:
                raise ValueError(
                    f"unknown parent_id for group {group.id}: {group.parent_id}"
                )

        for intent in self._intents:
            if intent.parent_id and intent.parent_id not in node_ids:
                raise ValueError(
                    f"unknown parent_id for intent {intent.id}: {intent.parent_id}"
                )

            if intent.kind == "MCP" and intent.enabled and not intent.mcp_tool_id:
                raise ValueError(
                    f"MCP intent {intent.id} requires mcp_tool_id when enabled"
                )
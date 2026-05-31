from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from .schema import IntentDefinition


DEFAULT_INTENT_TYPES = {"KB", "TOOL", "KB_TOOL", "KB_TICKET", "TICKET", "FLOW", "CHITCHAT", "UNKNOWN"}


def _normalize_alias(value: str) -> str:
    return value.strip().casefold()


class IntentTaxonomy:
    def __init__(self, intents: list[IntentDefinition], version: str = "v1"):
        self.version = version
        self._intents = intents
        self._by_id = {item.id: item for item in intents}
        self._dump_by_id = {item.id: item.model_dump() for item in intents}
        self._alias_to_id: dict[str, str] = {}
        for item in intents:
            for alias in item.aliases:
                normalized = _normalize_alias(alias)
                if not normalized:
                    continue
                if normalized in self._alias_to_id:
                    raise ValueError(f"duplicate intent alias: {alias.strip()}")
                self._alias_to_id[normalized] = item.id

    @classmethod
    def load(cls, path: str | Path) -> "IntentTaxonomy":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        version = str(data.get("version") or "v1")
        raw_intents = data.get("intents") or []
        if not isinstance(raw_intents, list):
            raise ValueError("intent taxonomy field 'intents' must be a list")

        intents: list[IntentDefinition] = []
        seen: set[str] = set()
        for raw in raw_intents:
            if not isinstance(raw, dict):
                raise ValueError("each intent item must be a mapping")
            item = IntentDefinition.model_validate(raw)
            if item.id in seen:
                raise ValueError(f"duplicate intent id: {item.id}")
            seen.add(item.id)
            intents.append(item)

        return cls(intents, version=version)

    @property
    def intents(self) -> list[dict[str, Any]]:
        return [item.model_dump() for item in self._intents]

    @property
    def definitions(self) -> list[IntentDefinition]:
        return list(self._intents)

    def get(self, intent_id: str) -> dict[str, Any] | None:
        item = self._dump_by_id.get(intent_id)
        return deepcopy(item) if item is not None else None

    def get_definition(self, intent_id: str) -> IntentDefinition | None:
        return self._by_id.get(intent_id)

    def has(self, intent_id: str) -> bool:
        return intent_id in self._by_id

    def intent_ids(self) -> list[str]:
        return list(self._by_id.keys())

    def resolve_id(self, intent_id_or_alias: str) -> str | None:
        normalized_id = intent_id_or_alias.strip()
        if normalized_id in self._by_id:
            return normalized_id
        return self._alias_to_id.get(_normalize_alias(intent_id_or_alias))

    def by_type(self, intent_type: str) -> list[dict[str, Any]]:
        return [item.model_dump() for item in self._intents if item.type == intent_type]

    def to_prompt_items(self) -> list[dict[str, Any]]:
        return [
            {
                "id": item.id,
                "name": item.name,
                "type": item.type,
                "description": item.description,
                "examples": item.examples,
                "aliases": item.aliases,
            }
            for item in self._intents
        ]

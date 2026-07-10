from __future__ import annotations

from .models import SkillDefinition


class SkillRegistry:
    def __init__(self) -> None:
        self._definitions: dict[str, SkillDefinition] = {}

    def register(self, definition: SkillDefinition) -> None:
        name = definition.name.strip()
        if name in self._definitions:
            raise ValueError(f"skill already registered: {name}")
        self._definitions[name] = definition

    def get(self, name: str) -> SkillDefinition:
        key = str(name or "").strip()
        definition = self._definitions.get(key)
        if definition is None:
            raise KeyError(f"unknown skill: {key or '<empty>'}")
        return definition

    def list(self) -> list[SkillDefinition]:
        return [self._definitions[name] for name in sorted(self._definitions)]

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._definitions

    def __len__(self) -> int:
        return len(self._definitions)

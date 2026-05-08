from __future__ import annotations

from typing import TypeAlias

from app.actions.base import Action


ActionInput: TypeAlias = Action | type[Action]

_ACTIONS: dict[str, Action] = {}


def register_action(action: ActionInput) -> None:
    if isinstance(action, type):
        if not issubclass(action, Action):
            raise TypeError("action class must inherit from Action")
        action = action()

    if not isinstance(action, Action):
        raise TypeError("action must be an Action instance or Action subclass")

    if not action.name:
        raise ValueError("action.name is required")

    # Duplicate names are intentionally overwritten for simple local development.
    _ACTIONS[action.name] = action


def get_action(name: str) -> Action | None:
    return _ACTIONS.get(name)


def list_actions() -> list[str]:
    return sorted(_ACTIONS.keys())


def clear_actions() -> None:
    _ACTIONS.clear()

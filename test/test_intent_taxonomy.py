from __future__ import annotations

import pytest

from app.intent import IntentDefinition, IntentTaxonomy


def _intent(intent_id: str, *, aliases: list[str] | None = None) -> IntentDefinition:
    return IntentDefinition(
        id=intent_id,
        name=intent_id,
        type="KB",
        description=f"{intent_id} description",
        aliases=aliases or [],
    )


def test_resolve_id_strips_intent_id() -> None:
    taxonomy = IntentTaxonomy([_intent("S1_TEST")])

    assert taxonomy.resolve_id(" S1_TEST ") == "S1_TEST"


def test_resolve_id_matches_alias_case_insensitively() -> None:
    taxonomy = IntentTaxonomy([_intent("S9_NETWORK", aliases=["WiFiConnect"])])

    assert taxonomy.resolve_id("wificonnect") == "S9_NETWORK"
    assert taxonomy.resolve_id(" WIFIConnect ") == "S9_NETWORK"


def test_duplicate_alias_raises_error_after_normalization() -> None:
    with pytest.raises(ValueError, match="duplicate intent alias"):
        IntentTaxonomy(
            [
                _intent("S9_NETWORK", aliases=["WiFiConnect"]),
                _intent("S10_APP", aliases=[" wificonnect "]),
            ]
        )


def test_get_returns_cached_dict_copy() -> None:
    taxonomy = IntentTaxonomy([_intent("S1_TEST", aliases=["test"])])

    first = taxonomy.get("S1_TEST")
    assert first is not None
    first["name"] = "changed"

    second = taxonomy.get("S1_TEST")
    assert second is not None
    assert second["name"] == "S1_TEST"

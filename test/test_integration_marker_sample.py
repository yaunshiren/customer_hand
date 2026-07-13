from __future__ import annotations

import pytest


def test_unit_control_runs_under_default_selector() -> None:
    assert True


@pytest.mark.integration
def test_integration_marker_sample_runs_only_when_explicitly_selected() -> None:
    assert True

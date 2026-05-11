from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.flow_loader import FlowLoader  # noqa: E402


def test_canonical_flow_ids_are_postsale_and_logistics() -> None:
    flows = FlowLoader().load_directory(PROJECT_ROOT / "data" / "flows")

    assert set(flows.keys()) == {"postsale", "logistics"}

"""验收：embed_query('退货规则') 向量维度为 1024。在 customer_hand 目录执行：

    python scripts/test_embed_query.py
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.rag.embedding import EmbeddingClient  # noqa: E402


def main() -> None:
    client = EmbeddingClient.from_env()
    vec = client.embed_query("退货规则")
    print("embedding OK", len(vec), vec[0] if vec else None)
    expected = client.dimensions
    if len(vec) != expected:
        raise SystemExit(f"expected dimension {expected}, got {len(vec)}")


if __name__ == "__main__":
    main()

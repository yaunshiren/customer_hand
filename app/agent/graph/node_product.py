from __future__ import annotations

from functools import lru_cache
import logging

from app.agent.diagnostic.models import ProductContext, ProductResolutionStatus
from app.agent.diagnostic.product_parser import DeterministicProductParser
from app.agent.graph.state import AgentState


logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_product_parser() -> DeterministicProductParser:
    return DeterministicProductParser()


def resolve_product(state: AgentState) -> AgentState:
    """Resolve a product from only the current request message."""

    try:
        message = str(state.get("message") or "")
        product_context = _get_product_parser().parse(message)
    except Exception:
        logger.exception("product resolution failed; using UNKNOWN")
        product_context = ProductContext(
            resolution_status=ProductResolutionStatus.UNKNOWN,
        )

    return {
        **state,
        "product_context": product_context,
    }

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Any, Iterable

from app.rag.documents import KnowledgeChunk
from app.rag.indexer import RetrievalMatch
from app.rag.scoring import metadata_matches_intent


GENERIC_QUERY_BIGRAMS = {
    "什么",
    "怎么",
    "多少",
    "多久",
    "可以",
    "能不",
    "不能",
    "一下",
    "哪里",
    "哪个",
    "哪款",
    "如何",
}

DOMAIN_TERMS: dict[str, tuple[str, ...]] = {
    "S6": ("充电器", "充电线", "配件", "兼容", "保护壳", "贴膜", "耳塞套"),
    "S13": ("滤芯", "保养", "维护", "更换", "多久换", "耗材", "边刷", "主刷"),
    "S14": ("保修", "保修期", "维修", "售后政策", "免费维修", "保外"),
    "S15": ("退货", "退款", "换货", "无理由", "退换货", "重新买"),
    "S16": ("物流", "快递", "发货", "已发货", "改地址", "收货地址", "配送", "拦截", "改派"),
    "S17": ("发票", "抬头", "开票", "会员", "积分"),
    "S9": ("WiFi", "wifi", "配网", "连网", "连接网络", "路由器", "2.4G", "5G"),
    "F1": ("故障", "异常", "报错", "不工作", "不开机", "充不进电", "发烫"),
}

POLICY_TERMS = {
    "保修",
    "保修期",
    "维修",
    "售后政策",
    "退货",
    "退款",
    "换货",
    "价保",
    "补差价",
    "物流",
    "发货",
    "改地址",
    "发票",
    "会员",
}


@dataclass(frozen=True)
class RerankWeights:
    base_score: float = 0.45
    intent_match: float = 0.25
    product_exact: float = 0.30
    title_keyword: float = 0.20
    body_keyword: float = 0.10
    policy_term: float = 0.15
    domain_term: float = 0.12
    multi_channel: float = 0.06
    short_chunk: float = -0.10
    long_chunk: float = -0.05


@dataclass(frozen=True)
class RerankSignal:
    name: str
    delta: float
    detail: str

    def to_dict(self) -> dict[str, str | float]:
        return {"name": self.name, "delta": self.delta, "detail": self.detail}


@dataclass(frozen=True)
class ScoredCandidate:
    match: RetrievalMatch
    original_index: int
    original_score: float
    base_score: float
    rerank_score: float
    signals: tuple[RerankSignal, ...]


class RuleBasedReranker:
    """Explainable reranker for customer-service RAG candidates.

    The reranker is intentionally deterministic and metadata-driven so it can be
    debugged in eval badcases and later replaced or combined with a model reranker.
    """

    def __init__(
        self,
        *,
        weights: RerankWeights | None = None,
        short_chunk_chars: int = 80,
        long_chunk_chars: int = 1800,
    ) -> None:
        self.weights = weights or RerankWeights()
        self.short_chunk_chars = short_chunk_chars
        self.long_chunk_chars = long_chunk_chars

    def rerank(
        self,
        query: str,
        candidates: list[RetrievalMatch],
        intent_id: str | None = None,
        top_k: int | None = None,
    ) -> list[RetrievalMatch]:
        if not candidates:
            return []

        max_score = max(abs(float(candidate.score)) for candidate in candidates) or 1.0
        scored = [
            self._score_candidate(
                query=query,
                match=match,
                intent_id=intent_id,
                original_index=index,
                max_score=max_score,
            )
            for index, match in enumerate(candidates)
        ]
        scored.sort(
            key=lambda item: (
                item.rerank_score,
                item.original_score,
                -item.original_index,
            ),
            reverse=True,
        )

        limit = len(scored) if top_k is None else max(0, top_k)
        return [self._with_rerank_metadata(item) for item in scored[:limit]]

    def _score_candidate(
        self,
        *,
        query: str,
        match: RetrievalMatch,
        intent_id: str | None,
        original_index: int,
        max_score: float,
    ) -> ScoredCandidate:
        metadata = dict(match.chunk.metadata or {})
        base_score = self._base_score(match.score, max_score)
        signals: list[RerankSignal] = [
            RerankSignal(
                name="base_score",
                delta=base_score * self.weights.base_score,
                detail=f"normalized retrieval score {base_score:.3f}",
            )
        ]

        signals.extend(self._intent_signals(metadata, intent_id))
        signals.extend(self._product_signals(query, match.chunk))
        signals.extend(self._keyword_signals(query, match.chunk))
        signals.extend(self._domain_signals(query, match.chunk, intent_id))
        signals.extend(self._channel_signals(metadata))
        signals.extend(self._length_signals(match.chunk))

        rerank_score = sum(signal.delta for signal in signals)
        return ScoredCandidate(
            match=match,
            original_index=original_index,
            original_score=float(match.score),
            base_score=base_score,
            rerank_score=rerank_score,
            signals=tuple(signals),
        )

    def _base_score(self, score: float, max_score: float) -> float:
        if max_score <= 0:
            return 0.0
        return max(0.0, min(1.0, float(score) / max_score))

    def _intent_signals(
        self,
        metadata: dict[str, Any],
        intent_id: str | None,
    ) -> list[RerankSignal]:
        if not metadata_matches_intent(metadata, intent_id):
            return []
        return [
            RerankSignal(
                name="intent_match",
                delta=self.weights.intent_match,
                detail=f"candidate metadata matches {intent_id}",
            )
        ]

    def _product_signals(self, query: str, chunk: KnowledgeChunk) -> list[RerankSignal]:
        query_norm = _normalize(query)
        if not query_norm:
            return []

        products = self._candidate_products(chunk)
        for product in products:
            product_norm = _normalize(product)
            if len(product_norm) >= 4 and product_norm in query_norm:
                return [
                    RerankSignal(
                        name="product_exact_match",
                        delta=self.weights.product_exact,
                        detail=product,
                    )
                ]
        return []

    def _keyword_signals(self, query: str, chunk: KnowledgeChunk) -> list[RerankSignal]:
        signals: list[RerankSignal] = []
        query_terms = _query_terms(query)
        if not query_terms:
            return signals

        metadata = dict(chunk.metadata or {})
        title = str(metadata.get("title") or "")
        title_hits = _matched_terms(query_terms, title)
        if title_hits:
            signals.append(
                RerankSignal(
                    name="title_keyword_hit",
                    delta=self.weights.title_keyword,
                    detail=", ".join(title_hits[:5]),
                )
            )

        body_text = " ".join(
            [
                " ".join(_metadata_values(metadata.get("keywords"))),
                chunk.text[:1200],
            ]
        )
        body_hits = _matched_terms(query_terms, body_text)
        if body_hits:
            signals.append(
                RerankSignal(
                    name="body_keyword_hit",
                    delta=self.weights.body_keyword,
                    detail=", ".join(body_hits[:5]),
                )
            )
        return signals

    def _domain_signals(
        self,
        query: str,
        chunk: KnowledgeChunk,
        intent_id: str | None,
    ) -> list[RerankSignal]:
        signals: list[RerankSignal] = []
        metadata = dict(chunk.metadata or {})
        haystack = _candidate_text(chunk)

        policy_hits = [
            term for term in POLICY_TERMS if _contains_normalized(query, term) and _contains_normalized(haystack, term)
        ]
        if policy_hits and self._is_policy_candidate(metadata):
            signals.append(
                RerankSignal(
                    name="policy_term_hit",
                    delta=self.weights.policy_term,
                    detail=", ".join(policy_hits[:5]),
                )
            )

        intent_code = _intent_code(intent_id)
        if intent_code:
            domain_hits = [
                term
                for term in DOMAIN_TERMS.get(intent_code, ())
                if _contains_normalized(query, term) and _contains_normalized(haystack, term)
            ]
            if domain_hits:
                signals.append(
                    RerankSignal(
                        name="domain_term_hit",
                        delta=self.weights.domain_term,
                        detail=", ".join(domain_hits[:5]),
                    )
                )
        return signals

    def _channel_signals(self, metadata: dict[str, Any]) -> list[RerankSignal]:
        channels = _metadata_values(metadata.get("hybrid_channels"))
        if len(set(channels)) < 2:
            return []
        return [
            RerankSignal(
                name="multi_channel_agreement",
                delta=self.weights.multi_channel,
                detail=", ".join(channels),
            )
        ]

    def _length_signals(self, chunk: KnowledgeChunk) -> list[RerankSignal]:
        length = len(chunk.text.strip())
        if length and length < self.short_chunk_chars:
            return [
                RerankSignal(
                    name="chunk_too_short",
                    delta=self.weights.short_chunk,
                    detail=f"{length} chars",
                )
            ]
        if length > self.long_chunk_chars:
            return [
                RerankSignal(
                    name="chunk_too_long",
                    delta=self.weights.long_chunk,
                    detail=f"{length} chars",
                )
            ]
        return []

    def _candidate_products(self, chunk: KnowledgeChunk) -> list[str]:
        metadata = dict(chunk.metadata or {})
        products: list[str] = []
        products.extend(_metadata_values(metadata.get("product_names")))
        products.extend(_metadata_values(metadata.get("tags")))

        title = str(metadata.get("title") or "")
        for marker in ("商品详情", "用户手册", "使用手册", "指南", "政策", "规则"):
            if marker in title:
                products.append(title.split(marker, 1)[0].strip())
        return _dedup_texts(products)

    def _is_policy_candidate(self, metadata: dict[str, Any]) -> bool:
        parts = [
            str(metadata.get("doc_type") or ""),
            str(metadata.get("category") or ""),
            str(metadata.get("title") or ""),
        ]
        normalized = _normalize(" ".join(parts))
        return "policy" in normalized or "政策" in "".join(parts) or "规则" in "".join(parts)

    def _with_rerank_metadata(self, scored: ScoredCandidate) -> RetrievalMatch:
        metadata = dict(scored.match.chunk.metadata or {})
        metadata["rerank_score"] = scored.rerank_score
        metadata["rerank_base_score"] = scored.base_score
        metadata["rerank_original_score"] = scored.original_score
        metadata["rerank_signals"] = [signal.to_dict() for signal in scored.signals]
        chunk = KnowledgeChunk(
            chunk_id=scored.match.chunk.chunk_id,
            source=scored.match.chunk.source,
            text=scored.match.chunk.text,
            metadata=metadata,
        )
        return RetrievalMatch(chunk=chunk, score=scored.rerank_score)


def _intent_code(intent_id: str | None) -> str:
    if not intent_id:
        return ""
    return intent_id.strip().split("_", 1)[0]


def _candidate_text(chunk: KnowledgeChunk) -> str:
    metadata = dict(chunk.metadata or {})
    return " ".join(
        [
            str(metadata.get("title") or ""),
            str(metadata.get("category") or ""),
            str(metadata.get("doc_type") or ""),
            " ".join(_metadata_values(metadata.get("keywords"))),
            " ".join(_metadata_values(metadata.get("tags"))),
            chunk.text[:1200],
        ]
    )


def _query_terms(query: str) -> list[str]:
    terms = [term for term in _bigrams(query) if term not in GENERIC_QUERY_BIGRAMS]
    for domain_terms in DOMAIN_TERMS.values():
        for term in domain_terms:
            if _contains_normalized(query, term):
                terms.append(term)
    return _dedup_texts(terms)


def _matched_terms(terms: Iterable[str], text: str) -> list[str]:
    return [term for term in terms if _contains_normalized(text, term)]


def _contains_normalized(text: str, needle: str) -> bool:
    normalized_text = _normalize(text)
    normalized_needle = _normalize(needle)
    return bool(normalized_needle) and normalized_needle in normalized_text


def _normalize(text: str) -> str:
    return "".join(
        char.lower()
        for char in str(text)
        if "\u4e00" <= char <= "\u9fff" or (char.isascii() and char.isalnum())
    )


def _bigrams(text: str) -> list[str]:
    normalized = _normalize(text)
    if len(normalized) < 2:
        return [normalized] if normalized else []
    return [normalized[index : index + 2] for index in range(len(normalized) - 1)]


def _metadata_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        if stripped.startswith("[") and stripped.endswith("]"):
            try:
                parsed = ast.literal_eval(stripped)
            except Exception:
                parsed = None
            if isinstance(parsed, (list, tuple, set)):
                return [str(item).strip() for item in parsed if str(item).strip()]
        return [stripped]
    return [str(value).strip()]


def _dedup_texts(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        stripped = str(value).strip()
        key = _normalize(stripped)
        if not stripped or not key or key in seen:
            continue
        seen.add(key)
        result.append(stripped)
    return result

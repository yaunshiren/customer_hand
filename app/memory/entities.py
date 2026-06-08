from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from app.rag.documents import KnowledgeDocumentLoader

ENTITY_KEYS = ("product", "order_id", "intent")


@dataclass(frozen=True, slots=True)
class EntityEvidence:
    value: str
    source: str
    signal: str

    def to_dict(self) -> dict[str, str]:
        return {
            "value": self.value,
            "source": self.source,
            "signal": self.signal,
        }


@dataclass(frozen=True, slots=True)
class EntityExtractionResult:
    entities: dict[str, str] = field(default_factory=dict)
    evidence: dict[str, EntityEvidence] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entities": dict(self.entities),
            "evidence": {key: value.to_dict() for key, value in self.evidence.items()},
        }


@dataclass(frozen=True, slots=True)
class ProductMatch:
    product: str
    signal: str


@dataclass(frozen=True, slots=True)
class _ProductCandidate:
    canonical: str
    aliases: tuple[str, ...]


class ProductCatalog:
    def __init__(self, product_names: Iterable[str] | None = None) -> None:
        names = _dedupe_preserve_order(_clean_text(item, max_chars=256) for item in (product_names or []))
        self._candidates = tuple(_ProductCandidate(name, tuple(_product_aliases(name))) for name in names if name)
        self._ordered = tuple(
            sorted(
                self._candidates,
                key=lambda item: max((len(_compact(alias)) for alias in item.aliases), default=0),
                reverse=True,
            )
        )

    @classmethod
    def from_knowledge_dir(cls, knowledge_dir: Path | None) -> "ProductCatalog":
        if knowledge_dir is None or not knowledge_dir.exists():
            return cls(FALLBACK_PRODUCT_NAMES)

        names: list[str] = []
        try:
            documents = KnowledgeDocumentLoader().load_documents(knowledge_dir)
        except Exception:
            return cls(FALLBACK_PRODUCT_NAMES)

        for document in documents:
            metadata = document.metadata or {}
            for value in _iter_metadata_values(metadata.get("product_names")):
                names.append(value)

            title = str(metadata.get("title") or "").strip()
            if title.endswith("商品详情"):
                names.append(title[: -len("商品详情")].strip())

        names.extend(FALLBACK_PRODUCT_NAMES)
        return cls(names)

    def find(self, text: str) -> ProductMatch | None:
        if not text or not self._ordered:
            return None

        normalized_text = _normalize(text)
        compact_text = _compact(normalized_text)
        for candidate in self._ordered:
            for alias in candidate.aliases:
                normalized_alias = _normalize(alias)
                compact_alias = _compact(normalized_alias)
                if not compact_alias:
                    continue
                if normalized_alias in normalized_text or compact_alias in compact_text:
                    return ProductMatch(product=candidate.canonical, signal=alias)

        fallback = _extract_product_by_pattern(text)
        if fallback:
            return ProductMatch(product=fallback, signal="product_model_pattern")
        return None


class MemoryEntityExtractor:
    def __init__(self, product_catalog: ProductCatalog | None = None) -> None:
        self.product_catalog = product_catalog or ProductCatalog(FALLBACK_PRODUCT_NAMES)

    @classmethod
    def from_knowledge_dir(cls, knowledge_dir: Path | None) -> "MemoryEntityExtractor":
        return cls(ProductCatalog.from_knowledge_dir(knowledge_dir))

    def extract(
        self,
        *,
        user_text: str = "",
        assistant_text: str = "",
        tracker: Any | None = None,
        intent_result: Any | None = None,
        business_classification: Any | None = None,
    ) -> EntityExtractionResult:
        entities: dict[str, str] = {}
        evidence: dict[str, EntityEvidence] = {}

        self._put_product(entities, evidence, user_text, source="user")
        if "product" not in entities:
            self._put_product(entities, evidence, assistant_text, source="assistant")

        self._put_order_id(entities, evidence, user_text, source="user")
        if "order_id" not in entities:
            self._put_order_id(entities, evidence, assistant_text, source="assistant")
        if "order_id" not in entities:
            self._put_order_id_from_business(entities, evidence, business_classification)

        self._put_intent(entities, evidence, user_text, source="user")
        if "intent" not in entities:
            self._put_intent(entities, evidence, assistant_text, source="assistant")
        if "intent" not in entities:
            self._put_intent_from_runtime(entities, evidence, intent_result, business_classification)

        return EntityExtractionResult(entities=entities, evidence=evidence)

    def update_memory(
        self,
        memory: Any,
        *,
        user_text: str = "",
        assistant_text: str = "",
        tracker: Any | None = None,
        intent_result: Any | None = None,
        business_classification: Any | None = None,
    ) -> EntityExtractionResult:
        result = self.extract(
            user_text=user_text,
            assistant_text=assistant_text,
            tracker=tracker,
            intent_result=intent_result,
            business_classification=business_classification,
        )
        if result.entities and hasattr(memory, "update_entities"):
            memory.update_entities(result.entities)
        return result

    def _put_product(
        self,
        entities: dict[str, str],
        evidence: dict[str, EntityEvidence],
        text: str,
        *,
        source: str,
    ) -> None:
        match = self.product_catalog.find(text)
        if match is None:
            return
        entities["product"] = match.product
        evidence["product"] = EntityEvidence(value=match.product, source=source, signal=match.signal)

    def _put_order_id(
        self,
        entities: dict[str, str],
        evidence: dict[str, EntityEvidence],
        text: str,
        *,
        source: str,
    ) -> None:
        order_id, signal = _extract_order_id(text)
        if not order_id:
            return
        entities["order_id"] = order_id
        evidence["order_id"] = EntityEvidence(value=order_id, source=source, signal=signal)

    def _put_order_id_from_business(
        self,
        entities: dict[str, str],
        evidence: dict[str, EntityEvidence],
        business_classification: Any | None,
    ) -> None:
        data = _as_dict(business_classification)
        arguments = data.get("extracted_arguments")
        if not isinstance(arguments, dict):
            return
        order_id = _clean_text(arguments.get("order_id"), max_chars=128)
        if not order_id:
            return
        entities["order_id"] = order_id
        evidence["order_id"] = EntityEvidence(value=order_id, source="business_classification", signal="order_id")

    def _put_intent(
        self,
        entities: dict[str, str],
        evidence: dict[str, EntityEvidence],
        text: str,
        *,
        source: str,
    ) -> None:
        intent, signal = _extract_issue_type(text)
        if not intent:
            return
        entities["intent"] = intent
        evidence["intent"] = EntityEvidence(value=intent, source=source, signal=signal)

    def _put_intent_from_runtime(
        self,
        entities: dict[str, str],
        evidence: dict[str, EntityEvidence],
        intent_result: Any | None,
        business_classification: Any | None,
    ) -> None:
        intent_data = _as_dict(intent_result)
        intent_name = _clean_text(intent_data.get("intent_name"), max_chars=128)
        intent_id = _clean_text(intent_data.get("intent_id"), max_chars=128)
        if intent_name and intent_id != "UNKNOWN":
            entities["intent"] = intent_name
            evidence["intent"] = EntityEvidence(value=intent_name, source="intent_classifier", signal=intent_id)
            return

        business_data = _as_dict(business_classification)
        question_type = _clean_text(business_data.get("question_type"), max_chars=128)
        label = BUSINESS_QUESTION_TYPE_LABELS.get(question_type)
        if label:
            entities["intent"] = label
            evidence["intent"] = EntityEvidence(value=label, source="business_classifier", signal=question_type)


def _extract_order_id(text: str) -> tuple[str, str]:
    normalized = unicodedata.normalize("NFKC", str(text or "")).strip()
    if not normalized:
        return "", ""

    for pattern in EXPLICIT_ORDER_PATTERNS:
        match = pattern.search(normalized)
        if match and _looks_like_order_id(match.group("order_id")):
            return match.group("order_id").strip(), "explicit_order_id"

    lookup_text = normalized.casefold()
    if not _contains_any(lookup_text, ORDER_CONTEXT_KEYWORDS):
        return "", ""

    for match in FALLBACK_ORDER_ID_RE.finditer(normalized):
        value = match.group("order_id").strip()
        if _looks_like_order_id(value) and not _looks_like_product_model(lookup_text, value.casefold()):
            return value, "context_order_id"
    return "", ""


def _extract_issue_type(text: str) -> tuple[str, str]:
    normalized = _normalize(text)
    if not normalized:
        return "", ""
    for label, keywords in ISSUE_TYPE_KEYWORDS:
        hit = next((keyword for keyword in keywords if keyword in normalized), "")
        if hit:
            return label, hit
    return "", ""


def _extract_product_by_pattern(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).strip()
    for pattern in PRODUCT_MODEL_PATTERNS:
        match = pattern.search(normalized)
        if match:
            return _normalize_product_spacing(match.group("product"))
    return ""


def _normalize_product_spacing(value: str) -> str:
    text = re.sub(r"\s+", " ", value.strip())
    text = re.sub(r"(小米|红米|米家|Redmi)\s*(\d)", r"\1 \2", text, flags=re.I)
    text = re.sub(r"\s+(Pro|Ultra|Max|Lite)\b", r" \1", text, flags=re.I)
    return text.strip()


def _product_aliases(product_name: str) -> list[str]:
    normalized = _normalize_product_spacing(product_name)
    aliases = [normalized, normalized.replace(" ", "")]
    aliases.append(re.sub(r"(小米|红米|米家)\s+", r"\1", normalized, flags=re.I))
    aliases.append(re.sub(r"\s+(Pro|Ultra|Max|Lite)\b", r"\1", normalized, flags=re.I))
    return _dedupe_preserve_order(aliases)


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "model_dump"):
        return dict(value.model_dump())
    if isinstance(value, dict):
        return dict(value)
    return {}


def _iter_metadata_values(value: Any) -> Iterable[str]:
    if isinstance(value, list):
        for item in value:
            text = _clean_text(item, max_chars=256)
            if text:
                yield text
    else:
        text = _clean_text(value, max_chars=256)
        if text:
            yield text


def _normalize(value: str) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip().casefold()


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", _normalize(value))


def _clean_text(value: Any, *, max_chars: int = 4000) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def _dedupe_preserve_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = _clean_text(value, max_chars=256)
        key = _compact(text)
        if not text or not key or key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _looks_like_order_id(value: str) -> bool:
    text = value.strip()
    if len(text) < 4 or len(text) > 64:
        return False
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", text, flags=re.IGNORECASE):
        return False
    return any(ch.isdigit() for ch in text)


def _looks_like_product_model(text: str, value: str) -> bool:
    index = text.find(value)
    if index < 0:
        return False
    window = text[max(0, index - 12) : index + len(value) + 12]
    return _contains_any(window, PRODUCT_MODEL_MARKERS)


FALLBACK_PRODUCT_NAMES = (
    "小米 14 Pro",
    "小米 14",
    "小米 13 Pro",
    "小米 13",
    "Redmi K70",
    "Redmi Note 13",
)

PRODUCT_MODEL_PATTERNS = (
    re.compile(r"(?P<product>(?:小米|红米|Redmi)\s*[A-Za-z]*\s*\d{1,3}\s*(?:Pro|Ultra|Max|Lite)?)", re.I),
    re.compile(r"(?P<product>RedmiBook\s+Pro\s+\d{1,2})", re.I),
)

EXPLICIT_ORDER_PATTERNS = (
    re.compile(r"(?:订单号?|单号|订单编号|order(?:\s*id)?)[\s:#：-]*(?P<order_id>[a-z0-9][a-z0-9_-]{3,63})", re.I),
)
FALLBACK_ORDER_ID_RE = re.compile(r"(?<![a-z0-9_-])(?P<order_id>[a-z]?\d[a-z0-9_-]{3,63})(?![a-z0-9_-])", re.I)

ORDER_CONTEXT_KEYWORDS = ("订单", "单号", "order", "物流", "快递", "发货", "到哪", "发票", "开票")
PRODUCT_MODEL_MARKERS = ("小米", "redmi", "pro", "max", "ultra", "手机", "平板", "手表")

ISSUE_TYPE_KEYWORDS = (
    ("保修", ("保修", "质保", "保外", "维修", "售后政策")),
    ("退货", ("7天无理由", "7 天无理由", "七天无理由", "退货", "退款", "不想要")),
    ("换货", ("换货", "换新", "更换")),
    ("物流", ("物流", "快递", "发货", "配送", "到哪", "签收", "运单", "改地址", "收货地址")),
    ("发票", ("发票", "开票", "抬头", "税号")),
    ("投诉", ("投诉", "态度差", "差评", "不满意", "消协")),
    ("故障", ("故障", "异常", "报错", "充不进电", "不开机", "发热", "不工作")),
    ("价格", ("价保", "降价", "优惠", "券", "补差价")),
    ("配件兼容", ("充电器", "保护壳", "贴膜", "耳塞", "配件", "兼容")),
    ("使用指导", ("怎么用", "如何使用", "设置", "连接", "首次使用", "教程")),
)

BUSINESS_QUESTION_TYPE_LABELS = {
    "policy": "政策咨询",
    "order_query": "订单查询",
    "logistics_query": "物流",
    "complaint": "投诉",
    "invoice_policy": "发票",
    "invoice_create": "发票",
}

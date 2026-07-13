from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
import re
import unicodedata

import yaml

from app.agent.diagnostic.models import (
    ProductContext,
    ProductEvidence,
    ProductResolutionStatus,
    ProductSupportLevel,
)


DEFAULT_CATALOG_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "catalog" / "cleaning_products.yml"
)


@dataclass(frozen=True)
class _CatalogProduct:
    model_id: str
    supported: bool
    support_level: ProductSupportLevel | None


@dataclass(frozen=True)
class _AliasPattern:
    matched_alias: str
    normalized_alias: str
    product: _CatalogProduct
    regex: re.Pattern[str]
    priority: int


@dataclass(frozen=True)
class _NormalizedText:
    value: str
    source_starts: tuple[int, ...]
    source_ends: tuple[int, ...]


@dataclass(frozen=True)
class _CandidateMatch:
    alias: _AliasPattern
    normalized_start: int
    normalized_end: int
    original_start: int
    original_end: int


class DeterministicProductParser:
    """Resolve product aliases from one user message using only the YAML catalog."""

    def __init__(self, catalog_path: str | Path = DEFAULT_CATALOG_PATH) -> None:
        self._catalog_path = Path(catalog_path)
        self._patterns, self._products = _load_catalog(self._catalog_path)

    def parse(self, user_message: str) -> ProductContext:
        if not isinstance(user_message, str):
            raise TypeError("user_message must be a string")

        normalized = _normalize_message(user_message)
        candidates = self._find_candidates(normalized)
        selected = _select_non_overlapping(candidates)
        selected.sort(key=lambda item: (item.original_start, item.original_end))

        evidence = tuple(
            ProductEvidence(
                matched_alias=item.alias.matched_alias,
                model_id=item.alias.product.model_id,
                start=item.original_start,
                end=item.original_end,
            )
            for item in selected
        )
        matched_models = _ordered_unique(
            [item.alias.product.model_id for item in selected if item.alias.product.supported]
        )
        unsupported_mentions = _ordered_unique(
            [item.alias.product.model_id for item in selected if not item.alias.product.supported]
        )

        if not matched_models and not unsupported_mentions:
            return ProductContext(resolution_status=ProductResolutionStatus.UNKNOWN)

        if len(matched_models) == 1 and not unsupported_mentions:
            model_id = matched_models[0]
            return ProductContext(
                resolution_status=ProductResolutionStatus.RESOLVED,
                model_id=model_id,
                matched_models=matched_models,
                support_level=self._products[model_id].support_level,
                evidence=evidence,
            )

        if not matched_models:
            return ProductContext(
                resolution_status=ProductResolutionStatus.UNSUPPORTED,
                unsupported_mentions=unsupported_mentions,
                evidence=evidence,
            )

        return ProductContext(
            resolution_status=ProductResolutionStatus.CONFLICT,
            matched_models=matched_models,
            unsupported_mentions=unsupported_mentions,
            evidence=evidence,
        )

    def _find_candidates(self, normalized: _NormalizedText) -> list[_CandidateMatch]:
        candidates: list[_CandidateMatch] = []
        for alias in self._patterns:
            for match in alias.regex.finditer(normalized.value):
                start, end = match.span()
                candidates.append(
                    _CandidateMatch(
                        alias=alias,
                        normalized_start=start,
                        normalized_end=end,
                        original_start=normalized.source_starts[start],
                        original_end=normalized.source_ends[end - 1],
                    )
                )
        return candidates


def _load_catalog(
    catalog_path: Path,
) -> tuple[tuple[_AliasPattern, ...], dict[str, _CatalogProduct]]:
    try:
        payload = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"unable to load product catalog: {catalog_path}") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("product catalog root must be a mapping")

    products: dict[str, _CatalogProduct] = {}
    patterns: list[_AliasPattern] = []
    alias_owners: dict[str, str] = {}

    for section, supported in (("supported_models", True), ("excluded_models", False)):
        entries = payload.get(section)
        if not isinstance(entries, list):
            raise ValueError(f"catalog {section} must be a list")
        for entry in entries:
            product, aliases = _parse_catalog_entry(entry, section=section, supported=supported)
            if product.model_id in products:
                raise ValueError(f"duplicate catalog model_id: {product.model_id}")
            products[product.model_id] = product

            for alias in aliases:
                normalized_alias = _normalize_alias(alias)
                owner = alias_owners.get(normalized_alias)
                if owner is not None and owner != product.model_id:
                    raise ValueError(
                        f"ambiguous catalog alias {alias!r}: owned by {owner} and {product.model_id}"
                    )
                if owner == product.model_id:
                    continue
                alias_owners[normalized_alias] = product.model_id
                patterns.append(
                    _AliasPattern(
                        matched_alias=alias,
                        normalized_alias=normalized_alias,
                        product=product,
                        regex=_compile_alias_pattern(normalized_alias),
                        priority=len(normalized_alias.replace(" ", "")),
                    )
                )

    patterns.sort(key=lambda item: (-item.priority, item.normalized_alias, item.product.model_id))
    return tuple(patterns), products


def _parse_catalog_entry(
    entry: object,
    *,
    section: str,
    supported: bool,
) -> tuple[_CatalogProduct, tuple[str, ...]]:
    if not isinstance(entry, Mapping):
        raise ValueError(f"catalog {section} entries must be mappings")

    model_id = _required_text(entry, "model_id", section)
    canonical_name = _required_text(entry, "canonical_name", section)
    raw_aliases = entry.get("aliases")
    if not isinstance(raw_aliases, list):
        raise ValueError(f"catalog {section}.{model_id}.aliases must be a list")
    aliases = [canonical_name]
    for raw_alias in raw_aliases:
        alias = str(raw_alias or "").strip()
        if not alias:
            raise ValueError(f"catalog {section}.{model_id}.aliases contains a blank alias")
        aliases.append(alias)

    support_level: ProductSupportLevel | None = None
    if supported:
        raw_support_level = _required_text(entry, "support_level", section)
        try:
            support_level = ProductSupportLevel(raw_support_level)
        except ValueError as exc:
            raise ValueError(
                f"catalog {section}.{model_id}.support_level is not supported: {raw_support_level}"
            ) from exc

    product = _CatalogProduct(
        model_id=model_id,
        supported=supported,
        support_level=support_level,
    )
    return product, tuple(aliases)


def _required_text(entry: Mapping[object, object], key: str, section: str) -> str:
    value = str(entry.get(key) or "").strip()
    if not value:
        raise ValueError(f"catalog {section}.{key} must not be blank")
    return value


def _normalize_alias(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = " ".join(normalized.split())
    if not normalized:
        raise ValueError("catalog aliases must not normalize to blank text")
    return normalized


def _normalize_message(value: str) -> _NormalizedText:
    chars: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    for index, char in enumerate(value):
        normalized_char = unicodedata.normalize("NFKC", char).casefold()
        for output_char in normalized_char:
            chars.append(output_char)
            starts.append(index)
            ends.append(index + 1)
    return _NormalizedText(
        value="".join(chars),
        source_starts=tuple(starts),
        source_ends=tuple(ends),
    )


def _compile_alias_pattern(normalized_alias: str) -> re.Pattern[str]:
    parts = normalized_alias.split(" ")
    body = r"\s+".join(re.escape(part) for part in parts)
    if normalized_alias[0].isascii() and normalized_alias[0].isalnum():
        body = rf"(?<![a-z0-9]){body}"
    if normalized_alias[-1].isascii() and normalized_alias[-1].isalnum():
        body = rf"{body}(?![a-z0-9])"
    return re.compile(body)


def _select_non_overlapping(candidates: list[_CandidateMatch]) -> list[_CandidateMatch]:
    ordered = sorted(
        candidates,
        key=lambda item: (
            -item.alias.priority,
            item.normalized_start,
            -(item.normalized_end - item.normalized_start),
            item.alias.normalized_alias,
        ),
    )
    selected: list[_CandidateMatch] = []
    occupied: list[tuple[int, int]] = []
    for candidate in ordered:
        overlaps = any(
            candidate.normalized_start < end and candidate.normalized_end > start
            for start, end in occupied
        )
        if overlaps:
            continue
        selected.append(candidate)
        occupied.append((candidate.normalized_start, candidate.normalized_end))
    return selected


def _ordered_unique(values: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))

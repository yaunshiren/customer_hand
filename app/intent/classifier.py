from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from app.llm.client import LLMClient

from .prompt import IntentPromptBuilder
from .schema import IntentCandidate, IntentResult
from .taxonomy import IntentTaxonomy


@dataclass(frozen=True)
class RuleIntentPattern:
    intent_id: str
    keywords: tuple[str, ...]
    confidence: float
    reason: str


DEFAULT_RULE_PATTERNS: tuple[RuleIntentPattern, ...] = (
    RuleIntentPattern(
        intent_id="F3_投诉吐槽",
        keywords=("投诉", "态度差", "态度太差", "消协", "差评", "不满意", "欺骗消费者"),
        confidence=0.95,
        reason="命中投诉或负向反馈表达",
    ),
    RuleIntentPattern(
        intent_id="F2_功能建议",
        keywords=("希望", "建议", "能不能加", "能否加", "加个", "新增", "优化", "儿童模式"),
        confidence=0.92,
        reason="命中功能建议或产品优化表达",
    ),
    RuleIntentPattern(
        intent_id="S14_售后政策",
        keywords=("保修", "维修", "保修期", "售后政策", "保外", "维修政策"),
        confidence=0.9,
        reason="命中保修或维修政策表达",
    ),
    RuleIntentPattern(
        intent_id="S17_发票会员",
        keywords=("发票", "抬头", "开票", "会员", "积分"),
        confidence=0.9,
        reason="命中发票或会员相关表达",
    ),
    RuleIntentPattern(
        intent_id="S16_物流配送",
        keywords=("物流", "快递", "发货", "改地址", "收货地址", "已经发货", "配送"),
        confidence=0.9,
        reason="命中物流配送相关表达",
    ),
    RuleIntentPattern(
        intent_id="F1_故障报告",
        keywords=("充不进电", "不开机", "发烫", "故障", "异常", "报错", "不工作"),
        confidence=0.9,
        reason="命中设备故障或异常表达",
    ),
)


class RuleIntentCandidateProvider:
    """High-precision intent hints for fallback, not the primary router."""

    def __init__(
        self,
        taxonomy: IntentTaxonomy,
        patterns: tuple[RuleIntentPattern, ...] = DEFAULT_RULE_PATTERNS,
    ) -> None:
        self.taxonomy = taxonomy
        self.patterns = patterns
        for pattern in patterns:
            if not taxonomy.has(pattern.intent_id):
                raise ValueError(f"unknown rule intent id: {pattern.intent_id}")

    def candidates(self, text: str, *, limit: int | None = None) -> list[IntentCandidate]:
        scores: dict[str, float] = {}
        normalized_text = text.casefold()

        for pattern in self.patterns:
            hits = [keyword for keyword in pattern.keywords if keyword.casefold() in normalized_text]
            if not hits:
                continue

            score = min(0.99, pattern.confidence + 0.01 * (len(hits) - 1))
            scores[pattern.intent_id] = max(score, scores.get(pattern.intent_id, 0.0))

        ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        if limit is not None:
            ordered = ordered[: max(0, limit)]
        return [IntentCandidate(intent_id=intent_id, confidence=score) for intent_id, score in ordered]

    def fallback_result(self, text: str) -> IntentResult:
        candidates = self.candidates(text)
        if not candidates:
            return IntentResult(
                intent_id="UNKNOWN",
                intent_name="未知",
                intent_type="UNKNOWN",
                intent_kind="UNKNOWN",
                route="fallback",
                confidence=0.0,
                candidates=[],
                reason="规则未命中高置信意图",
                source="unknown",
            )

        top = candidates[0]
        definition = self.taxonomy.get_definition(top.intent_id)
        if definition is None:
            return IntentResult(
                intent_id="UNKNOWN",
                intent_name="未知",
                intent_type="UNKNOWN",
                intent_kind="UNKNOWN",
                route="fallback",
                confidence=0.0,
                candidates=candidates,
                reason=f"规则命中未知意图：{top.intent_id}",
                source="unknown",
            )

        return IntentResult(
            intent_id=definition.id,
            intent_name=definition.name,
            intent_type=definition.type,
            intent_kind=definition.kind,
            route=definition.route,
            confidence=top.confidence,
            candidates=candidates,
            reason=self._reason_for(definition.id),
            source="rule_fallback",
        )

    def _reason_for(self, intent_id: str) -> str:
        for pattern in self.patterns:
            if pattern.intent_id == intent_id:
                return pattern.reason
        return "规则命中高置信意图"


class IntentClassifier:
    def __init__(
        self,
        taxonomy: IntentTaxonomy,
        *,
        llm_client: LLMClient | None = None,
        rule_provider: RuleIntentCandidateProvider | None = None,
        prompt_builder: IntentPromptBuilder | None = None,
        rule_candidate_limit: int = 5,
    ) -> None:
        self.taxonomy = taxonomy
        self.llm_client = llm_client or LLMClient.from_env()
        self.rule_provider = rule_provider or RuleIntentCandidateProvider(taxonomy)
        self.prompt_builder = prompt_builder or IntentPromptBuilder()
        self.rule_candidate_limit = rule_candidate_limit

    def classify(self, text: str) -> IntentResult:
        rule_candidates = self.rule_provider.candidates(
            text,
            limit=self.rule_candidate_limit,
        )

        if not getattr(self.llm_client, "enabled", False):
            return self._apply_clarification(
                self.rule_provider.fallback_result(text)
            )

        system_prompt, user_prompt = self.prompt_builder.build(
            taxonomy=self.taxonomy,
            user_text=text,
            rule_candidates=rule_candidates,
        )
        llm_result = self.llm_client.generate_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0,
            top_p=1,
        )

        if not llm_result.get("success") or not str(llm_result.get("raw_output") or "").strip():
            return self._apply_clarification(
                self.rule_provider.fallback_result(text)
            )

        try:
            payload = _extract_json_object(str(llm_result.get("raw_output") or ""))
            return self._build_llm_result(payload, rule_candidates=rule_candidates)
        except (TypeError, ValueError, json.JSONDecodeError):
            return self._apply_clarification(
                self.rule_provider.fallback_result(text)
            )

    def _build_llm_result(
        self,
        payload: dict[str, Any],
        *,
        rule_candidates: list[IntentCandidate],
    ) -> IntentResult:
        candidates = self._parse_candidates(payload.get("candidates"))

        # 兼容旧格式：如果 LLM 仍然返回顶层 intent_id/confidence，也纳入候选。
        top_level_candidate = self._parse_top_level_candidate(payload)
        if top_level_candidate is not None:
            candidates.append(top_level_candidate)

        candidates = _dedupe_candidates(candidates)

        reason = _clean_optional_str(payload.get("reason"))

        if not candidates:
            return self._apply_clarification(
                self._rule_fallback_from_candidates(
                    rule_candidates,
                    reason=reason or "LLM 未返回可用候选意图",
                )
            )

        top = candidates[0]
        definition = self.taxonomy.get_definition(top.intent_id)
        if definition is None:
            return self._apply_clarification(
                self._unknown_result(
                    candidates=candidates,
                    reason=f"LLM 返回了未知意图：{top.intent_id}",
                    source="llm_classifier",
                )
            )

        result = IntentResult(
            intent_id=definition.id,
            intent_name=definition.name,
            intent_type=definition.type,
            intent_kind=definition.kind,
            route=definition.route,
            confidence=top.confidence,
            candidates=candidates or rule_candidates,
            reason=reason,
            source="llm_classifier",
        )
        return self._apply_clarification(result)

    def _parse_top_level_candidate(self, payload: dict[str, Any]) -> IntentCandidate | None:
        raw_intent_id = payload.get("intent_id") or payload.get("id")
        if not isinstance(raw_intent_id, str) or not raw_intent_id.strip():
            return None

        if raw_intent_id.strip().upper() == "UNKNOWN":
            return None

        try:
            intent_id = self._resolve_required_intent_id(raw_intent_id)
            if not self._is_selectable_intent(intent_id):
                return None

            raw_confidence = payload.get("confidence", payload.get("score"))
            confidence = _parse_confidence(raw_confidence)
            return IntentCandidate(intent_id=intent_id, confidence=confidence)
        except ValueError:
            return None

    def _parse_candidates(self, raw_candidates: Any) -> list[IntentCandidate]:
        if raw_candidates is None:
            return []
        if not isinstance(raw_candidates, list):
            raise ValueError("candidates must be a list")

        candidates: list[IntentCandidate] = []
        for raw in raw_candidates:
            if not isinstance(raw, dict):
                continue

            raw_intent_id = raw.get("intent_id") or raw.get("id")
            if not isinstance(raw_intent_id, str) or not raw_intent_id.strip():
                continue
            if raw_intent_id.strip().upper() == "UNKNOWN":
                continue

            try:
                intent_id = self._resolve_required_intent_id(raw_intent_id)
                if not self._is_selectable_intent(intent_id):
                    continue

                raw_confidence = raw.get("confidence", raw.get("score"))
                confidence = _parse_confidence(raw_confidence)
            except ValueError:
                continue

            candidates.append(
                IntentCandidate(
                    intent_id=intent_id,
                    confidence=confidence,
                    reason=_clean_optional_str(raw.get("reason")),
                )
            )

        return sorted(candidates, key=lambda item: (-item.confidence, item.intent_id))[:3]

    def _resolve_required_intent_id(self, value: Any) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("intent_id is required")

        intent_id = self.taxonomy.resolve_id(value)
        if intent_id is None:
            raise ValueError(f"unknown intent id: {value}")
        return intent_id

    def _is_selectable_intent(self, intent_id: str) -> bool:
        definitions = getattr(self.taxonomy, "enabled_leaf_definitions", None)
        if definitions is None:
            return True

        selectable_ids = {item.id for item in definitions}
        if not selectable_ids:
            return True
        return intent_id in selectable_ids

    def _apply_clarification(self, result: IntentResult) -> IntentResult:
        config = self.taxonomy.clarification
        candidates = result.candidates

        if len(candidates) >= 2:
            margin = candidates[0].confidence - candidates[1].confidence
            if margin < config.min_margin:
                return result.model_copy(
                    update={
                        "needs_clarification": True,
                        "clarify_reason": "small_margin",
                        "clarify_question": self._ambiguous_question(candidates[:2]),
                    }
                )

        if result.intent_id == "UNKNOWN" or result.intent_type == "UNKNOWN":
            return result.model_copy(
                update={
                    "needs_clarification": False,
                    "clarify_reason": "unknown_intent",
                    "clarify_question": None,
                }
            )

        if result.confidence < config.min_confidence:
            return result.model_copy(
                update={
                    "needs_clarification": False,
                    "clarify_reason": "low_confidence",
                    "clarify_question": None,
                }
            )

        return result

    def _clarify_question_for(self, result: IntentResult) -> str:
        definition = self.taxonomy.get_definition(result.intent_id)
        if definition is not None and definition.clarify_question:
            return definition.clarify_question
        return self.taxonomy.clarification.default_question

    def _ambiguous_question(self, candidates: list[IntentCandidate]) -> str:
        names: list[str] = []
        for candidate in candidates:
            definition = self.taxonomy.get_definition(candidate.intent_id)
            if definition is not None:
                names.append(definition.name)

        if len(names) >= 2:
            return f"你是想咨询「{names[0]}」，还是「{names[1]}」？"
        return self.taxonomy.clarification.default_question

    def _unknown_result(
        self,
        *,
        candidates: list[IntentCandidate],
        reason: str,
        source: str,
    ) -> IntentResult:
        return IntentResult(
            intent_id="UNKNOWN",
            intent_name="未知",
            intent_type="UNKNOWN",
            intent_kind="UNKNOWN",
            route="fallback",
            confidence=0.0,
            candidates=candidates,
            reason=reason,
            source=source,
        )

    def _rule_fallback_from_candidates(
        self,
        candidates: list[IntentCandidate],
        *,
        reason: str,
    ) -> IntentResult:
        for candidate in candidates:
            definition = self.taxonomy.get_definition(candidate.intent_id)
            if definition is None:
                continue
            return IntentResult(
                intent_id=definition.id,
                intent_name=definition.name,
                intent_type=definition.type,
                intent_kind=definition.kind,
                route=definition.route,
                confidence=candidate.confidence,
                candidates=candidates,
                reason=reason,
                source="rule_fallback",
            )
        return self._unknown_result(
            candidates=candidates,
            reason=reason,
            source="llm_classifier",
        )


def _parse_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("confidence must be a number") from exc

    if confidence < 0 or confidence > 1:
        raise ValueError("confidence must be between 0 and 1")
    return confidence


def _dedupe_candidates(candidates: list[IntentCandidate]) -> list[IntentCandidate]:
    by_id: dict[str, IntentCandidate] = {}

    for candidate in candidates:
        existing = by_id.get(candidate.intent_id)
        if existing is None or candidate.confidence > existing.confidence:
            by_id[candidate.intent_id] = candidate

    return sorted(
        by_id.values(),
        key=lambda item: (-item.confidence, item.intent_id),
    )[:3]


def _clean_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _extract_json_object(raw_output: str) -> dict[str, Any]:
    text = raw_output.strip()
    fenced = re.search(
        r"```(?:json)?\s*(\{.*?\})\s*```",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if fenced:
        text = fenced.group(1).strip()

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise
        payload = json.loads(text[start : end + 1])

    if not isinstance(payload, dict):
        raise ValueError("LLM output must be a JSON object")
    return payload

from __future__ import annotations

from pathlib import Path

import pytest

from app.intent import IntentClassifier, IntentPromptBuilder, IntentTaxonomy, RuleIntentCandidateProvider, RuleIntentPattern


INTENT_FILE = Path("data/intents/customer_intents.yml")


class FakeLLMClient:
    def __init__(self, raw_output: str, *, success: bool = True, enabled: bool = True) -> None:
        self.raw_output = raw_output
        self.success = success
        self.enabled = enabled
        self.calls: list[dict[str, object]] = []

    def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float | None = None,
        top_p: float | None = None,
    ) -> dict[str, object]:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "temperature": temperature,
                "top_p": top_p,
            }
        )
        return {
            "success": self.success,
            "raw_output": self.raw_output,
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            "latency_ms": 1,
            "model": "fake",
            "error": None if self.success else "fake error",
        }


@pytest.fixture()
def provider() -> RuleIntentCandidateProvider:
    return RuleIntentCandidateProvider(IntentTaxonomy.load(INTENT_FILE))


@pytest.fixture()
def taxonomy() -> IntentTaxonomy:
    return IntentTaxonomy.load(INTENT_FILE)


@pytest.mark.parametrize(
    ("text", "intent_id"),
    [
        ("我要投诉，准备找消协处理", "F3_投诉吐槽"),
        ("希望 APP 能加个儿童模式", "F2_功能建议"),
        ("扫地机能不能加个语音播报关闭功能", "F2_功能建议"),
        ("这台手机保修期多久", "S14_售后政策"),
        ("发票抬头填错了还能改吗", "S17_发票会员"),
        ("已经发货了还能改地址吗", "S16_物流配送"),
        ("我的扫地机充不进电，还一直报错", "F1_故障报告"),
    ],
)
def test_rule_candidates_cover_high_precision_patterns(
    provider: RuleIntentCandidateProvider,
    text: str,
    intent_id: str,
) -> None:
    candidates = provider.candidates(text)

    assert candidates
    assert candidates[0].intent_id == intent_id


def test_rule_candidates_can_return_multiple_hints(provider: RuleIntentCandidateProvider) -> None:
    candidates = provider.candidates("我要投诉，快递一周还没发货")
    candidate_ids = [candidate.intent_id for candidate in candidates]

    assert candidate_ids[0] == "F3_投诉吐槽"
    assert "S16_物流配送" in candidate_ids


def test_rule_fallback_result_uses_rule_source(provider: RuleIntentCandidateProvider) -> None:
    result = provider.fallback_result("发票抬头怎么修改")

    assert result.intent_id == "S17_发票会员"
    assert result.source == "rule_fallback"
    assert result.candidates[0].intent_id == "S17_发票会员"


def test_rule_fallback_result_returns_unknown_without_match(provider: RuleIntentCandidateProvider) -> None:
    result = provider.fallback_result("随便聊点别的")

    assert result.intent_id == "UNKNOWN"
    assert result.source == "unknown"
    assert result.candidates == []


def test_rule_provider_validates_rule_intent_ids() -> None:
    taxonomy = IntentTaxonomy.load(INTENT_FILE)

    with pytest.raises(ValueError, match="unknown rule intent id"):
        RuleIntentCandidateProvider(
            taxonomy,
            patterns=(
                RuleIntentPattern(
                    intent_id="MISSING",
                    keywords=("missing",),
                    confidence=0.9,
                    reason="missing",
                ),
            ),
        )


def test_intent_prompt_builder_includes_schema_taxonomy_and_rule_candidates(
    taxonomy: IntentTaxonomy,
    provider: RuleIntentCandidateProvider,
) -> None:
    rule_candidates = provider.candidates("已经发货了还能改地址吗")
    system_prompt, user_prompt = IntentPromptBuilder().build(
        taxonomy=taxonomy,
        user_text="已经发货了还能改地址吗",
        rule_candidates=rule_candidates,
    )

    assert "只能输出 JSON" in system_prompt
    assert "intent_id" in system_prompt
    assert "intent_tree" in user_prompt
    assert "rule_candidates" in user_prompt
    assert "S16_物流配送" in user_prompt


def test_llm_intent_classifier_returns_structured_llm_result(taxonomy: IntentTaxonomy) -> None:
    fake_llm = FakeLLMClient(
        """
        ```json
        {
          "intent_id": "S16_物流配送",
          "confidence": 0.86,
          "candidates": [
            {"intent_id": "S16_物流配送", "confidence": 0.86},
            {"intent_id": "S15_退换货", "confidence": 0.42}
          ],
          "reason": "用户询问已发货后是否能改地址"
        }
        ```
        """
    )
    classifier = IntentClassifier(taxonomy, llm_client=fake_llm)

    result = classifier.classify("我能改收货地址吗？已经发货了")

    assert result.intent_id == "S16_物流配送"
    assert result.intent_name == "物流配送"
    assert result.intent_type == "KB_TOOL"
    assert result.confidence == 0.86
    assert result.source == "llm_classifier"
    assert [candidate.intent_id for candidate in result.candidates] == ["S16_物流配送", "S15_退换货"]
    assert fake_llm.calls[0]["temperature"] == 0
    assert fake_llm.calls[0]["top_p"] == 1


def test_llm_intent_classifier_resolves_alias_candidate_ids(taxonomy: IntentTaxonomy) -> None:
    fake_llm = FakeLLMClient(
        """
        {
          "intent_id": "WiFi连接",
          "confidence": 0.7,
          "candidates": [{"intent_id": "WiFi连接", "confidence": 0.7}],
          "reason": "用户描述设备连接网络问题"
        }
        """
    )
    classifier = IntentClassifier(taxonomy, llm_client=fake_llm)

    result = classifier.classify("设备连不上 WiFi")

    assert result.intent_id == "S9_配网连接"
    assert result.candidates[0].intent_id == "S9_配网连接"
    assert result.source == "llm_classifier"


def test_llm_intent_classifier_falls_back_to_rule_when_llm_disabled(taxonomy: IntentTaxonomy) -> None:
    fake_llm = FakeLLMClient("", enabled=False)
    classifier = IntentClassifier(taxonomy, llm_client=fake_llm)

    result = classifier.classify("发票抬头怎么改")

    assert result.intent_id == "S17_发票会员"
    assert result.source == "rule_fallback"
    assert fake_llm.calls == []


@pytest.mark.parametrize(
    "raw_output",
    [
        "",
        "not json",
        '{"intent_id":"MISSING","confidence":0.8,"candidates":[],"reason":"bad"}',
        '{"intent_id":"S16_物流配送","confidence":1.8,"candidates":[],"reason":"bad"}',
    ],
)
def test_llm_intent_classifier_falls_back_to_rule_on_invalid_llm_output(
    taxonomy: IntentTaxonomy,
    raw_output: str,
) -> None:
    fake_llm = FakeLLMClient(raw_output)
    classifier = IntentClassifier(taxonomy, llm_client=fake_llm)

    result = classifier.classify("已经发货了还能改地址吗")

    assert result.intent_id == "S16_物流配送"
    assert result.source == "rule_fallback"


@pytest.mark.parametrize(
    ("text", "intent_id", "intent_name", "intent_type"),
    [
        ("我的扫地机充不进电了", "F1_故障报告", "故障报告", "KB_TICKET"),
        ("希望 APP 能加个深色模式", "F2_功能建议", "功能建议", "TICKET"),
        ("扫地机能不能加个语音播报关闭功能", "F2_功能建议", "功能建议", "TICKET"),
        ("客服态度太差了", "F3_投诉吐槽", "投诉吐槽", "TICKET"),
        ("我能改收货地址吗？已经发货了", "S16_物流配送", "物流配送", "KB_TOOL"),
        ("小米 14 Pro 保修期多久？", "S14_售后政策", "售后政策", "KB"),
        ("小米 14 Pro 用什么充电器？", "S6_配件兼容", "配件兼容", "KB"),
        ("苹果 15 Pro 怎么样？", "C2_越界提问", "越界提问", "CHITCHAT"),
    ],
)
def test_llm_intent_classifier_covers_eval_acceptance_cases(
    taxonomy: IntentTaxonomy,
    text: str,
    intent_id: str,
    intent_name: str,
    intent_type: str,
) -> None:
    fake_llm = FakeLLMClient(
        f"""
        {{
          "intent_id": "{intent_id}",
          "confidence": 0.91,
          "candidates": [{{"intent_id": "{intent_id}", "confidence": 0.91}}],
          "reason": "验收用例分类"
        }}
        """
    )
    classifier = IntentClassifier(taxonomy, llm_client=fake_llm)

    result = classifier.classify(text)

    assert result.intent_id == intent_id
    assert result.intent_name == intent_name
    assert result.intent_type == intent_type
    assert result.source == "llm_classifier"
    assert result.confidence == 0.91

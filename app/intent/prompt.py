from __future__ import annotations

import json

from .schema import IntentCandidate
from .taxonomy import IntentTaxonomy


class IntentPromptBuilder:
    def build(
        self,
        *,
        taxonomy: IntentTaxonomy,
        user_text: str,
        rule_candidates: list[IntentCandidate] | None = None,
    ) -> tuple[str, str]:
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(
            taxonomy=taxonomy,
            user_text=user_text,
            rule_candidates=rule_candidates or [],
        )
        return system_prompt, user_prompt

    def _build_system_prompt(self) -> str:
        return "\n".join(
            [
                "你是智能客服系统中的意图分类器。",
                "你的任务是根据用户输入，从给定的叶子意图列表中选择最匹配的业务意图。",
                "只能输出 JSON，不要输出 Markdown、代码块或自然语言解释。",
                "",
                "分类要求：",
                "- 只能从 intent_leaf_nodes 中选择 intent_id。",
                "- 不要选择中间分组节点，只能选择叶子意图。",
                "- candidates 最多返回 3 个候选意图，按 confidence 从高到低排序。",
                "- confidence 必须是 0 到 1 之间的小数。",
                "- 如果没有任何意图匹配，intent_id 返回 UNKNOWN，confidence 返回 0，candidates 返回空数组。",
                "- intent_id 必须等于 candidates 中 confidence 最高的候选 intent_id。",
                "- 如果 candidates 为空，则 intent_id 必须是 UNKNOWN。",
                "- 不要因为出现商品名就默认选择参数咨询，要结合用户真实诉求。",
                "- 不要因为出现投诉语气就忽略其中明确的物流、故障或售后事实。",
                "- 区分知识库问答和工具调用：询问规则、政策、方法走 KB；查询本人订单、物流、发票等实时状态走 MCP/TOOL。",
                "",
                "输出 JSON schema：",
                "{",
                '  "intent_id": "S16_物流配送",',
                '  "confidence": 0.86,',
                '  "candidates": [',
                '    {',
                '      "intent_id": "S16_物流配送",',
                '      "confidence": 0.86,',
                '      "reason": "用户询问已发货后是否能改地址，属于物流配送规则"',
                "    }",
                "  ],",
                '  "reason": "用户主要询问物流配送规则"',
                "}",
            ]
        )

    def _build_user_prompt(
        self,
        *,
        taxonomy: IntentTaxonomy,
        user_text: str,
        rule_candidates: list[IntentCandidate],
    ) -> str:
        payload = {
            "user_text": user_text,
            "intent_leaf_nodes": taxonomy.to_prompt_items(),
            "rule_candidates": [
                candidate.model_dump()
                for candidate in rule_candidates
            ],
        }
        return (
            "请基于下面 JSON 中的 user_text 和 intent_leaf_nodes 输出意图分类结果。\n"
            "intent_leaf_nodes 是唯一允许选择的叶子意图范围。\n"
            "rule_candidates 只是高精度候选提示，不是最终答案；如果语义不匹配，应忽略它。\n\n"
            f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
        )
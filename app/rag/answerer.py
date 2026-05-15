from __future__ import annotations

from pathlib import Path
from typing import Any

from app.llm.client import LLMClient
from app.rag.retriever import KnowledgeBaseRetriever, RetrievalResult


class KnowledgeAnswerer:
    def __init__(self, docs_dir: Path | None = None) -> None:
        self.retriever = KnowledgeBaseRetriever(docs_dir=docs_dir)
        self.llm = LLMClient.from_env()

    def answer(self, query: str, top_k: int = 3) -> dict[str, Any]:
        retrieval = self.retriever.retrieve(query, top_k=top_k)
        context_blocks = [
            f"来源: {match.chunk.source}\n内容: {match.chunk.text}"
            for match in retrieval.matches
        ]

        if not context_blocks:
            return {
                "answer": "暂时没有找到相关知识，请稍后再试或换个问法。",
                "matches": [],
                "used_llm": False,
            }

        system_prompt = "你是电商客服助手，只能根据给定知识片段回答问题，不能编造。"
        user_prompt = self._build_user_prompt(query=query, context_blocks=context_blocks)
        llm_result = self.llm.generate_json(system_prompt=system_prompt, user_prompt=user_prompt)

        if not llm_result.get("success") or not llm_result.get("raw_output"):
            return {
                "answer": self._fallback_answer(retrieval),
                "matches": self._serialize_matches(retrieval),
                "used_llm": False,
            }

        return {
            "answer": str(llm_result.get("raw_output") or "").strip(),
            "matches": self._serialize_matches(retrieval),
            "used_llm": True,
            "llm_result": llm_result,
        }

    def _build_user_prompt(self, query: str, context_blocks: list[str]) -> str:
        context_text = "\n\n".join(context_blocks)
        return f"""
问题：{query}

知识片段：
{context_text}

请基于以上知识片段回答用户问题，回答要简洁、准确，不要编造。
""".strip()

    def _fallback_answer(self, retrieval: RetrievalResult) -> str:
        sources = ", ".join(match.chunk.source for match in retrieval.matches[:2])
        if sources:
            return f"我找到了相关知识，但当前生成失败。请参考来源：{sources}。"
        return "暂时没有找到相关知识，请稍后再试或换个问法。"

    def _serialize_matches(self, retrieval: RetrievalResult) -> list[dict[str, Any]]:
        return [
            {
                "chunk_id": match.chunk.chunk_id,
                "source": match.chunk.source,
                "score": match.score,
                "text": match.chunk.text,
                "metadata": dict(match.chunk.metadata),
            }
            for match in retrieval.matches
        ]

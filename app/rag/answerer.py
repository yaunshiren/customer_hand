from __future__ import annotations

from pathlib import Path
from typing import Any

from app.llm.client import LLMClient
from app.rag.citation import CitationBuilder
from app.rag.context_builder import ContextBuilder
from app.rag.retriever import KnowledgeBaseRetriever, RetrievalResult
from app.settings import settings
from app.utils.telemetry import emit_rag_event


class KnowledgeAnswerer:
    def __init__(self, docs_dir: Path | None = None) -> None:
        self.retriever = KnowledgeBaseRetriever(docs_dir=docs_dir)
        self.llm = LLMClient.from_env()
        self.context_builder = ContextBuilder()
        self.citation_builder = CitationBuilder(context_builder=self.context_builder)

    def answer(self, query: str, top_k: int = 3, intent_id: str | None = None) -> dict[str, Any]:
        emit_rag_event("answer.start", top_k=top_k, query_len=len(query))
        retrieval = self.retriever.retrieve(query, top_k=top_k, intent_id=intent_id)
        context_blocks = self.context_builder.build(retrieval.matches)
        citation_metadata = self.citation_builder.from_matches(retrieval.matches)

        if not context_blocks:
            emit_rag_event("answer.end", used_llm=False, reason="no_context", match_count=0)
            return {
                "answer": "暂时没有找到相关知识，请稍后再试或换个问法。",
                "matches": [],
                "used_llm": False,
                **citation_metadata,
            }

        system_prompt = "你是电商客服助手，只能根据给定知识片段回答问题，不能编造。"
        user_prompt = self._build_user_prompt(query=query, context_blocks=context_blocks)
        llm_result = self.llm.generate_json(system_prompt=system_prompt, user_prompt=user_prompt)

        if not llm_result.get("success") or not llm_result.get("raw_output"):
            emit_rag_event(
                "answer.end",
                used_llm=False,
                reason="llm_failed",
                match_count=len(retrieval.matches),
            )
            return {
                "answer": self._fallback_answer(retrieval),
                "matches": self._serialize_matches(retrieval),
                "used_llm": False,
                **citation_metadata,
            }

        emit_rag_event("answer.end", used_llm=True, match_count=len(retrieval.matches))
        return {
            "answer": str(llm_result.get("raw_output") or "").strip(),
            "matches": self._serialize_matches(retrieval),
            "used_llm": True,
            "llm_result": llm_result,
            **citation_metadata,
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
        backend = getattr(self.retriever, "backend", settings.rag_backend)
        return [
            {
                "chunk_id": match.chunk.chunk_id,
                "source": match.chunk.source,
                "score": match.score,
                "text": match.chunk.text,
                "metadata": dict(match.chunk.metadata),
                "rag_backend": backend,
            }
            for match in retrieval.matches
        ]

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import eval_retrieval_ablation as ablation


def _case(
    case_id: str,
    expected_doc_ids: list[str],
    retrieved_doc_ids: list[str],
    *,
    mode: str = "vector_bm25",
    channels: list[list[str]] | None = None,
    latency_ms: float = 10.0,
    retrieval_latency_ms: float | None = None,
    intent_latency_ms: float = 0.0,
    applied_intent_id: str | None = None,
    predicted_intent_id: str | None = None,
    predicted_intent_confidence: float | None = None,
    predicted_intent_source: str | None = None,
) -> ablation.CaseResult:
    return ablation.CaseResult(
        case_id=case_id,
        query=f"query {case_id}",
        expected_doc_ids=expected_doc_ids,
        intent_id="S9_NETWORK",
        mode=mode,
        retrieved_doc_ids=retrieved_doc_ids,
        retrieved_chunk_ids=[f"{doc_id}-0" for doc_id in retrieved_doc_ids],
        retrieved_channels=channels or [[] for _ in retrieved_doc_ids],
        latency_ms=latency_ms,
        retrieval_latency_ms=retrieval_latency_ms if retrieval_latency_ms is not None else latency_ms,
        intent_latency_ms=intent_latency_ms,
        applied_intent_id=applied_intent_id,
        predicted_intent_id=predicted_intent_id,
        predicted_intent_confidence=predicted_intent_confidence,
        predicted_intent_source=predicted_intent_source,
    )


def test_parser_defaults_include_three_mode_options() -> None:
    args = ablation.build_parser().parse_args([])

    assert args.llm_mode == "disabled"
    assert args.warmup == 1
    assert args.taxonomy.name == "customer_intents.yml"


def test_load_samples_supports_jsonl_fields_and_filters_non_rag(tmp_path: Path) -> None:
    dataset = tmp_path / "eval.jsonl"
    rows = [
        {
            "query_id": "Q1",
            "query": "wifi reconnect",
            "reference_doc_ids": ["NET_GUIDE_001"],
            "intent_l2": "S9_NETWORK",
            "requires_rag": True,
        },
        {
            "query_id": "Q2",
            "question": "hello",
            "reference_doc_ids": [],
            "intent_l2": "CHAT",
            "requires_rag": False,
        },
        {
            "query_id": "Q3",
            "query": "refund policy",
            "reference_doc_ids": "RET_POLICY_001;RET_POLICY_002",
            "expected_intent": "S2_RETURN",
            "requires_rag": "true",
        },
    ]
    dataset.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows),
        encoding="utf-8",
    )

    rag_samples = ablation.load_samples(dataset)
    assert [sample.case_id for sample in rag_samples] == ["Q1", "Q3"]
    assert rag_samples[1].expected_doc_ids == ["RET_POLICY_001", "RET_POLICY_002"]

    all_samples = ablation.load_samples(dataset, include_non_rag=True)
    assert [sample.case_id for sample in all_samples] == ["Q1", "Q2", "Q3"]
    assert all_samples[1].requires_rag is False

    filtered = ablation.load_samples(
        dataset,
        filter_intent="S9_NETWORK",
        include_non_rag=True,
    )
    assert [sample.case_id for sample in filtered] == ["Q1"]


def test_summarize_results_computes_recall_precision_mrr_and_channels() -> None:
    results = [
        _case(
            "A",
            ["D1"],
            ["D1", "D2"],
            channels=[["vector_global"], ["bm25"]],
            latency_ms=10.0,
        ),
        _case(
            "B",
            ["D3"],
            ["D2", "D3"],
            channels=[["bm25"], ["vector_global", "bm25"]],
            latency_ms=30.0,
        ),
        _case(
            "C",
            [],
            ["D4"],
            channels=[["bm25"]],
            latency_ms=20.0,
        ),
    ]

    summary = ablation.summarize_results(results, k_values=(1, 2))

    assert summary.total == 3
    assert summary.eligible == 2
    assert summary.non_rag == 1
    assert summary.metrics["hit@1"] == pytest.approx(0.5)
    assert summary.metrics["recall@2"] == pytest.approx(1.0)
    assert summary.metrics["precision@2"] == pytest.approx(0.5)
    assert summary.metrics["mrr@10"] == pytest.approx(0.75)
    assert summary.metrics["over_retrieval_rate"] == pytest.approx(1.0)
    assert summary.avg_latency_ms == pytest.approx(20.0)
    assert summary.p95_latency_ms == pytest.approx(30.0)
    assert summary.channel_coverage == {"bm25": 4, "vector_global": 2}


def test_summarize_results_includes_predicted_intent_accuracy() -> None:
    results = [
        _case(
            "A",
            ["D1"],
            ["D1"],
            mode="vector_bm25_predicted_intent",
            applied_intent_id="S9_NETWORK",
            predicted_intent_id="S9_NETWORK",
            predicted_intent_confidence=0.91,
            predicted_intent_source="llm_classifier",
            intent_latency_ms=12.0,
            retrieval_latency_ms=30.0,
            latency_ms=42.0,
        ),
        _case(
            "B",
            ["D2"],
            ["D8"],
            mode="vector_bm25_predicted_intent",
            applied_intent_id="S14_POLICY",
            predicted_intent_id="S14_POLICY",
            predicted_intent_source="rule_fallback",
            intent_latency_ms=8.0,
            retrieval_latency_ms=22.0,
            latency_ms=30.0,
        ),
    ]

    summary = ablation.summarize_results(results, k_values=(1,))

    assert summary.intent_total == 2
    assert summary.intent_correct == 1
    assert summary.intent_accuracy == pytest.approx(0.5)
    assert summary.avg_intent_latency_ms == pytest.approx(10.0)
    assert summary.avg_retrieval_latency_ms == pytest.approx(26.0)
    assert summary.intent_sources == {"llm_classifier": 1, "rule_fallback": 1}


def test_compare_modes_reports_intent_improvements_and_regressions() -> None:
    baseline = [
        _case("A", ["D1"], ["D9"], mode="vector_bm25"),
        _case("B", ["D2"], ["D2"], mode="vector_bm25"),
        _case("C", ["D3"], ["D8"], mode="vector_bm25"),
    ]
    candidate = [
        _case("A", ["D1"], ["D1"], mode="vector_bm25_intent"),
        _case("B", ["D2"], ["D8"], mode="vector_bm25_intent"),
        _case("C", ["D3"], ["D8"], mode="vector_bm25_intent"),
    ]

    comparison = ablation.compare_modes(
        baseline=baseline,
        candidate=candidate,
        k_values=(1, 3),
    )

    assert comparison["improved_count"] == 1
    assert comparison["regressed_count"] == 1
    assert comparison["unchanged_miss_count"] == 1
    assert comparison["improved_cases"][0]["case_id"] == "A"
    assert comparison["regressed_cases"][0]["case_id"] == "B"
    assert comparison["metric_delta"]["hit@1"] == pytest.approx(0.0)


def test_evaluate_mode_passes_intent_only_for_intent_mode() -> None:
    class FakeRetriever:
        def __init__(self) -> None:
            self.calls: list[tuple[str, int, str | None]] = []

        def retrieve(self, query: str, *, top_k: int, intent_id: str | None = None):
            self.calls.append((query, top_k, intent_id))
            return SimpleNamespace(matches=[])

    samples = [
        ablation.EvalSample(
            case_id="Q1",
            query="wifi reconnect",
            expected_doc_ids=["NET_GUIDE_001"],
            intent_id="S9_NETWORK",
        )
    ]

    retriever = FakeRetriever()
    ablation.evaluate_mode(
        retriever,  # type: ignore[arg-type]
        samples,
        mode="vector_bm25",
        top_k=5,
        use_intent=False,
    )
    ablation.evaluate_mode(
        retriever,  # type: ignore[arg-type]
        samples,
        mode="vector_bm25_intent",
        top_k=5,
        use_intent=True,
    )

    assert retriever.calls == [
        ("wifi reconnect", 5, None),
        ("wifi reconnect", 5, "S9_NETWORK"),
    ]


def test_evaluate_mode_predicted_intent_uses_classifier_result() -> None:
    class FakeRetriever:
        def __init__(self) -> None:
            self.calls: list[tuple[str, int, str | None]] = []

        def retrieve(self, query: str, *, top_k: int, intent_id: str | None = None):
            self.calls.append((query, top_k, intent_id))
            return SimpleNamespace(matches=[])

    class FakeClassifier:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def classify(self, text: str):
            self.calls.append(text)
            return SimpleNamespace(
                intent_id="S9_NETWORK",
                confidence=0.88,
                source="fake_classifier",
            )

    samples = [
        ablation.EvalSample(
            case_id="Q1",
            query="wifi reconnect",
            expected_doc_ids=["NET_GUIDE_001"],
            intent_id="S9_NETWORK",
        )
    ]
    retriever = FakeRetriever()
    classifier = FakeClassifier()

    results = ablation.evaluate_mode(
        retriever,  # type: ignore[arg-type]
        samples,
        mode="vector_bm25_predicted_intent",
        top_k=5,
        intent_mode="predicted",
        classifier=classifier,  # type: ignore[arg-type]
    )

    assert classifier.calls == ["wifi reconnect"]
    assert retriever.calls == [("wifi reconnect", 5, "S9_NETWORK")]
    assert results[0].applied_intent_id == "S9_NETWORK"
    assert results[0].predicted_intent_id == "S9_NETWORK"
    assert results[0].predicted_intent_confidence == pytest.approx(0.88)
    assert results[0].predicted_intent_source == "fake_classifier"

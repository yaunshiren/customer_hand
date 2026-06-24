from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.intent import IntentClassifier, IntentTaxonomy  # noqa: E402
from app.llm.client import LLMClient  # noqa: E402
from app.rag.hybrid_retriever import HybridRetriever  # noqa: E402
from app.rag.indexer import RetrievalMatch  # noqa: E402
from app.settings import settings  # noqa: E402

DEFAULT_DATASET = (
    PROJECT_ROOT.parents[1]
    / "ragenteval-main"
    / "eval"
    / "rag"
    / "dataset"
    / "eval_set_v1_all.jsonl"
)
DEFAULT_OUTPUT = PROJECT_ROOT / "docs" / "retrieval_ablation_report.json"
DEFAULT_TAXONOMY = PROJECT_ROOT / "data" / "intents" / "customer_intents.yml"
DEFAULT_K_VALUES = (1, 3, 5, 10)
MODE_BASELINE = "vector_bm25"
MODE_GOLD_INTENT = "vector_bm25_intent"
MODE_PREDICTED_INTENT = "vector_bm25_predicted_intent"


class DisabledLLMClient:
    enabled = False


@dataclass(frozen=True)
class EvalSample:
    case_id: str
    query: str
    expected_doc_ids: list[str]
    intent_id: str | None = None
    requires_rag: bool = True
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    query: str
    expected_doc_ids: list[str]
    intent_id: str | None
    mode: str
    retrieved_doc_ids: list[str]
    retrieved_chunk_ids: list[str]
    retrieved_channels: list[list[str]]
    latency_ms: float
    retrieval_latency_ms: float = 0.0
    intent_latency_ms: float = 0.0
    applied_intent_id: str | None = None
    predicted_intent_id: str | None = None
    predicted_intent_confidence: float | None = None
    predicted_intent_source: str | None = None

    @property
    def is_hit(self) -> bool:
        return bool(set(self.expected_doc_ids) & set(self.retrieved_doc_ids))


@dataclass(frozen=True)
class ModeSummary:
    mode: str
    total: int
    eligible: int
    non_rag: int
    metrics: dict[str, float | None]
    avg_latency_ms: float
    avg_retrieval_latency_ms: float
    avg_intent_latency_ms: float
    p95_latency_ms: float
    avg_retrieved_docs: float
    channel_coverage: dict[str, int]
    applied_intent_count: int
    intent_total: int = 0
    intent_correct: int = 0
    intent_accuracy: float | None = None
    intent_sources: dict[str, int] = field(default_factory=dict)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compare retrieval recall for vector+BM25, vector+BM25+gold-intent, "
            "and vector+BM25+predicted-intent without calling the answer LLM."
        )
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--docs-dir", type=Path, default=settings.knowledge_dir)
    parser.add_argument("--taxonomy", type=Path, default=DEFAULT_TAXONOMY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--filter-intent", default=None)
    parser.add_argument(
        "--warmup",
        type=int,
        default=1,
        help="Run this many sample queries before timed evaluation. Use 0 to disable.",
    )
    parser.add_argument(
        "--llm-mode",
        choices=["disabled", "env"],
        default="disabled",
        help=(
            "IntentClassifier mode for the predicted-intent experiment. "
            "disabled is deterministic rule fallback; env uses LLMClient.from_env()."
        ),
    )
    parser.add_argument(
        "--include-non-rag",
        action="store_true",
        help="Also evaluate samples with requires_rag=false for over-retrieval rate.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=10,
        help="Retrieve this many final candidates. Should be >= max --ks.",
    )
    parser.add_argument(
        "--ks",
        default="1,3,5,10",
        help="Comma-separated K values for hit/recall/precision metrics.",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=20,
        help="Print progress every N samples per mode. Use 0 to disable.",
    )
    parser.add_argument(
        "--require-vector",
        action="store_true",
        help="Exit non-zero when no result contains the vector_global channel.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    k_values = _parse_k_values(args.ks)
    top_k = max(args.top_k, max(k_values))
    samples = load_samples(
        args.dataset,
        start=args.start,
        limit=args.limit,
        filter_intent=args.filter_intent,
        include_non_rag=args.include_non_rag,
    )
    if not samples:
        raise SystemExit("No eval samples loaded.")

    print(
        f"dataset={args.dataset.resolve()} samples={len(samples)} "
        f"docs_dir={args.docs_dir.resolve()} taxonomy={args.taxonomy.resolve()} "
        f"top_k={top_k} llm_mode={args.llm_mode}"
    )

    retriever = HybridRetriever(docs_dir=args.docs_dir)
    retriever.build(args.docs_dir)
    classifier = build_intent_classifier(args.taxonomy, llm_mode=args.llm_mode)
    warmup_count = max(0, args.warmup)
    if warmup_count:
        warmup(
            retriever,
            classifier,
            samples[:warmup_count],
            top_k=top_k,
        )

    mode_results: dict[str, list[CaseResult]] = {
        MODE_BASELINE: evaluate_mode(
            retriever,
            samples,
            mode=MODE_BASELINE,
            top_k=top_k,
            intent_mode="none",
            progress_every=args.progress_every,
        ),
        MODE_GOLD_INTENT: evaluate_mode(
            retriever,
            samples,
            mode=MODE_GOLD_INTENT,
            top_k=top_k,
            intent_mode="gold",
            progress_every=args.progress_every,
        ),
        MODE_PREDICTED_INTENT: evaluate_mode(
            retriever,
            samples,
            mode=MODE_PREDICTED_INTENT,
            top_k=top_k,
            intent_mode="predicted",
            classifier=classifier,
            progress_every=args.progress_every,
        ),
    }
    summaries = {
        mode: summarize_results(results, k_values=k_values)
        for mode, results in mode_results.items()
    }
    comparisons = {
        "gold_vs_baseline": compare_modes(
            baseline=mode_results[MODE_BASELINE],
            candidate=mode_results[MODE_GOLD_INTENT],
            k_values=k_values,
        ),
        "predicted_vs_baseline": compare_modes(
            baseline=mode_results[MODE_BASELINE],
            candidate=mode_results[MODE_PREDICTED_INTENT],
            k_values=k_values,
        ),
        "predicted_vs_gold": compare_modes(
            baseline=mode_results[MODE_GOLD_INTENT],
            candidate=mode_results[MODE_PREDICTED_INTENT],
            k_values=k_values,
        ),
    }

    report = {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "dataset": str(args.dataset.resolve()),
        "docs_dir": str(args.docs_dir.resolve()),
        "taxonomy": str(args.taxonomy.resolve()),
        "llm_mode": args.llm_mode,
        "warmup": warmup_count,
        "top_k": top_k,
        "k_values": list(k_values),
        "sample_count": len(samples),
        "summaries": {mode: asdict(summary) for mode, summary in summaries.items()},
        "comparisons": comparisons,
        "cases": {
            mode: [asdict(result) for result in results]
            for mode, results in mode_results.items()
        },
    }
    _write_report(report, args.output)
    print_report(summaries, comparisons, args.output)

    if args.require_vector:
        total_vector_hits = sum(
            summary.channel_coverage.get("vector_global", 0)
            for summary in summaries.values()
        )
        if total_vector_hits <= 0:
            print(
                "ERROR: vector_global channel produced no retrieved result. "
                "Check embedding/vector-store configuration.",
                file=sys.stderr,
            )
            return 2
    return 0


def load_samples(
    dataset: Path,
    *,
    start: int = 0,
    limit: int | None = None,
    filter_intent: str | None = None,
    include_non_rag: bool = False,
) -> list[EvalSample]:
    rows = _read_rows(dataset)
    samples: list[EvalSample] = []
    for index, row in enumerate(rows):
        sample = _sample_from_row(row, fallback_case_id=str(index + 1))
        if sample is None:
            continue
        if filter_intent and sample.intent_id != filter_intent:
            continue
        if not include_non_rag and not sample.requires_rag:
            continue
        samples.append(sample)

    start = max(0, start)
    if start:
        samples = samples[start:]
    if limit is not None:
        samples = samples[: max(0, limit)]
    return samples


def evaluate_mode(
    retriever: HybridRetriever,
    samples: Sequence[EvalSample],
    *,
    mode: str,
    top_k: int,
    intent_mode: str | None = None,
    use_intent: bool | None = None,
    classifier: IntentClassifier | None = None,
    progress_every: int = 0,
) -> list[CaseResult]:
    if intent_mode is None:
        intent_mode = "gold" if use_intent else "none"
    if intent_mode == "predicted" and classifier is None:
        raise ValueError("classifier is required when intent_mode='predicted'")

    results: list[CaseResult] = []
    start_time = time.perf_counter()
    for index, sample in enumerate(samples, start=1):
        (
            applied_intent_id,
            predicted_intent_id,
            predicted_intent_confidence,
            predicted_intent_source,
            intent_latency_ms,
        ) = _resolve_applied_intent(sample, intent_mode=intent_mode, classifier=classifier)

        before_retrieval = time.perf_counter()
        retrieval = retriever.retrieve(
            sample.query,
            top_k=top_k,
            intent_id=applied_intent_id,
        )
        retrieval_latency_ms = (time.perf_counter() - before_retrieval) * 1000.0
        latency_ms = retrieval_latency_ms + intent_latency_ms
        results.append(
            CaseResult(
                case_id=sample.case_id,
                query=sample.query,
                expected_doc_ids=sample.expected_doc_ids,
                intent_id=sample.intent_id,
                mode=mode,
                retrieved_doc_ids=_retrieved_doc_ids(retrieval.matches),
                retrieved_chunk_ids=_retrieved_chunk_ids(retrieval.matches),
                retrieved_channels=_retrieved_channels(retrieval.matches),
                latency_ms=latency_ms,
                retrieval_latency_ms=retrieval_latency_ms,
                intent_latency_ms=intent_latency_ms,
                applied_intent_id=applied_intent_id,
                predicted_intent_id=predicted_intent_id,
                predicted_intent_confidence=predicted_intent_confidence,
                predicted_intent_source=predicted_intent_source,
            )
        )
        _print_progress(
            mode=mode,
            current=index,
            total=len(samples),
            start_time=start_time,
            progress_every=progress_every,
        )
    return results


def build_intent_classifier(taxonomy_path: Path, *, llm_mode: str) -> IntentClassifier:
    taxonomy = IntentTaxonomy.load(taxonomy_path)
    llm_client = LLMClient.from_env() if llm_mode == "env" else DisabledLLMClient()
    return IntentClassifier(taxonomy, llm_client=llm_client)


def warmup(
    retriever: HybridRetriever,
    classifier: IntentClassifier,
    samples: Sequence[EvalSample],
    *,
    top_k: int,
) -> None:
    for sample in samples:
        retriever.retrieve(sample.query, top_k=top_k, intent_id=None)
        if sample.intent_id:
            retriever.retrieve(sample.query, top_k=top_k, intent_id=sample.intent_id)
        predicted = classifier.classify(sample.query)
        predicted_intent_id = str(getattr(predicted, "intent_id", "") or "").strip()
        if predicted_intent_id and predicted_intent_id != "UNKNOWN":
            retriever.retrieve(sample.query, top_k=top_k, intent_id=predicted_intent_id)


def _resolve_applied_intent(
    sample: EvalSample,
    *,
    intent_mode: str,
    classifier: IntentClassifier | None,
) -> tuple[str | None, str | None, float | None, str | None, float]:
    if intent_mode == "none":
        return None, None, None, None, 0.0

    if intent_mode == "gold":
        return sample.intent_id, None, None, None, 0.0

    if intent_mode != "predicted":
        raise ValueError(f"unknown intent_mode: {intent_mode}")

    if classifier is None:
        raise ValueError("classifier is required when intent_mode='predicted'")

    before_intent = time.perf_counter()
    result = classifier.classify(sample.query)
    intent_latency_ms = (time.perf_counter() - before_intent) * 1000.0
    predicted_intent_id = str(getattr(result, "intent_id", "") or "").strip() or None
    applied_intent_id = predicted_intent_id
    if applied_intent_id == "UNKNOWN":
        applied_intent_id = None
    return (
        applied_intent_id,
        predicted_intent_id,
        _as_optional_float(getattr(result, "confidence", None)),
        _clean_optional_str(getattr(result, "source", None)),
        intent_latency_ms,
    )


def summarize_results(
    results: Sequence[CaseResult],
    *,
    k_values: Sequence[int],
) -> ModeSummary:
    eligible = [result for result in results if result.expected_doc_ids]
    non_rag = [result for result in results if not result.expected_doc_ids]
    metrics: dict[str, float | None] = {}
    for k in k_values:
        metrics[f"hit@{k}"] = _mean(_hit_at_k(result, k) for result in eligible)
        metrics[f"recall@{k}"] = _mean(_recall_at_k(result, k) for result in eligible)
        metrics[f"precision@{k}"] = _mean(_precision_at_k(result, k) for result in eligible)
    metrics["mrr@10"] = _mean(_mrr_at_k(result, 10) for result in eligible)
    metrics["over_retrieval_rate"] = _mean(
        1.0 if result.retrieved_doc_ids else 0.0
        for result in non_rag
    )

    latencies = [result.latency_ms for result in results]
    retrieval_latencies = [result.retrieval_latency_ms for result in results]
    intent_latencies = [result.intent_latency_ms for result in results]
    channel_coverage: dict[str, int] = {}
    for result in results:
        for channels in result.retrieved_channels:
            for channel in channels:
                channel_coverage[channel] = channel_coverage.get(channel, 0) + 1
    intent_eval = [
        result
        for result in results
        if result.intent_id and result.predicted_intent_id is not None
    ]
    intent_correct = sum(
        1
        for result in intent_eval
        if result.predicted_intent_id == result.intent_id
    )
    intent_sources: dict[str, int] = {}
    for result in results:
        if result.predicted_intent_source:
            intent_sources[result.predicted_intent_source] = (
                intent_sources.get(result.predicted_intent_source, 0) + 1
            )

    return ModeSummary(
        mode=results[0].mode if results else "",
        total=len(results),
        eligible=len(eligible),
        non_rag=len(non_rag),
        metrics=metrics,
        avg_latency_ms=_mean(latencies) or 0.0,
        avg_retrieval_latency_ms=_mean(retrieval_latencies) or 0.0,
        avg_intent_latency_ms=_mean(intent_latencies) or 0.0,
        p95_latency_ms=_percentile(latencies, 0.95),
        avg_retrieved_docs=_mean(len(result.retrieved_doc_ids) for result in results) or 0.0,
        channel_coverage=dict(sorted(channel_coverage.items())),
        applied_intent_count=sum(1 for result in results if result.applied_intent_id),
        intent_total=len(intent_eval),
        intent_correct=intent_correct,
        intent_accuracy=_ratio(intent_correct, len(intent_eval)) if intent_eval else None,
        intent_sources=dict(sorted(intent_sources.items())),
    )


def compare_modes(
    *,
    baseline: Sequence[CaseResult],
    candidate: Sequence[CaseResult],
    k_values: Sequence[int],
) -> dict[str, Any]:
    by_case = {result.case_id: result for result in baseline}
    improved: list[dict[str, Any]] = []
    regressed: list[dict[str, Any]] = []
    unchanged_miss: list[dict[str, Any]] = []

    for result in candidate:
        base = by_case.get(result.case_id)
        if base is None or not result.expected_doc_ids:
            continue
        before_hit = base.is_hit
        after_hit = result.is_hit
        item = {
            "case_id": result.case_id,
            "query": result.query,
            "gold_intent_id": result.intent_id,
            "baseline_applied_intent_id": base.applied_intent_id,
            "candidate_applied_intent_id": result.applied_intent_id,
            "candidate_predicted_intent_id": result.predicted_intent_id,
            "expected_doc_ids": result.expected_doc_ids,
            "baseline_doc_ids": base.retrieved_doc_ids,
            "candidate_doc_ids": result.retrieved_doc_ids,
        }
        if not before_hit and after_hit:
            improved.append(item)
        elif before_hit and not after_hit:
            regressed.append(item)
        elif not before_hit and not after_hit:
            unchanged_miss.append(item)

    baseline_summary = summarize_results(baseline, k_values=k_values)
    candidate_summary = summarize_results(candidate, k_values=k_values)
    metric_delta = {
        name: _delta(
            baseline_summary.metrics.get(name),
            candidate_summary.metrics.get(name),
        )
        for name in sorted(candidate_summary.metrics)
    }
    return {
        "baseline": baseline[0].mode if baseline else "",
        "candidate": candidate[0].mode if candidate else "",
        "metric_delta": metric_delta,
        "improved_count": len(improved),
        "regressed_count": len(regressed),
        "unchanged_miss_count": len(unchanged_miss),
        "improved_cases": improved[:100],
        "regressed_cases": regressed[:100],
        "unchanged_miss_cases": unchanged_miss[:100],
    }


def print_report(
    summaries: dict[str, ModeSummary],
    comparisons: dict[str, Any],
    output: Path,
) -> None:
    metric_names = [
        "hit@1",
        "hit@3",
        "hit@5",
        "recall@3",
        "recall@5",
        "mrr@10",
        "over_retrieval_rate",
    ]
    print("")
    print("=== Retrieval Ablation Summary ===")
    print(f"output={output.resolve()}")
    print("")
    header = (
        f"{'metric':<22} {'vector+bm25':>14} {'+gold':>14} "
        f"{'gold_delta':>14} {'+predicted':>14} {'pred_delta':>14}"
    )
    print(header)
    print("-" * len(header))
    base = summaries[MODE_BASELINE]
    gold = summaries[MODE_GOLD_INTENT]
    predicted = summaries[MODE_PREDICTED_INTENT]
    gold_delta = comparisons["gold_vs_baseline"]["metric_delta"]
    predicted_delta = comparisons["predicted_vs_baseline"]["metric_delta"]
    for name in metric_names:
        before = base.metrics.get(name)
        gold_value = gold.metrics.get(name)
        predicted_value = predicted.metrics.get(name)
        print(
            f"{name:<22} {_format_metric(before):>14} "
            f"{_format_metric(gold_value):>14} "
            f"{_format_delta(gold_delta.get(name)):>14} "
            f"{_format_metric(predicted_value):>14} "
            f"{_format_delta(predicted_delta.get(name)):>14}"
        )
    print("")
    for summary in (base, gold, predicted):
        print(
            f"{summary.mode}: total={summary.total} eligible={summary.eligible} "
            f"avg_latency={summary.avg_latency_ms:.1f}ms p95_latency={summary.p95_latency_ms:.1f}ms "
            f"avg_intent={summary.avg_intent_latency_ms:.1f}ms "
            f"avg_retrieval={summary.avg_retrieval_latency_ms:.1f}ms "
            f"avg_docs={summary.avg_retrieved_docs:.2f} "
            f"applied_intents={summary.applied_intent_count} channels={summary.channel_coverage}"
        )
        if summary.intent_total:
            print(
                f"  intent_top1={_format_metric(summary.intent_accuracy)} "
                f"intent_correct={summary.intent_correct}/{summary.intent_total} "
                f"sources={summary.intent_sources}"
            )

    print("")
    for name, comparison in comparisons.items():
        print(
            f"{name}: baseline={comparison['baseline']} candidate={comparison['candidate']} "
            f"improved={comparison['improved_count']} "
            f"regressed={comparison['regressed_count']} "
            f"unchanged_miss={comparison['unchanged_miss_count']}"
        )


def _read_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as file:
            return [dict(row) for row in csv.DictReader(file)]
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _sample_from_row(row: dict[str, Any], *, fallback_case_id: str) -> EvalSample | None:
    query = _pick_str(row, "query", "question", "user_query", "message")
    if not query:
        return None

    expected_doc_ids = _as_str_list(
        _pick(row, "expected_doc_ids", "reference_doc_ids", "expectedDocIds", "referenceDocIds")
    )
    requires_rag_raw = _pick(row, "requires_rag", "requiresRag")
    requires_rag = _as_bool(requires_rag_raw, default=bool(expected_doc_ids))
    case_id = _pick_str(row, "query_id", "case_id", "id") or fallback_case_id
    intent_id = _pick_str(row, "intent_l2", "expected_intent", "intent_id", "intent")
    return EvalSample(
        case_id=case_id,
        query=query,
        expected_doc_ids=expected_doc_ids,
        intent_id=intent_id,
        requires_rag=requires_rag,
        raw=row,
    )


def _retrieved_doc_ids(matches: Sequence[RetrievalMatch]) -> list[str]:
    seen: set[str] = set()
    doc_ids: list[str] = []
    for match in matches:
        doc_id = _doc_id(match)
        if not doc_id or doc_id in seen:
            continue
        seen.add(doc_id)
        doc_ids.append(doc_id)
    return doc_ids


def _retrieved_chunk_ids(matches: Sequence[RetrievalMatch]) -> list[str]:
    return [
        str(match.chunk.chunk_id or "").strip()
        for match in matches
        if str(match.chunk.chunk_id or "").strip()
    ]


def _retrieved_channels(matches: Sequence[RetrievalMatch]) -> list[list[str]]:
    channels: list[list[str]] = []
    for match in matches:
        metadata = dict(match.chunk.metadata or {})
        value = metadata.get("hybrid_channels")
        if isinstance(value, list):
            channels.append([str(item) for item in value])
        elif value:
            channels.append([str(value)])
        else:
            channels.append([])
    return channels


def _doc_id(match: RetrievalMatch) -> str:
    metadata = dict(match.chunk.metadata or {})
    value = str(metadata.get("doc_id") or "").strip()
    if value:
        return value
    source = str(match.chunk.source or "").strip()
    if not source:
        return ""
    return Path(source).stem


def _hit_at_k(result: CaseResult, k: int) -> float:
    expected = set(result.expected_doc_ids)
    return 1.0 if expected & set(result.retrieved_doc_ids[:k]) else 0.0


def _recall_at_k(result: CaseResult, k: int) -> float:
    expected = set(result.expected_doc_ids)
    if not expected:
        return 0.0
    return len(expected & set(result.retrieved_doc_ids[:k])) / len(expected)


def _precision_at_k(result: CaseResult, k: int) -> float:
    retrieved = result.retrieved_doc_ids[:k]
    if not retrieved:
        return 0.0
    expected = set(result.expected_doc_ids)
    return len(expected & set(retrieved)) / len(retrieved)


def _mrr_at_k(result: CaseResult, k: int) -> float:
    expected = set(result.expected_doc_ids)
    for index, doc_id in enumerate(result.retrieved_doc_ids[:k], start=1):
        if doc_id in expected:
            return 1.0 / index
    return 0.0


def _write_report(report: dict[str, Any], output: Path) -> None:
    out_path = output if output.is_absolute() else PROJECT_ROOT / output
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _print_progress(
    *,
    mode: str,
    current: int,
    total: int,
    start_time: float,
    progress_every: int,
) -> None:
    if progress_every <= 0:
        return
    if current != 1 and current != total and current % progress_every != 0:
        return
    elapsed = time.perf_counter() - start_time
    rate = current / elapsed if elapsed > 0 else 0.0
    print(
        f"{mode} progress={current}/{total} elapsed={elapsed:.1f}s rate={rate:.2f}/s",
        file=sys.stderr,
        flush=True,
    )


def _parse_k_values(raw: str) -> tuple[int, ...]:
    values = tuple(sorted({int(item.strip()) for item in raw.split(",") if item.strip()}))
    if not values or any(value <= 0 for value in values):
        raise argparse.ArgumentTypeError("--ks must contain positive integers")
    return values


def _pick(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return None


def _pick_str(row: dict[str, Any], *keys: str) -> str | None:
    value = _pick(row, *keys)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, (tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        if stripped.startswith("[") and stripped.endswith("]"):
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        return [item.strip() for item in stripped.replace(";", ",").split(",") if item.strip()]
    return [str(value).strip()]


def _as_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n"}:
        return False
    return default


def _as_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clean_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _mean(values: Iterable[float]) -> float | None:
    items = list(values)
    if not items:
        return None
    return sum(items) / len(items)


def _ratio(numerator: int, denominator: int) -> float:
    return 0.0 if denominator <= 0 else numerator / denominator


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * percentile))))
    return ordered[index]


def _delta(before: float | None, after: float | None) -> float | None:
    if before is None or after is None:
        return None
    return after - before


def _format_metric(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value * 100:.1f}%"


def _format_delta(value: float | None) -> str:
    if value is None:
        return "-"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value * 100:.1f}pp"


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.intent import IntentClassifier, IntentTaxonomy
from app.llm.client import LLMClient

DEFAULT_DATASET = PROJECT_ROOT.parents[1] / "ragenteval-main" / "eval" / "rag" / "dataset" / "eval_set_v1_all.jsonl"
DEFAULT_TAXONOMY = PROJECT_ROOT / "data" / "intents" / "customer_intents.yml"


class DisabledLLMClient:
    enabled = False


@dataclass
class IntentBadcase:
    query_id: str
    query: str
    expected: str
    predicted: str
    confidence: float
    source: str
    candidates: list[dict[str, Any]]
    reason: str | None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate intent Top-1 accuracy on a JSONL dataset.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--taxonomy", type=Path, default=DEFAULT_TAXONOMY)
    parser.add_argument(
        "--llm-mode",
        choices=["disabled", "env"],
        default="disabled",
        help="disabled is deterministic and does not call external APIs; env uses LLMClient.from_env().",
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON report output path.")
    parser.add_argument(
        "--progress-every",
        type=int,
        default=10,
        help="Print progress every N rows. Use 1 for every row, or 0 to disable.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report = evaluate(
        dataset=args.dataset,
        taxonomy_path=args.taxonomy,
        llm_mode=args.llm_mode,
        limit=args.limit,
        progress_every=args.progress_every,
    )
    print_report(report)
    if args.output is not None:
        out_path = args.output if args.output.is_absolute() else PROJECT_ROOT / args.output
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"\nreport_json={out_path}")
    return 0


def evaluate(
    *,
    dataset: Path,
    taxonomy_path: Path,
    llm_mode: str,
    limit: int | None,
    progress_every: int = 0,
) -> dict[str, Any]:
    taxonomy = IntentTaxonomy.load(taxonomy_path)
    llm_client = LLMClient.from_env() if llm_mode == "env" else DisabledLLMClient()
    classifier = IntentClassifier(taxonomy, llm_client=llm_client)

    rows = _load_rows(dataset)
    if limit is not None:
        rows = rows[: max(0, limit)]

    badcases: list[IntentBadcase] = []
    by_intent: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "correct": 0})
    by_l1: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "correct": 0})
    by_difficulty: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "correct": 0})
    sources: Counter[str] = Counter()
    start_time = time.perf_counter()
    correct_count = 0

    for index, row in enumerate(rows, start=1):
        result = classifier.classify(str(row["query"]))
        expected = str(row["intent_l2"])
        predicted = result.intent_id
        correct = predicted == expected
        correct_count += int(correct)

        _add_bucket(by_intent, expected, correct)
        _add_bucket(by_l1, str(row.get("intent_l1") or ""), correct)
        _add_bucket(by_difficulty, str(row.get("difficulty") or ""), correct)
        sources[result.source] += 1
        _print_progress(
            current=index,
            total=len(rows),
            correct_count=correct_count,
            start_time=start_time,
            progress_every=progress_every,
        )

        if not correct:
            badcases.append(
                IntentBadcase(
                    query_id=str(row["query_id"]),
                    query=str(row["query"]),
                    expected=expected,
                    predicted=predicted,
                    confidence=result.confidence,
                    source=result.source,
                    candidates=[candidate.model_dump() for candidate in result.candidates],
                    reason=result.reason,
                )
            )

    total = len(rows)
    return {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "mode": f"llm_{llm_mode}",
        "dataset": str(dataset.resolve()),
        "taxonomy": str(taxonomy_path.resolve()),
        "total": total,
        "correct": correct_count,
        "wrong": len(badcases),
        "intent_top1": _ratio(correct_count, total),
        "sources": dict(sorted(sources.items())),
        "by_l1": _finalize_buckets(by_l1),
        "by_difficulty": _finalize_buckets(by_difficulty),
        "by_intent": _finalize_buckets(by_intent),
        "badcases": [asdict(item) for item in badcases],
    }


def print_report(report: dict[str, Any]) -> None:
    print(f"mode={report['mode']}")
    print(f"dataset={report['dataset']}")
    print(
        f"total={report['total']} correct={report['correct']} wrong={report['wrong']} "
        f"intent_top1={report['intent_top1']:.4f}"
    )
    print("sources=" + json.dumps(report["sources"], ensure_ascii=False, sort_keys=True))

    for title in ("by_l1", "by_difficulty", "by_intent"):
        print(f"\n{title}")
        for key, item in sorted(report[title].items()):
            print(f"{key}\t{item['correct']}/{item['total']}\t{item['accuracy']:.4f}")

    print("\nbadcases_preview")
    for item in report["badcases"][:30]:
        candidates = ",".join(
            f"{candidate['intent_id']}:{candidate['confidence']:.2f}" for candidate in item["candidates"]
        )
        print(
            f"{item['query_id']}\texpected={item['expected']}\tpred={item['predicted']}"
            f"\tconf={item['confidence']:.2f}\tsource={item['source']}"
            f"\tcandidates=[{candidates}]\tquery={item['query']}"
        )


def _load_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _print_progress(
    *,
    current: int,
    total: int,
    correct_count: int,
    start_time: float,
    progress_every: int,
) -> None:
    if progress_every <= 0:
        return
    if current != 1 and current != total and current % progress_every != 0:
        return

    elapsed = time.perf_counter() - start_time
    rate = current / elapsed if elapsed > 0 else 0.0
    remaining = max(0, total - current)
    eta = remaining / rate if rate > 0 else 0.0
    print(
        f"progress={current}/{total} "
        f"accuracy={_ratio(correct_count, current):.4f} "
        f"elapsed={_format_duration(elapsed)} "
        f"eta={_format_duration(eta)}",
        file=sys.stderr,
        flush=True,
    )


def _format_duration(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}h{minutes:02d}m{sec:02d}s"
    if minutes:
        return f"{minutes:d}m{sec:02d}s"
    return f"{sec:d}s"


def _add_bucket(buckets: dict[str, dict[str, int]], key: str, correct: bool) -> None:
    buckets[key]["total"] += 1
    buckets[key]["correct"] += int(correct)


def _finalize_buckets(buckets: dict[str, dict[str, int]]) -> dict[str, dict[str, float | int]]:
    return {
        key: {
            "total": item["total"],
            "correct": item["correct"],
            "accuracy": _ratio(item["correct"], item["total"]),
        }
        for key, item in buckets.items()
    }


def _ratio(numerator: int, denominator: int) -> float:
    return 0.0 if denominator <= 0 else numerator / denominator


if __name__ == "__main__":
    raise SystemExit(main())

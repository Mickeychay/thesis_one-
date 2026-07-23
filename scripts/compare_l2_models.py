#!/usr/bin/env python3
"""Paired local L2 comparison with the H2L formula and retrieval backbone fixed."""

import argparse
import hashlib
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from H2LDetector import H2LDetectorV3
from config import get_config
from evaluate_h2l_proper import (
    EvaluationRunner,
    build_relevance_keywords,
    compute_all_metrics,
    judge_relevance,
    load_test_cases_from_ground_truth,
)


DEFAULT_MODELS = [
    "qwen2.5:7b",
    "scb10x/llama3.1-typhoon2-8b-instruct:latest",
]


def _expected_codes(case: Dict[str, Any]) -> List[str]:
    problems = case.get("expected_diagnosis", {}).get("problem_list", [])
    return list(dict.fromkeys(str(item.get("code") or "") for item in problems if item.get("code")))


def _set_metrics(expected: Sequence[str], predicted: Sequence[str]) -> Dict[str, float]:
    expected_set = set(expected)
    predicted_set = set(predicted)
    tp = len(expected_set & predicted_set)
    fp = len(predicted_set - expected_set)
    fn = len(expected_set - predicted_set)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    union = expected_set | predicted_set
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "jaccard": len(expected_set & predicted_set) / len(union) if union else 1.0,
        "exact_match": float(expected_set == predicted_set),
    }


def _mean(rows: Iterable[Dict[str, Any]], key: str) -> float:
    values = [float(row[key]) for row in rows if row.get(key) is not None]
    return statistics.fmean(values) if values else 0.0


def _percentile(values: Sequence[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * fraction)))
    return float(ordered[index])


def _aggregate(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    tp = sum(int(row["detector_metrics"]["tp"]) for row in rows)
    fp = sum(int(row["detector_metrics"]["fp"]) for row in rows)
    fn = sum(int(row["detector_metrics"]["fn"]) for row in rows)
    micro_precision = tp / (tp + fp) if tp + fp else 0.0
    micro_recall = tp / (tp + fn) if tp + fn else 0.0
    micro_f1 = (
        2 * micro_precision * micro_recall / (micro_precision + micro_recall)
        if micro_precision + micro_recall
        else 0.0
    )
    triggered = [row for row in rows if row["l2_attempted"]]
    latencies = [float(row["l2_ms"]) for row in triggered]
    retrieval_rows = [row["retrieval_metrics"] for row in rows if row.get("retrieval_metrics")]

    def detector_summary(selected: List[Dict[str, Any]]) -> Dict[str, float]:
        metrics = [row["detector_metrics"] for row in selected]
        return {
            "cases": len(selected),
            "macro_precision": _mean(metrics, "precision"),
            "macro_recall": _mean(metrics, "recall"),
            "macro_f1": _mean(metrics, "f1"),
            "mean_jaccard": _mean(metrics, "jaccard"),
            "exact_match_rate": _mean(metrics, "exact_match"),
        }

    return {
        "all_cases": {
            **detector_summary(rows),
            "micro_precision": micro_precision,
            "micro_recall": micro_recall,
            "micro_f1": micro_f1,
        },
        "l2_triggered_subset": detector_summary(triggered),
        "l2_attempt_rate": len(triggered) / len(rows) if rows else 0.0,
        "l2_degraded_rate": sum(bool(row["l2_degraded"]) for row in triggered) / len(triggered) if triggered else 0.0,
        "latency_ms": {
            "median_l2": statistics.median(latencies) if latencies else 0.0,
            "p95_l2": _percentile(latencies, 0.95),
            "mean_total_detection": _mean(rows, "total_detection_ms"),
        },
        "retrieval": {
            "cases": len(retrieval_rows),
            "MAP": _mean(retrieval_rows, "MAP"),
            "MRR": _mean(retrieval_rows, "MRR"),
            "nDCG@5": _mean(retrieval_rows, "nDCG@5"),
            "nDCG@10": _mean(retrieval_rows, "nDCG@10"),
            "P@5": _mean(retrieval_rows, "P@5"),
        },
    }


def _retrieval_metrics(
    retriever,
    runner: EvaluationRunner,
    case: Dict[str, Any],
    problems: List[Dict[str, Any]],
    top_k: int,
) -> Dict[str, Any]:
    expected = case.get("expected_diagnosis", {}).get("problem_list", [])
    relevance_keywords = build_relevance_keywords(expected, runner.taxonomy)
    started = time.perf_counter()
    results = retriever.retrieve(
        query=case.get("case_description", ""),
        explicit_problems=problems,
        top_k_override=top_k,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000
    grades = [
        judge_relevance(result.doc.text, relevance_keywords, expected)
        for result in results
    ]
    metrics = compute_all_metrics(grades, k_values=[3, 5, 10])
    return {
        **metrics,
        "retrieval_ms": elapsed_ms,
        "doc_ids": [int(result.doc.id) for result in results],
    }


def compare(args: argparse.Namespace) -> Dict[str, Any]:
    config = get_config()
    allowed = set(getattr(config, "L2_MODEL_OPTIONS", ()))
    unsupported = [model for model in args.models if model not in allowed]
    if unsupported:
        raise ValueError(f"Models are not in L2_MODEL_OPTIONS: {', '.join(unsupported)}")

    cases = load_test_cases_from_ground_truth(args.ground_truth)
    if args.max_cases:
        cases = cases[:args.max_cases]
    detector = H2LDetectorV3(config=config)

    runner = None
    retriever = None
    if args.with_retrieval:
        runner = EvaluationRunner(config=config)
        retriever = runner._get_retriever("h2l-hybrid")

    rows_by_model: Dict[str, List[Dict[str, Any]]] = {model: [] for model in args.models}
    for model in args.models:
        for repeat in range(1, args.repeats + 1):
            for index, case in enumerate(cases, start=1):
                case_id = str(case.get("case_id") or f"case_{index}")
                print(f"[{model}] repeat={repeat} case={index}/{len(cases)} {case_id}", flush=True)
                detection = detector.detect_with_metadata(
                    case.get("case_description", ""),
                    use_l2=True,
                    l2_model=model,
                )
                problems = detection.get("problems", [])
                metadata = detection.get("metadata", {})
                predicted = [str(item.get("code") or "") for item in problems if item.get("code")]
                expected = _expected_codes(case)
                timings = metadata.get("timings_ms", {})
                row = {
                    "model": model,
                    "repeat": repeat,
                    "case_id": case_id,
                    "complexity": case.get("complexity"),
                    "category": case.get("category"),
                    "expected_codes": expected,
                    "predicted_codes": predicted,
                    "detector_metrics": _set_metrics(expected, predicted),
                    "l2_attempted": bool(metadata.get("l2_attempted", False)),
                    "l2_degraded": bool(metadata.get("l2_degraded", False)),
                    "l2_model_reported": metadata.get("l2_model"),
                    "l2_ms": float(timings.get("l2", 0.0) or 0.0),
                    "total_detection_ms": float(timings.get("total_detection", 0.0) or 0.0),
                    "context_analysis": metadata.get("context_analysis", {}),
                }
                if retriever is not None and runner is not None:
                    row["retrieval_metrics"] = _retrieval_metrics(
                        retriever, runner, case, problems, args.top_k
                    )
                rows_by_model[model].append(row)

    aggregates = {model: _aggregate(rows) for model, rows in rows_by_model.items()}
    h2l_hash = hashlib.sha256((ROOT / "H2L_core.py").read_bytes()).hexdigest()
    return {
        "metadata": {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "ground_truth": str(args.ground_truth),
            "test_cases": len(cases),
            "repeats": args.repeats,
            "models": args.models,
            "with_retrieval": args.with_retrieval,
            "top_k": args.top_k,
            "controlled_variables": {
                "embedding_model": config.EMBEDDING_MODEL,
                "rerank_model": config.RERANK_MODEL,
                "retrieval_strategy": "h2l-hybrid" if args.with_retrieval else "not_run",
                "h2l_formula": "bayesian_v6_unchanged",
                "h2l_core_sha256": h2l_hash,
                "temperature": 0.2,
                "seed": 42,
            },
        },
        "aggregates": aggregates,
        "per_case": rows_by_model,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    parser.add_argument("--ground-truth", default="expanded_ground_truth.json")
    parser.add_argument("--max-cases", type=int)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--top-k", type=int, default=15)
    parser.add_argument("--with-retrieval", action="store_true")
    parser.add_argument(
        "--output",
        default="evaluation_results/model_comparison/l2_model_comparison.json",
    )
    args = parser.parse_args()

    payload = compare(args)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {output}")
    print(json.dumps(payload["aggregates"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

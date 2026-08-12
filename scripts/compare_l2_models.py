#!/usr/bin/env python3
"""Paired local L2 comparison with the H2L formula and retrieval backbone fixed."""

import argparse
import copy
import hashlib
import itertools
import json
import statistics
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from h2l.detector import H2LDetectorV3
from h2l.config import get_config
from evaluate_h2l_proper import (
    EvaluationRunner,
    STRATEGY_CONFIGS,
    build_relevance_keywords,
    compute_all_metrics,
    judge_relevance,
    load_test_cases_from_ground_truth,
)


DEFAULT_MODELS = [
    "qwen2.5:7b",
    "scb10x/llama3.1-typhoon2-8b-instruct:latest",
    "h2l/typhoon-gemma3-4b-templatefix-v2:latest",
]

MODEL_PATCH_MANIFESTS = {
    "h2l/typhoon-gemma3-4b-templatefix-v2:latest": (
        ROOT
        / "evaluation_results"
        / "model_comparison"
        / "typhoon_gemma3_templatefix_manifest.json"
    ),
}

DEFAULT_RETRIEVAL_STRATEGIES = list(STRATEGY_CONFIGS.keys())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_tree(path: Path) -> str:
    """Hash a file or a directory tree, including relative file names."""
    path = path.resolve()
    if path.is_file():
        return _sha256(path)
    if not path.is_dir():
        raise FileNotFoundError(f"Provenance input does not exist: {path}")

    digest = hashlib.sha256()
    files = sorted(candidate for candidate in path.rglob("*") if candidate.is_file())
    for candidate in files:
        relative = candidate.relative_to(path).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        with candidate.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    return digest.hexdigest()


def _index_store_path(config: Any) -> Path:
    """Resolve the on-disk vector index used by the configured backend."""
    configured = Path(config.DB_PATH)
    if str(config.DB_TYPE).lower() == "lancedb":
        configured = configured.with_name(f"{configured.name}.lance")
    return configured.resolve()


def _model_patch_provenance(models: Sequence[str]) -> Dict[str, Any]:
    """Lock local model repairs that are part of the experiment protocol."""
    result: Dict[str, Any] = {}
    for model in models:
        manifest_path = MODEL_PATCH_MANIFESTS.get(model)
        if manifest_path is None:
            continue
        if not manifest_path.is_file():
            raise FileNotFoundError(
                f"Model patch provenance is missing for {model}: {manifest_path}"
            )
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        if payload.get("status") != "complete" or not payload.get(
            "patched_file_sha256"
        ):
            raise ValueError(f"Model patch provenance is incomplete for {model}")
        result[model] = {
            "manifest_path": str(manifest_path.relative_to(ROOT)),
            "manifest_sha256": _sha256(manifest_path),
            "patched_file_sha256": payload["patched_file_sha256"],
            "original_template_sha256": payload.get("original_template_sha256"),
            "replacement_template_sha256": payload.get(
                "replacement_template_sha256"
            ),
            "metadata_key": payload.get("metadata_key"),
        }
    return result


def _runtime_config(config: Any) -> Dict[str, Any]:
    """Capture non-secret settings that can change detector or retrieval output."""
    keys = (
        "DB_TYPE",
        "DB_PATH",
        "METADATA_STORE",
        "EMBEDDING_MODEL",
        "RERANK_MODEL",
        "DEVICE",
        "ENABLE_DENSE_RUNTIME",
        "USE_LOCAL_LLM",
        "LOCAL_LLM_BASE_URL",
        "LOCAL_LLM_MODEL",
        "LLM_MAX_TOKENS",
        "USE_RERANK",
        "TOP_K",
        "BM25_K",
        "FUSION_K",
        "RRF_K",
        "MAX_HOPS",
        "ENABLE_L2_DETECTION",
        "L2_SIMILARITY_THRESHOLD",
        "L2_TOP_K",
        "SEED",
    )
    return {key: str(getattr(config, key)) if isinstance(getattr(config, key), Path) else getattr(config, key) for key in keys}


def _run_signature(
    args: argparse.Namespace,
    strategies: Sequence[str],
    ground_truth_path: Path,
    config: Any,
) -> Dict[str, Any]:
    """Describe every input that must remain fixed when resuming a run."""
    metadata_store = Path(config.METADATA_STORE).resolve()
    index_store = _index_store_path(config)
    return {
        "ground_truth_path": str(ground_truth_path),
        "ground_truth_sha256": _sha256(ground_truth_path),
        "taxonomy_sha256": _sha256(ROOT / "data/problem_codes.json"),
        "detector_code_sha256": _sha256(ROOT / "h2l" / "detector.py"),
        "h2l_core_sha256": _sha256(ROOT / "h2l" / "core.py"),
        "evaluation_code_sha256": _sha256(ROOT / "eval" / "run_benchmark.py"),
        "matrix_runner_sha256": _sha256(Path(__file__).resolve()),
        "config_code_sha256": _sha256(ROOT / "config.py"),
        "retrieval_engine_sha256": _sha256(ROOT / "retriever.py"),
        "unified_baselines_sha256": _sha256(ROOT / "unified_baselines.py"),
        "metadata_store_path": str(metadata_store),
        "metadata_store_sha256": _sha256_tree(metadata_store),
        "index_store_path": str(index_store),
        "index_store_sha256": _sha256_tree(index_store),
        "runtime_config": _runtime_config(config),
        "ollama_model_inventory": _ollama_model_inventory(
            config.LOCAL_LLM_BASE_URL,
            args.models,
        ) if bool(config.USE_LOCAL_LLM) else {"not_applicable": True},
        "model_patch_provenance": _model_patch_provenance(args.models),
        "models": list(args.models),
        "repeats": int(args.repeats),
        "with_retrieval": bool(args.with_retrieval),
        "retrieval_strategies": list(strategies),
        "top_k": int(args.top_k),
        "problem_source": "detected",
    }


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
    retrieval_by_strategy: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        for strategy, metrics in _retrieval_metrics_by_strategy(row).items():
            retrieval_by_strategy.setdefault(strategy, []).append(metrics)

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
        "high_severity_false_negatives": sum(
            len(row.get("missed_high_severity_codes", [])) for row in rows
        ),
        "latency_ms": {
            "median_l2": statistics.median(latencies) if latencies else 0.0,
            "p95_l2": _percentile(latencies, 0.95),
            "mean_total_detection": _mean(rows, "total_detection_ms"),
        },
        "retrieval": {
            strategy: {
                "rows": len(strategy_rows),
                "MAP": _mean(strategy_rows, "MAP"),
                "MRR": _mean(strategy_rows, "MRR"),
                "nDCG@5": _mean(strategy_rows, "nDCG@5"),
                "nDCG@10": _mean(strategy_rows, "nDCG@10"),
                "P@5": _mean(strategy_rows, "P@5"),
                "median_retrieval_ms": statistics.median(
                    float(item.get("retrieval_ms", 0.0) or 0.0)
                    for item in strategy_rows
                ),
            }
            for strategy, strategy_rows in sorted(retrieval_by_strategy.items())
        },
    }


def _retrieval_metrics_by_strategy(row: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    metrics = row.get("retrieval_metrics") or {}
    if not isinstance(metrics, dict):
        return {}
    if "MAP" in metrics:
        return {"h2l-hybrid": metrics}
    return {
        str(strategy): value
        for strategy, value in metrics.items()
        if isinstance(value, dict)
    }


def _stability(rows: List[Dict[str, Any]], repeats: int) -> Dict[str, Any]:
    if repeats < 2:
        return {"assessed": False, "reason": "Run with --repeats 2 or more."}

    predictions: Dict[str, set] = {}
    for row in rows:
        predictions.setdefault(str(row["case_id"]), set()).add(
            tuple(sorted(row.get("predicted_codes", [])))
        )
    stable = sum(len(code_sets) == 1 for code_sets in predictions.values())
    return {
        "assessed": True,
        "cases": len(predictions),
        "stable_cases": stable,
        "stable_case_rate": stable / len(predictions) if predictions else 0.0,
    }


def _retrieval_stability(
    rows: List[Dict[str, Any]],
    repeats: int,
    strategies: Sequence[str],
) -> Dict[str, Any]:
    if repeats < 2:
        return {"assessed": False, "reason": "Run with --repeats 2 or more."}

    result: Dict[str, Any] = {"assessed": True, "strategies": {}}
    for strategy in strategies:
        doc_sets: Dict[str, set] = {}
        for row in rows:
            metrics = _retrieval_metrics_by_strategy(row).get(strategy)
            if not metrics:
                continue
            doc_sets.setdefault(str(row["case_id"]), set()).add(
                tuple(metrics.get("doc_ids", []))
            )
        stable = sum(len(values) == 1 for values in doc_sets.values())
        result["strategies"][strategy] = {
            "cases": len(doc_sets),
            "stable_cases": stable,
            "stable_case_rate": stable / len(doc_sets) if doc_sets else 0.0,
        }
    return result


def _aggregates_by_repeat(
    rows_by_model: Dict[str, List[Dict[str, Any]]],
    repeats: int,
) -> Dict[str, Dict[str, Any]]:
    return {
        model: {
            str(repeat): _aggregate(
                [row for row in rows if int(row.get("repeat", 0)) == repeat]
            )
            for repeat in range(1, repeats + 1)
        }
        for model, rows in rows_by_model.items()
    }


def _paired_comparisons(rows_by_model: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    comparisons = []
    for model_a, model_b in itertools.combinations(rows_by_model, 2):
        rows_a = {
            (str(row["case_id"]), int(row["repeat"])): row
            for row in rows_by_model[model_a]
        }
        rows_b = {
            (str(row["case_id"]), int(row["repeat"])): row
            for row in rows_by_model[model_b]
        }
        keys = sorted(rows_a.keys() & rows_b.keys())
        f1_deltas = [
            float(rows_b[key]["detector_metrics"]["f1"])
            - float(rows_a[key]["detector_metrics"]["f1"])
            for key in keys
        ]
        comparisons.append({
            "model_a": model_a,
            "model_b": model_b,
            "paired_rows": len(keys),
            "different_final_code_sets": sum(
                set(rows_a[key].get("predicted_codes", []))
                != set(rows_b[key].get("predicted_codes", []))
                for key in keys
            ),
            "model_a_higher_case_f1": sum(delta < 0 for delta in f1_deltas),
            "model_b_higher_case_f1": sum(delta > 0 for delta in f1_deltas),
            "equal_case_f1": sum(delta == 0 for delta in f1_deltas),
            "mean_case_f1_delta_b_minus_a": (
                statistics.fmean(f1_deltas) if f1_deltas else 0.0
            ),
            "model_a_degraded_calls": sum(
                bool(rows_a[key].get("l2_degraded")) for key in keys
            ),
            "model_b_degraded_calls": sum(
                bool(rows_b[key].get("l2_degraded")) for key in keys
            ),
        })
    return comparisons


def _paired_retrieval_comparisons(
    rows_by_model: Dict[str, List[Dict[str, Any]]],
    strategies: Sequence[str],
) -> List[Dict[str, Any]]:
    comparisons = []
    for model_a, model_b in itertools.combinations(rows_by_model, 2):
        rows_a = {
            (str(row["case_id"]), int(row["repeat"])): row
            for row in rows_by_model[model_a]
        }
        rows_b = {
            (str(row["case_id"]), int(row["repeat"])): row
            for row in rows_by_model[model_b]
        }
        for strategy in strategies:
            paired = []
            for key in sorted(rows_a.keys() & rows_b.keys()):
                metrics_a = _retrieval_metrics_by_strategy(rows_a[key]).get(strategy)
                metrics_b = _retrieval_metrics_by_strategy(rows_b[key]).get(strategy)
                if metrics_a and metrics_b:
                    paired.append((metrics_a, metrics_b))
            deltas = [
                float(metrics_b.get("nDCG@5", 0.0))
                - float(metrics_a.get("nDCG@5", 0.0))
                for metrics_a, metrics_b in paired
            ]
            comparisons.append({
                "model_a": model_a,
                "model_b": model_b,
                "strategy": strategy,
                "paired_rows": len(paired),
                "model_a_higher_ndcg_at_5": sum(delta < 0 for delta in deltas),
                "model_b_higher_ndcg_at_5": sum(delta > 0 for delta in deltas),
                "equal_ndcg_at_5": sum(delta == 0 for delta in deltas),
                "mean_ndcg_at_5_delta_b_minus_a": (
                    statistics.fmean(deltas) if deltas else 0.0
                ),
            })
    return comparisons


def _ollama_model_inventory(base_url: str, requested_models: Sequence[str]) -> Dict[str, Any]:
    parts = urlsplit(base_url)
    tags_url = urlunsplit((parts.scheme, parts.netloc, "/api/tags", "", ""))
    try:
        with urllib.request.urlopen(tags_url, timeout=3.0) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return {"error": str(exc), "models": {}}

    available = {
        str(item.get("name") or item.get("model") or ""): item
        for item in payload.get("models", [])
    }
    inventory = {}
    for model in requested_models:
        item = available.get(model, {})
        details = item.get("details", {})
        inventory[model] = {
            "installed": bool(item),
            "digest": item.get("digest"),
            "size_bytes": int(item.get("size", 0) or 0),
            "parameter_size": details.get("parameter_size"),
            "quantization_level": details.get("quantization_level"),
            "family": details.get("family"),
        }
    return {"endpoint": tags_url, "models": inventory}


def _write_checkpoint(
    output_path: str,
    rows_by_model: Dict[str, List[Dict[str, Any]]],
    phase: str,
    completed_units: int,
    total_units: int,
    run_signature: Dict[str, Any],
) -> None:
    checkpoint = Path(f"{output_path}.checkpoint")
    payload = {
        "status": "running",
        "phase": phase,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "completed_units": completed_units,
        "total_units": total_units,
        "run_signature": run_signature,
        "per_case": rows_by_model,
    }
    temporary = checkpoint.with_suffix(f"{checkpoint.suffix}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(checkpoint)


def _load_resume_rows(
    path: str,
    models: Sequence[str],
    case_ids: set,
    repeats: int,
    require_detected_problems: bool,
    expected_signature: Dict[str, Any],
    retry_degraded: bool,
) -> Dict[str, List[Dict[str, Any]]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    actual_signature = payload.get("run_signature") or payload.get("metadata", {}).get(
        "run_signature"
    )
    if actual_signature != expected_signature:
        raise ValueError(
            "Resume artifact does not match the current run signature. "
            "Use a fresh --output path or restore the exact dataset/code/configuration."
        )
    source_rows = payload.get("per_case", {})
    if not isinstance(source_rows, dict):
        raise ValueError(f"Resume artifact has no per_case rows: {path}")

    rows_by_model: Dict[str, List[Dict[str, Any]]] = {model: [] for model in models}
    for model in models:
        seen = set()
        for source_row in source_rows.get(model, []):
            row = copy.deepcopy(source_row)
            key = (str(row.get("case_id", "")), int(row.get("repeat", 0) or 0))
            if key[0] not in case_ids or not 1 <= key[1] <= repeats or key in seen:
                continue
            if require_detected_problems and "detected_problems" not in row:
                continue
            if retry_degraded and bool(row.get("l2_degraded")):
                continue
            row["retrieval_metrics"] = _retrieval_metrics_by_strategy(row)
            rows_by_model[model].append(row)
            seen.add(key)
    return rows_by_model


def _retrieval_metrics(
    retriever,
    runner: EvaluationRunner,
    strategy: str,
    case: Dict[str, Any],
    problems: List[Dict[str, Any]],
    top_k: int,
) -> Dict[str, Any]:
    expected = case.get("expected_diagnosis", {}).get("problem_list", [])
    relevance_keywords = build_relevance_keywords(expected, runner.taxonomy)
    started = time.perf_counter()
    query = case.get("case_description", "")
    strategy_config = STRATEGY_CONFIGS[strategy]
    try:
        if strategy_config["needs_problems"]:
            results = retriever.retrieve(
                query=query,
                explicit_problems=problems,
                top_k_override=top_k,
            )
        else:
            results = retriever.retrieve(query, top_k_override=top_k)
    except TypeError:
        results = retriever.retrieve(query)
    elapsed_ms = (time.perf_counter() - started) * 1000
    grades = [
        judge_relevance(
            getattr(result.doc if hasattr(result, "doc") else result, "text", ""),
            relevance_keywords,
            expected,
        )
        for result in results
    ]
    metrics = compute_all_metrics(grades, k_values=[3, 5, 10])
    doc_ids = []
    for result in results:
        doc = result.doc if hasattr(result, "doc") else result
        doc_id = getattr(doc, "id", -1)
        try:
            doc_id = int(doc_id)
        except (TypeError, ValueError):
            doc_id = str(doc_id)
        doc_ids.append(doc_id)
    return {
        **metrics,
        "retrieval_ms": elapsed_ms,
        "doc_ids": doc_ids,
    }


def compare(args: argparse.Namespace) -> Dict[str, Any]:
    config = get_config()
    allowed = set(getattr(config, "L2_MODEL_OPTIONS", ()))
    unsupported = [model for model in args.models if model not in allowed]
    if unsupported:
        raise ValueError(f"Models are not in L2_MODEL_OPTIONS: {', '.join(unsupported)}")

    strategies = list(args.strategies or DEFAULT_RETRIEVAL_STRATEGIES) if args.with_retrieval else []
    unsupported_strategies = [
        strategy for strategy in strategies if strategy not in STRATEGY_CONFIGS
    ]
    if unsupported_strategies:
        raise ValueError(
            f"Unknown retrieval strategies: {', '.join(unsupported_strategies)}"
        )

    ground_truth_path = Path(args.ground_truth).resolve()
    cases = load_test_cases_from_ground_truth(str(ground_truth_path))
    if args.max_cases:
        cases = cases[:args.max_cases]
    if args.expected_test_cases is not None and len(cases) != args.expected_test_cases:
        raise ValueError(
            f"Expected {args.expected_test_cases} test cases, loaded {len(cases)} "
            f"from {ground_truth_path}"
        )
    run_signature = _run_signature(args, strategies, ground_truth_path, config)
    if bool(config.USE_LOCAL_LLM):
        model_inventory = run_signature["ollama_model_inventory"]
        if model_inventory.get("error"):
            raise RuntimeError(
                "Could not inventory local Ollama models before evaluation: "
                f"{model_inventory['error']}"
            )
        missing_models = [
            model
            for model, details in model_inventory.get("models", {}).items()
            if not details.get("installed") or not details.get("digest")
        ]
        if missing_models:
            raise ValueError(
                "Requested Ollama models are missing or have no immutable digest: "
                f"{', '.join(missing_models)}"
            )
    detector = H2LDetectorV3(config=config)
    taxonomy = detector.get_taxonomy()
    case_ids = {
        str(case.get("case_id") or f"case_{index}")
        for index, case in enumerate(cases, start=1)
    }
    if args.resume_from:
        rows_by_model = _load_resume_rows(
            args.resume_from,
            args.models,
            case_ids,
            args.repeats,
            require_detected_problems=bool(strategies),
            expected_signature=run_signature,
            retry_degraded=not args.keep_degraded_on_resume,
        )
    else:
        rows_by_model = {model: [] for model in args.models}

    total_detection_units = len(args.models) * args.repeats * len(cases)
    total_retrieval_units = total_detection_units * len(strategies)
    total_units = total_detection_units + total_retrieval_units
    completed_units = sum(len(rows) for rows in rows_by_model.values()) + sum(
        len(_retrieval_metrics_by_strategy(row))
        for rows in rows_by_model.values()
        for row in rows
    )
    row_maps = {
        model: {
            (str(row["case_id"]), int(row["repeat"])): row
            for row in rows
        }
        for model, rows in rows_by_model.items()
    }
    for model in args.models:
        for repeat in range(1, args.repeats + 1):
            for index, case in enumerate(cases, start=1):
                case_id = str(case.get("case_id") or f"case_{index}")
                key = (case_id, repeat)
                if key in row_maps[model]:
                    continue
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
                expected_high_severity = [
                    code
                    for code in expected
                    if int((taxonomy.get(code) or {}).get("severity", 0) or 0) >= 4
                ]
                timings = metadata.get("timings_ms", {})
                row = {
                    "model": model,
                    "repeat": repeat,
                    "case_id": case_id,
                    "complexity": case.get("complexity"),
                    "category": case.get("category"),
                    "evaluation_slice": case.get("evaluation_slice"),
                    "augmentation": copy.deepcopy(case.get("augmentation")),
                    "expected_codes": expected,
                    "expected_high_severity_codes": expected_high_severity,
                    "predicted_codes": predicted,
                    "detected_problems": copy.deepcopy(problems),
                    "missed_high_severity_codes": sorted(
                        set(expected_high_severity) - set(predicted)
                    ),
                    "detector_metrics": _set_metrics(expected, predicted),
                    "l2_attempted": bool(metadata.get("l2_attempted", False)),
                    "l2_degraded": bool(metadata.get("l2_degraded", False)),
                    "l2_model_reported": metadata.get("l2_model"),
                    "l2_ms": float(timings.get("l2", 0.0) or 0.0),
                    "total_detection_ms": float(timings.get("total_detection", 0.0) or 0.0),
                    "context_analysis": metadata.get("context_analysis", {}),
                    "retrieval_metrics": {},
                }
                rows_by_model[model].append(row)
                row_maps[model][key] = row
                completed_units += 1
                if args.checkpoint_every > 0 and completed_units % args.checkpoint_every == 0:
                    _write_checkpoint(
                        args.output,
                        rows_by_model,
                        "detection",
                        completed_units,
                        total_units,
                        run_signature,
                    )

    case_order = {
        str(case.get("case_id") or f"case_{index}"): index
        for index, case in enumerate(cases, start=1)
    }
    for model in args.models:
        rows_by_model[model].sort(
            key=lambda row: (
                int(row.get("repeat", 0)),
                case_order.get(str(row.get("case_id", "")), len(cases) + 1),
            )
        )
    _write_checkpoint(
        args.output,
        rows_by_model,
        "detection_complete",
        completed_units,
        total_units,
        run_signature,
    )

    if strategies:
        runner = EvaluationRunner(config=config)
        case_by_id = {
            str(case.get("case_id") or f"case_{index}"): case
            for index, case in enumerate(cases, start=1)
        }
        baseline_cache: Dict[tuple, Dict[str, Any]] = {}
        retrieval_calls = 0
        for strategy in strategies:
            retriever = runner._get_retriever(strategy)
            needs_problems = bool(STRATEGY_CONFIGS[strategy]["needs_problems"])
            for model in args.models:
                for row in rows_by_model[model]:
                    row_metrics = _retrieval_metrics_by_strategy(row)
                    row["retrieval_metrics"] = row_metrics
                    if strategy in row_metrics:
                        continue
                    case_id = str(row["case_id"])
                    cache_key = (strategy, case_id)
                    if not needs_problems and cache_key in baseline_cache:
                        metrics = copy.deepcopy(baseline_cache[cache_key])
                    else:
                        retrieval_calls += 1
                        if retrieval_calls == 1 or retrieval_calls % 10 == 0:
                            print(
                                f"[retrieval:{strategy}] call={retrieval_calls} "
                                f"model={model} repeat={row['repeat']} case={case_id}",
                                flush=True,
                            )
                        metrics = _retrieval_metrics(
                            retriever,
                            runner,
                            strategy,
                            case_by_id[case_id],
                            row.get("detected_problems", []),
                            args.top_k,
                        )
                        if not needs_problems:
                            baseline_cache[cache_key] = copy.deepcopy(metrics)
                    row_metrics[strategy] = metrics
                    completed_units += 1
                    if args.checkpoint_every > 0 and completed_units % args.checkpoint_every == 0:
                        _write_checkpoint(
                            args.output,
                            rows_by_model,
                            f"retrieval:{strategy}",
                            completed_units,
                            total_units,
                            run_signature,
                        )
            _write_checkpoint(
                args.output,
                rows_by_model,
                f"retrieval_complete:{strategy}",
                completed_units,
                total_units,
                run_signature,
            )

    final_signature = _run_signature(args, strategies, ground_truth_path, config)
    if final_signature != run_signature:
        raise RuntimeError(
            "Experiment inputs changed while the matrix was running; refusing to "
            "write a mixed-provenance final artifact."
        )

    aggregates = {model: _aggregate(rows) for model, rows in rows_by_model.items()}
    evaluation_slices: Dict[str, int] = {}
    for case in cases:
        slice_name = str(case.get("evaluation_slice") or "overall_test")
        evaluation_slices[slice_name] = evaluation_slices.get(slice_name, 0) + 1
    return {
        "metadata": {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "ground_truth": str(args.ground_truth),
            "test_cases": len(cases),
            "repeats": args.repeats,
            "models": args.models,
            "with_retrieval": args.with_retrieval,
            "retrieval_strategies": strategies,
            "top_k": args.top_k,
            "problem_source": "detected",
            "evaluation_slices": evaluation_slices,
            "resumed_from": args.resume_from,
            "run_signature": run_signature,
            "ollama": run_signature["ollama_model_inventory"],
            "controlled_variables": {
                "embedding_model": config.EMBEDDING_MODEL,
                "rerank_model": config.RERANK_MODEL,
                "retrieval_strategies": strategies or ["not_run"],
                "baseline_retrieval_cache": "once_per_strategy_case",
                "hyde_generation_endpoint": config.LOCAL_LLM_BASE_URL,
                "hyde_generation_model": config.LOCAL_LLM_MODEL,
                "hyde_generation_temperature": 0.3,
                "hyde_generation_seed": 42,
                "h2l_formula": "bayesian_v6_unchanged",
                "h2l_core_sha256": run_signature["h2l_core_sha256"],
                "h2l_detector_sha256": _sha256(ROOT / "h2l" / "detector.py"),
                "temperature": 0.2,
                "seed": 42,
                "l2_schema_validation": "validated_codes/implicit_problems arrays of objects; context_analysis object",
                "l2_corrective_retry_max": 1,
                "l2_corrective_retry_temperature": 0,
                "l2_corrective_retry_seed": 43,
                "max_tokens": config.LLM_MAX_TOKENS,
                "response_format": "json_object",
            },
        },
        "aggregates": aggregates,
        "aggregates_by_repeat": _aggregates_by_repeat(
            rows_by_model, args.repeats
        ),
        "stability": {
            model: _stability(rows, args.repeats)
            for model, rows in rows_by_model.items()
        },
        "retrieval_stability": {
            model: _retrieval_stability(rows, args.repeats, strategies)
            for model, rows in rows_by_model.items()
        },
        "paired_comparisons": _paired_comparisons(rows_by_model),
        "paired_retrieval_comparisons": _paired_retrieval_comparisons(
            rows_by_model, strategies
        ),
        "per_case": rows_by_model,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    parser.add_argument("--ground-truth", default="data/expanded_ground_truth.json")
    parser.add_argument("--max-cases", type=int)
    parser.add_argument(
        "--expected-test-cases",
        type=int,
        help="Fail before evaluation unless the loaded test split has this size",
    )
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--top-k", type=int, default=15)
    parser.add_argument("--with-retrieval", action="store_true")
    parser.add_argument(
        "--strategies",
        nargs="+",
        choices=DEFAULT_RETRIEVAL_STRATEGIES,
        help="Retrieval strategies (default: all strategies when --with-retrieval is set)",
    )
    parser.add_argument("--checkpoint-every", type=int, default=5)
    parser.add_argument(
        "--output",
        default="evaluation_results/model_comparison/l2_model_comparison.json",
    )
    parser.add_argument(
        "--resume-from",
        help="Resume completed rows and retrieval metrics from an artifact or checkpoint",
    )
    parser.add_argument(
        "--keep-degraded-on-resume",
        action="store_true",
        help="Keep degraded detector rows instead of retrying them when resuming",
    )
    args = parser.parse_args()

    checkpoint = Path(f"{args.output}.checkpoint")
    if not args.resume_from and checkpoint.exists():
        args.resume_from = str(checkpoint)

    payload = compare(args)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    checkpoint = Path(f"{output}.checkpoint")
    if checkpoint.exists():
        checkpoint.unlink()
    print(f"Saved {output}")
    print(json.dumps(payload["aggregates"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

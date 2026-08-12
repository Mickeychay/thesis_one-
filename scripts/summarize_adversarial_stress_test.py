#!/usr/bin/env python3
"""Summarize the held-out adversarial slice from a completed L2/retrieval matrix."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MATRIX = (
    ROOT
    / "evaluation_results"
    / "model_comparison"
    / "l2_full_matrix_95cases_3models_3repeats_8strategies.json"
)
DEFAULT_GROUND_TRUTH = ROOT / "data/expanded_ground_truth.json"
DEFAULT_TAXONOMY = ROOT / "data/problem_codes.json"
DEFAULT_JSON = ROOT / "evaluation_results" / "adversarial_stress_test_20260807.json"
DEFAULT_MARKDOWN = ROOT / "evaluation_results" / "adversarial_stress_test_20260807.md"
H2L_CORE = ROOT / "core.py"
EVALUATION_CODE = ROOT / "evaluate_h2l_proper.py"
RETRIEVAL_METRICS = ("nDCG@5", "nDCG@10", "MAP", "MRR")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def mean(rows: Iterable[dict[str, Any]], key: str) -> float:
    values = [float(row[key]) for row in rows if row.get(key) is not None]
    return statistics.fmean(values) if values else 0.0


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path.resolve())


def expected_codes(case: dict[str, Any]) -> list[str]:
    return list(
        dict.fromkeys(
            str(item["code"])
            for item in case.get("expected_diagnosis", {}).get("problem_list", [])
            if item.get("code")
        )
    )


def require_rate(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be numeric, got {value!r}") from exc
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise ValueError(f"{label} must be finite and within [0, 1], got {value!r}")
    return number


def require_nonnegative(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be numeric, got {value!r}") from exc
    if not math.isfinite(number) or number < 0.0:
        raise ValueError(f"{label} must be finite and non-negative, got {value!r}")
    return number


def load_inputs(
    matrix_path: Path,
    ground_truth_path: Path,
    taxonomy_path: Path,
    expected_cases: int,
    expected_test_cases: int,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, Any],
]:
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    ground_truth = json.loads(ground_truth_path.read_text(encoding="utf-8"))
    taxonomy = json.loads(taxonomy_path.read_text(encoding="utf-8"))
    raw_test_cases = [
        case for case in ground_truth.get("cases", []) if case.get("split") == "test"
    ]
    test_case_ids = [str(case.get("case_id", "")) for case in raw_test_cases]
    duplicate_test_ids = sorted(
        case_id for case_id, count in Counter(test_case_ids).items() if count > 1
    )
    if duplicate_test_ids:
        raise ValueError(f"Duplicate test case IDs: {duplicate_test_ids[:5]}")
    if any(not case_id for case_id in test_case_ids):
        raise ValueError("Every test case must have a non-empty case_id")
    test_cases = {
        str(case["case_id"]): case
        for case in raw_test_cases
    }
    if len(test_cases) != expected_test_cases:
        raise ValueError(
            f"Expected {expected_test_cases} total test cases, found {len(test_cases)}"
        )
    metadata_test_cases = ground_truth.get("metadata", {}).get("test_cases")
    if metadata_test_cases is not None and int(metadata_test_cases) != expected_test_cases:
        raise ValueError(
            "Ground-truth metadata test_cases mismatch: "
            f"expected={expected_test_cases}, actual={metadata_test_cases}"
        )

    adversarial = {
        case_id: case
        for case_id, case in test_cases.items()
        if case.get("evaluation_slice") == "adversarial_test"
    }
    if len(adversarial) != expected_cases:
        raise ValueError(
            f"Expected {expected_cases} adversarial test cases, found {len(adversarial)}"
        )
    for case_id, case in adversarial.items():
        augmentation = case.get("augmentation")
        if not isinstance(augmentation, dict) or augmentation.get("type") != "adversarial":
            raise ValueError(f"{case_id} must have augmentation.type=adversarial")
        false_trigger = augmentation.get("false_trigger_code")
        if not isinstance(false_trigger, str) or not false_trigger:
            raise ValueError(f"{case_id} is missing a valid false_trigger_code")
        raw_targets = [
            str(item["code"])
            for item in case.get("expected_diagnosis", {}).get("problem_list", [])
            if item.get("code")
        ]
        targets = expected_codes(case)
        if not targets:
            raise ValueError(f"{case_id} must define at least one expected target code")
        if len(raw_targets) != len(targets):
            raise ValueError(f"{case_id} contains duplicate expected target codes")
        if false_trigger in targets:
            raise ValueError(
                f"{case_id} false_trigger_code must be disjoint from expected targets"
            )
        unknown_codes = [code for code in [*targets, false_trigger] if code not in taxonomy]
        if unknown_codes:
            raise ValueError(f"{case_id} contains codes absent from taxonomy: {unknown_codes}")
    return matrix, ground_truth, test_cases, adversarial, taxonomy


def validate_matrix(
    matrix: dict[str, Any],
    test_cases: dict[str, dict[str, Any]],
    adversarial: dict[str, dict[str, Any]],
    expected_test_cases: int,
    expected_models: int,
    expected_repeats: int,
    expected_strategies: int,
    expected_top_k: int,
    ground_truth_hash: str,
    taxonomy_hash: str,
) -> dict[str, Any]:
    if matrix.get("status") == "running":
        raise ValueError("A running checkpoint is not a completed matrix artifact")
    metadata = matrix.get("metadata")
    per_case = matrix.get("per_case")
    if not isinstance(metadata, dict) or not isinstance(per_case, dict):
        raise ValueError("Matrix must contain metadata and per_case objects")
    if not metadata.get("created_at"):
        raise ValueError("Matrix metadata is missing created_at")
    if int(metadata.get("test_cases", -1)) != expected_test_cases:
        raise ValueError(
            f"Matrix test_cases={metadata.get('test_cases')}, expected {expected_test_cases}"
        )
    if int(metadata.get("repeats", -1)) != expected_repeats:
        raise ValueError(
            f"Matrix repeats={metadata.get('repeats')}, expected {expected_repeats}"
        )
    if metadata.get("with_retrieval") is not True:
        raise ValueError("Matrix must have with_retrieval=true")
    if metadata.get("problem_source") != "detected":
        raise ValueError(
            f"Matrix problem_source={metadata.get('problem_source')!r}, expected 'detected'"
        )
    if int(metadata.get("top_k", -1)) != expected_top_k:
        raise ValueError(
            f"Matrix top_k={metadata.get('top_k')}, expected {expected_top_k}"
        )

    models = [str(model) for model in metadata.get("models", [])]
    if len(models) != expected_models or len(set(models)) != len(models):
        raise ValueError(
            f"Matrix has {len(models)} unique model entries, expected {expected_models}"
        )
    if set(models) != set(per_case):
        raise ValueError(
            "Matrix metadata models do not match per_case keys: "
            f"metadata={models}, per_case={sorted(per_case)}"
        )
    strategies = list(metadata.get("retrieval_strategies", []))
    if len(strategies) != expected_strategies or len(set(strategies)) != len(strategies):
        raise ValueError(
            f"Matrix has {len(set(strategies))} unique strategies, expected {expected_strategies}"
        )

    expected_slices = Counter(
        case.get("evaluation_slice") or "overall_test" for case in test_cases.values()
    )
    reported_slices = metadata.get("evaluation_slices")
    if not isinstance(reported_slices, dict) or {
        str(key): int(value) for key, value in reported_slices.items()
    } != dict(expected_slices):
        raise ValueError(
            "Matrix evaluation_slices do not match ground truth: "
            f"matrix={reported_slices}, current={dict(expected_slices)}"
        )

    run_signature = metadata.get("run_signature")
    if not isinstance(run_signature, dict):
        raise ValueError("Matrix metadata is missing the required run_signature")
    expected_signature = {
        "ground_truth_sha256": ground_truth_hash,
        "taxonomy_sha256": taxonomy_hash,
        "h2l_core_sha256": sha256(H2L_CORE),
        "evaluation_code_sha256": sha256(EVALUATION_CODE),
        "models": models,
        "repeats": expected_repeats,
        "with_retrieval": True,
        "retrieval_strategies": strategies,
        "top_k": expected_top_k,
        "problem_source": "detected",
    }
    for field, expected_value in expected_signature.items():
        if run_signature.get(field) != expected_value:
            raise ValueError(
                f"Matrix run_signature.{field} mismatch: "
                f"source={run_signature.get(field)!r}, current={expected_value!r}"
            )

    expected_rows = expected_test_cases * expected_repeats
    expected_row_keys = {
        (case_id, repeat)
        for case_id in test_cases
        for repeat in range(1, expected_repeats + 1)
    }
    for model in models:
        rows = per_case[model]
        if not isinstance(rows, list):
            raise ValueError(f"per_case[{model!r}] must be a list")
        if len(rows) != expected_rows:
            raise ValueError(f"{model} has {len(rows)} rows, expected {expected_rows}")
        row_keys = [
            (str(row.get("case_id", "")), int(row.get("repeat", 0) or 0))
            for row in rows
        ]
        duplicate_keys = sorted(
            key for key, count in Counter(row_keys).items() if count > 1
        )
        if duplicate_keys:
            raise ValueError(
                f"{model} contains duplicate case/repeat rows: {duplicate_keys[:5]}"
            )
        if set(row_keys) != expected_row_keys:
            missing = sorted(expected_row_keys - set(row_keys))
            extra = sorted(set(row_keys) - expected_row_keys)
            raise ValueError(
                f"{model} has an incomplete case/repeat matrix: "
                f"missing={missing[:5]}, extra={extra[:5]}"
            )

        for row in rows:
            case_id = str(row["case_id"])
            repeat = int(row["repeat"])
            case = test_cases[case_id]
            label = f"{model}/{case_id}/repeat {repeat}"
            if row.get("model") != model:
                raise ValueError(f"{label} row.model does not match its per_case group")
            if list(row.get("expected_codes", [])) != expected_codes(case):
                raise ValueError(
                    f"Ground-truth mismatch for {label}: "
                    f"matrix={row.get('expected_codes', [])}, current={expected_codes(case)}"
                )
            for field in ("complexity", "category", "evaluation_slice", "augmentation"):
                if row.get(field) != case.get(field):
                    raise ValueError(f"Ground-truth field mismatch for {label}: {field}")
            predicted_codes = row.get("predicted_codes")
            if not isinstance(predicted_codes, list):
                raise ValueError(f"{label} predicted_codes must be a list")
            if len({str(code) for code in predicted_codes}) != len(predicted_codes):
                raise ValueError(f"{label} predicted_codes contains duplicates")
            if not isinstance(row.get("detected_problems"), list):
                raise ValueError(f"{label} detected_problems must be a list")
            for field in ("l2_attempted", "l2_degraded"):
                if not isinstance(row.get(field), bool):
                    raise ValueError(f"{label} {field} must be boolean")

            metrics = row.get("retrieval_metrics")
            if not isinstance(metrics, dict):
                raise ValueError(f"{label} retrieval_metrics must be an object")
            if set(metrics) != set(strategies):
                raise ValueError(
                    f"Incomplete retrieval metrics for {label}: "
                    f"expected={strategies}, actual={sorted(metrics)}"
                )
            for strategy in strategies:
                strategy_metrics = metrics[strategy]
                metric_label = f"{label}/{strategy}"
                if not isinstance(strategy_metrics, dict):
                    raise ValueError(f"{metric_label} metrics must be an object")
                doc_ids = strategy_metrics.get("doc_ids")
                if not isinstance(doc_ids, list) or len(doc_ids) != expected_top_k:
                    raise ValueError(
                        f"{metric_label} must contain exactly {expected_top_k} doc_ids"
                    )
                if len({str(doc_id) for doc_id in doc_ids}) != len(doc_ids):
                    raise ValueError(f"{metric_label} doc_ids contains duplicates")
                for metric in RETRIEVAL_METRICS:
                    if metric not in strategy_metrics:
                        raise ValueError(f"{metric_label} is missing {metric}")
                    require_rate(strategy_metrics[metric], f"{metric_label}/{metric}")
                if int(strategy_metrics.get("total_docs", -1)) != len(doc_ids):
                    raise ValueError(f"{metric_label} total_docs does not match doc_ids")
                total_relevant = int(strategy_metrics.get("total_relevant", -1))
                if not 0 <= total_relevant <= len(doc_ids):
                    raise ValueError(f"{metric_label} total_relevant is out of range")
                require_nonnegative(
                    strategy_metrics.get("retrieval_ms"),
                    f"{metric_label}/retrieval_ms",
                )

    expected_adv_rows = len(adversarial) * expected_repeats
    for model in models:
        adv_rows = [row for row in per_case[model] if str(row["case_id"]) in adversarial]
        if len(adv_rows) != expected_adv_rows:
            raise ValueError(
                f"{model} has {len(adv_rows)} adversarial rows, expected {expected_adv_rows}"
            )
    return {
        "models": models,
        "strategies": strategies,
        "repeats": expected_repeats,
        "top_k": expected_top_k,
        "problem_source": "detected",
        "run_signature": run_signature,
    }


def detector_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    target_total = sum(len(row["target_codes"]) for row in rows)
    target_hits = sum(len(row["target_hits"]) for row in rows)
    complete_count = sum(bool(row["target_all_preserved"]) for row in rows)
    suppressed_count = sum(bool(row["false_trigger_suppressed"]) for row in rows)
    joint_count = sum(bool(row["joint_pass"]) for row in rows)
    l2_attempted = sum(bool(row["l2_attempted"]) for row in rows)
    l2_degraded = sum(bool(row["l2_degraded"]) for row in rows)
    n_rows = len(rows)
    return {
        "n_rows": n_rows,
        "n_unique_cases": len({row["case_id"] for row in rows}),
        "target_code_opportunities": target_total,
        "target_code_hits": target_hits,
        "target_code_misses": target_total - target_hits,
        "target_code_recall": target_hits / target_total if target_total else 0.0,
        "complete_target_preservation_count": complete_count,
        "complete_target_preservation_rate": complete_count / n_rows if n_rows else 0.0,
        "false_trigger_suppression_count": suppressed_count,
        "false_trigger_suppression_rate": suppressed_count / n_rows if n_rows else 0.0,
        "false_trigger_activation_count": n_rows - suppressed_count,
        "false_trigger_activation_rate": (
            (n_rows - suppressed_count) / n_rows if n_rows else 0.0
        ),
        "joint_pass_count": joint_count,
        "joint_pass_rate": joint_count / n_rows if n_rows else 0.0,
        "joint_failure_count": n_rows - joint_count,
        "l2_attempted_rows": l2_attempted,
        "l2_attempt_rate": l2_attempted / n_rows if n_rows else 0.0,
        "l2_degraded_rows": l2_degraded,
        "l2_degraded_rate": l2_degraded / n_rows if n_rows else 0.0,
    }


def retrieval_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_case[row["case_id"]].append(row)
    case_means = {
        case_id: {
            metric: mean(case_rows, metric)
            for metric in RETRIEVAL_METRICS
        }
        for case_id, case_rows in by_case.items()
    }
    result: dict[str, Any] = {
        "n_rows": len(rows),
        "n_unique_cases": len(by_case),
        "repeats_per_case": sorted({len(case_rows) for case_rows in by_case.values()}),
        "aggregation_unit": "case mean across repeats, then unweighted mean across cases",
    }
    for metric in RETRIEVAL_METRICS:
        values = [case_metrics[metric] for case_metrics in case_means.values()]
        result[metric] = statistics.fmean(values) if values else 0.0
        result[f"{metric}_median_across_cases"] = (
            statistics.median(values) if values else 0.0
        )
        result[f"{metric}_std_across_cases"] = (
            statistics.stdev(values) if len(values) > 1 else 0.0
        )
    return result


def summarize(matrix: dict[str, Any], adversarial: dict[str, dict[str, Any]]) -> dict[str, Any]:
    strategies = list(matrix["metadata"]["retrieval_strategies"])
    detector_by_model: dict[str, dict[str, Any]] = {}
    all_detector_rows: list[dict[str, Any]] = []
    retrieval_records: list[dict[str, Any]] = []
    per_case_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for model, rows in matrix["per_case"].items():
        detector_rows: list[dict[str, Any]] = []
        for row in rows:
            case_id = str(row["case_id"])
            if case_id not in adversarial:
                continue
            case = adversarial[case_id]
            targets = expected_codes(case)
            target_set = set(targets)
            predicted = {str(code) for code in row.get("predicted_codes", [])}
            trigger = str(case["augmentation"]["false_trigger_code"])
            hits = sorted(target_set & predicted)
            target_all_preserved = target_set <= predicted
            false_trigger_suppressed = trigger not in predicted
            result = {
                "model": model,
                "repeat": int(row["repeat"]),
                "case_id": case_id,
                "target_codes": targets,
                "target_hits": hits,
                "target_recall": len(hits) / len(targets),
                "target_all_preserved": target_all_preserved,
                "false_trigger_code": trigger,
                "false_trigger_suppressed": false_trigger_suppressed,
                "false_trigger_activated": not false_trigger_suppressed,
                "joint_pass": target_all_preserved and false_trigger_suppressed,
                "predicted_codes": sorted(predicted),
                "l2_attempted": bool(row.get("l2_attempted")),
                "l2_degraded": bool(row.get("l2_degraded")),
            }
            detector_rows.append(result)
            all_detector_rows.append(result)
            per_case_rows[case_id].append(result)
            for strategy in strategies:
                metrics = row["retrieval_metrics"][strategy]
                retrieval_records.append(
                    {
                        "model": model,
                        "repeat": int(row["repeat"]),
                        "case_id": case_id,
                        "strategy": strategy,
                        **{
                            metric: float(metrics[metric])
                            for metric in RETRIEVAL_METRICS
                        },
                    }
                )

        detector_by_model[model] = detector_summary(detector_rows)

    retrieval_by_model: dict[str, dict[str, Any]] = {}
    for model in matrix["per_case"]:
        retrieval_by_model[model] = {}
        for strategy in strategies:
            selected = [
                row
                for row in retrieval_records
                if row["model"] == model and row["strategy"] == strategy
            ]
            retrieval_by_model[model][strategy] = retrieval_summary(selected)

    per_case = []
    for case_id, case in adversarial.items():
        rows = per_case_rows[case_id]
        case_summary = detector_summary(rows)
        retrieval_by_model_strategy: dict[str, dict[str, Any]] = {}
        for model in matrix["per_case"]:
            retrieval_by_model_strategy[model] = {}
            for strategy in strategies:
                selected = [
                    row
                    for row in retrieval_records
                    if row["case_id"] == case_id
                    and row["model"] == model
                    and row["strategy"] == strategy
                ]
                retrieval_by_model_strategy[model][strategy] = {
                    "n_rows": len(selected),
                    **{
                        metric: mean(selected, metric)
                        for metric in RETRIEVAL_METRICS
                    },
                }
        per_case.append(
            {
                "case_id": case_id,
                "description": case.get("case_description", ""),
                "target_codes": expected_codes(case),
                "false_trigger_code": case["augmentation"]["false_trigger_code"],
                "trigger_word": case["augmentation"].get("trigger_word"),
                **case_summary,
                "retrieval_by_model_strategy": retrieval_by_model_strategy,
                "failed_rows": [
                    {
                        "model": row["model"],
                        "repeat": row["repeat"],
                        "target_all_preserved": row["target_all_preserved"],
                        "false_trigger_suppressed": row["false_trigger_suppressed"],
                        "predicted_codes": row["predicted_codes"],
                    }
                    for row in rows
                    if not row["joint_pass"]
                ],
            }
        )

    return {
        "method": {
            "slice": "adversarial_test",
            "target_preservation": "all expected target codes are present in predicted_codes",
            "false_trigger_suppression": "augmentation.false_trigger_code is absent from predicted_codes",
            "joint_pass": "target_preservation AND false_trigger_suppression",
            "joint_scope": (
                "Only the annotated false-trigger code is tested; other unexpected "
                "predictions do not change joint_pass."
            ),
            "target_code_recall": (
                "micro recall over annotated target-code opportunities within each "
                "reported detector group"
            ),
            "detector_aggregation": (
                "by-model rates use model-case-repeat rows; detector_overall pools "
                "models and is descriptive, not an independent-sample estimate"
            ),
            "per_case_aggregation": "pooled model-repeat rows for audit-oriented case summaries",
            "retrieval_relevance": "graded against the expected target codes, not the false trigger",
            "retrieval_aggregation": (
                "mean within case across repeats, followed by an unweighted mean "
                "across adversarial cases"
            ),
            "degraded_rows": "retained in all denominators and reported explicitly",
        },
        "detector_overall": detector_summary(all_detector_rows),
        "detector_by_model": detector_by_model,
        "retrieval_by_model_strategy": retrieval_by_model,
        "per_case": per_case,
    }


def markdown_report(result: dict[str, Any]) -> str:
    metadata = result["metadata"]
    lines = [
        "# Adversarial Stress-Test Slice",
        "",
        f"Generated: {metadata['generated_at']}",
        f"Matrix: `{metadata['matrix_path']}` (`{metadata['matrix_sha256']}`)",
        f"Ground truth: `{metadata['ground_truth_path']}` (`{metadata['ground_truth_sha256']}`)",
        "",
        "Pass criteria: preserve every expected target code, suppress the annotated false-trigger code, and satisfy both for joint pass.",
        "Other unexpected predictions do not alter joint pass. Degraded rows remain in every denominator.",
        "",
        "## Detector",
        "",
        "| Model | Rows | Target hits/opportunities | Target recall | Complete targets | False trigger suppressed | Joint pass | Degraded |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    detector_rows = [("Overall (descriptive)", result["detector_overall"])]
    detector_rows.extend(result["detector_by_model"].items())
    for model, values in detector_rows:
        lines.append(
            f"| {model} | {values['n_rows']} | "
            f"{values['target_code_hits']}/{values['target_code_opportunities']} | "
            f"{values['target_code_recall']:.4f} | "
            f"{values['complete_target_preservation_count']}/{values['n_rows']} "
            f"({values['complete_target_preservation_rate']:.4f}) | "
            f"{values['false_trigger_suppression_count']}/{values['n_rows']} "
            f"({values['false_trigger_suppression_rate']:.4f}) | "
            f"{values['joint_pass_count']}/{values['n_rows']} "
            f"({values['joint_pass_rate']:.4f}) | "
            f"{values['l2_degraded_rows']}/{values['n_rows']} |"
        )
    lines.extend(
        [
            "",
            "## Retrieval",
            "",
            "Retrieval values first average repeats within each case, then average the case means across the adversarial slice.",
            "",
            "| Model | Strategy | Cases | nDCG@5 | nDCG@10 | MAP | MRR |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    for model, strategies in result["retrieval_by_model_strategy"].items():
        for strategy, values in strategies.items():
            lines.append(
                f"| {model} | {strategy} | {values['n_unique_cases']} | "
                f"{values['nDCG@5']:.4f} | {values['nDCG@10']:.4f} | "
                f"{values['MAP']:.4f} | {values['MRR']:.4f} |"
            )
    lines.extend(
        [
            "",
            "## Per Case",
            "",
            "| Case | Target | False trigger | Target hits/opportunities | Target recall | False-trigger suppression | Joint pass |",
            "|---|---|---|---:|---:|---:|---:|",
        ]
    )
    for row in result["per_case"]:
        lines.append(
            f"| {row['case_id']} | {', '.join(row['target_codes'])} | "
            f"{row['false_trigger_code']} | "
            f"{row['target_code_hits']}/{row['target_code_opportunities']} | "
            f"{row['target_code_recall']:.4f} | "
            f"{row['false_trigger_suppression_rate']:.4f} | {row['joint_pass_rate']:.4f} |"
        )
    lines.append("")
    return "\n".join(lines)


def build_report(
    matrix_path: Path,
    ground_truth_path: Path,
    taxonomy_path: Path,
    *,
    expected_cases: int,
    expected_test_cases: int,
    expected_models: int,
    expected_repeats: int,
    expected_strategies: int,
    expected_top_k: int,
) -> dict[str, Any]:
    matrix_path = matrix_path.resolve()
    ground_truth_path = ground_truth_path.resolve()
    taxonomy_path = taxonomy_path.resolve()
    ground_truth_hash = sha256(ground_truth_path)
    taxonomy_hash = sha256(taxonomy_path)
    matrix, ground_truth, test_cases, adversarial, _taxonomy = load_inputs(
        matrix_path,
        ground_truth_path,
        taxonomy_path,
        expected_cases,
        expected_test_cases,
    )
    validation = validate_matrix(
        matrix,
        test_cases,
        adversarial,
        expected_test_cases,
        expected_models,
        expected_repeats,
        expected_strategies,
        expected_top_k,
        ground_truth_hash,
        taxonomy_hash,
    )
    result = summarize(matrix, adversarial)
    result["status"] = "complete"
    result["metadata"] = {
        "generated_at": datetime.now(ZoneInfo("Asia/Bangkok")).isoformat(
            timespec="seconds"
        ),
        "artifact_type": "adversarial_stress_test_slice",
        "matrix_path": display_path(matrix_path),
        "matrix_created_at": matrix["metadata"]["created_at"],
        "matrix_sha256": sha256(matrix_path),
        "matrix_run_signature": validation["run_signature"],
        "ground_truth_path": display_path(ground_truth_path),
        "ground_truth_sha256": ground_truth_hash,
        "ground_truth_last_updated": ground_truth.get("metadata", {}).get(
            "last_updated"
        ),
        "taxonomy_path": display_path(taxonomy_path),
        "taxonomy_sha256": taxonomy_hash,
        "h2l_core_sha256": sha256(H2L_CORE),
        "evaluation_code_sha256": sha256(EVALUATION_CODE),
        "problem_source": validation["problem_source"],
        "top_k": validation["top_k"],
        "n_test_cases": len(test_cases),
        "n_adversarial_cases": len(adversarial),
        "n_cases": len(adversarial),
        "models": validation["models"],
        "repeats": validation["repeats"],
        "strategies": validation["strategies"],
        "validation": "complete_matrix_schema_and_provenance_verified",
    }
    return result


def write_report(result: dict[str, Any], json_path: Path, markdown_path: Path) -> None:
    payloads = {
        json_path.resolve(): json.dumps(result, ensure_ascii=False, indent=2),
        markdown_path.resolve(): markdown_report(result),
    }
    for path, content in payloads.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f"{path.suffix}.tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--ground-truth", type=Path, default=DEFAULT_GROUND_TRUTH)
    parser.add_argument("--taxonomy", type=Path, default=DEFAULT_TAXONOMY)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--output-markdown", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--expected-cases", type=int, default=20)
    parser.add_argument("--expected-test-cases", type=int, default=95)
    parser.add_argument("--expected-models", type=int, default=3)
    parser.add_argument("--expected-repeats", type=int, default=3)
    parser.add_argument("--expected-strategies", type=int, default=8)
    parser.add_argument("--expected-top-k", type=int, default=15)
    args = parser.parse_args()

    result = build_report(
        args.matrix,
        args.ground_truth,
        args.taxonomy,
        expected_cases=args.expected_cases,
        expected_test_cases=args.expected_test_cases,
        expected_models=args.expected_models,
        expected_repeats=args.expected_repeats,
        expected_strategies=args.expected_strategies,
        expected_top_k=args.expected_top_k,
    )
    write_report(result, args.output_json, args.output_markdown)
    print(args.output_json)
    print(args.output_markdown)


if __name__ == "__main__":
    main()

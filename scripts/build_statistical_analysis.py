#!/usr/bin/env python3
"""Build reproducible paired statistics directly from a retrieval matrix."""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from scipy.stats import wilcoxon

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.derive_latest_retrieval_metrics import holm_adjust, rank_biserial, sha256


DEFAULT_SOURCE = (
    ROOT
    / "evaluation_results"
    / "model_comparison"
    / "l2_full_matrix_100cases_3models_3repeats_8strategies.json"
)
DEFAULT_OUTPUT = ROOT / "evaluation_results" / "statistical_analysis_20260815_thesis.json"
DEFAULT_GROUND_TRUTH = ROOT / "data" / "expanded_ground_truth.json"
DEFAULT_TAXONOMY = ROOT / "data" / "problem_codes.json"
PRIMARY_MODEL = "qwen2.5:7b"
PRIMARY_STRATEGY = "h2l-hybrid"
METRICS = ("nDCG@5", "nDCG@10", "MAP", "MRR")


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path.resolve())


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def _validate_source(
    artifact: dict[str, Any],
    source: Path,
    ground_truth: Path,
    taxonomy: Path,
    *,
    allow_versioned_source: bool,
) -> dict[str, Any]:
    metadata = artifact.get("metadata")
    if not isinstance(metadata, dict):
        raise ValueError("Matrix metadata must be an object")
    signature = metadata.get("run_signature")
    if not isinstance(signature, dict):
        raise ValueError("Matrix metadata.run_signature must be an object")

    source_taxonomy_sha256 = signature.get("taxonomy_sha256")
    source_ground_truth_sha256 = signature.get("ground_truth_sha256")
    current_taxonomy_sha256 = sha256(taxonomy)
    current_ground_truth_sha256 = sha256(ground_truth)
    taxonomy_current = source_taxonomy_sha256 == current_taxonomy_sha256
    ground_truth_current = source_ground_truth_sha256 == current_ground_truth_sha256
    inputs_current = bool(taxonomy_current and ground_truth_current)
    if not inputs_current and not allow_versioned_source:
        raise ValueError(
            "Matrix inputs do not match the current repository inputs: "
            f"taxonomy source={source_taxonomy_sha256!r} current={current_taxonomy_sha256!r}; "
            f"ground_truth source={source_ground_truth_sha256!r} current={current_ground_truth_sha256!r}. "
            "Rerun the matrix or pass --allow-versioned-source to build a clearly versioned artifact."
        )

    return {
        "source": _display_path(source),
        "source_sha256": sha256(source),
        "source_created_at": metadata.get("created_at"),
        "source_run_signature": signature,
        "taxonomy_sha256": source_taxonomy_sha256,
        "ground_truth_sha256": source_ground_truth_sha256,
        "current_taxonomy_sha256": current_taxonomy_sha256,
        "current_ground_truth_sha256": current_ground_truth_sha256,
        "taxonomy_current": taxonomy_current,
        "ground_truth_current": ground_truth_current,
        "current_input_match": inputs_current,
        "provenance_status": "current" if inputs_current else "versioned-source",
    }


def _matrix_frame(
    artifact: dict[str, Any],
    primary_model: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    metadata = artifact["metadata"]
    models = metadata.get("models")
    strategies = metadata.get("retrieval_strategies")
    repeats = int(metadata.get("repeats", 0) or 0)
    expected_cases = int(metadata.get("test_cases", 0) or 0)
    if not isinstance(models, list) or primary_model not in models:
        raise ValueError(f"Primary model is absent from matrix: {primary_model}")
    if not isinstance(strategies, list) or PRIMARY_STRATEGY not in strategies:
        raise ValueError(f"Primary strategy is absent from matrix: {PRIMARY_STRATEGY}")
    if repeats < 1 or expected_cases < 1:
        raise ValueError("Matrix repeats and test_cases must be positive")

    per_case = artifact.get("per_case", {}).get(primary_model)
    if not isinstance(per_case, list):
        raise ValueError(f"per_case[{primary_model!r}] must be a list")

    row_keys: set[tuple[str, int]] = set()
    records: list[dict[str, Any]] = []
    for row in per_case:
        case_id = str(row.get("case_id") or "")
        repeat = int(row.get("repeat", 0) or 0)
        if not case_id or repeat < 1:
            raise ValueError("Every matrix row requires case_id and a positive repeat")
        row_key = (case_id, repeat)
        if row_key in row_keys:
            raise ValueError(f"Duplicate matrix row: {row_key}")
        row_keys.add(row_key)
        retrieval = row.get("retrieval_metrics")
        if not isinstance(retrieval, dict) or set(retrieval) != set(strategies):
            raise ValueError(f"Incomplete retrieval strategies for {case_id}/repeat={repeat}")
        for strategy in strategies:
            metric_payload = retrieval[strategy]
            record = {"case_id": case_id, "repeat": repeat, "strategy": strategy}
            for metric in METRICS:
                value = metric_payload.get(metric)
                if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                    raise ValueError(
                        f"Missing or non-finite {metric} for {case_id}/repeat={repeat}/{strategy}"
                    )
                record[metric] = float(value)
            records.append(record)

    expected_rows = expected_cases * repeats
    if len(row_keys) != expected_rows:
        raise ValueError(
            f"Incomplete primary-model matrix: expected {expected_rows} case/repeat rows, found {len(row_keys)}"
        )
    unique_cases = len({case_id for case_id, _ in row_keys})
    if unique_cases != expected_cases:
        raise ValueError(
            f"Unique case count mismatch: expected {expected_cases}, found {unique_cases}"
        )

    frame = pd.DataFrame(records)
    per_case_frame = frame.groupby(["case_id", "strategy"], as_index=False)[list(METRICS)].mean()
    expected_cells = expected_cases * len(strategies)
    if len(per_case_frame) != expected_cells:
        raise ValueError(
            f"Incomplete per-case strategy matrix: expected {expected_cells} cells, found {len(per_case_frame)}"
        )
    return per_case_frame, {
        "models": models,
        "strategies": strategies,
        "repeats": repeats,
        "n_cases": expected_cases,
        "top_k": metadata.get("top_k"),
        "problem_source": metadata.get("problem_source"),
    }


def _metric_block(
    frame: pd.DataFrame,
    metric: str,
    strategies: list[str],
) -> dict[str, Any]:
    pivot = frame.pivot(index="case_id", columns="strategy", values=metric)
    comparison_strategies = [strategy for strategy in strategies if strategy != PRIMARY_STRATEGY]
    raw_p_values: list[float] = []
    pairs: list[dict[str, Any]] = []

    for strategy in comparison_strategies:
        paired = pivot[[PRIMARY_STRATEGY, strategy]].dropna()
        differences = (
            paired[PRIMARY_STRATEGY].to_numpy(dtype=float)
            - paired[strategy].to_numpy(dtype=float)
        )
        nonzero = int(np.count_nonzero(np.abs(differences) > 1e-15))
        if nonzero:
            statistic, raw_p = wilcoxon(
                differences,
                zero_method="wilcox",
                alternative="two-sided",
                method="auto",
            )
        else:
            statistic, raw_p = 0.0, 1.0
        raw_p_values.append(float(raw_p))
        pairs.append({
            "strategy": strategy,
            "reference_mean": float(paired[PRIMARY_STRATEGY].mean()),
            "comparison_mean": float(paired[strategy].mean()),
            "mean_difference": float(differences.mean()),
            "median_difference": float(np.median(differences)),
            "wilcoxon_statistic": float(statistic),
            "raw_p": float(raw_p),
            "rank_biserial": rank_biserial(differences),
            "n_nonzero_differences": nonzero,
            "n_pairs": int(len(paired)),
        })

    for pair, adjusted_p in zip(pairs, holm_adjust(raw_p_values)):
        pair["holm_family_size"] = len(pairs)
        pair["holm_p"] = float(adjusted_p)
        pair["significant_0_05"] = bool(adjusted_p < 0.05)

    means = pivot.mean(axis=0)
    stds = pivot.std(axis=0, ddof=1).fillna(0.0)
    counts = pivot.count(axis=0)
    return {
        "metric_name": metric,
        "descriptive_stats": {
            "Mean": {strategy: float(means[strategy]) for strategy in strategies},
            "Std": {strategy: float(stds[strategy]) for strategy in strategies},
            "N": {strategy: int(counts[strategy]) for strategy in strategies},
        },
        "pairs": pairs,
        "significant_pairs": [
            pair["strategy"] for pair in pairs if pair["significant_0_05"]
        ],
        "source_function": "scripts/build_statistical_analysis.py::build_artifact",
    }


def build_artifact(
    source: Path = DEFAULT_SOURCE,
    output: Path = DEFAULT_OUTPUT,
    *,
    ground_truth: Path = DEFAULT_GROUND_TRUTH,
    taxonomy: Path = DEFAULT_TAXONOMY,
    primary_model: str = PRIMARY_MODEL,
    allow_versioned_source: bool = False,
) -> dict[str, Any]:
    source = source.resolve()
    output = output.resolve()
    ground_truth = ground_truth.resolve()
    taxonomy = taxonomy.resolve()
    artifact = _load_json(source)
    provenance = _validate_source(
        artifact,
        source,
        ground_truth,
        taxonomy,
        allow_versioned_source=allow_versioned_source,
    )
    frame, protocol = _matrix_frame(artifact, primary_model)
    strategies = protocol["strategies"]

    result: dict[str, Any] = {
        "generated_at": datetime.now(ZoneInfo("Asia/Bangkok")).isoformat(timespec="seconds"),
        **provenance,
        "source_function": "scripts/build_statistical_analysis.py::build_artifact",
        "primary_model": primary_model,
        "primary_strategy": PRIMARY_STRATEGY,
        **protocol,
        "scoring_path": "matrix_runtime_per_case",
        "statistical_test": "paired two-sided Wilcoxon signed-rank",
        "alternative": "two-sided",
        "zero_method": "wilcox",
        "multiplicity_correction": "Holm, applied separately within each metric",
        "note": (
            "Derived directly from stored per-case runtime metrics. "
            "A versioned-source artifact is reproducible for its frozen matrix but is not current-runtime evidence."
        ),
    }
    for metric in METRICS:
        result[metric] = _metric_block(frame, metric, strategies)

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(output)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--ground-truth", type=Path, default=DEFAULT_GROUND_TRUTH)
    parser.add_argument("--taxonomy", type=Path, default=DEFAULT_TAXONOMY)
    parser.add_argument("--primary-model", default=PRIMARY_MODEL)
    parser.add_argument("--allow-versioned-source", action="store_true")
    args = parser.parse_args()
    result = build_artifact(
        args.source,
        args.output,
        ground_truth=args.ground_truth,
        taxonomy=args.taxonomy,
        primary_model=args.primary_model,
        allow_versioned_source=args.allow_versioned_source,
    )
    print(json.dumps({
        "output": _display_path(args.output),
        "provenance_status": result["provenance_status"],
        "current_input_match": result["current_input_match"],
        "alternative": result["alternative"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

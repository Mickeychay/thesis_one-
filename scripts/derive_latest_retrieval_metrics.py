#!/usr/bin/env python3
"""Derive complete @5/@10 metrics from the latest L2 retrieval matrix."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from scipy.stats import rankdata, wilcoxon


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DEFAULT_SOURCE = (
    ROOT
    / "evaluation_results"
    / "model_comparison"
    / "l2_full_matrix_95cases_3models_3repeats_8strategies.json"
)
DEFAULT_OUTPUT_DIR = ROOT / "evaluation_results" / "derived"
DEFAULT_GROUND_TRUTH = ROOT / "data/expanded_ground_truth.json"
DEFAULT_DOCUMENT_METADATA = ROOT / "data" / "vector_db_lancedb" / "metadata.json"
DEFAULT_TAXONOMY = ROOT / "data/problem_codes.json"
DEFAULT_OUTPUT_TAG = "20260807"
DEFAULT_EXPECTED_CASE_COUNT = 95
PRIMARY_MODEL = "qwen2.5:7b"
PRIMARY_STRATEGY = "h2l-hybrid"
METRICS = [
    "P@5",
    "R@5",
    "F1@5",
    "DCG@5",
    "IDCG@5",
    "nDCG@5",
    "P@10",
    "R@10",
    "F1@10",
    "DCG@10",
    "IDCG@10",
    "nDCG@10",
    "MAP",
    "MRR",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def display_path(path: Path) -> str:
    """Use repository-relative paths when possible without breaking temp fixtures."""
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path.resolve())


def expected_codes(case: dict[str, Any]) -> list[str]:
    problems = case.get("expected_diagnosis", {}).get("problem_list", [])
    return list(
        dict.fromkeys(
            str(problem.get("code"))
            for problem in problems
            if problem.get("code")
        )
    )


def augmentation_fields(case: dict[str, Any]) -> dict[str, Any]:
    augmentation = case.get("augmentation")
    if augmentation is None:
        return {
            "augmentation": None,
            "augmentation_type": case_augmentation_type(case),
        }
    return {
        "augmentation": json.dumps(
            augmentation,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        "augmentation_type": (
            augmentation.get("type") if isinstance(augmentation, dict) else None
        ),
    }


def case_augmentation_type(case: dict[str, Any]) -> str:
    """Match the benchmark audit's mutually exclusive case classification."""
    case_id = str(case.get("case_id", ""))
    if case_id.startswith("NEG_"):
        return "polarity"
    augmentation = case.get("augmentation")
    if isinstance(augmentation, dict) and augmentation.get("type"):
        return str(augmentation["type"])
    return "original"


def validate_matrix(
    artifact: dict[str, Any],
    cases: dict[str, dict[str, Any]],
    expected_case_count: int,
) -> dict[str, Any]:
    """Fail before derivation when the benchmark matrix is incomplete or stale."""
    if expected_case_count <= 0:
        raise ValueError("expected_case_count must be greater than zero")
    if len(cases) != expected_case_count:
        raise ValueError(
            "Ground truth test split count mismatch: "
            f"expected={expected_case_count}, actual={len(cases)}"
        )

    metadata = artifact.get("metadata")
    per_case = artifact.get("per_case")
    if not isinstance(metadata, dict) or not isinstance(per_case, dict):
        raise ValueError("Source artifact must contain metadata and per_case objects")

    models = [str(model) for model in metadata.get("models", [])]
    strategies = [str(strategy) for strategy in metadata.get("retrieval_strategies", [])]
    repeats = int(metadata.get("repeats", 0) or 0)
    if not models or not strategies or repeats <= 0:
        raise ValueError("Source metadata must define models, retrieval_strategies, and repeats")
    if set(per_case) != set(models):
        raise ValueError(
            "Source per_case model keys do not match metadata models: "
            f"metadata={models}, per_case={sorted(per_case)}"
        )
    if int(metadata.get("test_cases", -1)) != expected_case_count:
        raise ValueError(
            "Source metadata test_cases mismatch: "
            f"expected={expected_case_count}, actual={metadata.get('test_cases')}"
        )

    case_ids = set(cases)
    expected_row_keys = {
        (case_id, repeat)
        for case_id in case_ids
        for repeat in range(1, repeats + 1)
    }
    all_rows: list[dict[str, Any]] = []
    for model in models:
        model_rows = per_case[model]
        if not isinstance(model_rows, list):
            raise ValueError(f"per_case[{model!r}] must be a list")
        row_keys: list[tuple[str, int]] = []
        for row in model_rows:
            case_id = str(row.get("case_id", ""))
            repeat = int(row.get("repeat", 0) or 0)
            row_keys.append((case_id, repeat))
            if case_id not in cases:
                raise ValueError(f"Unknown test case in source artifact: {case_id}")
            if list(row.get("expected_codes", [])) != expected_codes(cases[case_id]):
                raise ValueError(
                    f"Expected codes differ from ground truth for model={model}, "
                    f"case={case_id}, repeat={repeat}"
                )
            retrieval_metrics = row.get("retrieval_metrics")
            if not isinstance(retrieval_metrics, dict):
                raise ValueError(
                    f"Missing retrieval_metrics for model={model}, case={case_id}, repeat={repeat}"
                )
            if set(retrieval_metrics) != set(strategies):
                raise ValueError(
                    f"Retrieval strategies are incomplete for model={model}, "
                    f"case={case_id}, repeat={repeat}: "
                    f"expected={strategies}, actual={sorted(retrieval_metrics)}"
                )
            for strategy, metrics in retrieval_metrics.items():
                if not isinstance(metrics, dict) or not isinstance(metrics.get("doc_ids"), list):
                    raise ValueError(
                        f"Missing doc_ids for model={model}, case={case_id}, "
                        f"repeat={repeat}, strategy={strategy}"
                    )
            all_rows.append(row)

        duplicate_keys = sorted(
            key for key, count in Counter(row_keys).items() if count > 1
        )
        if duplicate_keys:
            raise ValueError(f"Duplicate case/repeat rows for model={model}: {duplicate_keys[:5]}")
        actual_row_keys = set(row_keys)
        if actual_row_keys != expected_row_keys:
            missing = sorted(expected_row_keys - actual_row_keys)
            extra = sorted(actual_row_keys - expected_row_keys)
            raise ValueError(
                f"Incomplete case/repeat matrix for model={model}: "
                f"missing={missing[:5]}, extra={extra[:5]}"
            )

    artifact_case_ids = {str(row["case_id"]) for row in all_rows}
    if len(artifact_case_ids) != expected_case_count or artifact_case_ids != case_ids:
        raise ValueError(
            "Source unique test case IDs do not match ground truth: "
            f"expected={expected_case_count}, actual={len(artifact_case_ids)}"
        )

    explicit_problem_source = metadata.get("problem_source")
    all_have_detected_problems = all("detected_problems" in row for row in all_rows)
    if explicit_problem_source is None and all_have_detected_problems:
        problem_source = "detected"
        problem_source_provenance = "inferred_from_detected_problems_rows"
    else:
        problem_source = explicit_problem_source
        problem_source_provenance = "source_metadata"
    if problem_source != "detected":
        raise ValueError(
            "Final benchmark requires problem_source=detected; "
            f"source reports {problem_source!r}"
        )

    return {
        "models": models,
        "strategies": strategies,
        "repeats": repeats,
        "case_ids": case_ids,
        "problem_source": problem_source,
        "problem_source_provenance": problem_source_provenance,
    }


def holm_adjust(p_values: list[float]) -> list[float]:
    """Holm step-down adjusted p-values in the original order."""
    count = len(p_values)
    order = sorted(range(count), key=lambda index: p_values[index])
    adjusted = [1.0] * count
    running_max = 0.0
    for rank, index in enumerate(order):
        candidate = min(1.0, (count - rank) * p_values[index])
        running_max = max(running_max, candidate)
        adjusted[index] = running_max
    return adjusted


def rank_biserial(differences: np.ndarray) -> float:
    nonzero = differences[np.abs(differences) > 1e-15]
    if nonzero.size == 0:
        return 0.0
    ranks = rankdata(np.abs(nonzero))
    positive = float(ranks[nonzero > 0].sum())
    negative = float(ranks[nonzero < 0].sum())
    return (positive - negative) / (positive + negative)


def paired_tests(frame: pd.DataFrame) -> pd.DataFrame:
    if PRIMARY_MODEL not in set(frame["model"]):
        raise ValueError(f"Primary model is absent from matrix: {PRIMARY_MODEL}")
    selected = frame[frame["model"] == PRIMARY_MODEL]
    if PRIMARY_STRATEGY not in set(selected["strategy"]):
        raise ValueError(f"Primary strategy is absent from matrix: {PRIMARY_STRATEGY}")
    per_case = (
        selected.groupby(["case_id", "strategy"], as_index=False)[["nDCG@5", "nDCG@10"]]
        .mean()
    )
    strategies = [
        strategy
        for strategy in selected["strategy"].drop_duplicates().tolist()
        if strategy != PRIMARY_STRATEGY
    ]
    records: list[dict] = []

    for metric in ("nDCG@5", "nDCG@10"):
        pivot = per_case.pivot(index="case_id", columns="strategy", values=metric)
        raw_p_values: list[float] = []
        metric_records: list[dict] = []
        for strategy in strategies:
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
            metric_records.append(
                {
                    "metric": metric,
                    "holm_family": metric,
                    "reference": PRIMARY_STRATEGY,
                    "comparison": strategy,
                    "n_pairs": int(len(paired)),
                    "n_nonzero_differences": nonzero,
                    "reference_mean": float(paired[PRIMARY_STRATEGY].mean()),
                    "comparison_mean": float(paired[strategy].mean()),
                    "mean_difference": float(differences.mean()),
                    "median_difference": float(np.median(differences)),
                    "wilcoxon_statistic": float(statistic),
                    "raw_p": float(raw_p),
                    "rank_biserial": rank_biserial(differences),
                }
            )

        adjusted = holm_adjust(raw_p_values)
        for record, adjusted_p in zip(metric_records, adjusted):
            record["holm_family_size"] = len(metric_records)
            record["holm_p"] = adjusted_p
            record["significant_0_05"] = bool(adjusted_p < 0.05)
            records.append(record)

    return pd.DataFrame(records)


def derive(
    source: Path,
    output_dir: Path,
    *,
    ground_truth: Path = DEFAULT_GROUND_TRUTH,
    document_metadata: Path = DEFAULT_DOCUMENT_METADATA,
    taxonomy_path: Path = DEFAULT_TAXONOMY,
    expected_case_count: int = DEFAULT_EXPECTED_CASE_COUNT,
    output_tag: str = DEFAULT_OUTPUT_TAG,
    per_case_output: Path | None = None,
    aggregate_output: Path | None = None,
    significance_output: Path | None = None,
    json_output: Path | None = None,
) -> dict:
    from evaluate_h2l_proper import (
        build_relevance_keywords,
        compute_all_metrics,
        judge_relevance,
        load_problem_taxonomy,
        load_test_cases_from_ground_truth,
    )

    source = source.resolve()
    output_dir = output_dir.resolve()
    ground_truth = ground_truth.resolve()
    document_metadata = document_metadata.resolve()
    taxonomy_path = taxonomy_path.resolve()

    artifact = json.loads(source.read_text(encoding="utf-8"))
    ground_truth_payload = json.loads(ground_truth.read_text(encoding="utf-8"))
    ground_truth_hash = sha256(ground_truth)
    taxonomy_hash = sha256(taxonomy_path)
    document_metadata_hash = sha256(document_metadata)
    evaluation_code_hash = sha256(ROOT / "evaluate_h2l_proper.py")
    source_run_signature = artifact.get("metadata", {}).get("run_signature")
    if source_run_signature is not None:
        if not isinstance(source_run_signature, dict):
            raise ValueError("Source metadata run_signature must be an object")
        expected_signature_hashes = {
            "ground_truth_sha256": ground_truth_hash,
            "taxonomy_sha256": taxonomy_hash,
            "evaluation_code_sha256": evaluation_code_hash,
        }
        for field, expected_hash in expected_signature_hashes.items():
            reported_hash = source_run_signature.get(field)
            if reported_hash != expected_hash:
                raise ValueError(
                    f"Source run signature {field} does not match current input: "
                    f"source={reported_hash!r}, current={expected_hash!r}"
                )
    documents = json.loads(document_metadata.read_text(encoding="utf-8"))
    document_text = {int(item["doc_id"]): item["content"] for item in documents}
    test_cases = load_test_cases_from_ground_truth(str(ground_truth))
    test_case_ids = [str(case.get("case_id", "")) for case in test_cases]
    duplicate_case_ids = sorted(
        case_id for case_id, count in Counter(test_case_ids).items() if count > 1
    )
    if duplicate_case_ids:
        raise ValueError(f"Duplicate test case IDs in ground truth: {duplicate_case_ids[:5]}")
    cases = {str(case["case_id"]): case for case in test_cases}
    matrix = validate_matrix(artifact, cases, expected_case_count)
    taxonomy = load_problem_taxonomy(str(taxonomy_path))

    records: list[dict] = []
    max_existing_metric_difference = 0.0
    missing_document_ids: set[int] = set()
    for model, model_rows in artifact["per_case"].items():
        for row in model_rows:
            case = cases[row["case_id"]]
            expected = case.get("expected_diagnosis", {}).get("problem_list", [])
            relevance_keywords = build_relevance_keywords(expected, taxonomy)
            for strategy, original_metrics in row["retrieval_metrics"].items():
                grades: list[int] = []
                for raw_doc_id in original_metrics["doc_ids"]:
                    doc_id = int(raw_doc_id)
                    if doc_id not in document_text:
                        missing_document_ids.add(doc_id)
                        continue
                    grades.append(
                        judge_relevance(document_text[doc_id], relevance_keywords, expected)
                    )
                metrics = compute_all_metrics(grades, k_values=[3, 5, 10])
                for metric, value in metrics.items():
                    if metric in original_metrics:
                        max_existing_metric_difference = max(
                            max_existing_metric_difference,
                            abs(float(value) - float(original_metrics[metric])),
                        )
                records.append(
                    {
                        "model": model,
                        "repeat": int(row["repeat"]),
                        "case_id": str(row["case_id"]),
                        "complexity": case.get("complexity"),
                        "category": case.get("category"),
                        "evaluation_slice": case.get("evaluation_slice"),
                        **augmentation_fields(case),
                        "strategy": strategy,
                        **{metric: float(metrics[metric]) for metric in METRICS},
                    }
                )

    if missing_document_ids:
        raise ValueError(f"Missing document IDs: {sorted(missing_document_ids)}")
    if max_existing_metric_difference > 1e-12:
        raise ValueError(
            "Reconstructed metrics differ from the source artifact: "
            f"max_abs_difference={max_existing_metric_difference:.3e}"
        )

    frame = pd.DataFrame(records)
    unique_case_count = int(frame["case_id"].nunique())
    if unique_case_count != expected_case_count:
        raise ValueError(
            "Derived frame unique case count mismatch: "
            f"expected={expected_case_count}, actual={unique_case_count}"
        )
    aggregates = (
        frame.groupby(["model", "strategy"], sort=False)[METRICS]
        .agg(["mean", "std"])
        .reset_index()
    )
    aggregates.columns = [
        "_".join(str(part) for part in column if part).rstrip("_")
        if isinstance(column, tuple)
        else str(column)
        for column in aggregates.columns
    ]
    tests = paired_tests(frame)
    if not tests.empty and set(tests["n_pairs"]) != {expected_case_count}:
        raise ValueError(
            "Wilcoxon inputs are incomplete: "
            f"expected n_pairs={expected_case_count}, actual={sorted(set(tests['n_pairs']))}"
        )

    generated_at = datetime.now(ZoneInfo("Asia/Bangkok")).isoformat(timespec="seconds")
    source_hash = sha256(source)
    provenance = {
        "generated_at": generated_at,
        "source_path": display_path(source),
        "source_created_at": artifact["metadata"]["created_at"],
        "source_sha256": source_hash,
        "ground_truth_path": display_path(ground_truth),
        "ground_truth_sha256": ground_truth_hash,
        "ground_truth_last_updated": ground_truth_payload.get("metadata", {}).get(
            "last_updated"
        ),
        "document_metadata_path": display_path(document_metadata),
        "document_metadata_sha256": document_metadata_hash,
        "taxonomy_path": display_path(taxonomy_path),
        "taxonomy_sha256": taxonomy_hash,
        "evaluation_code_sha256": evaluation_code_hash,
        "source_run_signature": source_run_signature,
        "expected_case_count": expected_case_count,
        "unique_test_case_count": unique_case_count,
        "models": matrix["models"],
        "repeats": matrix["repeats"],
        "strategies": matrix["strategies"],
        "top_k": artifact["metadata"]["top_k"],
        "problem_source": matrix["problem_source"],
        "problem_source_provenance": matrix["problem_source_provenance"],
    }
    significance_columns = {
        "generated_at": generated_at,
        "source_path": display_path(source),
        "source_created_at": artifact["metadata"]["created_at"],
        "source_sha256": source_hash,
        "ground_truth_path": display_path(ground_truth),
        "ground_truth_sha256": ground_truth_hash,
        "document_metadata_sha256": document_metadata_hash,
        "taxonomy_sha256": taxonomy_hash,
        "evaluation_code_sha256": evaluation_code_hash,
        "expected_case_count": expected_case_count,
        "unique_test_case_count": unique_case_count,
        "repeats": matrix["repeats"],
        "top_k": artifact["metadata"]["top_k"],
        "problem_source": matrix["problem_source"],
    }
    for column, value in reversed(list(significance_columns.items())):
        tests.insert(0, column, value)

    per_case_path = (
        per_case_output.resolve()
        if per_case_output
        else output_dir / f"retrieval_metrics_{output_tag}_per_case.csv"
    )
    aggregate_path = (
        aggregate_output.resolve()
        if aggregate_output
        else output_dir / f"retrieval_metrics_{output_tag}_aggregates.csv"
    )
    tests_path = (
        significance_output.resolve()
        if significance_output
        else output_dir / f"retrieval_significance_{output_tag}.csv"
    )
    json_path = (
        json_output.resolve()
        if json_output
        else output_dir / f"retrieval_metrics_{output_tag}_latest.json"
    )
    for path in (per_case_path, aggregate_path, tests_path, json_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(per_case_path, index=False)
    aggregates.to_csv(aggregate_path, index=False)
    tests.to_csv(tests_path, index=False)

    evaluation_slice_counts = Counter(
        case.get("evaluation_slice") or "standard_test" for case in cases.values()
    )
    augmentation_type_counts = Counter(
        case_augmentation_type(case) for case in cases.values()
    )

    result = {
        "metadata": {
            **provenance,
            "test_cases": unique_case_count,
            "evaluation_slice_counts": dict(sorted(evaluation_slice_counts.items())),
            "augmentation_type_counts": dict(sorted(augmentation_type_counts.items())),
            "relevance_reconstruction_verified": True,
            "max_existing_metric_difference": max_existing_metric_difference,
            "significance_unit": (
                f"per-case mean across {matrix['repeats']} repeats "
                f"(n={unique_case_count})"
            ),
            "significance_test": "paired two-sided Wilcoxon signed-rank",
            "multiplicity_correction": "Holm, applied separately to nDCG@5 and nDCG@10",
        },
        "metrics": METRICS,
        "aggregates": aggregates.to_dict(orient="records"),
        "paired_tests": tests.to_dict(orient="records"),
        "files": {
            "per_case": display_path(per_case_path),
            "aggregates": display_path(aggregate_path),
            "paired_tests": display_path(tests_path),
            "json": display_path(json_path),
        },
    }
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--ground-truth", type=Path, default=DEFAULT_GROUND_TRUTH)
    parser.add_argument(
        "--document-metadata",
        type=Path,
        default=DEFAULT_DOCUMENT_METADATA,
    )
    parser.add_argument("--taxonomy", type=Path, default=DEFAULT_TAXONOMY)
    parser.add_argument(
        "--expected-case-count",
        type=int,
        default=DEFAULT_EXPECTED_CASE_COUNT,
    )
    parser.add_argument("--output-tag", default=DEFAULT_OUTPUT_TAG)
    parser.add_argument("--per-case-output", type=Path)
    parser.add_argument("--aggregate-output", type=Path)
    parser.add_argument("--significance-output", type=Path)
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args()
    result = derive(
        args.source,
        args.output_dir,
        ground_truth=args.ground_truth,
        document_metadata=args.document_metadata,
        taxonomy_path=args.taxonomy,
        expected_case_count=args.expected_case_count,
        output_tag=args.output_tag,
        per_case_output=args.per_case_output,
        aggregate_output=args.aggregate_output,
        significance_output=args.significance_output,
        json_output=args.json_output,
    )
    print(json.dumps(result["metadata"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

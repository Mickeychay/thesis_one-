#!/usr/bin/env python3
"""Build Chapter 4 from a mutually consistent set of final experiment artifacts.

The default mode is deliberately fail-closed: no report is written unless every
artifact describes the same 220/125/95 dataset, the 20-case adversarial slice,
and the complete experimental matrices.  ``--schema-only`` is a read-only
compatibility check for older artifacts and never writes thesis output.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
BANGKOK_TZ = ZoneInfo("Asia/Bangkok")
THAI_MONTHS = (
    "",
    "มกราคม",
    "กุมภาพันธ์",
    "มีนาคม",
    "เมษายน",
    "พฤษภาคม",
    "มิถุนายน",
    "กรกฎาคม",
    "สิงหาคม",
    "กันยายน",
    "ตุลาคม",
    "พฤศจิกายน",
    "ธันวาคม",
)
DEFAULT_MATRIX = ROOT / "evaluation_results/model_comparison/l2_full_matrix_95cases_3models_3repeats_8strategies.json"
DEFAULT_GROUND_TRUTH_AUDIT = ROOT / "evaluation_results/ground_truth_audit.json"
DEFAULT_RETRIEVAL_JSON = ROOT / "evaluation_results/derived/retrieval_metrics_20260807_latest.json"
DEFAULT_RETRIEVAL_PER_CASE = ROOT / "evaluation_results/derived/retrieval_metrics_20260807_per_case.csv"
DEFAULT_RETRIEVAL_SIGNIFICANCE = ROOT / "evaluation_results/derived/retrieval_significance_20260807.csv"
DEFAULT_POLARITY = ROOT / "evaluation_results/sentence_polarity_eval_20260807_full95.json"
DEFAULT_ADVERSARIAL_STRESS = ROOT / "evaluation_results/adversarial_stress_test_20260807.json"
DEFAULT_ABLATION_DIR = ROOT / "ablation_results/rq6_test_95cases_20260807"
DEFAULT_SENSITIVITY_DIR = ROOT / "sensitivity_results/run_20260807"
DEFAULT_OUTPUT = ROOT / "md_report/thesis_ch4_verified_20260807.md"
DEFAULT_MANIFEST = ROOT / "evaluation_results/chapter4_artifact_manifest_20260807.json"
MODEL_PATCH_MANIFEST = ROOT / "evaluation_results/model_comparison/typhoon_gemma3_templatefix_manifest.json"
PRIMARY_MODEL = "qwen2.5:7b"
PRIMARY_STRATEGY = "h2l-hybrid"
EXPECTED_MODELS = [
    "qwen2.5:7b",
    "scb10x/llama3.1-typhoon2-8b-instruct:latest",
    "h2l/typhoon-gemma3-4b-templatefix-v2:latest",
]
EXPECTED_STRATEGIES = [
    "bm25_only",
    "naive_rag",
    "hyde",
    "basic",
    "h2l-bm25",
    "h2l-naive_rag",
    "h2l-hyde",
    "h2l-hybrid",
]
EXPECTED_VARIANTS = [
    "Full V6",
    "w/o Adaptive Alpha",
    "w/o Bayesian Prior",
    "w/o IDF Specificity",
    "w/o KL Penalty",
    "w/o Margin Activation",
    "w/o Negation Gate",
    "Product Feature Mode",
]


@dataclass(frozen=True)
class EvidencePaths:
    ground_truth: Path
    ground_truth_audit: Path
    taxonomy: Path
    document_metadata: Path
    matrix: Path
    retrieval_json: Path
    retrieval_per_case: Path
    retrieval_significance: Path
    polarity: Path
    adversarial_stress: Path
    ablation_dir: Path
    sensitivity_dir: Path
    output: Path
    manifest: Path

    @property
    def ablation_results(self) -> Path:
        return self.ablation_dir / "rq6_results.csv"

    @property
    def ablation_significance(self) -> Path:
        return self.ablation_dir / "rq6_significance.csv"

    @property
    def ablation_slices(self) -> Path:
        return self.ablation_dir / "rq6_slice_summary.csv"

    @property
    def ablation_metadata(self) -> Path:
        return self.ablation_dir / "run_metadata.json"

    @property
    def sensitivity_raw(self) -> Path:
        return self.sensitivity_dir / "sensitivity_raw.csv"

    @property
    def sensitivity_metadata(self) -> Path:
        return self.sensitivity_dir / "run_metadata.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path.resolve())


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def load_json(path: Path) -> dict[str, Any]:
    require(path.is_file(), f"Required JSON artifact is missing: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"JSON root must be an object: {path}")
    return value


def parse_artifact_timestamp(value: Any, label: str) -> datetime:
    require(isinstance(value, str) and value.strip(), f"Missing artifact timestamp: {label}")
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"Invalid artifact timestamp for {label}: {value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=BANGKOK_TZ)
    return parsed.astimezone(BANGKOK_TZ)


def thai_calendar_date(value: datetime) -> str:
    local = value.astimezone(BANGKOK_TZ)
    return f"{local.day} {THAI_MONTHS[local.month]} {local.year + 543}"


def artifact_provenance_window(
    matrix_metadata: dict[str, Any],
    retrieval_metadata: dict[str, Any],
    polarity_metadata: dict[str, Any],
    adversarial_metadata: dict[str, Any],
    ablation_metadata: dict[str, Any],
    sensitivity_metadata: dict[str, Any],
) -> dict[str, Any]:
    """Normalize the final artifact timestamps into one auditable Bangkok-time window."""
    timestamp_fields = (
        ("L2/retrieval matrix", "created_at", matrix_metadata.get("created_at")),
        ("Derived retrieval metrics", "generated_at", retrieval_metadata.get("generated_at")),
        ("Contextual polarity", "timestamp", polarity_metadata.get("timestamp")),
        ("Adversarial stress-test summary", "generated_at", adversarial_metadata.get("generated_at")),
        ("RQ6 ablation", "completed_at", ablation_metadata.get("completed_at")),
        ("Parameter sensitivity", "completed_at", sensitivity_metadata.get("completed_at")),
    )
    events = []
    for artifact, field, raw_value in timestamp_fields:
        parsed = parse_artifact_timestamp(raw_value, f"{artifact}.{field}")
        events.append({
            "artifact": artifact,
            "field": field,
            "reported_at": raw_value,
            "bangkok_at": parsed.isoformat(timespec="seconds"),
            "_parsed": parsed,
        })

    started_at = min(event["_parsed"] for event in events)
    completed_at = max(event["_parsed"] for event in events)
    public_events = [
        {key: value for key, value in event.items() if key != "_parsed"}
        for event in events
    ]
    return {
        "timezone": "Asia/Bangkok",
        "started_at": started_at.isoformat(timespec="seconds"),
        "completed_at": completed_at.isoformat(timespec="seconds"),
        "started_date_th": thai_calendar_date(started_at),
        "completed_date_th": thai_calendar_date(completed_at),
        "events": public_events,
    }


def artifact_date_statement(window: dict[str, Any]) -> str:
    start_date = str(window["started_date_th"])
    completion_date = str(window["completed_date_th"])
    if start_date == completion_date:
        return f"artifact ทั้งหมดสร้างและสรุปผลเมื่อวันที่ {completion_date}"
    return (
        f"การรันและสร้าง artifact เริ่มเมื่อวันที่ {start_date} "
        f"และสรุปผลครบเมื่อวันที่ {completion_date}"
    )


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def expected_codes(case: dict[str, Any]) -> list[str]:
    return [
        str(problem["code"])
        for problem in case.get("expected_diagnosis", {}).get("problem_list", [])
        if problem.get("code")
    ]


def normalized_slice(value: Any) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)) or not str(value).strip():
        return "standard_test"
    return str(value)


def as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return bool(value)


def validate_ground_truth(payload: dict[str, Any]) -> dict[str, Any]:
    cases = payload.get("cases")
    require(isinstance(cases, list), "Ground truth must contain a cases array")
    ids = [str(case.get("case_id", "")) for case in cases]
    require(all(ids), "Every ground-truth case must have a case_id")
    require(len(ids) == len(set(ids)), "Ground truth contains duplicate case IDs")

    split_counts = Counter(str(case.get("split")) for case in cases)
    test_cases = [case for case in cases if case.get("split") == "test"]
    train_cases = [case for case in cases if case.get("split") == "train"]
    slice_counts = Counter(normalized_slice(case.get("evaluation_slice")) for case in test_cases)
    require(len(cases) == 220, f"Expected 220 total cases, found {len(cases)}")
    require(split_counts == Counter({"train": 125, "test": 95}), f"Unexpected split counts: {dict(split_counts)}")
    require(slice_counts == Counter({"standard_test": 75, "adversarial_test": 20}), f"Unexpected test slices: {dict(slice_counts)}")

    metadata = payload.get("metadata", {})
    for field, expected in (
        ("total_cases", 220),
        ("train_cases", 125),
        ("test_cases", 95),
        ("adversarial_test_cases", 20),
    ):
        if field in metadata:
            require(int(metadata[field]) == expected, f"Ground-truth metadata {field}={metadata[field]}, expected {expected}")
    require(
        metadata.get("split_method") == "family_level_stratified_by_category",
        "Ground-truth split_method is not the final family-level stratified protocol",
    )
    require(int(metadata.get("split_seed", -1)) == 42, "Ground-truth split_seed must be 42")
    require(
        abs(float(metadata.get("near_duplicate_resolution_threshold", -1.0)) - 0.90) <= 1e-12,
        "Ground-truth near-duplicate threshold must be 0.90",
    )

    train_empty = [case["case_id"] for case in train_cases if not expected_codes(case)]
    return {
        "cases": cases,
        "case_by_id": {str(case["case_id"]): case for case in cases},
        "test_cases": test_cases,
        "test_ids": {str(case["case_id"]) for case in test_cases},
        "train_cases": train_cases,
        "train_empty_problem_lists": train_empty,
        "split_counts": dict(split_counts),
        "slice_counts": dict(slice_counts),
    }


def validate_ground_truth_audit(
    audit: dict[str, Any],
    ground_truth: dict[str, Any],
) -> dict[str, Any]:
    expected_augmentation_counts = {
        "original": 100,
        "paraphrase": 44,
        "complexity_escalation": 10,
        "complexity_reduction": 10,
        "adversarial": 20,
        "polarity": 36,
    }
    require(int(audit.get("total_cases", 0)) == 220, "Ground-truth audit must contain 220 cases")
    require(audit.get("split_counts") == {"train": 125, "test": 95}, "Ground-truth audit split counts are invalid")
    require(audit.get("augmentation_counts") == expected_augmentation_counts, "Ground-truth audit augmentation counts are invalid")
    require(sum(expected_augmentation_counts.values()) == 220, "Ground-truth audit augmentation classes must be exhaustive")

    actual_augmentation_counts = Counter()
    actual_split_by_augmentation: dict[str, Counter] = {}
    for case in ground_truth["cases"]:
        case_id = str(case.get("case_id", ""))
        augmentation = case.get("augmentation")
        if case_id.startswith("NEG_"):
            augmentation_type = "polarity"
        elif "_PAR_" in case_id:
            augmentation_type = "paraphrase"
        elif "_ESC_" in case_id:
            augmentation_type = "complexity_escalation"
        elif "_SIM_" in case_id:
            augmentation_type = "complexity_reduction"
        elif case_id.startswith("ADV_"):
            augmentation_type = "adversarial"
        elif isinstance(augmentation, dict) and augmentation.get("type"):
            augmentation_type = str(augmentation["type"])
        else:
            augmentation_type = str(case.get("augmentation_type") or "original")
        actual_augmentation_counts[augmentation_type] += 1
        actual_split_by_augmentation.setdefault(augmentation_type, Counter())[str(case.get("split"))] += 1
    require(dict(actual_augmentation_counts) == expected_augmentation_counts, "Ground-truth audit augmentation counts differ from the dataset")

    reported_split_by_augmentation = audit.get("split_by_augmentation")
    require(isinstance(reported_split_by_augmentation, dict), "Ground-truth audit split_by_augmentation is missing")
    normalized_reported = {
        str(name): {str(split): int(count) for split, count in counts.items()}
        for name, counts in reported_split_by_augmentation.items()
    }
    normalized_actual = {
        name: dict(counts)
        for name, counts in actual_split_by_augmentation.items()
    }
    require(normalized_reported == normalized_actual, "Ground-truth audit split-by-augmentation counts differ from the dataset")

    for field in ("missing_split", "cross_split_families", "exact_duplicates", "near_duplicates"):
        require(audit.get(field) == [], f"Ground-truth audit {field} must be empty")
    require(math.isclose(float(audit.get("duplicate_threshold", -1)), 0.90, abs_tol=1e-12), "Ground-truth audit duplicate threshold must be 0.90")
    return {
        "original_non_augmented_cases": expected_augmentation_counts["original"],
        "generated_modified_cases": 220 - expected_augmentation_counts["original"],
        "family_leakage_count": len(audit["cross_split_families"]),
        "exact_duplicate_count": len(audit["exact_duplicates"]),
        "cross_split_near_duplicate_count": len(audit["near_duplicates"]),
        "near_duplicate_threshold": float(audit["duplicate_threshold"]),
        "augmentation_counts": expected_augmentation_counts,
    }


def validate_matrix(
    artifact: dict[str, Any],
    ground_truth: dict[str, Any],
    paths: EvidencePaths,
) -> dict[str, Any]:
    metadata = artifact.get("metadata")
    per_case = artifact.get("per_case")
    require(isinstance(metadata, dict) and isinstance(per_case, dict), "Matrix requires metadata and per_case objects")
    require(int(metadata.get("test_cases", 0)) == 95, "Matrix must contain 95 test cases")
    require(int(metadata.get("repeats", 0)) == 3, "Matrix must contain 3 repeats")
    require(metadata.get("models") == EXPECTED_MODELS, "Matrix model order/content is not the final protocol")
    require(metadata.get("retrieval_strategies") == EXPECTED_STRATEGIES, "Matrix strategy order/content is not the final protocol")
    require(int(metadata.get("top_k", 0)) == 15, "Matrix top_k must be 15")
    require(metadata.get("problem_source") == "detected", "Matrix must use detected problems")

    signature = metadata.get("run_signature")
    require(isinstance(signature, dict), "Final matrix must contain a run_signature")
    expected_hashes = {
        "ground_truth_sha256": sha256(paths.ground_truth),
        "taxonomy_sha256": sha256(paths.taxonomy),
        "detector_code_sha256": sha256(ROOT / "detector.py"),
        "h2l_core_sha256": sha256(ROOT / "core.py"),
        "evaluation_code_sha256": sha256(ROOT / "evaluate_h2l_proper.py"),
        "config_code_sha256": sha256(ROOT / "config.py"),
        "retrieval_engine_sha256": sha256(ROOT / "retriever.py"),
        "unified_baselines_sha256": sha256(ROOT / "unified_baselines.py"),
        "metadata_store_sha256": sha256(paths.document_metadata),
    }
    for field, expected in expected_hashes.items():
        require(signature.get(field) == expected, f"Matrix signature mismatch for {field}")

    patch_manifest = load_json(MODEL_PATCH_MANIFEST)
    require(patch_manifest.get("status") == "complete", "Typhoon-Gemma patch manifest is incomplete")
    patch_provenance = signature.get("model_patch_provenance", {}).get(EXPECTED_MODELS[2])
    require(isinstance(patch_provenance, dict), "Matrix signature is missing Typhoon-Gemma patch provenance")
    require(
        patch_provenance.get("manifest_sha256") == sha256(MODEL_PATCH_MANIFEST),
        "Matrix Typhoon-Gemma patch manifest hash mismatch",
    )
    for field in (
        "patched_file_sha256",
        "original_template_sha256",
        "replacement_template_sha256",
        "metadata_key",
    ):
        require(
            patch_provenance.get(field) == patch_manifest.get(field),
            f"Matrix Typhoon-Gemma patch provenance mismatch for {field}",
        )

    test_case_by_id = {str(case["case_id"]): case for case in ground_truth["test_cases"]}
    expected_keys = {(case_id, repeat) for case_id in ground_truth["test_ids"] for repeat in range(1, 4)}
    rows_by_model: dict[str, list[dict[str, Any]]] = {}
    for model in EXPECTED_MODELS:
        rows = per_case.get(model)
        require(isinstance(rows, list), f"Matrix rows missing for model {model}")
        keys = [(str(row.get("case_id", "")), int(row.get("repeat", 0) or 0)) for row in rows]
        require(len(keys) == 285 and set(keys) == expected_keys and len(keys) == len(set(keys)), f"Incomplete or duplicate matrix rows for {model}")
        for row in rows:
            case_id = str(row["case_id"])
            require(row.get("expected_codes", []) == expected_codes(test_case_by_id[case_id]), f"Matrix expected codes changed for {case_id}")
            retrieval = row.get("retrieval_metrics")
            require(isinstance(retrieval, dict) and set(retrieval) == set(EXPECTED_STRATEGIES), f"Incomplete retrieval metrics for {model}/{case_id}")
            require(all(isinstance(retrieval[name].get("doc_ids"), list) for name in EXPECTED_STRATEGIES), f"Missing ranked documents for {model}/{case_id}")
        rows_by_model[model] = rows

    slices = Counter(normalized_slice(case.get("evaluation_slice")) for case in ground_truth["test_cases"])
    reported_slices = metadata.get("evaluation_slices", {})
    require(reported_slices == dict(slices), f"Matrix slice counts differ from ground truth: {reported_slices}")
    return {
        "metadata": metadata,
        "rows_by_model": rows_by_model,
        "degraded": {model: sum(bool(row.get("l2_degraded")) for row in rows) for model, rows in rows_by_model.items()},
    }


def validate_retrieval(
    artifact: dict[str, Any],
    frame: pd.DataFrame,
    significance: pd.DataFrame,
    paths: EvidencePaths,
    matrix_hash: str,
) -> dict[str, Any]:
    metadata = artifact.get("metadata")
    require(isinstance(metadata, dict), "Retrieval artifact requires metadata")
    require(int(metadata.get("test_cases", 0)) == 95, "Retrieval artifact must contain 95 test cases")
    require(int(metadata.get("repeats", 0)) == 3, "Retrieval artifact must use 3 repeats")
    require(metadata.get("models") == EXPECTED_MODELS, "Retrieval model set differs from matrix")
    require(metadata.get("strategies") == EXPECTED_STRATEGIES, "Retrieval strategies differ from matrix")
    require(metadata.get("source_sha256") == matrix_hash, "Retrieval artifact source hash differs from matrix")
    require(metadata.get("ground_truth_sha256") == sha256(paths.ground_truth), "Retrieval ground-truth hash mismatch")
    require(metadata.get("taxonomy_sha256") == sha256(paths.taxonomy), "Retrieval taxonomy hash mismatch")
    require(metadata.get("document_metadata_sha256") == sha256(paths.document_metadata), "Retrieval document hash mismatch")
    require(metadata.get("relevance_reconstruction_verified") is True, "Retrieval relevance reconstruction was not verified")
    require(float(metadata.get("max_existing_metric_difference", 1.0)) <= 1e-12, "Reconstructed metrics differ from matrix")

    required_columns = {"model", "repeat", "case_id", "complexity", "evaluation_slice", "strategy", "nDCG@5", "nDCG@10", "MAP", "MRR"}
    require(required_columns.issubset(frame.columns), f"Retrieval per-case CSV is missing columns: {sorted(required_columns - set(frame.columns))}")
    require(len(frame) == 3 * 3 * 95 * 8, f"Expected 6840 retrieval rows, found {len(frame)}")
    require(frame["case_id"].nunique() == 95, "Retrieval per-case CSV must contain 95 unique cases")
    keys = frame[["model", "repeat", "case_id", "strategy"]].astype(str).agg("|".join, axis=1)
    require(keys.nunique() == len(frame), "Retrieval per-case CSV contains duplicate matrix cells")
    frame = frame.copy()
    frame["evaluation_slice"] = frame["evaluation_slice"].map(normalized_slice)
    slice_case_counts = frame.groupby("evaluation_slice")["case_id"].nunique().to_dict()
    require(slice_case_counts == {"adversarial_test": 20, "standard_test": 75}, f"Retrieval slice counts are invalid: {slice_case_counts}")

    require(len(artifact.get("aggregates", [])) == 24, "Retrieval artifact must have 24 model-strategy aggregate rows")
    require(len(artifact.get("paired_tests", [])) == 14, "Retrieval artifact must have 14 paired tests")
    require(len(significance) == 14, "Retrieval significance CSV must have 14 rows")
    require(set(significance["metric"]) == {"nDCG@5", "nDCG@10"}, "Retrieval significance families are invalid")
    require(set(significance["n_pairs"].astype(int)) == {95}, "Retrieval Wilcoxon tests must use 95 paired cases")
    require(set(significance["holm_family_size"].astype(int)) == {7}, "Each retrieval Holm family must contain 7 comparisons")
    require(set(significance["source_sha256"].astype(str)) == {matrix_hash}, "Significance source hashes differ from matrix")
    return {"metadata": metadata, "frame": frame, "significance": significance}


def validate_polarity(
    artifact: dict[str, Any],
    ground_truth: dict[str, Any],
) -> dict[str, Any]:
    metadata = artifact.get("metadata", {})
    overall = artifact.get("overall", {})
    rows = artifact.get("per_case")
    require(int(metadata.get("total_polarity_cases", 0)) == 95, "Polarity artifact must contain 95 cases")
    require(isinstance(rows, list) and len(rows) == 95, "Polarity per_case must contain 95 rows")
    require({str(row.get("case_id")) for row in rows} == ground_truth["test_ids"], "Polarity case IDs differ from the test split")
    require(int(overall.get("total_cases", 0)) == 95, "Polarity overall total must be 95")
    require(int(overall.get("n_positive", 0)) + int(overall.get("n_negated", 0)) == 95, "Polarity class counts do not sum to 95")
    adversarial = artifact.get("slice_summaries", {}).get("adversarial_test")
    require(isinstance(adversarial, dict) and int(adversarial.get("n_cases", 0)) == 20, "Polarity adversarial summary must contain 20 cases")
    require(int(adversarial.get("false_trigger_evaluated_count", 0)) == 20, "All adversarial false triggers must be evaluated")
    return {"metadata": metadata, "overall": overall, "rows": rows, "adversarial": adversarial}


def validate_adversarial_stress(
    artifact: dict[str, Any],
    ground_truth: dict[str, Any],
    matrix: dict[str, Any],
    retrieval: dict[str, Any],
    paths: EvidencePaths,
    matrix_hash: str,
) -> dict[str, Any]:
    """Verify the standalone stress-test summary against its primary artifacts."""
    require(artifact.get("status") == "complete", "Adversarial stress-test status must be complete")
    metadata = artifact.get("metadata")
    require(isinstance(metadata, dict), "Adversarial stress-test metadata must be an object")
    require(metadata.get("artifact_type") == "adversarial_stress_test_slice", "Unexpected adversarial artifact type")
    require(metadata.get("validation") == "complete_matrix_schema_and_provenance_verified", "Adversarial matrix validation is incomplete")
    require(metadata.get("matrix_sha256") == matrix_hash, "Adversarial summary matrix hash mismatch")
    require(metadata.get("ground_truth_sha256") == sha256(paths.ground_truth), "Adversarial summary ground-truth hash mismatch")
    require(metadata.get("taxonomy_sha256") == sha256(paths.taxonomy), "Adversarial summary taxonomy hash mismatch")
    require(metadata.get("h2l_core_sha256") == sha256(ROOT / "core.py"), "Adversarial summary H2L core hash mismatch")
    require(metadata.get("evaluation_code_sha256") == sha256(ROOT / "evaluate_h2l_proper.py"), "Adversarial summary evaluator hash mismatch")
    require(int(metadata.get("n_test_cases", 0)) == 95, "Adversarial summary must originate from 95 test cases")
    require(int(metadata.get("n_adversarial_cases", 0)) == 20, "Adversarial summary must contain 20 cases")
    require(int(metadata.get("n_cases", 0)) == 20, "Adversarial summary n_cases must equal 20")
    require(metadata.get("models") == EXPECTED_MODELS, "Adversarial summary model set differs from final protocol")
    require(int(metadata.get("repeats", 0)) == 3, "Adversarial summary must use 3 repeats")
    require(metadata.get("strategies") == EXPECTED_STRATEGIES, "Adversarial summary strategies differ from final protocol")
    require(int(metadata.get("top_k", 0)) == 15, "Adversarial summary top_k must be 15")
    require(metadata.get("problem_source") == "detected", "Adversarial summary must use detected problems")
    require(metadata.get("matrix_run_signature") == matrix["metadata"].get("run_signature"), "Adversarial summary matrix signature mismatch")

    adversarial_cases = {
        str(case["case_id"]): case
        for case in ground_truth["test_cases"]
        if normalized_slice(case.get("evaluation_slice")) == "adversarial_test"
    }
    per_case = artifact.get("per_case")
    require(isinstance(per_case, list) and len(per_case) == 20, "Adversarial summary per_case must contain 20 rows")
    case_ids = [str(row.get("case_id", "")) for row in per_case]
    require(len(case_ids) == len(set(case_ids)), "Adversarial summary contains duplicate case IDs")
    require(set(case_ids) == set(adversarial_cases), "Adversarial summary case IDs differ from ground truth")

    metric_names = ("nDCG@5", "nDCG@10", "MAP", "MRR")
    frame = retrieval["frame"]
    selected = frame[frame["evaluation_slice"].map(normalized_slice) == "adversarial_test"]
    case_means = selected.groupby(["case_id", "model", "strategy"], as_index=False)[list(metric_names)].mean()
    case_lookup = {
        (str(row["case_id"]), str(row["model"]), str(row["strategy"])): row
        for _, row in case_means.iterrows()
    }
    expected_case_cells = 20 * len(EXPECTED_MODELS) * len(EXPECTED_STRATEGIES)
    require(len(case_lookup) == expected_case_cells, f"Expected {expected_case_cells} adversarial retrieval cells")

    max_case_difference = 0.0
    for summary in per_case:
        case_id = str(summary["case_id"])
        case = adversarial_cases[case_id]
        require(list(summary.get("target_codes", [])) == expected_codes(case), f"Adversarial target codes differ for {case_id}")
        require(summary.get("false_trigger_code") == case["augmentation"]["false_trigger_code"], f"Adversarial false-trigger code differs for {case_id}")
        model_map = summary.get("retrieval_by_model_strategy")
        require(isinstance(model_map, dict) and set(model_map) == set(EXPECTED_MODELS), f"Incomplete adversarial model map for {case_id}")
        for model in EXPECTED_MODELS:
            strategy_map = model_map[model]
            require(isinstance(strategy_map, dict) and set(strategy_map) == set(EXPECTED_STRATEGIES), f"Incomplete adversarial strategies for {model}/{case_id}")
            for strategy in EXPECTED_STRATEGIES:
                reported = strategy_map[strategy]
                require(int(reported.get("n_rows", 0)) == 3, f"Adversarial case summary must average 3 repeats for {model}/{case_id}/{strategy}")
                derived = case_lookup[(case_id, model, strategy)]
                for metric in metric_names:
                    difference = abs(float(reported[metric]) - float(derived[metric]))
                    max_case_difference = max(max_case_difference, difference)
    require(max_case_difference <= 1e-12, f"Adversarial case-first retrieval mismatch: {max_case_difference:.3e}")

    aggregate_map = artifact.get("retrieval_by_model_strategy")
    require(isinstance(aggregate_map, dict) and set(aggregate_map) == set(EXPECTED_MODELS), "Incomplete adversarial retrieval aggregates")
    derived_aggregates = case_means.groupby(["model", "strategy"], as_index=False)[list(metric_names)].mean()
    aggregate_lookup = {
        (str(row["model"]), str(row["strategy"])): row
        for _, row in derived_aggregates.iterrows()
    }
    max_aggregate_difference = 0.0
    for model in EXPECTED_MODELS:
        require(set(aggregate_map[model]) == set(EXPECTED_STRATEGIES), f"Incomplete adversarial aggregate strategies for {model}")
        for strategy in EXPECTED_STRATEGIES:
            reported = aggregate_map[model][strategy]
            require(int(reported.get("n_unique_cases", 0)) == 20, f"Adversarial aggregate must contain 20 cases for {model}/{strategy}")
            require(int(reported.get("n_rows", 0)) == 60, f"Adversarial aggregate must contain 60 rows for {model}/{strategy}")
            require(reported.get("repeats_per_case") == [3], f"Adversarial aggregate repeat count mismatch for {model}/{strategy}")
            derived = aggregate_lookup[(model, strategy)]
            for metric in metric_names:
                difference = abs(float(reported[metric]) - float(derived[metric]))
                max_aggregate_difference = max(max_aggregate_difference, difference)
    require(max_aggregate_difference <= 1e-12, f"Adversarial aggregate retrieval mismatch: {max_aggregate_difference:.3e}")

    detector_map = artifact.get("detector_by_model")
    require(isinstance(detector_map, dict) and set(detector_map) == set(EXPECTED_MODELS), "Incomplete adversarial detector summary")
    detector_primary = {row["model"]: row for row in l2_slice_summary(matrix, "adversarial_test")}
    for model in EXPECTED_MODELS:
        reported = detector_map[model]
        derived = detector_primary[model]
        require(int(reported.get("n_rows", 0)) == 60 and int(reported.get("n_unique_cases", 0)) == 20, f"Adversarial detector counts differ for {model}")
        for reported_field, derived_field in (
            ("complete_target_preservation_rate", "target_preservation_rate"),
            ("false_trigger_suppression_rate", "false_trigger_suppression_rate"),
            ("joint_pass_rate", "joint_pass_rate"),
        ):
            require(
                abs(float(reported[reported_field]) - float(derived[derived_field])) <= 1e-12,
                f"Adversarial detector {reported_field} differs for {model}",
            )
        require(int(reported.get("l2_degraded_rows", -1)) == int(derived["degraded"]), f"Adversarial degraded count differs for {model}")

    overall = artifact.get("detector_overall")
    require(isinstance(overall, dict) and int(overall.get("n_rows", 0)) == 180, "Adversarial detector overall must contain 180 model-repeat rows")
    require(int(overall.get("n_unique_cases", 0)) == 20, "Adversarial detector overall must contain 20 unique cases")
    return {
        "metadata": metadata,
        "max_case_first_retrieval_difference": max_case_difference,
        "max_aggregate_retrieval_difference": max_aggregate_difference,
    }


def validate_ablation(
    metadata: dict[str, Any],
    frame: pd.DataFrame,
    significance: pd.DataFrame,
    slices: pd.DataFrame,
    paths: EvidencePaths,
    matrix_hash: str,
) -> dict[str, Any]:
    require(metadata.get("status") == "complete", "Ablation run_metadata status must be complete")
    require(metadata.get("split") == "test", "Ablation must use the test split")
    require(int(metadata.get("available_cases_after_filter", 0)) == 95, "Ablation must contain 95 cases")
    require(metadata.get("max_cases") is None, "Final ablation must not use max_cases")
    require(int(metadata.get("top_k", 0)) == 15, "Ablation top_k must be 15")
    require(metadata.get("rq_filter") == [6], "Final ablation must be an RQ6-only run")
    require(metadata.get("ground_truth_sha256") == sha256(paths.ground_truth), "Ablation ground-truth hash mismatch")
    cache = metadata.get("detected_problems_cache", {})
    require(cache.get("sha256") == matrix_hash, "Ablation detector cache hash differs from final matrix")
    require(cache.get("selected_model") == PRIMARY_MODEL and int(cache.get("selected_repeat", 0)) == 1, "Ablation cache selection is not Qwen repeat 1")

    required = {"variant", "case_id", "evaluation_slice", "nDCG@5", "nDCG@10", "MAP", "MRR"}
    require(required.issubset(frame.columns), f"Ablation CSV is missing columns: {sorted(required - set(frame.columns))}")
    require(len(frame) == 760, f"Expected 760 RQ6 rows, found {len(frame)}")
    require(set(frame["variant"]) == set(EXPECTED_VARIANTS), "Ablation variants differ from the final protocol")
    require(frame["case_id"].nunique() == 95, "Ablation must contain 95 unique cases")
    require(frame.groupby("case_id")["variant"].nunique().eq(8).all(), "Each ablation case must contain all 8 variants")
    normalized = frame["evaluation_slice"].map(normalized_slice)
    slice_rows = Counter(normalized)
    require(slice_rows == Counter({"standard_test": 600, "adversarial_test": 160}), f"Ablation slice rows are invalid: {dict(slice_rows)}")

    for cutoff in (5, 10):
        dcg = frame[f"DCG@{cutoff}"].astype(float)
        idcg = frame[f"IDCG@{cutoff}"].astype(float)
        expected_ndcg = dcg.where(idcg == 0, dcg / idcg).where(idcg != 0, 0.0)
        error = (expected_ndcg - frame[f"nDCG@{cutoff}"].astype(float)).abs().max()
        require(float(error) <= 1e-12, f"Ablation nDCG identity failed at cutoff {cutoff}")

    require(len(significance) == 14, "Ablation significance CSV must contain 14 rows")
    require(set(significance["metric"]) == {"nDCG@5", "nDCG@10"}, "Ablation significance metrics are invalid")
    require(set(significance["n_pairs"].astype(int)) == {95}, "Ablation Wilcoxon tests must use 95 pairs")
    require(set(significance["multiplicity_correction"]) == {"Holm-Bonferroni"}, "Ablation statistics must use Holm-Bonferroni")
    expected_slice_rows = {("all_test", 95), ("standard_test", 75), ("adversarial_test", 20)}
    actual_slice_rows = set(zip(slices["evaluation_slice"], slices["n_cases"].astype(int)))
    require(expected_slice_rows.issubset(actual_slice_rows), f"Ablation slice summary is incomplete: {actual_slice_rows}")
    return {"metadata": metadata, "frame": frame.assign(evaluation_slice=normalized), "significance": significance, "slices": slices}


def validate_sensitivity(
    metadata: dict[str, Any],
    frame: pd.DataFrame,
    paths: EvidencePaths,
    ground_truth: dict[str, Any],
) -> dict[str, Any]:
    require(metadata.get("status") == "complete", "Sensitivity run_metadata status must be complete")
    require(metadata.get("analysis_scope") == "score_function_oat", "Sensitivity analysis_scope must be score_function_oat")
    require(metadata.get("split") == "train", "Sensitivity analysis must use the train split")
    require(int(metadata.get("selected_cases", 0)) == 125, "Sensitivity must select 125 train cases")
    require(int(metadata.get("scored_cases", 0)) == 115, "Sensitivity must score 115 non-empty train cases")
    require(int(metadata.get("skipped_empty_problem_lists", 0)) == 10, "Sensitivity must disclose 10 empty problem lists")
    require(metadata.get("ground_truth_sha256") == sha256(paths.ground_truth), "Sensitivity ground-truth hash mismatch")
    require(metadata.get("h2l_core_sha256") == sha256(ROOT / "core.py"), "Sensitivity H2L core hash mismatch")
    require(set(metadata.get("skipped_case_ids", [])) == set(ground_truth["train_empty_problem_lists"]), "Sensitivity skipped IDs differ from ground truth")
    scoring_assumptions = metadata.get("scoring_assumptions")
    require(isinstance(scoring_assumptions, dict), "Sensitivity scoring_assumptions must be an object")
    require(scoring_assumptions.get("retrieval_executed") is False, "Sensitivity must disclose retrieval_executed=false")
    not_exercised = scoring_assumptions.get("not_exercised_parameters")
    require(isinstance(not_exercised, dict), "Sensitivity must disclose not_exercised_parameters")
    require(
        set(not_exercised) == {"MARGIN_M", "L1_WEIGHT_BETA"},
        "Sensitivity not_exercised_parameters must identify MARGIN_M and L1_WEIGHT_BETA",
    )
    require(
        all(isinstance(reason, str) and reason.strip() for reason in not_exercised.values()),
        "Every non-exercised sensitivity parameter must include a reason",
    )
    required = {"parameter", "label", "value", "is_default", "mean_score", "delta_score_pct", "n_scored"}
    require(required.issubset(frame.columns), f"Sensitivity CSV is missing columns: {sorted(required - set(frame.columns))}")
    require(frame["parameter"].nunique() == 8, "Sensitivity analysis must contain 8 parameters")
    require(set(frame["n_scored"].astype(int)) == {115}, "Every sensitivity configuration must score 115 cases")
    require(frame.groupby("parameter")["is_default"].apply(lambda values: sum(as_bool(value) for value in values) == 1).all(), "Each sensitivity parameter must have one default row")
    return {"metadata": metadata, "frame": frame}


def sensitivity_table_rows(sensitivity: dict[str, Any]) -> list[list[Any]]:
    frame = sensitivity["frame"]
    not_exercised = sensitivity["metadata"]["scoring_assumptions"]["not_exercised_parameters"]
    rows = []
    for parameter, group in frame.groupby("parameter", sort=False):
        default = group[group["is_default"].astype(str).str.lower() == "true"].iloc[0]
        deltas = group["delta_score_pct"].astype(float)
        max_abs = float(deltas.abs().max())
        if parameter in not_exercised:
            verdict = "ไม่ถูกกระตุ้นในสมมติฐานนี้"
        else:
            verdict = "เสถียร" if max_abs < 5 else "ปานกลาง" if max_abs < 10 else "อ่อนไหว"
        rows.append([
            default["label"],
            default["value"],
            f"{deltas.min():+.2f}%",
            f"{deltas.max():+.2f}%",
            f"{max_abs:.2f}%",
            verdict,
        ])
    return rows


def schema_smoke(paths: EvidencePaths) -> dict[str, Any]:
    """Read legacy or final artifacts without asserting final counts or provenance."""
    matrix = load_json(paths.matrix)
    retrieval = load_json(paths.retrieval_json)
    polarity = load_json(paths.polarity)
    ablation = pd.read_csv(paths.ablation_results)
    sensitivity = pd.read_csv(paths.sensitivity_raw)
    require({"metadata", "per_case"}.issubset(matrix), "Matrix schema is missing metadata/per_case")
    require({"metadata", "aggregates", "paired_tests"}.issubset(retrieval), "Retrieval schema is incomplete")
    require({"metadata", "overall", "per_case"}.issubset(polarity), "Polarity schema is incomplete")
    require({"variant", "case_id", "nDCG@5"}.issubset(ablation.columns), "Ablation schema is incomplete")
    require({"parameter", "value", "mean_score"}.issubset(sensitivity.columns), "Sensitivity schema is incomplete")
    return {
        "status": "schema_only_passed",
        "matrix_models": sorted(matrix["per_case"]),
        "retrieval_aggregate_rows": len(retrieval["aggregates"]),
        "polarity_rows": len(polarity["per_case"]),
        "ablation_rows": len(ablation),
        "sensitivity_rows": len(sensitivity),
        "outputs_written": False,
    }


def fmt(value: Any, digits: int = 4) -> str:
    return f"{float(value):.{digits}f}"


def fmt_p(value: Any) -> str:
    number = float(value)
    return "<0.0001" if number < 0.0001 else f"{number:.4f}"


def md_table(headers: list[str], rows: Iterable[Iterable[Any]], numeric_from: int = 1) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |"]
    separators = ["---" if index < numeric_from else "---:" for index in range(len(headers))]
    lines.append("|" + "|".join(separators) + "|")
    lines.extend("| " + " | ".join(str(value) for value in row) + " |" for row in rows)
    return lines


def aggregate_lookup(retrieval: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {(str(row["model"]), str(row["strategy"])): row for row in retrieval["aggregates"]}


def model_label(model: str) -> str:
    return {
        EXPECTED_MODELS[0]: "Qwen 2.5 7B",
        EXPECTED_MODELS[1]: "Typhoon 2 8B",
        EXPECTED_MODELS[2]: "Typhoon-Gemma3 4B (template-fixed)",
    }.get(model, model)


def strategy_label(strategy: str) -> str:
    return {
        "bm25_only": "BM25 only",
        "naive_rag": "Naive RAG",
        "hyde": "HyDE",
        "basic": "Basic hybrid",
        "h2l-bm25": "H2L-BM25",
        "h2l-naive_rag": "H2L-naive RAG",
        "h2l-hyde": "H2L-HyDE",
        "h2l-hybrid": "H2L-hybrid",
    }.get(strategy, strategy)


def evaluation_protocol_rows(ground_truth_audit: dict[str, Any]) -> list[list[str]]:
    return [
        ["ชุดข้อมูลทั้งหมด", "220 กรณี"],
        ["ชุดฝึก / ชุดทดสอบ", "125 / 95 กรณี"],
        ["เคสอ้างอิงที่ไม่ติดป้าย augmentation (92 เคสหลัก + Short 5 + Tiny 3)", f"{ground_truth_audit['original_non_augmented_cases']} กรณี"],
        ["เคสสร้าง/ดัดแปลง (Paraphrase 44 + Escalation 10 + Reduction 10 + Adversarial 20 + Polarity 36)", f"{ground_truth_audit['generated_modified_cases']} กรณี"],
        ["Standard test slice", "75 กรณี"],
        ["Adversarial stress-test slice", "20 กรณี"],
        ["วิธีแบ่งข้อมูล", "family-level stratified split, seed = 42"],
        ["Family leakage across split", str(ground_truth_audit["family_leakage_count"])],
        ["Exact duplicate descriptions", str(ground_truth_audit["exact_duplicate_count"])],
        ["Cross-split near-duplicates (cosine >= 0.90)", str(ground_truth_audit["cross_split_near_duplicate_count"])],
        ["แบบจำลอง L2", "3 แบบจำลอง × 3 รอบ"],
        ["กลยุทธ์ค้นคืน", "8 กลยุทธ์"],
        ["ข้อกำหนดค้นคืน", "problem_source=detected, top_k=15"],
        ["หน่วยของ Wilcoxon", "ค่าเฉลี่ยต่อกรณี, n = 95"],
        ["Holm families", "แยก nDCG@5 และ nDCG@10, family ละ 7 คู่"],
    ]


def l2_slice_summary(matrix: dict[str, Any], slice_name: str) -> list[dict[str, Any]]:
    summaries = []
    for model, rows in matrix["rows_by_model"].items():
        selected = [row for row in rows if normalized_slice(row.get("evaluation_slice")) == slice_name]
        tp = sum(int(row["detector_metrics"]["tp"]) for row in selected)
        fp = sum(int(row["detector_metrics"]["fp"]) for row in selected)
        fn = sum(int(row["detector_metrics"]["fn"]) for row in selected)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        micro_f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        false_trigger_rows = [
            row
            for row in selected
            if isinstance(row.get("augmentation"), dict)
            and row["augmentation"].get("false_trigger_code")
        ]
        require(
            len(false_trigger_rows) == len(selected),
            f"Every {slice_name} row must identify a false-trigger code for {model}",
        )
        target_preserved = 0
        false_trigger_suppressed = 0
        joint_pass = 0
        for row in false_trigger_rows:
            predicted = set(map(str, row.get("predicted_codes", [])))
            expected = set(map(str, row.get("expected_codes", [])))
            target_ok = bool(expected) and expected.issubset(predicted)
            false_trigger_ok = str(row["augmentation"]["false_trigger_code"]) not in predicted
            target_preserved += target_ok
            false_trigger_suppressed += false_trigger_ok
            joint_pass += target_ok and false_trigger_ok
        summaries.append({
            "model": model,
            "rows": len(selected),
            "cases": len({row["case_id"] for row in selected}),
            "micro_precision": precision,
            "micro_recall": recall,
            "micro_f1": micro_f1,
            "macro_f1": sum(float(row["detector_metrics"]["f1"]) for row in selected) / len(selected),
            "exact_match": sum(float(row["detector_metrics"]["exact_match"]) for row in selected) / len(selected),
            "target_preservation_rate": target_preserved / len(false_trigger_rows),
            "false_trigger_suppression_rate": false_trigger_suppressed / len(false_trigger_rows),
            "joint_pass_rate": joint_pass / len(false_trigger_rows),
            "degraded": sum(bool(row.get("l2_degraded")) for row in selected),
        })
    return summaries


def build_markdown(
    ground_truth: dict[str, Any],
    ground_truth_audit: dict[str, Any],
    matrix: dict[str, Any],
    retrieval: dict[str, Any],
    polarity: dict[str, Any],
    ablation: dict[str, Any],
    sensitivity: dict[str, Any],
    sources: dict[str, dict[str, Any]],
    provenance_window: dict[str, Any],
) -> str:
    date_statement = artifact_date_statement(provenance_window)
    lines: list[str] = [
        "# บทที่ 4",
        "",
        "## ผลการวิจัย",
        "",
        "บทนี้รายงานผลจากชุดข้อมูลฉบับสุดท้าย 220 กรณีเท่านั้น โดยใช้ชุดฝึก 125 กรณี ชุดทดสอบ 95 กรณี และแยก Adversarial Cases 20 กรณีเป็น held-out stress-test slice การค้นคืน แบบจำลอง L2, Contextual Polarity Gate, component ablation และสถิติ Wilcoxon-Holm ล้วนคำนวณจาก artifact ชุดเดียวกันที่ตรวจสอบ hash และจำนวนแถวร่วมกันแล้ว โดย " + date_statement + " ตาม timestamp ที่บันทึกใน provenance manifest",
        "",
        "การทดสอบนัยสำคัญใช้หน่วยวิเคราะห์เป็นกรณีอิสระ โดยเฉลี่ยผล 3 รอบภายในแต่ละกรณีก่อนใช้ two-sided Wilcoxon signed-rank test และปรับ Holm แยกสำหรับ nDCG@5 และ nDCG@10 ผลของ stress-test เป็นหลักฐานความทนทานต่อกรณีสร้างเชิงท้าทาย ไม่ใช้แทนค่าประสิทธิภาพของข้อมูลภาคสนาม",
        "",
        "## 4.1 กรอบการประเมินและชุดข้อมูล",
        "",
        "**ตารางที่ 4.1 สรุปชุดข้อมูลและข้อกำหนดการประเมิน**",
        "",
    ]
    lines += md_table(["รายการ", "ค่า"], evaluation_protocol_rows(ground_truth_audit))
    lines += [
        "",
        "การจำแนก 100/120 ใช้กติกาจาก ground-truth audit: กลุ่ม 100 หมายถึงเคสที่ไม่ติดป้าย augmentation ซึ่งรวม 92 เคสหลัก Short 5 เคส และ Tiny 3 เคส ขณะที่กลุ่ม 120 เป็นเคสสร้างหรือดัดแปลงตามห้าประเภทที่ระบุในตาราง จึงไม่ควรตีความ metadata original_cases=92 ว่าเป็นจำนวนเดียวกับกลุ่ม audit 100 เคส",
        "",
    ]
    lines += ["", "**ตารางที่ 4.1ก แหล่งหลักฐานและรหัสตรวจสอบ**", ""]
    source_rows = []
    for name, item in sources.items():
        source_rows.append([name, item["path"], item["sha256"][:12]])
    lines += md_table(["หลักฐาน", "ไฟล์", "SHA-256 (12 ตัวแรก)"], source_rows, numeric_from=3)

    overall = polarity["overall"]
    lines += [
        "",
        "## 4.2 ผลการประเมิน Contextual Polarity Gate",
        "",
        "**ตารางที่ 4.2 ผลรวมของ Contextual Polarity Gate (n = 95)**",
        "",
    ]
    lines += md_table(["ตัวชี้วัด", "ค่า"], [
        ["Positive / negated", f"{int(overall['n_positive'])} / {int(overall['n_negated'])}"],
        ["Accuracy", fmt(overall["accuracy"])],
        ["Negation Detection Rate", fmt(overall["negation_detection_rate"])],
        ["False Positive Rate", fmt(overall["false_positive_rate"])],
        ["Precision", fmt(overall["precision"])],
        ["F1-score", fmt(overall["f1_score"])],
        ["Mean G_neg: positive", fmt(overall["mean_g_neg_positive"])],
        ["Mean G_neg: negated", fmt(overall["mean_g_neg_negated"])],
    ])
    lines += ["", "**ตารางที่ 4.3 ผล polarity จำแนกตามกลุ่มความยาว**", ""]
    length_order = ["tiny", "short", "medium", "long", "unknown"]
    length_rows = []
    for name in length_order:
        summary = polarity.get("length_summary", {}).get(name)
        if summary:
            length_rows.append([name, int(summary["n_positive"]), int(summary["n_negated"]), fmt(summary["ndr"]), fmt(summary["fpr"])])
    lines += md_table(["กลุ่ม", "Positive", "Negated", "NDR", "FPR"], length_rows)
    lines += ["", "กลุ่ม unknown คงไว้ตามข้อมูลจริงและไม่ถูกอนุมานย้อนหลังจากจำนวนตัวอักษร จึงใช้ตารางนี้เป็นการวิเคราะห์ตาม strata ที่ระบุไว้ล่วงหน้าเท่านั้น", ""]

    lookup = aggregate_lookup(retrieval)
    lines += ["## 4.3 ผลการประเมินการค้นคืนเอกสาร", "", "ผลหลักต่อไปนี้ใช้ Qwen 2.5 7B และเฉลี่ย 3 รอบ รวม 285 แถวต่อกลยุทธ์ หรือ 95 กรณีอิสระ", "", "**ตารางที่ 4.4ก ผลการค้นคืนที่ลำดับ 5 (n = 95)**", ""]
    metric5 = ["P@5", "R@5", "F1@5", "DCG@5", "IDCG@5", "nDCG@5", "MAP", "MRR"]
    rows5 = [[strategy_label(strategy)] + [fmt(lookup[(PRIMARY_MODEL, strategy)][f"{metric}_mean"]) for metric in metric5] for strategy in EXPECTED_STRATEGIES]
    lines += md_table(["กลยุทธ์"] + metric5, rows5)
    lines += ["", "**ตารางที่ 4.4ข ผลการค้นคืนที่ลำดับ 10 (n = 95)**", ""]
    metric10 = ["P@10", "R@10", "F1@10", "DCG@10", "IDCG@10", "nDCG@10", "MAP", "MRR"]
    rows10 = [[strategy_label(strategy)] + [fmt(lookup[(PRIMARY_MODEL, strategy)][f"{metric}_mean"]) for metric in metric10] for strategy in EXPECTED_STRATEGIES]
    lines += md_table(["กลยุทธ์"] + metric10, rows10)

    sig = retrieval["significance"]
    for metric, suffix in (("nDCG@5", "ก"), ("nDCG@10", "ข")):
        lines += ["", f"**ตารางที่ 4.5{suffix} ผล Wilcoxon-Holm ของ {metric} เทียบกับ H2L-hybrid**", ""]
        selected = sig[sig["metric"] == metric]
        sig_rows = []
        for _, row in selected.iterrows():
            sig_rows.append([
                strategy_label(str(row["comparison"])),
                f"{float(row['mean_difference']):+.4f}",
                f"{int(row['n_nonzero_differences'])} / {int(row['n_pairs'])}",
                fmt_p(row["raw_p"]),
                fmt_p(row["holm_p"]),
                "มีนัยสำคัญ" if as_bool(row["significant_0_05"]) else "ไม่พบความแตกต่าง",
            ])
        lines += md_table(["กลยุทธ์เปรียบเทียบ", "ผลต่างเฉลี่ย", "คู่ไม่เป็นศูนย์", "p ดิบ", "Holm p", "ผลสรุป"], sig_rows)
    significant_flags = sig["significant_0_05"].map(as_bool)
    sig5 = int(sig[(sig["metric"] == "nDCG@5") & significant_flags].shape[0])
    sig10 = int(sig[(sig["metric"] == "nDCG@10") & significant_flags].shape[0])
    lines += ["", f"หลังปรับ Holm พบความแตกต่างที่ nDCG@5 จำนวน {sig5} จาก 7 คู่ และที่ nDCG@10 จำนวน {sig10} จาก 7 คู่ การตีความยึดผลหลังปรับและจำนวนคู่ที่ผลต่างไม่เป็นศูนย์ ไม่ใช้ p ดิบเพียงอย่างเดียว", ""]

    standard = retrieval["frame"][(retrieval["frame"]["model"] == PRIMARY_MODEL) & (retrieval["frame"]["evaluation_slice"] == "standard_test")]
    per_case_standard = standard.groupby(["case_id", "complexity", "strategy"], as_index=False)["nDCG@10"].mean()
    complexity_counts = per_case_standard[["case_id", "complexity"]].drop_duplicates()["complexity"].value_counts().to_dict()
    complexity = per_case_standard.groupby(["strategy", "complexity"])["nDCG@10"].mean().unstack()
    lines += ["**ตารางที่ 4.6 nDCG@10 ตามความซับซ้อนของ standard test slice**", ""]
    selected_strategies = ["bm25_only", "basic", "h2l-bm25", "h2l-hybrid"]
    complexity_columns = [name for name in ("simple", "moderate", "complex") if name in complexity.columns]
    complexity_rows = []
    for strategy in selected_strategies:
        complexity_rows.append([strategy_label(strategy)] + [fmt(complexity.loc[strategy, name]) for name in complexity_columns])
    lines += md_table(["กลยุทธ์"] + [f"{name} (n = {int(complexity_counts.get(name, 0))})" for name in complexity_columns], complexity_rows)
    lines += ["", "Adversarial 20 กรณีมีป้ายความซับซ้อน moderate ทั้งหมด จึงถูกตัดออกจากตารางความซับซ้อนนี้และรายงานเป็น stress-test แยกในหัวข้อ 4.7", ""]

    lines += ["## 4.4 ผลการเปรียบเทียบแบบจำลอง L2", "", "**ตารางที่ 4.7 ผล detector ของแบบจำลอง L2 เฉลี่ย 3 รอบ**", ""]
    l2_rows = []
    for model in EXPECTED_MODELS:
        aggregate = matrix["metadata_artifact"]["aggregates"][model]["all_cases"]
        latency = matrix["metadata_artifact"]["aggregates"][model]["latency_ms"]
        l2_rows.append([
            model_label(model), fmt(aggregate["micro_precision"]), fmt(aggregate["micro_recall"]),
            fmt(aggregate["micro_f1"]), fmt(aggregate["macro_f1"]), fmt(aggregate["exact_match_rate"]),
            fmt(latency["median_l2"] / 1000, 2), fmt(latency["p95_l2"] / 1000, 2),
            f"{100 * float(matrix['metadata_artifact']['aggregates'][model]['l2_degraded_rate']):.2f}%",
        ])
    lines += md_table(["แบบจำลอง", "Micro P", "Micro R", "Micro F1", "Macro F1", "Exact", "Median L2 (s)", "P95 L2 (s)", "Degraded"], l2_rows)
    for cutoff, suffix, metrics in ((5, "ก", metric5), (10, "ข", metric10)):
        lines += ["", f"**ตารางที่ 4.7{suffix} ผล H2L-hybrid ที่ลำดับ {cutoff} จำแนกตามแบบจำลอง L2**", ""]
        model_rows = [[model_label(model)] + [fmt(lookup[(model, PRIMARY_STRATEGY)][f"{metric}_mean"]) for metric in metrics] for model in EXPECTED_MODELS]
        lines += md_table(["แบบจำลอง"] + metrics, model_rows)

    abl = ablation["frame"]
    abl_avg = abl.groupby("variant")
    lines += ["", "## 4.5 Component Ablation และ Parameter Sensitivity", "", "**ตารางที่ 4.8ก ผล RQ6 component ablation ที่ลำดับ 5 (n = 95)**", ""]
    abl5 = [[variant] + [fmt(abl_avg.get_group(variant)[metric].mean()) for metric in metric5] for variant in EXPECTED_VARIANTS]
    lines += md_table(["Configuration"] + metric5, abl5)
    lines += ["", "**ตารางที่ 4.8ข ผล RQ6 component ablation ที่ลำดับ 10 (n = 95)**", ""]
    abl10 = [[variant] + [fmt(abl_avg.get_group(variant)[metric].mean()) for metric in metric10] for variant in EXPECTED_VARIANTS]
    lines += md_table(["Configuration"] + metric10, abl10)
    lines += ["", "**ตารางที่ 4.8ค ผล Wilcoxon-Holm ของ RQ6 เทียบกับ Full V6**", ""]
    abl_sig_rows = []
    for _, row in ablation["significance"].iterrows():
        abl_sig_rows.append([
            row["metric"], row["comparison"], f"{float(row['reference_minus_comparison_mean']):+.4f}",
            f"{int(row['n_nonzero_differences'])} / {int(row['n_pairs'])}", fmt_p(row["raw_p"]), fmt_p(row["holm_p"]),
            "มีนัยสำคัญ" if as_bool(row["significant_0_05"]) else "ไม่พบความแตกต่าง",
        ])
    lines += md_table(["ตัวชี้วัด", "Configuration", "ผลต่าง", "คู่ไม่เป็นศูนย์", "p ดิบ", "Holm p", "ผลสรุป"], abl_sig_rows)

    sensitivity_rows = sensitivity_table_rows(sensitivity)
    lines += ["", "**ตารางที่ 4.9 ผล One-at-a-Time sensitivity analysis**", ""]
    lines += md_table(["Parameter", "Default", "Min delta", "Max delta", "Max absolute delta", "ผลสรุป"], sensitivity_rows)
    lines += [
        "",
        f"Sensitivity analysis เลือกชุดฝึก {sensitivity['metadata']['selected_cases']} กรณี แต่คำนวณคะแนนได้ {sensitivity['metadata']['scored_cases']} กรณี เนื่องจาก {sensitivity['metadata']['skipped_empty_problem_lists']} กรณีประเภท complexity reduction ไม่มี expected problem list การรายงานจึงแยกจำนวนที่เลือกออกจากจำนวนที่คำนวณจริง",
        "",
        "การวิเคราะห์นี้มีขอบเขตเป็น score_function_oat และกำหนด retrieval_executed=false จึงประเมินเฉพาะความไวของฟังก์ชันคะแนนภายใต้ input ที่ตรึงไว้ ไม่ใช่หลักฐาน whole-system robustness ทั้ง MARGIN_M และ L1_WEIGHT_BETA ไม่ถูกกระตุ้นภายใต้สมมติฐานดังกล่าว จึงไม่ตีความค่า delta ศูนย์ว่าเป็นความเสถียรของพารามิเตอร์",
        "",
    ]

    primary_case = retrieval["frame"][retrieval["frame"]["model"] == PRIMARY_MODEL].groupby(["case_id", "evaluation_slice", "strategy"], as_index=False)["nDCG@10"].mean()
    pivot = primary_case.pivot(index=["case_id", "evaluation_slice"], columns="strategy", values="nDCG@10").reset_index()
    pivot["delta"] = pivot[PRIMARY_STRATEGY] - pivot["basic"]
    example_keys = []
    for slice_name in ("standard_test", "adversarial_test"):
        subset = pivot[pivot["evaluation_slice"] == slice_name]
        example_keys.extend([(str(subset.nlargest(1, "delta").iloc[0]["case_id"]), slice_name), (str(subset.nsmallest(1, "delta").iloc[0]["case_id"]), slice_name)])
    qwen_repeat1 = {(str(row["case_id"]), normalized_slice(row.get("evaluation_slice"))): row for row in matrix["rows_by_model"][PRIMARY_MODEL] if int(row["repeat"]) == 1}
    example_rows = []
    for case_id, slice_name in example_keys:
        metrics = pivot[(pivot["case_id"] == case_id) & (pivot["evaluation_slice"] == slice_name)].iloc[0]
        detection = qwen_repeat1[(case_id, slice_name)]
        example_rows.append([case_id, slice_name, ", ".join(detection["expected_codes"]), ", ".join(detection["predicted_codes"]), fmt(metrics["basic"]), fmt(metrics[PRIMARY_STRATEGY]), f"{float(metrics['delta']):+.4f}"])
    lines += ["", "## 4.6 การวิเคราะห์ผลรายกรณี", "", "**ตารางที่ 4.10 กรณีที่ H2L-hybrid เปลี่ยน nDCG@10 มากที่สุดและน้อยที่สุดในแต่ละ slice**", ""]
    lines += md_table(["Case ID", "Slice", "Expected", "Predicted", "Basic", "H2L-hybrid", "Delta"], example_rows, numeric_from=4)

    adv = polarity["adversarial"]
    lines += ["", "## 4.7 ผล Adversarial Stress-Test Slice (n = 20)", "", "ผลส่วนนี้แยกออกจาก standard test และไม่รวมเข้ากับข้อสรุปตามระดับความซับซ้อน", "", "**ตารางที่ 4.11ก ผล polarity gate บน adversarial slice**", ""]
    lines += md_table(["ตัวชี้วัด", "ค่า"], [
        ["Target preservation", f"{int(adv['target_preserved_count'])} / {int(adv['target_evaluated_count'])} ({fmt(adv['target_preservation_rate'])})"],
        ["Expected-target false suppression", f"{int(adv['false_suppression_count'])} / {int(adv['target_evaluated_count'])} ({fmt(adv['false_suppression_rate'])})"],
        ["False trigger suppressed by G_neg", f"{int(adv['false_trigger_negation_suppression_count'])} / 20 ({fmt(adv['false_trigger_negation_suppression_rate'])})"],
        ["False trigger suppressed by G_sub", f"{int(adv['false_trigger_subject_suppression_count'])} / 20 ({fmt(adv['false_trigger_subject_suppression_rate'])})"],
        ["False trigger suppressed by G_total", f"{int(adv['false_trigger_contextual_suppression_count'])} / 20 ({fmt(adv['false_trigger_contextual_suppression_rate'])})"],
        ["Joint pass", f"{int(adv['joint_pass_count'])} / {int(adv['joint_pass_eligible_count'])} ({fmt(adv['joint_pass_rate'])})"],
    ])

    lines += ["", "**ตารางที่ 4.11ข ผล L2 detector บน adversarial slice (20 กรณี × 3 รอบ)**", ""]
    stress_l2 = l2_slice_summary(matrix, "adversarial_test")
    lines += md_table(
        ["แบบจำลอง", "Target preservation", "False-trigger suppression", "Joint pass", "Micro F1", "Exact", "Degraded"],
        [[
            model_label(row["model"]),
            fmt(row["target_preservation_rate"]),
            fmt(row["false_trigger_suppression_rate"]),
            fmt(row["joint_pass_rate"]),
            fmt(row["micro_f1"]),
            fmt(row["exact_match"]),
            row["degraded"],
        ] for row in stress_l2],
    )

    adv_retrieval = retrieval["frame"][(retrieval["frame"]["model"] == PRIMARY_MODEL) & (retrieval["frame"]["evaluation_slice"] == "adversarial_test")]
    adv_case = adv_retrieval.groupby(["case_id", "strategy"], as_index=False)[["nDCG@5", "nDCG@10", "MAP", "MRR"]].mean()
    adv_agg = adv_case.groupby("strategy")[["nDCG@5", "nDCG@10", "MAP", "MRR"]].mean()
    lines += ["", "**ตารางที่ 4.11ค ผล retrieval ของ Qwen บน adversarial slice**", ""]
    lines += md_table(["กลยุทธ์", "nDCG@5", "nDCG@10", "MAP", "MRR"], [[strategy_label(strategy)] + [fmt(adv_agg.loc[strategy, metric]) for metric in ("nDCG@5", "nDCG@10", "MAP", "MRR")] for strategy in EXPECTED_STRATEGIES])

    stress_ablation = ablation["slices"][ablation["slices"]["evaluation_slice"] == "adversarial_test"].set_index("variant")
    lines += ["", "**ตารางที่ 4.11ง ผล RQ6 ablation บน adversarial slice**", ""]
    lines += md_table(["Configuration", "nDCG@5", "nDCG@10", "MAP", "MRR"], [[variant, fmt(stress_ablation.loc[variant, "nDCG@5_mean"]), fmt(stress_ablation.loc[variant, "nDCG@10_mean"]), fmt(stress_ablation.loc[variant, "MAP_mean"]), fmt(stress_ablation.loc[variant, "MRR_mean"])] for variant in EXPECTED_VARIANTS])

    primary = lookup[(PRIMARY_MODEL, PRIMARY_STRATEGY)]
    lines += [
        "",
        "## 4.8 สรุปบท",
        "",
        f"บนชุดทดสอบ 95 กรณี H2L-hybrid มี nDCG@5 = {fmt(primary['nDCG@5_mean'])}, nDCG@10 = {fmt(primary['nDCG@10_mean'])}, MAP = {fmt(primary['MAP_mean'])} และ MRR = {fmt(primary['MRR_mean'])} ผล Wilcoxon-Holm สนับสนุนความแตกต่าง {sig5} จาก 7 คู่ที่ลำดับ 5 และ {sig10} จาก 7 คู่ที่ลำดับ 10 โดยข้อสรุปนี้เป็นผลของชุดทดสอบรวมและไม่หมายความว่าระบบดีขึ้นทุกกรณี",
        "",
        f"Adversarial stress-test แสดง target preservation ของ polarity เท่ากับ {fmt(adv['target_preservation_rate'])} และ joint pass เท่ากับ {fmt(adv['joint_pass_rate'])} จึงยังมีข้อจำกัดต่อ false trigger เชิงบริบท ส่วน component ablation และ sensitivity ใช้เพื่ออธิบายพฤติกรรมของระบบ ไม่ใช้เป็นหลักฐานประสิทธิผลทางคลินิก และการประเมินโดยผู้เชี่ยวชาญยังต้องรายงานแยกเมื่อมีข้อมูลที่กรอกจริง",
        "",
    ]
    return "\n".join(lines)


def build(paths: EvidencePaths) -> dict[str, Any]:
    source_paths = {
        "Ground truth": paths.ground_truth,
        "Ground-truth audit": paths.ground_truth_audit,
        "Taxonomy": paths.taxonomy,
        "Document metadata": paths.document_metadata,
        "Typhoon-Gemma template patch": MODEL_PATCH_MANIFEST,
        "L2/retrieval matrix": paths.matrix,
        "Derived retrieval metrics": paths.retrieval_json,
        "Retrieval per-case CSV": paths.retrieval_per_case,
        "Retrieval Wilcoxon-Holm CSV": paths.retrieval_significance,
        "Polarity": paths.polarity,
        "Adversarial stress-test summary": paths.adversarial_stress,
        "RQ6 results": paths.ablation_results,
        "RQ6 Wilcoxon-Holm": paths.ablation_significance,
        "RQ6 slice summary": paths.ablation_slices,
        "RQ6 run metadata": paths.ablation_metadata,
        "Sensitivity results": paths.sensitivity_raw,
        "Sensitivity run metadata": paths.sensitivity_metadata,
    }
    for path in source_paths.values():
        require(path.is_file(), f"Required final artifact is missing: {path}")

    ground_truth_payload = load_json(paths.ground_truth)
    ground_truth = validate_ground_truth(ground_truth_payload)
    ground_truth_audit = validate_ground_truth_audit(
        load_json(paths.ground_truth_audit),
        ground_truth,
    )
    matrix_payload = load_json(paths.matrix)
    matrix = validate_matrix(matrix_payload, ground_truth, paths)
    matrix["metadata_artifact"] = matrix_payload
    matrix_hash = sha256(paths.matrix)
    retrieval = validate_retrieval(
        load_json(paths.retrieval_json),
        pd.read_csv(paths.retrieval_per_case),
        pd.read_csv(paths.retrieval_significance),
        paths,
        matrix_hash,
    )
    retrieval["aggregates"] = load_json(paths.retrieval_json)["aggregates"]
    polarity_artifact = load_json(paths.polarity)
    polarity = validate_polarity(polarity_artifact, ground_truth)
    polarity["length_summary"] = polarity_artifact.get("per_length_summary", {})
    adversarial_stress = validate_adversarial_stress(
        load_json(paths.adversarial_stress),
        ground_truth,
        matrix,
        retrieval,
        paths,
        matrix_hash,
    )
    ablation = validate_ablation(
        load_json(paths.ablation_metadata),
        pd.read_csv(paths.ablation_results),
        pd.read_csv(paths.ablation_significance),
        pd.read_csv(paths.ablation_slices),
        paths,
        matrix_hash,
    )
    sensitivity = validate_sensitivity(
        load_json(paths.sensitivity_metadata),
        pd.read_csv(paths.sensitivity_raw),
        paths,
        ground_truth,
    )

    provenance_window = artifact_provenance_window(
        matrix["metadata"],
        retrieval["metadata"],
        polarity["metadata"],
        adversarial_stress["metadata"],
        ablation["metadata"],
        sensitivity["metadata"],
    )

    sources = {
        name: {"path": display_path(path), "sha256": sha256(path), "bytes": path.stat().st_size}
        for name, path in source_paths.items()
    }
    markdown = build_markdown(
        ground_truth,
        ground_truth_audit,
        matrix,
        retrieval,
        polarity,
        ablation,
        sensitivity,
        sources,
        provenance_window,
    )
    stale_markers = ("205 กรณี", "129 / 76", "n = 76", "Adversarial Cases ทั้ง 5")
    require(not any(marker in markdown for marker in stale_markers), "Generated report contains a stale dataset marker")
    require("TODO" not in markdown and "TBD" not in markdown, "Generated report contains placeholder text")
    atomic_write(paths.output, markdown + "\n")

    generated_at = datetime.now(ZoneInfo("Asia/Bangkok")).isoformat(timespec="seconds")
    manifest = {
        "schema_version": 1,
        "status": "complete",
        "generated_at": generated_at,
        "builder": {
            "path": display_path(Path(__file__)),
            "sha256": sha256(Path(__file__)),
        },
        "protocol": {
            "total_cases": 220,
            "train_cases": 125,
            "test_cases": 95,
            "standard_test_cases": 75,
            "adversarial_test_cases": 20,
            "models": EXPECTED_MODELS,
            "repeats": 3,
            "strategies": EXPECTED_STRATEGIES,
            "top_k": 15,
            "problem_source": "detected",
            "statistical_test": "paired two-sided Wilcoxon signed-rank",
            "multiplicity_correction": "Holm separately for nDCG@5 and nDCG@10",
        },
        "artifact_provenance_window": provenance_window,
        "sources": sources,
        "validation": {
            "matrix_rows_per_model": 285,
            "retrieval_rows": 6840,
            "retrieval_significance_rows": 14,
            "ablation_rows": 760,
            "ablation_significance_rows": 14,
            "ablation_standard_rows": 600,
            "ablation_adversarial_rows": 160,
            "sensitivity_selected_cases": 125,
            "sensitivity_scored_cases": 115,
            "polarity_cases": 95,
            "adversarial_cases": 20,
            "original_non_augmented_cases": ground_truth_audit["original_non_augmented_cases"],
            "generated_modified_cases": ground_truth_audit["generated_modified_cases"],
            "family_leakage_count": ground_truth_audit["family_leakage_count"],
            "exact_duplicate_count": ground_truth_audit["exact_duplicate_count"],
            "cross_split_near_duplicate_count": ground_truth_audit["cross_split_near_duplicate_count"],
            "near_duplicate_threshold": ground_truth_audit["near_duplicate_threshold"],
            "adversarial_case_first_retrieval_max_abs_difference": adversarial_stress["max_case_first_retrieval_difference"],
            "adversarial_aggregate_retrieval_max_abs_difference": adversarial_stress["max_aggregate_retrieval_difference"],
        },
        "outputs": {
            "markdown": {
                "path": display_path(paths.output),
                "sha256": sha256(paths.output),
                "bytes": paths.output.stat().st_size,
            }
        },
    }
    atomic_write(paths.manifest, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ground-truth", type=Path, default=ROOT / "data/expanded_ground_truth.json")
    parser.add_argument("--ground-truth-audit", type=Path, default=DEFAULT_GROUND_TRUTH_AUDIT)
    parser.add_argument("--taxonomy", type=Path, default=ROOT / "data/problem_codes.json")
    parser.add_argument("--document-metadata", type=Path, default=ROOT / "data/vector_db_lancedb/metadata.json")
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--retrieval-json", type=Path, default=DEFAULT_RETRIEVAL_JSON)
    parser.add_argument("--retrieval-per-case", type=Path, default=DEFAULT_RETRIEVAL_PER_CASE)
    parser.add_argument("--retrieval-significance", type=Path, default=DEFAULT_RETRIEVAL_SIGNIFICANCE)
    parser.add_argument("--polarity", type=Path, default=DEFAULT_POLARITY)
    parser.add_argument("--adversarial-stress", type=Path, default=DEFAULT_ADVERSARIAL_STRESS)
    parser.add_argument("--ablation-dir", type=Path, default=DEFAULT_ABLATION_DIR)
    parser.add_argument("--sensitivity-dir", type=Path, default=DEFAULT_SENSITIVITY_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--schema-only", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    paths = EvidencePaths(
        ground_truth=args.ground_truth.resolve(),
        ground_truth_audit=args.ground_truth_audit.resolve(),
        taxonomy=args.taxonomy.resolve(),
        document_metadata=args.document_metadata.resolve(),
        matrix=args.matrix.resolve(),
        retrieval_json=args.retrieval_json.resolve(),
        retrieval_per_case=args.retrieval_per_case.resolve(),
        retrieval_significance=args.retrieval_significance.resolve(),
        polarity=args.polarity.resolve(),
        adversarial_stress=args.adversarial_stress.resolve(),
        ablation_dir=args.ablation_dir.resolve(),
        sensitivity_dir=args.sensitivity_dir.resolve(),
        output=args.output.resolve(),
        manifest=args.manifest.resolve(),
    )
    result = schema_smoke(paths) if args.schema_only else build(paths)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

import json
from pathlib import Path

import pandas as pd
import pytest

from scripts.derive_latest_retrieval_metrics import (
    augmentation_fields,
    case_augmentation_type,
    derive,
    sha256,
)


MODEL = "qwen2.5:7b"
STRATEGIES = ["basic", "h2l-hybrid"]


def test_polarity_cases_use_the_audit_classification_without_augmentation_object():
    case = {"case_id": "NEG_SH_NEG_V2"}
    assert case_augmentation_type(case) == "polarity"
    assert augmentation_fields(case) == {
        "augmentation": None,
        "augmentation_type": "polarity",
    }


def _write_json(path: Path, payload) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _synthetic_inputs(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    cases = [
        {
            "case_id": "CASE_001",
            "split": "test",
            "complexity": "complex",
            "category": "adversarial_l2_test",
            "evaluation_slice": "adversarial_test",
            "augmentation": {
                "type": "adversarial",
                "false_trigger_code": "X1",
            },
            "expected_diagnosis": {
                "problem_list": [
                    {
                        "code": "P1",
                        "category": "P1 - Support need",
                        "severity": 3,
                        "details": "financial support",
                    }
                ]
            },
        },
        {
            "case_id": "CASE_002",
            "split": "test",
            "complexity": "simple",
            "category": "standard_category",
            "expected_diagnosis": {
                "problem_list": [
                    {
                        "code": "P1",
                        "category": "P1 - Support need",
                        "severity": 3,
                        "details": "financial support",
                    }
                ]
            },
        },
    ]
    ground_truth = _write_json(
        tmp_path / "ground_truth.json",
        {
            "metadata": {"test_cases": 2, "last_updated": "2099-01-01T00:00:00"},
            "cases": cases,
        },
    )
    documents = _write_json(
        tmp_path / "metadata.json",
        [
            {"doc_id": 1, "content": "financial support for this support need"},
            {"doc_id": 2, "content": "unrelated document"},
        ],
    )
    taxonomy = _write_json(
        tmp_path / "taxonomy.json",
        {
            "P1": {
                "name": "Support need",
                "category": "P1: Support",
                "keywords": ["financial support", "support need"],
            }
        },
    )

    rows = []
    for repeat in (1, 2):
        for case in cases:
            rows.append(
                {
                    "model": MODEL,
                    "repeat": repeat,
                    "case_id": case["case_id"],
                    "complexity": "stale_complexity",
                    "category": "stale_category",
                    "expected_codes": ["P1"],
                    "detected_problems": [{"code": "P1"}],
                    "retrieval_metrics": {
                        "basic": {"doc_ids": [2]},
                        "h2l-hybrid": {"doc_ids": [1]},
                    },
                }
            )
    source = _write_json(
        tmp_path / "matrix.json",
        {
            "metadata": {
                "created_at": "2099-01-02T00:00:00+00:00",
                "models": [MODEL],
                "repeats": 2,
                "test_cases": 2,
                "retrieval_strategies": STRATEGIES,
                "top_k": 15,
                "problem_source": "detected",
            },
            "per_case": {MODEL: rows},
        },
    )
    return source, ground_truth, documents, taxonomy


def test_synthetic_derivation_joins_slices_and_writes_current_provenance(tmp_path):
    source, ground_truth, documents, taxonomy = _synthetic_inputs(tmp_path)
    output_dir = tmp_path / "derived"
    output_dir.mkdir()
    old_output = output_dir / "retrieval_significance_20260730.csv"
    old_output.write_text("legacy artifact\n", encoding="utf-8")

    result = derive(
        source,
        output_dir,
        ground_truth=ground_truth,
        document_metadata=documents,
        taxonomy_path=taxonomy,
        expected_case_count=2,
    )

    per_case_path = output_dir / "retrieval_metrics_20260807_per_case.csv"
    significance_path = output_dir / "retrieval_significance_20260807.csv"
    json_path = output_dir / "retrieval_metrics_20260807_latest.json"
    assert per_case_path.exists()
    assert significance_path.exists()
    assert json_path.exists()
    assert old_output.read_text(encoding="utf-8") == "legacy artifact\n"

    per_case = pd.read_csv(per_case_path)
    adversarial = per_case[per_case["case_id"] == "CASE_001"]
    assert set(adversarial["category"]) == {"adversarial_l2_test"}
    assert set(adversarial["evaluation_slice"]) == {"adversarial_test"}
    assert set(adversarial["augmentation_type"]) == {"adversarial"}
    assert json.loads(adversarial.iloc[0]["augmentation"])["false_trigger_code"] == "X1"

    metadata = result["metadata"]
    assert metadata["ground_truth_sha256"] == sha256(ground_truth)
    assert metadata["unique_test_case_count"] == 2
    assert metadata["evaluation_slice_counts"] == {
        "adversarial_test": 1,
        "standard_test": 1,
    }
    assert metadata["significance_unit"] == "per-case mean across 2 repeats (n=2)"

    significance = pd.read_csv(significance_path)
    assert set(significance["ground_truth_sha256"]) == {sha256(ground_truth)}
    assert set(significance["source_sha256"]) == {sha256(source)}
    assert set(significance["n_pairs"]) == {2}
    assert set(significance["holm_family_size"]) == {1}
    assert set(significance["problem_source"]) == {"detected"}


def test_derivation_rejects_wrong_expected_case_count_before_writing(tmp_path):
    source, ground_truth, documents, taxonomy = _synthetic_inputs(tmp_path)
    output_dir = tmp_path / "derived"

    with pytest.raises(ValueError, match="Ground truth test split count mismatch"):
        derive(
            source,
            output_dir,
            ground_truth=ground_truth,
            document_metadata=documents,
            taxonomy_path=taxonomy,
            expected_case_count=3,
        )

    assert not output_dir.exists()

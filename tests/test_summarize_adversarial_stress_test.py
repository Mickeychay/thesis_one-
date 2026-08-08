import copy
import json
from pathlib import Path

import pytest

from scripts.summarize_adversarial_stress_test import (
    EVALUATION_CODE,
    H2L_CORE,
    build_report,
    markdown_report,
    sha256,
    write_report,
)


MODELS = ["model-a", "model-b"]
STRATEGIES = ["basic", "h2l-hybrid"]
REPEATS = 2
TOP_K = 2


def _write_json(path: Path, payload) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _cases():
    return [
        {
            "case_id": "ADV_001",
            "split": "test",
            "complexity": "complex",
            "category": "adversarial_l2_test",
            "case_description": "Adversarial case one",
            "evaluation_slice": "adversarial_test",
            "augmentation": {
                "type": "adversarial",
                "false_trigger_code": "F1",
                "trigger_word": "trap one",
            },
            "expected_diagnosis": {
                "problem_list": [{"code": "T1", "severity": 3}]
            },
        },
        {
            "case_id": "ADV_002",
            "split": "test",
            "complexity": "moderate",
            "category": "adversarial_l2_test",
            "case_description": "Adversarial case two",
            "evaluation_slice": "adversarial_test",
            "augmentation": {
                "type": "adversarial",
                "false_trigger_code": "F2",
                "trigger_word": "trap two",
            },
            "expected_diagnosis": {
                "problem_list": [
                    {"code": "T2", "severity": 3},
                    {"code": "T3", "severity": 2},
                ]
            },
        },
        {
            "case_id": "STD_001",
            "split": "test",
            "complexity": "simple",
            "category": "standard_test",
            "case_description": "Standard case",
            "expected_diagnosis": {
                "problem_list": [{"code": "T1", "severity": 3}]
            },
        },
    ]


def _predictions(model: str, case_id: str, repeat: int) -> list[str]:
    values = {
        ("model-a", "ADV_001", 1): ["T1"],
        ("model-a", "ADV_001", 2): ["T1", "F1"],
        ("model-a", "ADV_002", 1): ["T2", "T3"],
        ("model-a", "ADV_002", 2): ["T2"],
        ("model-b", "ADV_001", 1): ["T1"],
        ("model-b", "ADV_001", 2): ["T1"],
        ("model-b", "ADV_002", 1): ["F2"],
        ("model-b", "ADV_002", 2): ["T2", "T3"],
    }
    return values.get((model, case_id, repeat), ["T1"])


def _retrieval_score(model: str, strategy: str, case_id: str, repeat: int) -> float:
    scores = {
        ("model-a", "basic", "ADV_001"): [0.2, 0.4],
        ("model-a", "basic", "ADV_002"): [0.6, 0.8],
        ("model-a", "h2l-hybrid", "ADV_001"): [0.8, 0.8],
        ("model-a", "h2l-hybrid", "ADV_002"): [1.0, 1.0],
        ("model-b", "basic", "ADV_001"): [0.1, 0.1],
        ("model-b", "basic", "ADV_002"): [0.3, 0.3],
        ("model-b", "h2l-hybrid", "ADV_001"): [0.4, 0.6],
        ("model-b", "h2l-hybrid", "ADV_002"): [0.6, 0.8],
    }
    return scores.get((model, strategy, case_id), [0.25, 0.25])[repeat - 1]


def _metric_payload(score: float) -> dict:
    return {
        "doc_ids": [101, 102],
        "total_docs": 2,
        "total_relevant": 1,
        "nDCG@5": score,
        "nDCG@10": score,
        "MAP": score,
        "MRR": score,
        "retrieval_ms": 12.5,
    }


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    cases = _cases()
    ground_truth = _write_json(
        tmp_path / "ground_truth.json",
        {
            "metadata": {
                "test_cases": len(cases),
                "last_updated": "2099-01-01T00:00:00",
            },
            "cases": cases,
        },
    )
    taxonomy = _write_json(
        tmp_path / "taxonomy.json",
        {
            code: {"name": code}
            for code in ("T1", "T2", "T3", "F1", "F2")
        },
    )

    per_case = {}
    for model in MODELS:
        rows = []
        for repeat in range(1, REPEATS + 1):
            for case in cases:
                predicted = _predictions(model, case["case_id"], repeat)
                rows.append(
                    {
                        "model": model,
                        "repeat": repeat,
                        "case_id": case["case_id"],
                        "complexity": case.get("complexity"),
                        "category": case.get("category"),
                        "evaluation_slice": case.get("evaluation_slice"),
                        "augmentation": copy.deepcopy(case.get("augmentation")),
                        "expected_codes": [
                            item["code"]
                            for item in case["expected_diagnosis"]["problem_list"]
                        ],
                        "predicted_codes": predicted,
                        "detected_problems": [
                            {"code": code} for code in predicted
                        ],
                        "l2_attempted": True,
                        "l2_degraded": (
                            model == "model-b"
                            and case["case_id"] == "ADV_002"
                            and repeat == 1
                        ),
                        "retrieval_metrics": {
                            strategy: _metric_payload(
                                _retrieval_score(
                                    model,
                                    strategy,
                                    case["case_id"],
                                    repeat,
                                )
                            )
                            for strategy in STRATEGIES
                        },
                    }
                )
        per_case[model] = rows

    run_signature = {
        "ground_truth_path": str(ground_truth.resolve()),
        "ground_truth_sha256": sha256(ground_truth),
        "taxonomy_sha256": sha256(taxonomy),
        "h2l_core_sha256": sha256(H2L_CORE),
        "evaluation_code_sha256": sha256(EVALUATION_CODE),
        "models": MODELS,
        "repeats": REPEATS,
        "with_retrieval": True,
        "retrieval_strategies": STRATEGIES,
        "top_k": TOP_K,
        "problem_source": "detected",
    }
    matrix = _write_json(
        tmp_path / "matrix.json",
        {
            "metadata": {
                "created_at": "2099-01-02T00:00:00+00:00",
                "test_cases": len(cases),
                "models": MODELS,
                "repeats": REPEATS,
                "with_retrieval": True,
                "retrieval_strategies": STRATEGIES,
                "top_k": TOP_K,
                "problem_source": "detected",
                "evaluation_slices": {
                    "adversarial_test": 2,
                    "overall_test": 1,
                },
                "run_signature": run_signature,
            },
            "per_case": per_case,
        },
    )
    return matrix, ground_truth, taxonomy


def _build(matrix: Path, ground_truth: Path, taxonomy: Path):
    return build_report(
        matrix,
        ground_truth,
        taxonomy,
        expected_cases=2,
        expected_test_cases=3,
        expected_models=2,
        expected_repeats=2,
        expected_strategies=2,
        expected_top_k=2,
    )


def test_complete_matrix_detector_retrieval_and_provenance(tmp_path):
    matrix, ground_truth, taxonomy = _fixture(tmp_path)
    result = _build(matrix, ground_truth, taxonomy)
    assert result["status"] == "complete"

    model_a = result["detector_by_model"]["model-a"]
    assert model_a["target_code_hits"] == 5
    assert model_a["target_code_opportunities"] == 6
    assert model_a["target_code_recall"] == pytest.approx(5 / 6)
    assert model_a["complete_target_preservation_rate"] == pytest.approx(3 / 4)
    assert model_a["false_trigger_suppression_rate"] == pytest.approx(3 / 4)
    assert model_a["joint_pass_rate"] == pytest.approx(2 / 4)

    overall = result["detector_overall"]
    assert overall["target_code_hits"] == 9
    assert overall["target_code_opportunities"] == 12
    assert overall["target_code_recall"] == pytest.approx(3 / 4)
    assert overall["false_trigger_activation_count"] == 2
    assert overall["joint_pass_count"] == 5
    assert overall["joint_pass_rate"] == pytest.approx(5 / 8)
    assert overall["l2_degraded_rows"] == 1

    model_a_basic = result["retrieval_by_model_strategy"]["model-a"]["basic"]
    assert model_a_basic["n_rows"] == 4
    assert model_a_basic["n_unique_cases"] == 2
    assert model_a_basic["repeats_per_case"] == [2]
    assert model_a_basic["nDCG@5"] == pytest.approx(0.5)
    assert model_a_basic["nDCG@5_std_across_cases"] == pytest.approx(
        0.282842712474619
    )
    assert result["retrieval_by_model_strategy"]["model-a"]["h2l-hybrid"][
        "nDCG@5"
    ] == pytest.approx(0.9)

    metadata = result["metadata"]
    assert metadata["ground_truth_sha256"] == sha256(ground_truth)
    assert metadata["taxonomy_sha256"] == sha256(taxonomy)
    assert metadata["matrix_sha256"] == sha256(matrix)
    assert metadata["problem_source"] == "detected"
    assert metadata["n_adversarial_cases"] == 2
    assert metadata["validation"] == "complete_matrix_schema_and_provenance_verified"

    markdown = markdown_report(result)
    assert "## Retrieval" in markdown
    assert "5/6" in markdown
    assert "model-a | basic | 2 | 0.5000" in markdown

    json_output = tmp_path / "report.json"
    markdown_output = tmp_path / "report.md"
    write_report(result, json_output, markdown_output)
    assert json.loads(json_output.read_text(encoding="utf-8"))["metadata"] == metadata
    assert "## Retrieval" in markdown_output.read_text(encoding="utf-8")


def test_complete_matrix_rejects_missing_retrieval_metric(tmp_path):
    matrix, ground_truth, taxonomy = _fixture(tmp_path)
    payload = json.loads(matrix.read_text(encoding="utf-8"))
    del payload["per_case"]["model-a"][0]["retrieval_metrics"]["basic"]["MRR"]
    _write_json(matrix, payload)

    with pytest.raises(ValueError, match="is missing MRR"):
        _build(matrix, ground_truth, taxonomy)


def test_complete_matrix_rejects_duplicate_case_repeat_row(tmp_path):
    matrix, ground_truth, taxonomy = _fixture(tmp_path)
    payload = json.loads(matrix.read_text(encoding="utf-8"))
    payload["per_case"]["model-a"][-1] = copy.deepcopy(
        payload["per_case"]["model-a"][0]
    )
    _write_json(matrix, payload)

    with pytest.raises(ValueError, match="duplicate case/repeat rows"):
        _build(matrix, ground_truth, taxonomy)


def test_complete_matrix_rejects_stale_ground_truth_provenance(tmp_path):
    matrix, ground_truth, taxonomy = _fixture(tmp_path)
    payload = json.loads(matrix.read_text(encoding="utf-8"))
    payload["metadata"]["run_signature"]["ground_truth_sha256"] = "stale"
    _write_json(matrix, payload)

    with pytest.raises(ValueError, match="run_signature.ground_truth_sha256 mismatch"):
        _build(matrix, ground_truth, taxonomy)

import json
from pathlib import Path

import pytest
from scipy.stats import wilcoxon

from scripts.build_statistical_analysis import build_artifact
from scripts.derive_latest_retrieval_metrics import sha256


def _write_json(path: Path, payload) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    ground_truth = _write_json(tmp_path / "ground_truth.json", {"cases": []})
    taxonomy = _write_json(tmp_path / "taxonomy.json", {"P1": {"name": "Problem"}})
    rows = []
    hybrid_values = [0.875, 0.75, 0.375, 0.25]
    baseline_values = [0.25, 0.625, 0.5, 0.125]
    for index, (hybrid, baseline) in enumerate(zip(hybrid_values, baseline_values), start=1):
        rows.append({
            "model": "qwen2.5:7b",
            "repeat": 1,
            "case_id": f"CASE_{index:03d}",
            "retrieval_metrics": {
                "basic": {
                    "nDCG@5": baseline,
                    "nDCG@10": baseline,
                    "MAP": baseline,
                    "MRR": baseline,
                },
                "h2l-hybrid": {
                    "nDCG@5": hybrid,
                    "nDCG@10": hybrid,
                    "MAP": hybrid,
                    "MRR": hybrid,
                },
            },
        })
    matrix = _write_json(
        tmp_path / "matrix.json",
        {
            "metadata": {
                "created_at": "2099-01-01T00:00:00+07:00",
                "models": ["qwen2.5:7b"],
                "repeats": 1,
                "test_cases": 4,
                "retrieval_strategies": ["basic", "h2l-hybrid"],
                "top_k": 15,
                "problem_source": "detected",
                "run_signature": {
                    "taxonomy_sha256": sha256(taxonomy),
                    "ground_truth_sha256": sha256(ground_truth),
                },
            },
            "per_case": {"qwen2.5:7b": rows},
        },
    )
    return matrix, ground_truth, taxonomy


def test_builder_uses_two_sided_wilcoxon_and_records_source_hash(tmp_path):
    matrix, ground_truth, taxonomy = _inputs(tmp_path)
    output = tmp_path / "statistics.json"
    result = build_artifact(
        matrix,
        output,
        ground_truth=ground_truth,
        taxonomy=taxonomy,
    )

    differences = [0.625, 0.125, -0.125, 0.125]
    expected_p = wilcoxon(
        differences,
        zero_method="wilcox",
        alternative="two-sided",
        method="auto",
    ).pvalue
    pair = result["nDCG@5"]["pairs"][0]
    assert pair["raw_p"] == pytest.approx(expected_p)
    assert pair["holm_p"] == pytest.approx(expected_p)
    assert result["alternative"] == "two-sided"
    assert result["source_sha256"] == sha256(matrix)
    assert result["current_input_match"] is True
    assert output.exists()


def test_builder_fails_closed_on_stale_inputs_unless_explicitly_versioned(tmp_path):
    matrix, ground_truth, taxonomy = _inputs(tmp_path)
    taxonomy.write_text('{"P1":{"name":"Changed"}}', encoding="utf-8")

    with pytest.raises(ValueError, match="Matrix inputs do not match"):
        build_artifact(
            matrix,
            tmp_path / "strict.json",
            ground_truth=ground_truth,
            taxonomy=taxonomy,
        )

    versioned = build_artifact(
        matrix,
        tmp_path / "versioned.json",
        ground_truth=ground_truth,
        taxonomy=taxonomy,
        allow_versioned_source=True,
    )
    assert versioned["provenance_status"] == "versioned-source"
    assert versioned["current_input_match"] is False

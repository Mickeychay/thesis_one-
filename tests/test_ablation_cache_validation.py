import json

import pytest

from eval.ablation_study import AblationRunner


MODEL = "qwen2.5:7b"


def write_fixture(tmp_path, *, ground_truth_ids, cache_ids):
    ground_truth = tmp_path / "ground_truth.json"
    ground_truth.write_text(
        json.dumps({
            "metadata": {"test_cases": len(ground_truth_ids)},
            "cases": [
                {
                    "case_id": case_id,
                    "split": "test",
                    "case_description": case_id,
                    "expected_diagnosis": {
                        "problem_list": [{"code": "1001"}],
                    },
                }
                for case_id in ground_truth_ids
            ],
        }),
        encoding="utf-8",
    )
    cache = tmp_path / "matrix.json"
    cache.write_text(
        json.dumps({
            "metadata": {
                "created_at": "2026-08-08T00:00:00+07:00",
                "models": [MODEL],
                "repeats": 3,
                "test_cases": len(ground_truth_ids),
                "top_k": 15,
                "retrieval_strategies": ["h2l-hybrid"],
            },
            "per_case": {
                MODEL: [
                    {
                        "case_id": case_id,
                        "repeat": 1,
                        "expected_codes": ["1001"],
                        "detected_problems": [{"code": "1001"}],
                    }
                    for case_id in cache_ids
                ],
            },
        }),
        encoding="utf-8",
    )
    return ground_truth, cache


def test_smoke_run_accepts_full_split_cache_as_superset(tmp_path):
    ground_truth, cache = write_fixture(
        tmp_path,
        ground_truth_ids=["CASE_1", "CASE_2", "CASE_3"],
        cache_ids=["CASE_1", "CASE_2", "CASE_3"],
    )
    runner = AblationRunner(
        ground_truth_path=str(ground_truth),
        split="test",
        max_cases=1,
        detected_problems_cache_path=str(cache),
    )

    provenance = runner.validate_detected_problems_cache()

    assert provenance["selected_cases"] == 1
    assert provenance["cached_cases"] == 3
    assert provenance["case_set_validation"] == "selected_subset_of_cache"


def test_full_run_still_requires_an_exact_cache_case_set(tmp_path):
    ground_truth, cache = write_fixture(
        tmp_path,
        ground_truth_ids=["CASE_1", "CASE_2"],
        cache_ids=["CASE_1", "CASE_2", "EXTRA"],
    )
    runner = AblationRunner(
        ground_truth_path=str(ground_truth),
        split="test",
        detected_problems_cache_path=str(cache),
    )

    with pytest.raises(ValueError, match="does not match the selected split"):
        runner.validate_detected_problems_cache()


def test_smoke_run_rejects_a_cache_missing_the_selected_case(tmp_path):
    ground_truth, cache = write_fixture(
        tmp_path,
        ground_truth_ids=["CASE_1", "CASE_2"],
        cache_ids=["CASE_2"],
    )
    runner = AblationRunner(
        ground_truth_path=str(ground_truth),
        split="test",
        max_cases=1,
        detected_problems_cache_path=str(cache),
    )

    with pytest.raises(ValueError, match=r"missing=\['CASE_1'\]"):
        runner.validate_detected_problems_cache()

"""Guards for RQ1's L2 ablation.

RQ1 previously varied H2LConfigV3.L1_WEIGHT_BETA (0.3 vs 1.0) to represent
"L2 on vs off". That parameter is never read by any scoring function, so both
arms ran the identical pipeline and produced byte-identical metrics on all 95
test cases — a false null result. These tests pin the corrected behaviour:
L2 is ablated at detection time via use_l2, and the failure modes that
previously went unnoticed now raise or log an error.
"""

import json
import logging

import pandas as pd
import pytest

from eval.ablation_study import AblationRunner, RQ1_L2Filtering


MODEL = "qwen2.5:7b"


class FakeDetector:
    """Records the use_l2 value it was called with."""

    def __init__(self):
        self.calls = []

    def detect_problems(self, case_text, use_l2=True):
        self.calls.append(use_l2)
        # L2 validation filters candidates, so the L1-only arm returns more.
        if use_l2:
            return [{"code": "1001", "confidence": 0.9}]
        return [
            {"code": "1001", "confidence": 0.9},
            {"code": "9999", "confidence": 0.4},
        ]


def write_ground_truth(tmp_path, case_ids):
    path = tmp_path / "ground_truth.json"
    path.write_text(
        json.dumps({
            "metadata": {"test_cases": len(case_ids)},
            "cases": [
                {
                    "case_id": case_id,
                    "split": "test",
                    "case_description": f"description for {case_id}",
                    "expected_diagnosis": {"problem_list": [{"code": "1001"}]},
                }
                for case_id in case_ids
            ],
        }),
        encoding="utf-8",
    )
    return path


def write_cache(tmp_path, case_ids):
    path = tmp_path / "matrix.json"
    path.write_text(
        json.dumps({
            "metadata": {
                "created_at": "2026-08-08T00:00:00+07:00",
                "models": [MODEL],
                "repeats": 3,
                "test_cases": len(case_ids),
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
                    for case_id in case_ids
                ],
            },
        }),
        encoding="utf-8",
    )
    return path


def test_rq1_refuses_to_run_against_a_detected_problems_cache(tmp_path):
    """The cache holds one fixed L2-validated list, so both arms would match."""
    ground_truth = write_ground_truth(tmp_path, ["CASE_1"])
    cache = write_cache(tmp_path, ["CASE_1"])
    runner = AblationRunner(
        ground_truth_path=str(ground_truth),
        split="test",
        detected_problems_cache_path=str(cache),
    )

    with pytest.raises(ValueError, match="cannot run against a detected-problems cache"):
        RQ1_L2Filtering().run(runner)


def test_l1_only_condition_refuses_to_serve_cached_l2_problems(tmp_path):
    ground_truth = write_ground_truth(tmp_path, ["CASE_1"])
    cache = write_cache(tmp_path, ["CASE_1"])
    runner = AblationRunner(
        ground_truth_path=str(ground_truth),
        split="test",
        detected_problems_cache_path=str(cache),
    )
    case = {"case_id": "CASE_1", "case_description": "x"}

    with pytest.raises(ValueError, match="both arms would be identical"):
        runner.detected_problems_for_case(case, runner=None, use_l2=False)


def test_use_l2_reaches_the_detector(tmp_path):
    """Without this wiring the two RQ1 arms are the same pipeline run twice."""
    from evaluate_h2l_proper import EvaluationRunner

    detector = FakeDetector()
    runner = EvaluationRunner.__new__(EvaluationRunner)
    runner._ensure_detector = lambda: detector

    on = runner.detect_problems("case text", use_l2=True)
    off = runner.detect_problems("case text", use_l2=False)

    assert detector.calls == [True, False]
    assert len(on) == 1
    assert len(off) == 2


def test_detect_problems_defaults_to_using_l2():
    from evaluate_h2l_proper import EvaluationRunner

    detector = FakeDetector()
    runner = EvaluationRunner.__new__(EvaluationRunner)
    runner._ensure_detector = lambda: detector

    runner.detect_problems("case text")

    assert detector.calls == [True]


def test_manipulation_check_errors_when_both_arms_detect_the_same_problems(caplog):
    """This is the exact shape of the false null result RQ1 produced before."""
    df = pd.DataFrame([
        {"variant": "L1+L2 detection", "case_id": "C1", "n_problems": 3},
        {"variant": "L1-only detection", "case_id": "C1", "n_problems": 3},
        {"variant": "L1+L2 detection", "case_id": "C2", "n_problems": 2},
        {"variant": "L1-only detection", "case_id": "C2", "n_problems": 2},
    ])

    with caplog.at_level(logging.ERROR):
        RQ1_L2Filtering._manipulation_check(df)

    assert "manipulation check FAILED" in caplog.text


def test_manipulation_check_passes_when_the_arms_differ(caplog):
    df = pd.DataFrame([
        {"variant": "L1+L2 detection", "case_id": "C1", "n_problems": 1},
        {"variant": "L1-only detection", "case_id": "C1", "n_problems": 2},
        {"variant": "L1+L2 detection", "case_id": "C2", "n_problems": 2},
        {"variant": "L1-only detection", "case_id": "C2", "n_problems": 2},
    ])

    with caplog.at_level(logging.ERROR):
        RQ1_L2Filtering._manipulation_check(df)

    assert "manipulation check FAILED" not in caplog.text


def test_beta_is_not_used_as_an_l2_switch_anywhere_in_rq1():
    """Regression guard: β has no implementation, so it cannot ablate L2."""
    import inspect

    source = inspect.getsource(RQ1_L2Filtering)
    run_body = inspect.getsource(RQ1_L2Filtering.run)

    assert "use_l2" in run_body
    # β may only appear in the explanatory docstring, never in executed code.
    assert "L1_WEIGHT_BETA" not in run_body
    assert "L1_WEIGHT_BETA" in source  # the warning note is retained

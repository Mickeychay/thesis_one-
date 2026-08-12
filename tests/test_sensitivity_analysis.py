import csv
import json
from pathlib import Path

import pytest

from h2l import core
from eval.sensitivity_analysis import (
    PARAMETER_SWEEPS,
    SensitivityAnalyzer,
    build_run_metadata,
    file_sha256,
    generate_csv,
    generate_report,
)


def _write_ground_truth(path: Path) -> Path:
    cases = []
    for index in range(125):
        problem_list = [] if index < 10 else [
            {
                "code": "P1",
                "category": "Support need",
                "severity": 3,
            }
        ]
        cases.append(
            {
                "case_id": f"TRAIN_{index:03d}",
                "split": "train",
                "case_description": f"train description {index}",
                "expected_diagnosis": {"problem_list": problem_list},
                "relevant_keywords": {"P1": ["support"]},
            }
        )
    for index in range(95):
        cases.append(
            {
                "case_id": f"TEST_{index:03d}",
                "split": "test",
                "case_description": f"test description {index}",
                "expected_diagnosis": {"problem_list": []},
            }
        )

    path.write_text(
        json.dumps(
            {
                "metadata": {
                    "total_cases": 220,
                    "train_cases": 125,
                    "test_cases": 95,
                    "last_updated": "2099-01-01T00:00:00",
                },
                "cases": cases,
            }
        ),
        encoding="utf-8",
    )
    return path


def _successful_score(**kwargs):
    assert kwargs["query_text"] == kwargs["doc_text"]
    return 0.75, {
        "boost": 1.2,
        "α_eff": 1.1,
        "factors": [{"Φ_i": 0.4}],
    }


def test_full_train_selection_distinguishes_selected_scored_and_skipped(
    tmp_path, monkeypatch
):
    ground_truth = _write_ground_truth(tmp_path / "ground_truth.json")
    monkeypatch.setattr(
        core,
        "calculate_final_score_probabilistic",
        _successful_score,
    )

    analyzer = SensitivityAnalyzer(str(ground_truth))
    metrics = analyzer.run_single_config(object())

    assert len(analyzer.cases) == 125
    assert len(analyzer.scorable_cases) == 115
    assert len(analyzer.skipped_case_ids) == 10
    assert analyzer.skipped_case_ids == [f"TRAIN_{index:03d}" for index in range(10)]
    assert metrics["n_scored"] == 115
    assert len(metrics["scored_case_ids"]) == 115


def test_scoring_exception_aborts_instead_of_changing_case_set(tmp_path, monkeypatch):
    ground_truth = _write_ground_truth(tmp_path / "ground_truth.json")

    def failing_score(**kwargs):
        if kwargs["doc_text"] == "train description 10":
            raise ValueError("synthetic scoring failure")
        return _successful_score(**kwargs)

    monkeypatch.setattr(
        core,
        "calculate_final_score_probabilistic",
        failing_score,
    )
    analyzer = SensitivityAnalyzer(str(ground_truth))

    with pytest.raises(RuntimeError, match="TRAIN_010.*synthetic scoring failure"):
        analyzer.run_single_config(object())


def test_csv_and_metadata_match_chapter4_evidence_contract(tmp_path, monkeypatch):
    ground_truth = _write_ground_truth(tmp_path / "ground_truth.json")
    monkeypatch.setattr(
        core,
        "calculate_final_score_probabilistic",
        _successful_score,
    )
    analyzer = SensitivityAnalyzer(str(ground_truth))
    baseline = analyzer.run_single_config(object())

    results = {}
    for sweep in PARAMETER_SWEEPS:
        results[sweep.name] = {}
        for value in sweep.values:
            metrics = dict(baseline)
            metrics["mean_score"] = baseline["mean_score"] + (value - sweep.default) * 0.001
            results[sweep.name][value] = metrics

    generate_csv(results, baseline, tmp_path, expected_n_scored=115)
    with (tmp_path / "sensitivity_raw.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    required = {
        "parameter",
        "label",
        "value",
        "is_default",
        "mean_score",
        "delta_score_pct",
        "n_scored",
    }
    assert required.issubset(rows[0])
    assert {row["parameter"] for row in rows} == {sweep.name for sweep in PARAMETER_SWEEPS}
    assert {int(row["n_scored"]) for row in rows} == {115}
    for sweep in PARAMETER_SWEEPS:
        parameter_rows = [row for row in rows if row["parameter"] == sweep.name]
        assert sum(row["is_default"] == "True" for row in parameter_rows) == 1

    metadata = build_run_metadata(
        analyzer,
        baseline,
        started_at="2099-01-01T00:00:00+07:00",
    )
    assert metadata["status"] == "complete"
    assert metadata["analysis_scope"] == "score_function_oat"
    assert metadata["selected_cases"] == 125
    assert metadata["scored_cases"] == 115
    assert metadata["skipped_empty_problem_lists"] == 10
    assert metadata["ground_truth_sha256"] == file_sha256(ground_truth)
    assert metadata["h2l_core_sha256"] == file_sha256(
        Path(__file__).resolve().parents[1] / "h2l" / "core.py"
    )
    assert metadata["case_set_invariant_verified"] is True
    assert metadata["scoring_assumptions"]["retrieval_executed"] is False
    assert set(metadata["scoring_assumptions"]["not_exercised_parameters"]) == {
        "MARGIN_M",
        "L1_WEIGHT_BETA",
    }

    generate_report(results, baseline, 125, 115, 10, tmp_path)
    report = (tmp_path / "sensitivity_report.md").read_text(encoding="utf-8")
    assert "**Retrieval executed**: `false`" in report
    assert "Not exercised in this score-function setup" in report
    assert "ความไวของฟังก์ชันคะแนน" in report
    for informal_phrase in ("โมเดลฉลาดพอ", "คำหลอก", "รวนง่าย", "คะแนนมั่ว"):
        assert informal_phrase not in report

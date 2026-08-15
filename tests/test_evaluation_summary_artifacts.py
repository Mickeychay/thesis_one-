from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.main import (
    _artifact_input_status,
    _evaluation_progress_summary,
    _evaluation_summary,
    _statistical_artifact_status,
)


def test_evaluation_summary_uses_latest_aliases():
    summary = _evaluation_summary()

    proper = summary["proper_eval"]
    polarity = summary["polarity_eval"]
    data_sources = summary["data_sources"]

    assert proper["source"].endswith("evaluation_results/proper_eval_latest_summary.json")
    assert polarity["source"].endswith("evaluation_results/sentence_polarity_latest.json")

    inventory = data_sources["artifact_inventory"]
    assert "history_retention_policy" in inventory
    assert inventory["proper_eval_history_count"] >= 0
    assert inventory["polarity_history_count"] >= 0


def test_evaluation_progress_summary_has_real_paths():
    progress = _evaluation_progress_summary()

    proper = progress["proper_eval"]
    polarity = progress["sentence_polarity"]

    assert proper["source"].endswith("evaluation_results/proper_eval_progress.json")
    assert polarity["source"].endswith("evaluation_results/sentence_polarity_progress.json")
    assert Path(proper["source"]).name == "proper_eval_progress.json"
    assert Path(polarity["source"]).name == "sentence_polarity_progress.json"


def test_missing_artifact_hashes_are_stale():
    status = _artifact_input_status({}, "taxonomy-current", "ground-truth-current")
    assert status["taxonomy_hash_present"] is False
    assert status["ground_truth_hash_present"] is False
    assert status["current"] is False


def test_statistical_artifact_requires_current_inputs_source_hash_and_two_sided(tmp_path):
    source = tmp_path / "matrix.json"
    source.write_text("{}", encoding="utf-8")
    from api.main import _file_sha256

    valid = _statistical_artifact_status(
        {
            "source": str(source),
            "source_sha256": _file_sha256(source),
            "taxonomy_sha256": "taxonomy-current",
            "ground_truth_sha256": "ground-truth-current",
            "statistical_test": "paired two-sided Wilcoxon signed-rank",
            "alternative": "two-sided",
        },
        "taxonomy-current",
        "ground-truth-current",
    )
    assert valid["current"] is True

    one_sided = _statistical_artifact_status(
        {
            **{
                "source": str(source),
                "source_sha256": _file_sha256(source),
                "taxonomy_sha256": "taxonomy-current",
                "ground_truth_sha256": "ground-truth-current",
                "statistical_test": "paired Wilcoxon signed-rank",
            },
            "alternative": "greater",
        },
        "taxonomy-current",
        "ground-truth-current",
    )
    assert one_sided["current"] is False

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api import _evaluation_progress_summary, _evaluation_summary


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

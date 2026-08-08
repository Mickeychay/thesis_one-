#!/usr/bin/env python3
"""Focused regressions for sentence-polarity evaluation artifacts."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import evaluate_sentence_polarity as evaluator


class TestSentencePolarityEvaluator(unittest.TestCase):
    def _write_json(self, directory, name, payload):
        path = Path(directory) / name
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def test_taxonomy_loader_supports_flat_and_legacy_schemas(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            flat_path = self._write_json(
                tmpdir,
                "flat.json",
                {
                    "1001": {
                        "name": "Financial problem",
                        "category": "Finance",
                        "severity": 3,
                        "keywords": ["debt"],
                    }
                },
            )
            legacy_path = self._write_json(
                tmpdir,
                "legacy.json",
                {
                    "categories": [
                        {
                            "id": "C1",
                            "name": "Legacy Category",
                            "problems": [
                                {
                                    "code": "L1",
                                    "name": "Legacy problem",
                                    "severity": 4,
                                    "keywords": ["legacy"],
                                }
                            ],
                        }
                    ]
                },
            )

            flat = evaluator.load_problems_from_taxonomy(flat_path)
            legacy = evaluator.load_problems_from_taxonomy(legacy_path)

        self.assertEqual(flat["1001"]["category_name"], "Finance")
        self.assertEqual(flat["1001"]["category_id"], "Finance")
        self.assertEqual(flat["1001"]["keywords"], ["debt"])
        self.assertEqual(legacy["L1"]["category_id"], "C1")
        self.assertEqual(legacy["L1"]["category_name"], "Legacy Category")

    def test_adversarial_slice_tracks_targets_and_false_triggers(self):
        ground_truth = {
            "metadata": {"test_cases": 2},
            "cases": [
                {
                    "case_id": "ADV_TEST_1",
                    "category": "adversarial_l2_test",
                    "evaluation_slice": "adversarial_test",
                    "split": "test",
                    "is_negated": False,
                    "case_description": "target one with a denied false trigger",
                    "expected_diagnosis": {
                        "problem_list": [{"code": "TARGET_A", "severity": 3}]
                    },
                    "relevant_keywords": {"TARGET_A": ["target one"]},
                    "augmentation": {
                        "type": "adversarial",
                        "false_trigger_code": "FALSE_NEG",
                        "trigger_word": "false trigger",
                    },
                },
                {
                    "case_id": "ADV_TEST_2",
                    "category": "adversarial_l2_test",
                    "evaluation_slice": "adversarial_test",
                    "split": "test",
                    "is_negated": False,
                    "case_description": "target two and another person's false subject",
                    "expected_diagnosis": {
                        "problem_list": [{"code": "TARGET_B", "severity": 3}]
                    },
                    "relevant_keywords": {"TARGET_B": ["target two"]},
                    "augmentation": {
                        "type": "adversarial",
                        "false_trigger_code": "FALSE_SUB",
                        "trigger_word": "false subject",
                    },
                },
            ],
        }
        taxonomy = {
            "TARGET_A": {
                "name": "Target A",
                "category": "Targets",
                "severity": 3,
                "keywords": ["target one"],
            },
            "TARGET_B": {
                "name": "Target B",
                "category": "Targets",
                "severity": 3,
                "keywords": ["target two"],
            },
            "FALSE_NEG": {
                "name": "False negated trigger",
                "category": "Distractors",
                "severity": 4,
                "keywords": ["taxonomy false term"],
            },
        }
        gate_results = {
            "TARGET_A": {"gate_total": 1.0, "gate_neg": 1.0, "gate_len": 1.0, "gate_sub": 1.0},
            "TARGET_B": {"gate_total": 0.4, "gate_neg": 0.4, "gate_len": 1.0, "gate_sub": 1.0},
            "FALSE_NEG": {"gate_total": 0.4, "gate_neg": 0.4, "gate_len": 1.0, "gate_sub": 1.0},
            "FALSE_SUB": {"gate_total": 0.85, "gate_neg": 1.0, "gate_len": 1.0, "gate_sub": 0.85},
        }

        def fake_polarity(problem, _query, _config):
            return gate_results[problem["code"]]

        with tempfile.TemporaryDirectory() as tmpdir:
            gt_path = self._write_json(tmpdir, "ground_truth.json", ground_truth)
            taxonomy_path = self._write_json(tmpdir, "taxonomy.json", taxonomy)
            progress_path = Path(tmpdir) / "progress.json"
            with (
                patch.object(evaluator, "calculate_sentence_polarity", side_effect=fake_polarity),
                patch.object(evaluator, "POLARITY_PROGRESS_ARTIFACT", progress_path),
            ):
                results = evaluator.evaluate_sentence_polarity(gt_path, taxonomy_path)

        self.assertEqual(results["overall"]["total_cases"], 2)
        self.assertEqual(results["overall"]["false_positive_rate"], 0.5)

        first, second = results["per_case"]
        self.assertEqual(first["evaluation_slice"], "adversarial_test")
        self.assertEqual(first["category"], "adversarial_l2_test")
        self.assertEqual(first["augmentation"]["false_trigger_code"], "FALSE_NEG")
        self.assertTrue(first["target_gate_evaluated"])
        self.assertTrue(first["target_preserved"])
        self.assertTrue(first["adversarial_false_trigger"]["taxonomy_problem_found"])
        self.assertTrue(first["adversarial_false_trigger"]["evaluated"])
        self.assertIn("false trigger", first["adversarial_false_trigger"]["keywords_used"])
        self.assertFalse(second["target_preserved"])
        self.assertFalse(second["adversarial_false_trigger"]["taxonomy_problem_found"])
        self.assertEqual(second["adversarial_false_trigger"]["keywords_used"], ["false subject"])

        summary = results["slice_summaries"]["adversarial_test"]
        self.assertEqual(summary["n_cases"], 2)
        self.assertEqual(summary["n_positive"], 2)
        self.assertEqual(summary["n_negated"], 0)
        self.assertEqual(summary["target_evaluated_count"], 2)
        self.assertEqual(summary["target_preservation_rate"], 0.5)
        self.assertEqual(summary["false_suppression_rate"], 0.5)
        self.assertEqual(summary["false_trigger_negation_suppression_rate"], 0.5)
        self.assertEqual(summary["false_trigger_subject_suppression_rate"], 0.5)
        self.assertEqual(summary["false_trigger_contextual_suppression_rate"], 1.0)
        self.assertEqual(summary["joint_pass_rate"], 0.5)
        self.assertEqual(summary["thresholds"]["comparison"], "strictly_less_than")
        self.assertIn("Adversarial Test Slice", evaluator.format_results_text(results))


if __name__ == "__main__":
    unittest.main()

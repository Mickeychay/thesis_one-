#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for research-integrity guardrails."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class TestIntegrityConfig(unittest.TestCase):
    def test_integrity_flags_disabled_by_default(self):
        from h2l.config import Config

        self.assertFalse(Config.ALLOW_DEMO_DATA)
        self.assertFalse(Config.ALLOW_SYNTHETIC_STATS)
        self.assertFalse(Config.ALLOW_GROUND_TRUTH_INDEX)


class TestSyntheticStatisticsGuard(unittest.TestCase):
    def test_summary_synthetic_data_requires_explicit_flag(self):
        from eval.statistical_analysis import load_summary_as_synthetic_data

        with tempfile.TemporaryDirectory() as tmp:
            summary_path = Path(tmp) / "benchmark_summary_test.json"
            summary_path.write_text(
                json.dumps(
                    {
                        "bm25_only": {
                            "total_queries": 3,
                            "successful_queries": 3,
                            "avg_quality": 0.5,
                        }
                    }
                ),
                encoding="utf-8",
            )

            self.assertIsNone(
                load_summary_as_synthetic_data(str(summary_path), allow_synthetic=False)
            )
            synthetic = load_summary_as_synthetic_data(str(summary_path), allow_synthetic=True)
            self.assertIn("bm25_only", synthetic)


class TestGroundTruthIndexGuard(unittest.TestCase):
    def test_ground_truth_loader_strips_labels_unless_explicit(self):
        from scripts.index_documents import load_ground_truth_documents

        case = {
            "case_id": "q_test",
            "case_description": "ผู้รับบริการมีภาวะเครียดจากปัญหาครอบครัว",
            "category": "test",
            "expected_diagnosis": {
                "problem_list": [{"code": "F43", "severity": 3}]
            },
            "relevant_keywords": {"F43": ["เครียด"]},
        }

        with tempfile.TemporaryDirectory() as tmp:
            gt_path = Path(tmp) / "gt.json"
            gt_path.write_text(json.dumps({"cases": [case]}, ensure_ascii=False), encoding="utf-8")

            stripped = load_ground_truth_documents(str(gt_path), include_labels=False)
            self.assertEqual(len(stripped), 1)
            self.assertNotIn("expected_diagnosis_full", stripped[0])
            self.assertNotIn("problem_codes", stripped[0])
            self.assertNotIn("relevant_keywords", stripped[0])

            labeled = load_ground_truth_documents(str(gt_path), include_labels=True)
            self.assertIn("expected_diagnosis_full", labeled[0])
            self.assertIn("problem_codes", labeled[0])
            self.assertIn("relevant_keywords", labeled[0])
            self.assertEqual(labeled[0]["data_source"], "ground_truth_label_index")


class TestEvaluationArtifactProvenance(unittest.TestCase):
    def test_proper_evaluation_payload_records_input_hashes(self):
        from eval.evaluate_h2l_proper import build_results_payload, _sha256_file

        with tempfile.TemporaryDirectory() as tmp:
            ground_truth = Path(tmp) / "ground_truth.json"
            taxonomy = Path(tmp) / "taxonomy.json"
            ground_truth.write_text('{"cases":[]}', encoding="utf-8")
            taxonomy.write_text('{"P1":{"name":"Problem"}}', encoding="utf-8")

            payload = build_results_payload(
                cases=[],
                strategies=["basic"],
                top_k=15,
                problem_source="detected",
                per_strategy={},
                aggregates={},
                ground_truth_path=str(ground_truth),
                taxonomy_path=str(taxonomy),
            )

            metadata = payload["metadata"]
            self.assertEqual(metadata["ground_truth_sha256"], _sha256_file(str(ground_truth)))
            self.assertEqual(metadata["taxonomy_sha256"], _sha256_file(str(taxonomy)))
            self.assertTrue(metadata["evaluation_code_sha256"])


class TestVisualizationGuard(unittest.TestCase):
    def test_3d_visualization_does_not_create_demo_docs_by_default(self):
        from visualizations import create_3d_vector_space_with_hover

        fig = create_3d_vector_space_with_hover(
            problems=[{"code": "F32", "name": "ซึมเศร้า", "severity": 4, "confidence": 0.8}],
            real_docs=None,
            dr_method="UMAP",
            demo_mode=False,
        )

        trace_names = [getattr(trace, "name", "") for trace in fig.data]
        self.assertNotIn("🟢 Relevant Docs", trace_names)
        self.assertNotIn("⚪ Other Docs", trace_names)
        annotation_texts = [ann.text for ann in fig.layout.annotations]
        self.assertTrue(any("Synthetic document points are disabled" in text for text in annotation_texts))


if __name__ == "__main__":
    unittest.main()

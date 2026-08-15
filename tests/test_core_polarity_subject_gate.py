#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regressions for the H2L core subject gate (G_sub) and dense similarity conversion."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from h2l.core import H2LConfigV3, calculate_sentence_polarity


SEVERE_PROBLEM = {
    "name": "ถูกข่มขืน",
    "keywords": ["ข่มขืน"],
    "severity": 5,
}


class TestSubjectGate(unittest.TestCase):
    def setUp(self):
        self.config = H2LConfigV3()

    def _gate_sub(self, text, problem=None):
        result = calculate_sentence_polarity(problem or SEVERE_PROBLEM, text, self.config)
        return result["gate_sub"]

    def test_reported_media_framing_is_penalised_more_than_third_party(self):
        reported = self._gate_sub("อ่านข่าวข่มขืนแล้วรู้สึกกลัว")
        third_party = self._gate_sub("เพื่อนบ้านถูกข่มขืน")

        self.assertEqual(reported, self.config.SUB_REPORTED_LAMBDA)
        self.assertEqual(third_party, self.config.SUB_LAMBDA)
        self.assertLess(reported, third_party)

    def test_client_attribution_is_not_penalised(self):
        for text in ("ผู้ป่วยถูกข่มขืน", "ฉันถูกข่มขืน", "หนูถูกข่มขืนเมื่อปีที่แล้ว"):
            with self.subTest(text=text):
                self.assertEqual(self._gate_sub(text), 1.0)

    def test_self_marker_overrides_third_party_and_reported_markers(self):
        text = "ผู้ป่วยเล่าว่าอ่านข่าวข่มขืน และตัวผู้ป่วยเองก็เคยถูกข่มขืน"
        self.assertEqual(self._gate_sub(text), 1.0)

    def test_gate_inactive_below_minimum_severity(self):
        low_severity = {"name": "หนี้สิน", "keywords": ["หนี้"], "severity": 2}
        self.assertEqual(self._gate_sub("เพื่อนบ้านมีหนี้สินจำนวนมาก", low_severity), 1.0)

    def test_lexicons_are_config_overridable(self):
        config = H2LConfigV3()
        config.REPORTED_MARKERS = ["พอดแคสต์"]
        config.OTHER_SUBJECTS = []
        result = calculate_sentence_polarity(
            SEVERE_PROBLEM, "ฟังพอดแคสต์เรื่องข่มขืน", config
        )
        self.assertEqual(result["gate_sub"], config.SUB_REPORTED_LAMBDA)

    def test_default_lexicons_are_not_shared_between_instances(self):
        first = H2LConfigV3()
        first.OTHER_SUBJECTS.append("__sentinel__")
        self.assertNotIn("__sentinel__", H2LConfigV3().OTHER_SUBJECTS)


class TestNegationWindow(unittest.TestCase):
    def setUp(self):
        self.config = H2LConfigV3()

    def test_negation_window_is_configurable_and_look_back_only(self):
        problem = {"name": "ถูกทำร้าย", "keywords": ["ทำร้าย"], "severity": 4}

        preceding = calculate_sentence_polarity(problem, "ไม่ได้ถูกทำร้าย", self.config)
        self.assertLess(preceding["gate_neg"], 1.0)

        trailing = calculate_sentence_polarity(problem, "ถูกทำร้าย ไม่ได้", self.config)
        self.assertEqual(trailing["gate_neg"], 1.0)

    def test_zero_window_disables_negation_detection(self):
        config = H2LConfigV3()
        config.NEG_WINDOW_CHARS = 0
        problem = {"name": "ถูกทำร้าย", "keywords": ["ทำร้าย"], "severity": 4}
        result = calculate_sentence_polarity(problem, "ไม่ได้ถูกทำร้าย", config)
        self.assertEqual(result["gate_neg"], 1.0)

    def test_adaptive_window_clamps_short_and_long_queries(self):
        config = H2LConfigV3(ADAPTIVE_WINDOW_ENABLE=True, ADAPTIVE_WINDOW_MODE='balanced')
        # Short query (30 chars): 30 * 0.15 = 4.5 -> clamped to min 20
        self.assertEqual(config.get_negation_window_size("ก" * 30), 20)
        # Medium query (180 chars): 180 * 0.15 = 27 -> inside [20, 32]
        self.assertEqual(config.get_negation_window_size("ก" * 180), 27)
        # Long query (400 chars): 400 * 0.15 = 60 -> clamped to max 32
        self.assertEqual(config.get_negation_window_size("ก" * 400), 32)

    def test_adaptive_window_safety_mode(self):
        config = H2LConfigV3(ADAPTIVE_WINDOW_ENABLE=True, ADAPTIVE_WINDOW_MODE='safety')
        # Short query (40 chars): 40 * 0.15 = 6 -> clamped to min 25
        self.assertEqual(config.get_negation_window_size("ก" * 40), 25)
        # Long query (400 chars): 400 * 0.15 = 60 -> clamped to max 35
        self.assertEqual(config.get_negation_window_size("ก" * 400), 35)

    def test_fixed_window_mode(self):
        config = H2LConfigV3(ADAPTIVE_WINDOW_MODE='fixed', NEG_WINDOW_CHARS=42)
        self.assertEqual(config.get_negation_window_size("ก" * 100), 42)

    def test_clause_boundary_truncation(self):
        config = H2LConfigV3()
        prob_drug = {"name": "ยาเสพติด", "keywords": ["ยาเสพติด"], "severity": 4}
        prob_tuition = {"name": "ค่าเทอม", "keywords": ["ค่าเทอม"], "severity": 3}
        query = "เด็กไม่ได้เล่นยาเสพติด แต่ปัญหาแท้จริงคือพ่อแม่หาเงินค่าเทอมไม่พอ"

        res_drug = calculate_sentence_polarity(prob_drug, query, config)
        res_tuition = calculate_sentence_polarity(prob_tuition, query, config)

        self.assertLess(res_drug["gate_neg"], 1.0)
        self.assertEqual(res_tuition["gate_neg"], 1.0)

    def test_symptom_exceptions_bypass_negation(self):
        config = H2LConfigV3()
        prob_non_adhere = {"name": "ไม่ยอมกินยา", "keywords": ["กินยา", "ความร่วมมือ"], "severity": 3}
        prob_stroke = {"name": "หลอดเลือดสมอง", "keywords": ["หลอดเลือดสมอง", "พูด"], "severity": 4}

        res1 = calculate_sentence_polarity(prob_non_adhere, "คนไข้ไม่ยอมกินยา ไม่ให้ความร่วมมือรักษา", config)
        res2 = calculate_sentence_polarity(prob_stroke, "ผู้ป่วยอัมพาตครึ่งซีก พูดไม่ได้ กลืนลำบาก", config)

        self.assertEqual(res1["gate_neg"], 1.0)
        self.assertEqual(res2["gate_neg"], 1.0)


class TestDenseSimilarityConversion(unittest.TestCase):
    """LanceDB returns squared L2; unit-norm vectors give cos = 1 - d/2."""

    def test_squared_l2_maps_to_cosine_for_unit_vectors(self):
        import numpy as np

        rng = np.random.default_rng(0)
        for _ in range(20):
            a = rng.normal(size=32).astype("float32")
            b = rng.normal(size=32).astype("float32")
            a /= np.linalg.norm(a)
            b /= np.linalg.norm(b)

            squared_l2 = float(((a - b) ** 2).sum())
            self.assertAlmostEqual(1.0 - squared_l2 / 2.0, float(a @ b), places=5)


if __name__ == "__main__":
    unittest.main()

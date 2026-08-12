#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for sentence-polarity candidate gating."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.main import _apply_polarity_gate, _candidate_polarity_signal, _sentence_profile


class TestPolarityGate(unittest.TestCase):
    def test_negation_targets_self_harm_but_not_stress_clause(self):
        text = "ผู้ป่วยปฏิเสธการทำร้ายตัวเอง แต่ยอมรับว่ามีความเครียดสูงจากภาระหนี้สิน"
        profile = _sentence_profile(text)

        self_harm = {
            "code": "X60-X84",
            "confidence": 0.426,
            "matched_keywords": ["ทำร้ายตัวเอง"],
        }
        stress = {
            "code": "F43.2",
            "confidence": 0.2845,
            "matched_keywords": ["ความเครียด", "เครียด"],
        }

        self_harm_signal = _candidate_polarity_signal(self_harm, text, profile)
        stress_signal = _candidate_polarity_signal(stress, text, profile)

        self.assertTrue(self_harm_signal["negated"])
        self.assertEqual(self_harm_signal["gate"], 0.4)
        self.assertFalse(stress_signal["negated"])
        self.assertEqual(stress_signal["gate"], 1.0)

    def test_negated_passive_violence_is_filtered_but_stress_is_kept(self):
        text = "ผู้ป่วยไม่ได้ถูกทำร้าย แต่มีความเครียดสะสมจากหนี้สิน"
        profile = _sentence_profile(text)
        problems = [
            {
                "code": "T74",
                "name": "กลุ่มอาการจากการถูกทารุณกรรม",
                "confidence": 0.6557,
                "matched_keywords": ["ทำร้าย"],
                "context_valid": True,
            },
            {
                "code": "F43.2",
                "name": "Adjustment Disorder",
                "confidence": 0.6908,
                "matched_keywords": ["ความเครียด", "เครียด"],
                "context_valid": True,
            },
        ]

        kept, filtered = _apply_polarity_gate(text, problems, [], profile, enabled=True)

        kept_codes = [item["code"] for item in kept]
        filtered_codes = [item["code"] for item in filtered]

        self.assertEqual(kept_codes, ["F43.2"])
        self.assertIn("T74", filtered_codes)

    def test_positive_case_keeps_gate_at_one(self):
        text = "เด็กหญิงถูกแม่ดุด่าเป็นประจำ ครอบครัวรายได้น้อย เครียดมากและไม่อยากไปโรงเรียน"
        profile = _sentence_profile(text)
        item = {
            "code": "F43.2",
            "confidence": 0.7702,
            "matched_keywords": ["เครียดมาก", "เครียด"],
        }

        signal = _candidate_polarity_signal(item, text, profile)

        self.assertFalse(signal["negated"])
        self.assertEqual(signal["gate"], 1.0)


if __name__ == "__main__":
    unittest.main()

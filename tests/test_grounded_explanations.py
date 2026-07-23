#!/usr/bin/env python3
"""Grounding regressions for human-readable problem explanations."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api import (
    _apply_polarity_gate,
    _attach_grounded_explanations,
    _sentence_profile,
)


def _abuse_problem(keywords):
    return {
        "code": "0206",
        "name": "การกระทำทารุณกรรมต่อบุตร/พ่อแม่",
        "category": "02: ปัญหาระหว่างบิดา มารดา บุตร",
        "severity": 4,
        "confidence": 0.72,
        "detection_level": "L1",
        "matched_keywords": keywords,
        "context_valid": True,
    }


class TestGroundedExplanations(unittest.TestCase):
    def _annotate(self, text, problem):
        profile = _sentence_profile(text)
        kept, filtered = _apply_polarity_gate(
            text, [problem], [], profile, enabled=True
        )
        kept, filtered = _attach_grounded_explanations(
            text, kept, filtered, profile
        )
        self.assertFalse(filtered)
        return kept[0]

    def test_physical_and_psychological_aspects_use_exact_case_quotes(self):
        text = "มารดาตีเด็กหลายครั้ง และมารดาดุด่าบุตรว่าเป็นภาระ"
        result = self._annotate(text, _abuse_problem(["ตี", "ดุด่า"]))
        aspects = {aspect["id"]: aspect for aspect in result["evidence_aspects"]}

        self.assertEqual(
            set(aspects),
            {"physical_violence", "psychological_violence"},
        )
        for aspect in aspects.values():
            self.assertTrue(aspect["grounded"])
            self.assertIn(aspect["evidence_quote"], text)
            self.assertIn(aspect["evidence_quote"], aspect["summary"])

        explanation = result["grounded_explanation"]
        for indicator in explanation["indicators"]:
            self.assertIn(indicator, explanation["evidence_quote"])

        self.assertIn("ตี", aspects["physical_violence"]["indicators"])
        self.assertIn("ดุด่า", aspects["psychological_violence"]["indicators"])
        self.assertEqual(aspects["physical_violence"]["actor"], "มารดา")
        self.assertEqual(aspects["psychological_violence"]["actor"], "มารดา")

    def test_stress_alone_does_not_create_psychological_violence(self):
        text = "มารดาตีเด็กหลายครั้งเพราะเครียด"
        result = self._annotate(text, _abuse_problem(["ตี"]))
        aspect_ids = {aspect["id"] for aspect in result["evidence_aspects"]}

        self.assertEqual(aspect_ids, {"physical_violence"})

    def test_generic_grounded_quote_is_always_a_case_substring(self):
        text = "ครอบครัวไม่มีเงินเพียงพอชำระค่าเช่า"
        problem = {
            "code": "1001",
            "name": "ไม่มีรายได้/รายได้ไม่เพียงพอ",
            "category": "10: ปัญหาการเงิน",
            "severity": 3,
            "confidence": 0.7,
            "detection_level": "L1",
            "matched_keywords": ["ไม่มีเงิน"],
            "context_valid": True,
        }
        result = self._annotate(text, problem)
        explanation = result["grounded_explanation"]

        self.assertTrue(explanation["grounded"])
        self.assertIn(explanation["evidence_quote"], text)
        self.assertEqual(result["evidence_aspects"], [])


if __name__ == "__main__":
    unittest.main()

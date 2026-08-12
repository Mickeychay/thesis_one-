#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for differentiated detector confidence scoring."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from h2l.detector import L1ContextAwareDetector


class TestConfidenceScoring(unittest.TestCase):
    def test_confidence_uses_keyword_specificity_not_only_match_count(self):
        detector = L1ContextAwareDetector(taxonomy={})
        text = "เด็กไม่อยากไปโรงเรียน เพราะถูกดุด่าและครอบครัวรายได้น้อย"

        short_match = detector._calculate_confidence(
            text_lower=text,
            matched_keywords=["ดุด่า"],
            all_keywords=["ดุด่า", "ทำร้ายจิตใจ", "ข่มขู่"],
            confidence_multiplier=1.0,
        )
        specific_match = detector._calculate_confidence(
            text_lower=text,
            matched_keywords=["ไม่อยากไปโรงเรียน"],
            all_keywords=["ไม่อยากไปโรงเรียน", "ขาดเรียน", "ออกจากโรงเรียน"],
            confidence_multiplier=1.0,
        )

        self.assertGreater(specific_match, short_match)
        self.assertNotEqual(specific_match, short_match)

    def test_context_multiplier_still_lowers_invalid_context(self):
        detector = L1ContextAwareDetector(taxonomy={})
        valid = detector._calculate_confidence(
            text_lower="ถูกดุด่า",
            matched_keywords=["ดุด่า"],
            all_keywords=["ดุด่า"],
            confidence_multiplier=1.0,
        )
        invalid = detector._calculate_confidence(
            text_lower="ถูกดุด่า",
            matched_keywords=["ดุด่า"],
            all_keywords=["ดุด่า"],
            confidence_multiplier=0.4,
        )

        self.assertLess(invalid, valid)


if __name__ == "__main__":
    unittest.main()

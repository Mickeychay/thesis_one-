#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression tests for context-aware stress detection."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from H2LDetector import H2LDetectorV3


class TestStressDetection(unittest.TestCase):
    def setUp(self):
        self.detector = H2LDetectorV3(enable_l2=False)

    def test_stress_with_school_avoidance_is_detected(self):
        text = "เด็กหญิงถูกแม่ดุด่าเป็นประจำ ครอบครัวรายได้น้อย เครียดมากและไม่อยากไปโรงเรียน"

        result = self.detector.detect_with_metadata(text, use_l2=True)
        problems = result["problems"]
        by_code = {problem["code"]: problem for problem in problems}

        self.assertIn("F43.2", by_code)
        self.assertTrue(by_code["F43.2"]["context_valid"])
        self.assertIn("เครียด", by_code["F43.2"]["matched_keywords"])
        self.assertIn("0206", by_code)
        self.assertIn("1101", by_code)

    def test_mild_stress_without_functional_impact_is_filtered(self):
        text = "ผู้รับบริการเครียดนิดหน่อยแต่ยังทำงานได้ตามปกติ"

        result = self.detector.detect_with_metadata(text, use_l2=True)
        codes = {problem["code"] for problem in result["problems"]}
        filtered_codes = {problem["code"] for problem in result["filtered_out"]}

        self.assertNotIn("F43.2", codes)
        self.assertIn("F43.2", filtered_codes)


if __name__ == "__main__":
    unittest.main()

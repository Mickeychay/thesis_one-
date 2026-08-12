#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression tests for clause-scoped context and polarity handling."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from h2l.detector import DetectedProblem, H2LDetectorV3, L2SemanticDetector
from api.main import (
    _apply_polarity_gate,
    _apply_user_adjusted_spans_to_candidates,
    _candidate_evidence_spans,
    _apply_review_status,
    _candidate_relation,
    _normalize_user_adjusted_spans,
    _polarity_effect,
    _review_status_summary,
    _sentence_profile,
)


class TestContextScoping(unittest.TestCase):
    def setUp(self):
        self.detector = H2LDetectorV3(enable_l2=False)

    def test_country_name_in_food_context_does_not_trigger_migration_problem(self):
        text = "มารดามีความถนัดทำอาหารประเภทแกงอีสาน แกงลาว และขายอาหารตามสั่ง"

        result = self.detector.detect_with_metadata(text, use_l2=True)
        codes = {problem["code"] for problem in result["problems"]}
        filtered_codes = {problem["code"] for problem in result["filtered_out"]}

        self.assertNotIn("1306", codes)
        self.assertIn("1306", filtered_codes)

    def test_neutral_work_history_does_not_trigger_generic_occupation_problem(self):
        text = (
            "บิดาอาชีพรับจ้างทั่วไป ทำงานเข็นรถส่งของ รายได้เดือนละ 3,000 บาท "
            "เดิมทำงานโรงพิมพ์บริเวณเสาชิงช้า"
        )

        result = self.detector.detect_with_metadata(text, use_l2=True)
        codes = {problem["code"] for problem in result["problems"]}
        filtered_codes = {problem["code"] for problem in result["filtered_out"]}

        self.assertNotIn("1205", codes)
        self.assertIn("1205", filtered_codes)

    def test_financial_hardship_phrase_is_not_treated_as_problem_denial(self):
        text = "ครอบครัวไม่มีเงินเพียงพอชำระค่าเช่า และยังไม่ได้นำส่งหนี้นอกระบบ"
        profile = _sentence_profile(text)
        problem = {
            "code": "1005",
            "name": "ปัญหาการเงิน อื่นๆ",
            "category": "10: ปัญหาการเงิน",
            "confidence": 0.284,
            "matched_keywords": ["เงิน"],
            "context_valid": True,
        }

        kept, filtered = _apply_polarity_gate(text, [problem], [], profile, enabled=True)

        self.assertEqual(len(filtered), 0)
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["polarity_gate"], 1.0)

    def test_polarity_effect_uses_candidate_scoped_relation_instead_of_global_event(self):
        text = (
            "มารดามีการติดหนี้สินนอกระบบประมาณ 8,000 บาท ยังไม่ได้นำส่ง "
            "มารดาตีเด็กหลายครั้งเพราะเครียด"
        )
        profile = _sentence_profile(text)
        finance_problem = {
            "code": "1005",
            "name": "ปัญหาการเงิน อื่นๆ",
            "category": "10: ปัญหาการเงิน",
            "confidence": 0.284,
            "matched_keywords": ["เงิน"],
            "context_valid": True,
        }
        abuse_problem = {
            "code": "0206",
            "name": "การกระทำทารุณกรรมต่อบุตร/พ่อแม่",
            "category": "02: ปัญหาระหว่างบิดา มารดา บุตร",
            "confidence": 0.726,
            "matched_keywords": ["ตี"],
            "context_valid": True,
        }

        kept, filtered = _apply_polarity_gate(text, [finance_problem, abuse_problem], [], profile, enabled=True)
        effect = _polarity_effect(kept, filtered, profile)
        by_code = {row["code"]: row for row in effect["rows"]}

        self.assertEqual(by_code["1005"]["actor"], "ไม่ชัดเจน")
        self.assertEqual(by_code["1005"]["action"], "ไม่ชัดเจน")
        self.assertEqual(by_code["0206"]["actor"], "มารดา")
        self.assertEqual(by_code["0206"]["action"], "ตี")

    def test_non_interpersonal_candidates_do_not_inherit_abuse_relation(self):
        text = (
            "มารดาเครียด บางครั้งควบคุมอารมณ์ไม่ได้ เลยระบายด้วยการตีเด็ก "
            "เด็กไม่ได้ไปโรงเรียน และครอบครัวมีรายได้น้อย"
        )
        profile = _sentence_profile(text)
        candidates = [
            {
                "code": "0206",
                "name": "การกระทำทารุณกรรมต่อบุตร/พ่อแม่",
                "category": "02: ปัญหาระหว่างบิดา มารดา บุตร",
                "confidence": 0.72,
                "matched_keywords": ["ตี"],
                "context_valid": True,
            },
            {
                "code": "F43.2",
                "name": "Adjustment Disorder",
                "category": "สุขภาพจิต",
                "confidence": 0.77,
                "matched_keywords": ["เครียด"],
                "context_valid": True,
            },
            {
                "code": "1001",
                "name": "ไม่มีรายได้/รายได้ไม่เพียงพอ",
                "category": "10: ปัญหาการเงิน",
                "confidence": 0.70,
                "matched_keywords": ["รายได้น้อย"],
                "context_valid": True,
            },
            {
                "code": "1101",
                "name": "ไม่ได้เรียน/ออกกลางคัน",
                "category": "11: ปัญหาการศึกษา",
                "confidence": 0.74,
                "matched_keywords": ["ไม่ได้ไปโรงเรียน"],
                "context_valid": True,
            },
        ]

        kept, filtered = _apply_polarity_gate(text, candidates, [], profile, enabled=True)
        effect = _polarity_effect(kept, filtered, profile)
        by_code = {row["code"]: row for row in effect["rows"]}

        self.assertEqual(by_code["0206"]["actor"], "มารดา")
        self.assertEqual(by_code["0206"]["action"], "ตี")
        for code in ("F43.2", "1001", "1101"):
            self.assertEqual(by_code[code]["actor"], "ไม่ชัดเจน")
            self.assertEqual(by_code[code]["target"], "ไม่ชัดเจน")
            self.assertEqual(by_code[code]["action"], "ไม่ชัดเจน")

    def test_causal_เลย_after_negation_does_not_negate_following_abuse_event(self):
        text = "มารดาเครียด บางครั้งควบคุมอารมณ์ไม่ได้ เลยระบายด้วยการตีเด็ก"
        profile = _sentence_profile(text)
        problem = {
            "code": "0206",
            "name": "การกระทำทารุณกรรมต่อบุตร/พ่อแม่",
            "category": "02: ปัญหาระหว่างบิดา มารดา บุตร",
            "confidence": 0.7389,
            "matched_keywords": ["ตีเด็ก"],
            "context_valid": True,
        }

        kept, filtered = _apply_polarity_gate(text, [problem], [], profile, enabled=True)

        self.assertEqual(len(filtered), 0)
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["polarity_gate"], 1.0)

    def test_candidate_relation_ignores_later_repeated_parent_mentions(self):
        text = (
            "มารดามีโรคประจำตัว มารดาเคยตีเด็กหลายครั้งเพราะเครียด "
            "มารดาคนที่สามมาดูแลเรื่องอาหารและไม่เคยกล่าวถึงการตีเด็ก"
        )
        profile = _sentence_profile(text)
        problem = {
            "code": "0206",
            "name": "การกระทำทารุณกรรมต่อบุตร/พ่อแม่",
            "category": "02: ปัญหาระหว่างบิดา มารดา บุตร",
            "confidence": 0.72,
            "matched_keywords": ["มารดา", "ตี"],
            "context_valid": True,
        }

        relation = _candidate_relation(problem, text, profile)

        self.assertEqual(relation["actor"], "มารดา")
        self.assertEqual(relation["target"], "ผู้รับบริการ/เด็ก")
        self.assertEqual(relation["action"], "ตี")
        self.assertTrue(relation["event_id"])

    def test_polarity_uses_selected_match_span_instead_of_other_occurrence(self):
        text = "ผู้ป่วยไม่ได้ตีเด็กในอดีต แต่ตอนนี้มารดาตีเด็กหลายครั้งเพราะเครียด"
        profile = _sentence_profile(text)
        problem = {
            "code": "0206",
            "name": "การกระทำทารุณกรรมต่อบุตร/พ่อแม่",
            "category": "02: ปัญหาระหว่างบิดา มารดา บุตร",
            "confidence": 0.72,
            "matched_keywords": ["ตีเด็ก"],
            "matched_spans": [{"keyword": "ตีเด็ก", "start": 38, "end": 44}],
            "context_valid": True,
        }

        kept, filtered = _apply_polarity_gate(text, [problem], [], profile, enabled=True)

        self.assertEqual(len(filtered), 0)
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["polarity_gate"], 1.0)

    def test_polarity_can_filter_negated_occurrence_when_selected_span_is_negated(self):
        text = "ผู้ป่วยไม่ได้ตีเด็กในอดีต แต่ตอนนี้มารดาตีเด็กหลายครั้งเพราะเครียด"
        profile = _sentence_profile(text)
        problem = {
            "code": "0206",
            "name": "การกระทำทารุณกรรมต่อบุตร/พ่อแม่",
            "category": "02: ปัญหาระหว่างบิดา มารดา บุตร",
            "confidence": 0.72,
            "matched_keywords": ["ตีเด็ก"],
            "matched_spans": [{"keyword": "ตีเด็ก", "start": 13, "end": 19}],
            "context_valid": True,
        }

        kept, filtered = _apply_polarity_gate(text, [problem], [], profile, enabled=True)

        self.assertEqual(len(kept), 0)
        self.assertEqual(len(filtered), 1)
        self.assertLess(filtered[0]["polarity_gate"], 1.0)

    def test_user_adjusted_position_is_kept_as_primary_evidence_anchor(self):
        text = "ผู้ป่วยไม่ได้ตีเด็กในอดีต แต่ตอนนี้มารดาตีเด็กหลายครั้งเพราะเครียด"
        problem = {
            "code": "0206",
            "name": "การกระทำทารุณกรรมต่อบุตร/พ่อแม่",
            "category": "02: ปัญหาระหว่างบิดา มารดา บุตร",
            "confidence": 0.72,
            "matched_keywords": ["ตีเด็ก"],
            "matched_spans": [{
                "keyword": "ตีเด็ก",
                "start": 38,
                "end": 44,
                "position_source": "user_adjusted",
                "user_adjusted": True,
            }],
            "context_valid": True,
        }

        evidence_spans = _candidate_evidence_spans(problem, text)

        self.assertEqual(evidence_spans[0]["scope"], "anchor")
        self.assertEqual(evidence_spans[0]["start"], 38)
        self.assertEqual(evidence_spans[0]["end"], 44)
        self.assertEqual(evidence_spans[0]["position_source"], "user_adjusted")

    def test_user_adjusted_spans_are_remapped_after_trim_and_pii_redaction(self):
        raw_text = "  เด็กหญิง สมศรี ถูกแม่ดุด่าเป็นประจำ"
        sanitized_text = "[PERSON] ถูกแม่ดุด่าเป็นประจำ"
        raw_spans = [{
            "keyword": "ดุด่า",
            "start": 23,
            "end": 28,
            "text": "ดุด่า",
            "position_source": "user_adjusted",
            "user_adjusted": True,
        }]

        normalized = _normalize_user_adjusted_spans(raw_spans, raw_text, sanitized_text)

        self.assertEqual(len(normalized), 1)
        self.assertEqual(normalized[0]["start"], 15)
        self.assertEqual(normalized[0]["end"], 20)
        self.assertEqual(normalized[0]["text"], "ดุด่า")
        self.assertTrue(normalized[0]["user_adjusted"])

    def test_user_adjusted_spans_replace_other_occurrences_for_same_candidate(self):
        text = "ผู้ป่วยไม่ได้ตีเด็กในอดีต แต่ตอนนี้มารดาตีเด็กหลายครั้งเพราะเครียด"
        problems = [{
            "code": "0206",
            "name": "การกระทำทารุณกรรมต่อบุตร/พ่อแม่",
            "category": "02: ปัญหาระหว่างบิดา มารดา บุตร",
            "confidence": 0.72,
            "matched_keywords": ["ตีเด็ก"],
            "context_valid": True,
        }]
        user_adjusted_spans = [{
            "keyword": "ตีเด็ก",
            "start": 38,
            "end": 44,
            "text": "ตีเด็ก",
            "position_source": "user_adjusted",
            "user_adjusted": True,
        }]

        applied = _apply_user_adjusted_spans_to_candidates(problems, text, user_adjusted_spans)
        evidence_spans = _candidate_evidence_spans(problems[0], text)

        self.assertEqual(applied, 1)
        self.assertEqual(problems[0]["matched_spans"], user_adjusted_spans)
        self.assertEqual(evidence_spans[0]["scope"], "anchor")
        self.assertEqual(evidence_spans[0]["start"], 38)
        self.assertEqual(evidence_spans[0]["end"], 44)

    def test_review_status_marks_polarity_filtered_candidate_as_filtered(self):
        text = "เด็กไม่ได้ถูกแม่ดุด่า"
        profile = _sentence_profile(text)
        problem = {
            "code": "0206",
            "name": "การกระทำทารุณกรรมต่อบุตร/พ่อแม่",
            "category": "02: ปัญหาระหว่างบิดา มารดา บุตร",
            "confidence": 0.5,
            "matched_keywords": ["ดุด่า"],
            "context_valid": True,
        }

        kept, filtered = _apply_polarity_gate(text, [problem], [], profile, enabled=True)
        kept, filtered = _apply_review_status(kept, filtered)

        self.assertEqual(len(kept), 0)
        self.assertEqual(filtered[0]["review_status"], "filtered")

    def test_review_status_summary_counts_each_bucket(self):
        problems = [
            {"code": "0206", "review_status": "confirmed"},
            {"code": "1304", "review_status": "verify_documents"},
            {"code": "0401", "review_status": "needs_review"},
        ]
        filtered = [
            {"code": "1005", "review_status": "filtered"},
        ]

        summary = _review_status_summary(problems, filtered, baseline_mode=False)

        self.assertEqual(summary["confirmed"], 1)
        self.assertEqual(summary["verify_documents"], 1)
        self.assertEqual(summary["needs_review"], 1)
        self.assertEqual(summary["filtered"], 1)
        self.assertEqual(summary["total"], 4)

    def test_l2_validation_does_not_remove_non_targeted_l1_candidates(self):
        detector = L2SemanticDetector.__new__(L2SemanticDetector)
        candidates = [
            DetectedProblem(
                code="1001",
                name="ไม่มีรายได้/รายได้ไม่เพียงพอ",
                category="10: ปัญหาการเงิน",
                severity=3,
                confidence=0.66,
                detection_level="L1",
                reasoning="ตรวจพบคำสำคัญ 'ไม่มีเงิน'",
                matched_keywords=["ไม่มีเงิน"],
                context_valid=True,
            ),
            DetectedProblem(
                code="1306",
                name="ผู้ป่วยเข้าเมืองผิดกฎหมาย/ต่างด้าว/ต่างชาติ",
                category="13: ปัญหาทางกฎหมาย",
                severity=3,
                confidence=0.28,
                detection_level="L1-NeedsValidation",
                reasoning="พบเพียงชื่อประเทศ",
                matched_keywords=["ลาว"],
                context_valid=False,
            ),
        ]
        validation_results = [
            {"code": "1001", "is_valid": False, "reason": "LLM ตัดผิด"},
            {"code": "1306", "is_valid": False, "reason": "ควรตรวจเอกสาร"},
        ]

        kept = detector._process_validation(candidates, validation_results, validation_targets={"1306"})
        kept_codes = {item.code for item in kept}

        self.assertIn("1001", kept_codes)
        self.assertNotIn("1306", kept_codes)

    def test_l2_implicit_high_precision_category_requires_taxonomy_anchor(self):
        detector = L2SemanticDetector.__new__(L2SemanticDetector)
        taxonomy = {
            "0802": {
                "name": "สภาพบ้านไม่เหมาะสม/ไม่ถูกสุขลักษณะ",
                "category": "08: ปัญหาที่อยู่อาศัย/สภาพแวดล้อม",
                "keywords": ["บ้านพัง", "คับแคบ", "แออัด", "สกปรก", "ไม่ถูกสุขลักษณะ"],
            }
        }
        implicit = detector._process_implicit(
            [
                {
                    "code": "0802",
                    "name": "สภาพบ้านไม่เหมาะสม/ไม่ถูกสุขลักษณะ",
                    "category": "08: ปัญหาที่อยู่อาศัย/สภาพแวดล้อม",
                    "severity": 2,
                    "confidence": 0.75,
                    "reasoning": "มารดาตีเด็กหลายครั้งเพราะเครียด",
                    "evidence": "มารดาตีเด็กหลายครั้งเพราะเครียด",
                }
            ],
            [],
            full_text="มารดาตีเด็กหลายครั้งเพราะเครียด",
            taxonomy=taxonomy,
        )

        self.assertEqual(implicit, [])

    def test_l2_implicit_family_code_without_taxonomy_anchor_is_rejected(self):
        detector = L2SemanticDetector.__new__(L2SemanticDetector)
        taxonomy = {
            "0205": {
                "name": "ปัญหาเกี่ยวกับการเป็นบุตรบุญธรรม",
                "category": "02: ปัญหาระหว่างบิดา มารดา บุตร",
                "keywords": ["บุตรบุญธรรม", "รับเป็นบุตรบุญธรรม", "ลูกบุญธรรม"],
            }
        }

        implicit = detector._process_implicit(
            [
                {
                    "code": "0205",
                    "name": "ปัญหาเกี่ยวกับการเป็นบุตรบุญธรรม",
                    "category": "02: ปัญหาระหว่างบิดา มารดา บุตร",
                    "severity": 2,
                    "confidence": 0.74,
                    "reasoning": "แม่ระบุว่าตีเด็กหลายครั้งเพราะเครียด",
                    "evidence": "แม่ระบุว่าตีเด็กหลายครั้งเพราะเครียด",
                }
            ],
            [],
            full_text="มารดาตีเด็กหลายครั้งเพราะเครียด",
            taxonomy=taxonomy,
        )

        self.assertEqual(implicit, [])


if __name__ == "__main__":
    unittest.main()

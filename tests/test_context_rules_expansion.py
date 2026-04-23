#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression tests for expanded context-aware rules."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from H2LDetector import H2LDetectorV3


class TestContextRulesExpansion(unittest.TestCase):
    def setUp(self):
        self.detector = H2LDetectorV3(enable_l2=False)

    def test_education_history_does_not_trigger_generic_education_problem(self):
        text = "มารดาจบชั้นประถมศึกษา 4 และบุตรกำลังเรียนอยู่ชั้นมัธยมศึกษาปีที่ 2"

        result = self.detector.detect_with_metadata(text, use_l2=True)
        codes = {problem["code"] for problem in result["problems"]}
        filtered_codes = {problem["code"] for problem in result["filtered_out"]}

        self.assertNotIn("1106", codes)
        self.assertIn("1106", filtered_codes)

    def test_simple_caregiving_role_does_not_trigger_burden_other(self):
        text = "บุตรสาวเป็นผู้ดูแลมารดาอยู่ที่บ้านและช่วยพาไปโรงพยาบาลตามนัด"

        result = self.detector.detect_with_metadata(text, use_l2=True)
        codes = {problem["code"] for problem in result["problems"]}
        filtered_codes = {problem["code"] for problem in result["filtered_out"]}

        self.assertNotIn("0703", codes)
        self.assertIn("0703", filtered_codes)

    def test_partner_mention_without_conflict_does_not_trigger_romantic_conflict(self):
        text = "ผู้รับบริการมีแฟนคบกันมานานและวางแผนแต่งงานในปีหน้า"

        result = self.detector.detect_with_metadata(text, use_l2=True)
        codes = {problem["code"] for problem in result["problems"]}
        filtered_codes = {problem["code"] for problem in result["filtered_out"]}

        self.assertNotIn("0502", codes)
        self.assertIn("0502", filtered_codes)

    def test_general_healthcare_right_mention_does_not_trigger_legal_issue(self):
        text = "ผู้ป่วยใช้สิทธิบัตรทองรักษาต่อเนื่องที่โรงพยาบาลประจำตามปกติ"

        result = self.detector.detect_with_metadata(text, use_l2=True)
        codes = {problem["code"] for problem in result["problems"]}
        filtered_codes = {problem["code"] for problem in result["filtered_out"]}

        self.assertNotIn("1304", codes)
        self.assertIn("1304", filtered_codes)

    def test_denied_labor_rights_trigger_specific_legal_issue(self):
        text = "ผู้ป่วยบาดเจ็บจากงาน แต่นายจ้างไม่ส่งประกันสังคมและไม่จ่ายเงินทดแทน"

        result = self.detector.detect_with_metadata(text, use_l2=True)
        by_code = {problem["code"]: problem for problem in result["problems"]}

        self.assertIn("1302", by_code)
        self.assertTrue(by_code["1302"]["context_valid"])

    def test_external_person_mentions_without_conflict_do_not_trigger_outsider_problem(self):
        text = "ผู้ป่วยพักอาศัยร่วมกับเพื่อนร่วมงานและมีเจ้าของบ้านเช่าคนเดิมมาหลายปี"

        result = self.detector.detect_with_metadata(text, use_l2=True)
        codes = {problem["code"] for problem in result["problems"]}
        filtered_codes = {problem["code"] for problem in result["filtered_out"]}

        self.assertNotIn("0901", codes)
        self.assertIn("0901", filtered_codes)

    def test_accident_without_school_impact_does_not_trigger_learning_impairment_code(self):
        text = "ผู้ป่วยได้รับอุบัติเหตุจากการทำงานและต้องพักรักษาตัว"

        result = self.detector.detect_with_metadata(text, use_l2=True)
        codes = {problem["code"] for problem in result["problems"]}
        filtered_codes = {problem["code"] for problem in result["filtered_out"]}

        self.assertNotIn("1102", codes)
        self.assertIn("1102", filtered_codes)

    def test_kin_mentions_without_conflict_do_not_trigger_kin_relationship_problem(self):
        text = "ญาติพี่น้องเดินทางมาเยี่ยมผู้ป่วยที่โรงพยาบาลและช่วยกันดูแล"

        result = self.detector.detect_with_metadata(text, use_l2=True)
        codes = {problem["code"] for problem in result["problems"]}
        filtered_codes = {problem["code"] for problem in result["filtered_out"]}

        self.assertNotIn("0401", codes)
        self.assertIn("0401", filtered_codes)

    def test_generic_icd_umbrella_is_downgraded_when_specific_codes_exist(self):
        text = "ครอบครัวไม่มีที่อยู่อาศัย รายได้น้อย และไม่มีเงินจ่ายค่าเช่าบ้าน"

        result = self.detector.detect_with_metadata(text, use_l2=True)
        codes = {problem["code"] for problem in result["problems"]}
        filtered_codes = {problem["code"] for problem in result["filtered_out"]}

        self.assertIn("0801", codes)
        self.assertIn("1001", codes)
        self.assertNotIn("Z59", codes)
        self.assertIn("Z59", filtered_codes)

    def test_exact_homelessness_duplicate_keeps_single_primary_code(self):
        text = "ครอบครัวไม่มีที่อยู่อาศัยและต้องนอนในที่สาธารณะมาหลายวัน"

        result = self.detector.detect_with_metadata(text, use_l2=True)
        codes = {problem["code"] for problem in result["problems"]}
        filtered_by_code = {problem["code"]: problem for problem in result["filtered_out"]}

        self.assertIn("0801", codes)
        self.assertNotIn("Z59.0", codes)
        self.assertIn("Z59.0", filtered_by_code)
        self.assertIn("ประเด็นเดียวกัน", filtered_by_code["Z59.0"]["reasoning"])

    def test_partner_mention_and_non_romantic_conflict_do_not_cross_contaminate(self):
        text = "ผู้รับบริการมีแฟนคบกันมานาน. ผู้รับบริการทะเลาะกับเจ้าหนี้เรื่องหนี้สินและค่าเช่าห้อง"

        result = self.detector.detect_with_metadata(text, use_l2=True)
        codes = {problem["code"] for problem in result["problems"]}
        filtered_codes = {problem["code"] for problem in result["filtered_out"]}

        self.assertNotIn("0502", codes)
        self.assertIn("0502", filtered_codes)

    def test_impairment_and_learning_signals_in_separate_sentences_do_not_merge(self):
        text = "ผู้ป่วยเคยประสบอุบัติเหตุจากรถชนเมื่อหลายปีก่อน. บุตรเรียนไม่ทันเพราะขาดเรียนบ่อย"

        result = self.detector.detect_with_metadata(text, use_l2=True)
        codes = {problem["code"] for problem in result["problems"]}
        filtered_codes = {problem["code"] for problem in result["filtered_out"]}

        self.assertNotIn("1102", codes)
        self.assertIn("1102", filtered_codes)

    def test_outsider_mention_and_family_conflict_in_separate_sentences_do_not_merge(self):
        text = "ผู้ป่วยพักอยู่ติดกับเพื่อนบ้านมาหลายปี. ระยะหลังทะเลาะกับน้องชายเรื่องทรัพย์สิน"

        result = self.detector.detect_with_metadata(text, use_l2=True)
        codes = {problem["code"] for problem in result["problems"]}
        filtered_codes = {problem["code"] for problem in result["filtered_out"]}

        self.assertNotIn("0901", codes)
        self.assertIn("0901", filtered_codes)

    def test_partner_and_family_conflict_in_same_sentence_do_not_merge(self):
        text = "มารดามีแฟน แต่ทะเลาะกับน้องชายเรื่องทรัพย์สิน"

        result = self.detector.detect_with_metadata(text, use_l2=True)
        codes = {problem["code"] for problem in result["problems"]}
        filtered_codes = {problem["code"] for problem in result["filtered_out"]}

        self.assertNotIn("0502", codes)
        self.assertIn("0502", filtered_codes)

    def test_parent_impairment_and_child_learning_issue_in_same_sentence_do_not_merge(self):
        text = "มารดาพิการจากอุบัติเหตุ แต่บุตรเรียนไม่ทันเพราะขาดเรียนบ่อย"

        result = self.detector.detect_with_metadata(text, use_l2=True)
        codes = {problem["code"] for problem in result["problems"]}
        filtered_codes = {problem["code"] for problem in result["filtered_out"]}

        self.assertNotIn("1102", codes)
        self.assertIn("1102", filtered_codes)

    def test_outsider_mention_and_kin_conflict_in_same_sentence_do_not_merge(self):
        text = "ผู้ป่วยพักติดกับเพื่อนบ้าน แต่ทะเลาะกับพี่ชายเรื่องมรดก"

        result = self.detector.detect_with_metadata(text, use_l2=True)
        codes = {problem["code"] for problem in result["problems"]}
        filtered_codes = {problem["code"] for problem in result["filtered_out"]}

        self.assertNotIn("0901", codes)
        self.assertIn("0901", filtered_codes)

    def test_spouse_actor_in_other_sentence_does_not_trigger_generic_spouse_conflict(self):
        text = "ผู้รับบริการมีแฟนคบกันมานาน. ระยะหลังผู้รับบริการทะเลาะกับเจ้าหนี้เรื่องหนี้สิน"

        result = self.detector.detect_with_metadata(text, use_l2=True)
        codes = {problem["code"] for problem in result["problems"]}
        filtered_codes = {problem["code"] for problem in result["filtered_out"]}

        self.assertNotIn("0101", codes)
        self.assertIn("0101", filtered_codes)

    def test_parent_actor_in_other_sentence_does_not_trigger_parent_child_conflict(self):
        text = "มารดามาเยี่ยมผู้ป่วยที่โรงพยาบาล. ผู้ป่วยทะเลาะกับเจ้าหนี้เรื่องค่าเช่าห้อง"

        result = self.detector.detect_with_metadata(text, use_l2=True)
        codes = {problem["code"] for problem in result["problems"]}
        filtered_codes = {problem["code"] for problem in result["filtered_out"]}

        self.assertNotIn("0201", codes)
        self.assertIn("0201", filtered_codes)

    def test_spouse_actor_in_other_sentence_does_not_trigger_spousal_violence(self):
        text = "ผู้ป่วยมีสามีและอยู่กินกันมาหลายปี. ต่อมาถูกเพื่อนบ้านทุบตีระหว่างมีปากเสียง"

        result = self.detector.detect_with_metadata(text, use_l2=True)
        codes = {problem["code"] for problem in result["problems"]}
        filtered_codes = {problem["code"] for problem in result["filtered_out"]}

        self.assertNotIn("0102", codes)
        self.assertIn("0102", filtered_codes)

    def test_parent_pronoun_reference_can_still_trigger_parent_child_abuse(self):
        text = "มารดาเครียดมาก. เขาดุด่าเด็กเป็นประจำ"

        result = self.detector.detect_with_metadata(text, use_l2=True)
        by_code = {problem["code"]: problem for problem in result["problems"]}

        self.assertIn("0206", by_code)
        self.assertEqual(by_code["0206"]["review_status"], "confirmed")

    def test_spouse_reference_term_can_still_trigger_spousal_violence(self):
        text = "ผู้ป่วยมีสามี. รายนี้ทุบตีเป็นประจำ"

        result = self.detector.detect_with_metadata(text, use_l2=True)
        by_code = {problem["code"]: problem for problem in result["problems"]}

        self.assertIn("0102", by_code)
        self.assertEqual(by_code["0102"]["review_status"], "confirmed")

    def test_parent_hitting_child_is_detected_as_parent_child_abuse(self):
        text = "มารดาตีเด็กหลายครั้งเพราะเครียด"

        result = self.detector.detect_with_metadata(text, use_l2=True)
        by_code = {problem["code"]: problem for problem in result["problems"]}

        self.assertIn("0206", by_code)
        self.assertIn("ตี", by_code["0206"]["matched_keywords"])

    def test_document_heavy_filtered_code_gets_verify_documents_status(self):
        text = "มารดาทำอาหารแกงลาวขายหน้าวัด"

        result = self.detector.detect_with_metadata(text, use_l2=True)
        by_code = {problem["code"]: problem for problem in result["filtered_out"]}

        self.assertIn("1306", by_code)
        self.assertEqual(by_code["1306"]["review_status"], "verify_documents")

    def test_baseline_mode_marks_candidates_as_baseline_preview(self):
        text = "มารดาดุด่าเด็กเป็นประจำ"

        result = self.detector.detect_with_metadata(text, use_l2=False)
        by_code = {problem["code"]: problem for problem in result["problems"]}

        self.assertIn("0206", by_code)
        self.assertEqual(by_code["0206"]["review_status"], "baseline_candidate")


if __name__ == "__main__":
    unittest.main()

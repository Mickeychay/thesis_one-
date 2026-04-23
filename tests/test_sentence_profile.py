#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for sentence actor/target/action extraction."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api import _sanitize_pii, _sentence_profile


class TestSentenceProfile(unittest.TestCase):
    def test_peer_bullying_does_not_promote_later_parents_to_agents(self):
        text = (
            "[PERSON] 14 ปี ม.2 เข้ารักษาจากบาดแผลที่ข้อมือ "
            "(รอยกรีดตื้นๆ หลายเส้น) บอกว่าตัดเองเพราะเครียด "
            "ถูกเพื่อนรังแก ด่าว่าเกย์ โพสต์รูปล้อเลียนในโซเชียล "
            "ไม่อยากไป[LOCATION] ไม่อยากกินข้าว บิดามารดาไม่รู้เรื่อง "
            "เพิ่งเห็นรอยตัดพอดี ช็อกมาก"
        )

        roles = _sentence_profile(text)["actor_roles"]

        self.assertEqual(roles["agents"], ["เพื่อน"])
        self.assertEqual(roles["targets"], ["ผู้รับบริการ/เด็ก"])
        self.assertIn("รังแก", roles["actions"])
        self.assertIn("ด่าว่า", roles["actions"])
        self.assertIn("โพสต์รูปล้อเลียน", roles["actions"])
        self.assertNotIn("บิดา", roles["agents"])
        self.assertNotIn("มารดา", roles["agents"])

    def test_parent_abuse_keeps_parent_as_agent(self):
        roles = _sentence_profile("เด็กถูกแม่ดุด่าเป็นประจำ")["actor_roles"]

        self.assertEqual(roles["agents"], ["แม่"])
        self.assertEqual(roles["targets"], ["ผู้รับบริการ/เด็ก"])
        self.assertIn("ดุด่า", roles["actions"])

    def test_pii_sanitizer_preserves_passive_child_abuse_clause(self):
        text = "เด็กหญิงถูกแม่ดุด่าเป็นประจำ ครอบครัวรายได้น้อย เครียดมากและไม่อยากไปโรงเรียน"
        sanitized, count = _sanitize_pii(text)
        roles = _sentence_profile(sanitized)["actor_roles"]

        self.assertEqual(count, 0)
        self.assertIn("เด็กหญิงถูกแม่ดุด่า", sanitized)
        self.assertEqual(roles["agents"], ["แม่"])
        self.assertEqual(roles["targets"], ["ผู้รับบริการ/เด็ก"])
        self.assertIn("ดุด่า", roles["actions"])

    def test_pii_sanitizer_redacts_explicit_named_child_without_losing_context(self):
        sanitized, count = _sanitize_pii("เด็กหญิง สมศรี ถูกแม่ดุด่าเป็นประจำ")
        roles = _sentence_profile(sanitized)["actor_roles"]

        self.assertEqual(count, 1)
        self.assertIn("[PERSON] ถูกแม่ดุด่า", sanitized)
        self.assertEqual(roles["agents"], ["แม่"])
        self.assertEqual(roles["targets"], ["ผู้รับบริการ/เด็ก"])
        self.assertIn("ดุด่า", roles["actions"])

    def test_common_passive_and_active_patterns(self):
        cases = [
            ("ภรรยาถูกสามีทำร้ายร่างกาย", ["สามี"], ["ภรรยา"], "ทำร้าย"),
            ("พ่อทำร้ายลูก", ["พ่อ"], ["ลูก"], "ทำร้าย"),
            ("ลูกทำร้ายแม่", ["ลูก"], ["แม่"], "ทำร้าย"),
            ("ผู้สูงอายุโดนลูกทอดทิ้งไม่ดูแล", ["ลูก"], ["ผู้สูงอายุ"], "ทอดทิ้ง"),
            ("นักเรียนถูกครูตีหน้าชั้นเรียน", ["ครู"], ["ผู้รับบริการ/เด็ก"], "ตี"),
        ]

        for text, expected_agents, expected_targets, expected_action in cases:
            with self.subTest(text=text):
                roles = _sentence_profile(text)["actor_roles"]
                self.assertEqual(roles["agents"], expected_agents)
                self.assertEqual(roles["targets"], expected_targets)
                self.assertIn(expected_action, roles["actions"])

    def test_self_harm_maps_subject_without_external_agent(self):
        roles = _sentence_profile("เด็กกรีดข้อมือตัวเองเพราะเครียด")["actor_roles"]

        self.assertEqual(roles["agents"], ["ตนเอง"])
        self.assertEqual(roles["targets"], ["ผู้รับบริการ/เด็ก"])
        self.assertIn("กรีดข้อมือ", roles["actions"])

    def test_context_only_family_mentions_are_not_agents(self):
        roles = _sentence_profile("บิดามารดาไม่รู้เรื่อง เพิ่งเห็นรอยตัดพอดี ช็อกมาก")["actor_roles"]

        self.assertEqual(roles["agents"], [])
        self.assertEqual(roles["targets"], [])
        self.assertEqual(roles["actions"], [])

    def test_pronoun_reference_resolves_to_previous_parent(self):
        roles = _sentence_profile("มารดาเครียดมาก. เขาดุด่าเด็กเป็นประจำ")["actor_roles"]

        self.assertEqual(roles["agents"], ["มารดา"])
        self.assertEqual(roles["targets"], ["ผู้รับบริการ/เด็ก"])
        self.assertIn("ดุด่า", roles["actions"])

    def test_pronoun_reference_resolves_to_previous_partner(self):
        roles = _sentence_profile("ผู้ป่วยมีสามี. เขาทุบตีภรรยาหลายครั้ง")["actor_roles"]

        self.assertEqual(roles["agents"], ["สามี"])
        self.assertEqual(roles["targets"], ["ภรรยา"])
        self.assertIn("ทุบตี", roles["actions"])

    def test_reporting_clause_prefers_sentence_subject_for_pronoun(self):
        roles = _sentence_profile("บิดาบอกมารดาว่า เขาดุด่าเด็กเป็นประจำ")["actor_roles"]

        self.assertEqual(roles["agents"], ["บิดา"])
        self.assertEqual(roles["targets"], ["ผู้รับบริการ/เด็ก"])
        self.assertIn("ดุด่า", roles["actions"])


if __name__ == "__main__":
    unittest.main()

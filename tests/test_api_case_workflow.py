#!/usr/bin/env python3
"""Focused regressions for API case identity and finalization semantics."""

import sys
import unittest
from pathlib import Path
from uuid import UUID

from fastapi import HTTPException
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api import (
    CASE_CACHE,
    FINALIZED_CASES,
    FinalizeRequest,
    _determine_severity,
    _new_case_id,
    finalize_case,
)


class TestCaseIdentifiers(unittest.TestCase):
    def test_case_ids_are_unique_uuid4_values(self):
        case_ids = {_new_case_id() for _ in range(100)}

        self.assertEqual(len(case_ids), 100)
        for case_id in case_ids:
            self.assertTrue(case_id.startswith("CASE_"))
            parsed = UUID(hex=case_id.removeprefix("CASE_"))
            self.assertEqual(parsed.version, 4)

    def test_no_findings_do_not_imply_mild_risk(self):
        self.assertEqual(_determine_severity([]), "NOT_ASSESSED")


class TestFinalizeSelections(unittest.TestCase):
    def setUp(self):
        self.case_id = _new_case_id()
        CASE_CACHE[self.case_id] = {
            "case_id": self.case_id,
            "problems": [
                {"code": "F32", "name": "Depressive episode"},
                {"code": "Z63", "name": "Family circumstances"},
            ],
            "retrieved_docs": [],
            "severity_level": "MODERATE",
            "runtime_status": {"status": "ready"},
        }

    def tearDown(self):
        CASE_CACHE.pop(self.case_id, None)
        FINALIZED_CASES.pop(self.case_id, None)

    def test_explicit_empty_findings_remain_empty_everywhere(self):
        summary = finalize_case(FinalizeRequest(
            case_id=self.case_id,
            selected_findings=[],
        ))

        self.assertEqual(summary["selected_findings"], [])
        self.assertEqual(summary["export_json"]["selected_findings"], [])
        self.assertIn("Selected findings: None", summary["export_markdown"])

    def test_omitted_findings_preserve_legacy_default(self):
        summary = finalize_case(FinalizeRequest(case_id=self.case_id))

        self.assertEqual(summary["selected_findings"], ["F32", "Z63"])
        self.assertIn("Selected findings: F32, Z63", summary["export_markdown"])

    def test_finding_review_states_remain_distinct_and_consistent(self):
        summary = finalize_case(FinalizeRequest(
            case_id=self.case_id,
            selected_findings=["F32"],
            finding_review_states={"F32": "excluded", "Z63": "review"},
            expert_override_rejected=["Z63", "MANUAL-CODE"],
        ))

        expected_states = {"F32": "excluded", "Z63": "review"}
        self.assertEqual(summary["finding_review_states"], expected_states)
        self.assertEqual(summary["selected_findings"], ["Z63"])
        self.assertEqual(summary["expert_override_rejected"], ["MANUAL-CODE", "F32"])
        self.assertEqual(summary["export_json"]["finding_review_states"], expected_states)
        self.assertEqual(summary["export_json"]["selected_findings"], ["Z63"])
        self.assertIn("- F32: excluded", summary["export_markdown"])
        self.assertIn("- Z63: review", summary["export_markdown"])
        self.assertIn("Excluded findings: MANUAL-CODE, F32", summary["export_markdown"])

    def test_rejected_findings_are_removed_from_selected_without_state_map(self):
        summary = finalize_case(FinalizeRequest(
            case_id=self.case_id,
            selected_findings=["F32", "Z63"],
            expert_override_rejected=["F32"],
        ))

        self.assertEqual(summary["selected_findings"], ["Z63"])
        self.assertEqual(summary["expert_override_rejected"], ["F32"])

    def test_invalid_finding_review_state_is_rejected(self):
        with self.assertRaises(ValidationError):
            FinalizeRequest(
                case_id=self.case_id,
                finding_review_states={"F32": "pending"},
            )

    def test_unknown_finding_review_code_is_rejected(self):
        with self.assertRaises(HTTPException) as context:
            finalize_case(FinalizeRequest(
                case_id=self.case_id,
                finding_review_states={"UNKNOWN": "review"},
            ))

        self.assertEqual(context.exception.status_code, 422)

    def test_zero_finding_case_requires_explicit_acknowledgement(self):
        CASE_CACHE[self.case_id]["problems"] = []

        with self.assertRaises(HTTPException) as context:
            finalize_case(FinalizeRequest(case_id=self.case_id))

        self.assertEqual(context.exception.status_code, 422)

        summary = finalize_case(FinalizeRequest(
            case_id=self.case_id,
            selected_findings=[],
            zero_finding_acknowledged=True,
        ))
        self.assertEqual(summary["selected_findings"], [])
        self.assertTrue(summary["zero_finding_acknowledged"])
        self.assertTrue(summary["export_json"]["zero_finding_acknowledged"])
        self.assertIn("Zero-finding acknowledged: Yes", summary["export_markdown"])


if __name__ == "__main__":
    unittest.main()

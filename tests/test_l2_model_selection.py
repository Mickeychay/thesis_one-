#!/usr/bin/env python3
"""Regressions for request-scoped L2 model selection."""

import json
import sys
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from h2l.detector import L2SemanticDetector
from api.main import RuntimeManager


class _FakeCompletions:
    def __init__(self):
        self.calls = []
        self.lock = threading.Lock()

    def create(self, **kwargs):
        with self.lock:
            self.calls.append(dict(kwargs))
        content = json.dumps({
            "validated_codes": [],
            "implicit_problems": [],
            "context_analysis": {"demographic_group": "general"},
        })
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )


class _CorrectingCompletions:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(dict(kwargs))
        if len(self.calls) == 1:
            content = json.dumps({
                "validated_codes": ["invalid"],
                "implicit_problems": ["invalid"],
            })
        else:
            content = json.dumps({
                "validated_codes": [],
                "implicit_problems": [
                    {
                        "code": "1001",
                        "name": "ปัญหาการเงิน",
                        "severity": 3,
                        "confidence": 0.8,
                        "reasoning": "พบปัญหาการเงิน",
                        "evidence": "ไม่มีเงิน",
                    },
                ],
                "context_analysis": {"demographic_group": "adult"},
            })
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )


class TestRequestScopedModelSelection(unittest.TestCase):
    def setUp(self):
        self.completions = _FakeCompletions()
        self.detector = L2SemanticDetector.__new__(L2SemanticDetector)
        self.detector.config = None
        self.detector.client = SimpleNamespace(
            chat=SimpleNamespace(completions=self.completions)
        )
        self.detector.model = "qwen2.5:7b"
        self.detector.is_ready = True

    def test_model_override_is_forwarded_without_mutating_default(self):
        self.detector.validate_and_detect(
            "ตัวอย่างเคส",
            [],
            [],
            {},
            taxonomy={},
            model="scb10x/llama3.1-typhoon2-8b-instruct:latest",
        )

        self.assertEqual(
            self.completions.calls[0]["model"],
            "scb10x/llama3.1-typhoon2-8b-instruct:latest",
        )
        self.assertEqual(
            self.completions.calls[0]["response_format"],
            {"type": "json_object"},
        )
        self.assertEqual(self.completions.calls[0]["max_tokens"], 2048)
        self.assertEqual(self.detector.model, "qwen2.5:7b")

    def test_concurrent_requests_keep_their_own_model(self):
        models = [
            "qwen2.5:7b",
            "scb10x/llama3.1-typhoon2-8b-instruct:latest",
        ] * 4
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(
                lambda model: self.detector.validate_and_detect(
                    "ตัวอย่างเคส", [], [], {}, taxonomy={}, model=model
                ),
                models,
            ))

        self.assertCountEqual(
            [call["model"] for call in self.completions.calls],
            models,
        )
        self.assertEqual(self.detector.model, "qwen2.5:7b")

    def test_malformed_schema_is_retried_with_corrective_instructions(self):
        correcting = _CorrectingCompletions()
        self.detector.client = SimpleNamespace(
            chat=SimpleNamespace(completions=correcting)
        )
        validated, implicit, context = self.detector.validate_and_detect(
            "ผู้รับบริการไม่มีเงิน",
            [],
            [],
            {},
            taxonomy={
                "1001": {
                    "name": "ปัญหาการเงิน",
                    "category": "การเงิน",
                    "severity": 3,
                    "keywords": ["ไม่มีเงิน"],
                }
            },
        )

        self.assertEqual(validated, [])
        self.assertEqual([problem.code for problem in implicit], ["1001"])
        self.assertEqual(context, {"demographic_group": "adult"})
        self.assertEqual(len(correcting.calls), 2)
        self.assertEqual(correcting.calls[1]["temperature"], 0)
        self.assertEqual(correcting.calls[1]["seed"], 43)
        self.assertIn("previous response was malformed", correcting.calls[1]["messages"][-1]["content"])


class TestRuntimeModelAllowlist(unittest.TestCase):
    def setUp(self):
        self.runtime = RuntimeManager()
        self.runtime.config = SimpleNamespace(
            USE_LOCAL_LLM=True,
            LOCAL_LLM_MODEL="qwen2.5:7b",
            L2_MODEL_OPTIONS=(
                "qwen2.5:7b",
                "scb10x/llama3.1-typhoon2-8b-instruct:latest",
                "h2l/typhoon-gemma3-4b-templatefix-v2:latest",
            ),
        )
        self.runtime.available_l2_models = {
            "qwen2.5:7b",
            "scb10x/llama3.1-typhoon2-8b-instruct:latest",
            "h2l/typhoon-gemma3-4b-templatefix-v2:latest",
        }

    def test_allowed_installed_model_is_selected(self):
        selected = self.runtime.resolve_l2_model(
            "scb10x/llama3.1-typhoon2-8b-instruct:latest"
        )
        self.assertEqual(selected, "scb10x/llama3.1-typhoon2-8b-instruct:latest")

    def test_compatible_gemma_model_is_selected(self):
        selected = self.runtime.resolve_l2_model(
            "h2l/typhoon-gemma3-4b-templatefix-v2:latest"
        )
        self.assertEqual(selected, "h2l/typhoon-gemma3-4b-templatefix-v2:latest")

    def test_unknown_model_is_rejected(self):
        with self.assertRaises(HTTPException) as context:
            self.runtime.resolve_l2_model("unknown/model")
        self.assertEqual(context.exception.status_code, 422)

    def test_allowed_but_uninstalled_model_is_rejected(self):
        self.runtime.available_l2_models.remove(
            "scb10x/llama3.1-typhoon2-8b-instruct:latest"
        )
        with self.assertRaises(HTTPException) as context:
            self.runtime.resolve_l2_model(
                "scb10x/llama3.1-typhoon2-8b-instruct:latest"
            )
        self.assertEqual(context.exception.status_code, 503)


if __name__ == "__main__":
    unittest.main()

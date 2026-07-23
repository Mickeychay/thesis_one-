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

from H2LDetector import L2SemanticDetector
from api import RuntimeManager


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


class TestRuntimeModelAllowlist(unittest.TestCase):
    def setUp(self):
        self.runtime = RuntimeManager()
        self.runtime.config = SimpleNamespace(
            USE_LOCAL_LLM=True,
            LOCAL_LLM_MODEL="qwen2.5:7b",
            L2_MODEL_OPTIONS=(
                "qwen2.5:7b",
                "scb10x/llama3.1-typhoon2-8b-instruct:latest",
            ),
        )
        self.runtime.available_l2_models = {
            "qwen2.5:7b",
            "scb10x/llama3.1-typhoon2-8b-instruct:latest",
        }

    def test_allowed_installed_model_is_selected(self):
        selected = self.runtime.resolve_l2_model(
            "scb10x/llama3.1-typhoon2-8b-instruct:latest"
        )
        self.assertEqual(selected, "scb10x/llama3.1-typhoon2-8b-instruct:latest")

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

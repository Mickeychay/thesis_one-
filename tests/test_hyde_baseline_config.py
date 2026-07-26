import unittest
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Another legacy test installs a module-level MagicMock under this import name.
# Load the implementation in isolation so full-suite collection order is irrelevant.
_SPEC = importlib.util.spec_from_file_location(
    "_unified_baselines_hyde_config_test",
    ROOT / "unified_baselines.py",
)
_MODULE = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(_MODULE)
HyDEBaseline = _MODULE.HyDEBaseline


class _FakeCompletions:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="เอกสารสมมติ"))]
        )


class _FakeOpenAI:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.chat = SimpleNamespace(completions=_FakeCompletions())
        self.instances.append(self)


class TestHyDEBaselineConfig(unittest.TestCase):
    def setUp(self):
        _FakeOpenAI.instances.clear()

    def test_local_hyde_uses_configured_endpoint_model_and_seed(self):
        config = SimpleNamespace(
            USE_LOCAL_LLM=True,
            LOCAL_LLM_BASE_URL="http://127.0.0.1:11435/v1",
            LOCAL_LLM_MODEL="qwen2.5:7b",
        )
        shared = {"dense_retriever": object(), "doc_map": {}}

        with patch("openai.OpenAI", _FakeOpenAI):
            baseline = HyDEBaseline(config, shared)
            generated = baseline._generate_hypothetical_doc("ตัวอย่างเคส")

        client = _FakeOpenAI.instances[0]
        self.assertEqual(client.kwargs["base_url"], config.LOCAL_LLM_BASE_URL)
        self.assertEqual(client.kwargs["api_key"], "ollama")
        self.assertEqual(generated, "เอกสารสมมติ")
        self.assertEqual(client.chat.completions.calls[0]["model"], "qwen2.5:7b")
        self.assertEqual(client.chat.completions.calls[0]["seed"], 42)


if __name__ == "__main__":
    unittest.main()

import struct

import pytest

from scripts.patch_gguf_chat_template import (
    GGUF_STRING,
    SAFE_GEMMA_TEMPLATE,
    locate_string_metadata,
    patch_template,
)


def gguf_string(value: bytes) -> bytes:
    return struct.pack("<Q", len(value)) + value


def write_gguf(path, template: str):
    entries = [
        (b"general.architecture", b"gemma3"),
        (b"tokenizer.chat_template", template.encode("utf-8")),
    ]
    payload = b"GGUF" + struct.pack("<IQQ", 3, 0, len(entries))
    for key, value in entries:
        payload += gguf_string(key)
        payload += struct.pack("<I", GGUF_STRING)
        payload += gguf_string(value)
    path.write_bytes(payload)


def test_patch_replaces_template_without_changing_file_size(tmp_path):
    path = tmp_path / "model.gguf"
    original_template = "{{ messages | selectattr('tool_calls') }}" + " " * 500
    write_gguf(path, original_template)
    size_before = path.stat().st_size

    result = patch_template(path)

    _, allocated, value, version, tensor_count = locate_string_metadata(
        path, "tokenizer.chat_template"
    )
    assert path.stat().st_size == size_before
    assert version == 3
    assert tensor_count == 0
    assert allocated == len(original_template)
    assert value.startswith(SAFE_GEMMA_TEMPLATE.encode("utf-8"))
    assert b"selectattr" not in value
    assert result["padding_bytes"] > 0


def test_patch_requires_the_incompatible_marker(tmp_path):
    path = tmp_path / "model.gguf"
    write_gguf(path, SAFE_GEMMA_TEMPLATE + " " * 100)

    with pytest.raises(ValueError, match="required marker"):
        patch_template(path)

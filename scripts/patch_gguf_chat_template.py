#!/usr/bin/env python3
"""Replace a GGUF string metadata value without moving tensor data."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


GGUF_STRING = 8
GGUF_ARRAY = 9
PRIMITIVE_SIZES = {
    0: 1,   # uint8
    1: 1,   # int8
    2: 2,   # uint16
    3: 2,   # int16
    4: 4,   # uint32
    5: 4,   # int32
    6: 4,   # float32
    7: 1,   # bool
    10: 8,  # uint64
    11: 8,  # int64
    12: 8,  # float64
}

SAFE_GEMMA_TEMPLATE = """{{ bos_token }}
{% for message in messages %}
{% if message['role'] == 'system' %}<start_of_turn>user
{{ message['content'] }}<end_of_turn>
{% elif message['role'] == 'user' %}<start_of_turn>user
{{ message['content'] }}<end_of_turn>
{% elif message['role'] == 'assistant' %}<start_of_turn>model
{{ message['content'] }}<end_of_turn>
{% endif %}
{% endfor %}
{% if add_generation_prompt %}<start_of_turn>model
{% endif %}"""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_exact(handle, count: int) -> bytes:
    value = handle.read(count)
    if len(value) != count:
        raise ValueError("Unexpected end of GGUF metadata")
    return value


def _read_u32(handle) -> int:
    return struct.unpack("<I", _read_exact(handle, 4))[0]


def _read_u64(handle) -> int:
    return struct.unpack("<Q", _read_exact(handle, 8))[0]


def _read_string(handle) -> bytes:
    return _read_exact(handle, _read_u64(handle))


def _skip_value(handle, value_type: int) -> None:
    if value_type in PRIMITIVE_SIZES:
        handle.seek(PRIMITIVE_SIZES[value_type], 1)
        return
    if value_type == GGUF_STRING:
        handle.seek(_read_u64(handle), 1)
        return
    if value_type == GGUF_ARRAY:
        element_type = _read_u32(handle)
        count = _read_u64(handle)
        if element_type in PRIMITIVE_SIZES:
            handle.seek(PRIMITIVE_SIZES[element_type] * count, 1)
            return
        for _ in range(count):
            _skip_value(handle, element_type)
        return
    raise ValueError(f"Unsupported GGUF metadata type: {value_type}")


def locate_string_metadata(path: Path, key: str) -> tuple[int, int, bytes, int, int]:
    with path.open("rb") as handle:
        if _read_exact(handle, 4) != b"GGUF":
            raise ValueError("Input is not a GGUF file")
        version = _read_u32(handle)
        tensor_count = _read_u64(handle)
        metadata_count = _read_u64(handle)
        for _ in range(metadata_count):
            metadata_key = _read_string(handle).decode("utf-8")
            value_type = _read_u32(handle)
            if metadata_key == key:
                if value_type != GGUF_STRING:
                    raise ValueError(f"GGUF metadata {key!r} is not a string")
                length = _read_u64(handle)
                offset = handle.tell()
                value = _read_exact(handle, length)
                return offset, length, value, version, tensor_count
            _skip_value(handle, value_type)
    raise KeyError(f"GGUF metadata key not found: {key}")


def patch_template(
    path: Path,
    *,
    template: str = SAFE_GEMMA_TEMPLATE,
    key: str = "tokenizer.chat_template",
    required_marker: str = "selectattr",
) -> dict:
    path = path.resolve()
    offset, allocated_length, original, version, tensor_count = locate_string_metadata(
        path, key
    )
    replacement = template.encode("utf-8")
    marker = required_marker.encode("utf-8")
    if marker and marker not in original:
        raise ValueError(
            f"Refusing to patch {key!r}: required marker {required_marker!r} is absent"
        )
    if len(replacement) > allocated_length:
        raise ValueError(
            f"Replacement template has {len(replacement)} bytes but only "
            f"{allocated_length} bytes are available"
        )
    padded = replacement + b" " * (allocated_length - len(replacement))
    with path.open("r+b") as handle:
        handle.seek(offset)
        handle.write(padded)
        handle.flush()

    check_offset, check_length, current, _, _ = locate_string_metadata(path, key)
    if check_offset != offset or check_length != allocated_length or current != padded:
        raise RuntimeError("GGUF template verification failed after patching")
    return {
        "status": "complete",
        "patched_at": datetime.now(ZoneInfo("Asia/Bangkok")).isoformat(
            timespec="seconds"
        ),
        "path": str(path),
        "gguf_version": version,
        "tensor_count": tensor_count,
        "metadata_key": key,
        "value_offset": offset,
        "allocated_bytes": allocated_length,
        "replacement_bytes": len(replacement),
        "padding_bytes": allocated_length - len(replacement),
        "original_template_sha256": hashlib.sha256(original).hexdigest(),
        "replacement_template_sha256": hashlib.sha256(replacement).hexdigest(),
        "patched_file_sha256": sha256_file(path),
        "required_marker_removed": required_marker,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gguf", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--key", default="tokenizer.chat_template")
    parser.add_argument("--required-marker", default="selectattr")
    args = parser.parse_args()

    result = patch_template(
        args.gguf,
        key=args.key,
        required_marker=args.required_marker,
    )
    if args.manifest:
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

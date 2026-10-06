from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
import zlib


def fully_qualified_sequences(source: bytes) -> tuple[str, ...]:
    """Extract only fully-qualified rows from an official emoji-test file."""

    sequences: list[str] = []
    seen: set[str] = set()
    for raw_line in source.decode("utf-8").splitlines():
        data = raw_line.split("#", 1)[0].strip()
        if not data:
            continue
        codepoints_text, separator, status = data.partition(";")
        if not separator or status.strip() != "fully-qualified":
            continue
        try:
            sequence = "".join(
                chr(int(token, 16)) for token in codepoints_text.split()
            )
        except (ValueError, OverflowError) as exc:
            raise ValueError(f"Invalid code point row: {raw_line!r}") from exc
        if not sequence or sequence in seen:
            raise ValueError("Official emoji catalog contains an invalid duplicate")
        sequence.encode("utf-8", errors="strict")
        seen.add(sequence)
        sequences.append(sequence)
    if not sequences:
        raise ValueError("No fully-qualified emoji rows were found")
    return tuple(sequences)


def catalog_payload(source: bytes) -> bytes:
    return "\n".join(fully_qualified_sequences(source)).encode("utf-8")


def generated_metadata(source: bytes) -> dict[str, object]:
    sequences = fully_qualified_sequences(source)
    payload = "\n".join(sequences).encode("utf-8")
    return {
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "catalog_sha256": hashlib.sha256(payload).hexdigest(),
        "catalog_size": len(sequences),
        "max_codepoints": max(map(len, sequences)),
        "max_utf8_bytes": max(len(item.encode("utf-8")) for item in sequences),
        "base85_zlib": base64.b85encode(zlib.compress(payload, 9)).decode("ascii"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate Mesh Chat's pinned reaction emoji catalog metadata"
    )
    parser.add_argument("emoji_test", type=Path)
    arguments = parser.parse_args()
    source = arguments.emoji_test.read_bytes()
    print(json.dumps(generated_metadata(source), indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

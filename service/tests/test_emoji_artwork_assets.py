from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ASSET_ROOT = ROOT / "public" / "emoji" / "twemoji" / "17.0.3"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _png_dimensions(path: Path) -> tuple[int, int]:
    payload = path.read_bytes()[:24]
    assert payload[:8] == b"\x89PNG\r\n\x1a\n"
    assert payload[12:16] == b"IHDR"
    return struct.unpack(">II", payload[16:24])


def test_offline_twemoji_manifest_and_sprite_integrity() -> None:
    manifest_path = ASSET_ROOT / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["unicode"] == {
        "version": "18.0",
        "source_sha256": "8f3735cda1f92a779d78af67cf86066bb1f07143dc22f2ac29394d9bc57ab21a",
        "catalog_size": 3963,
    }
    assert manifest["artwork"]["name"] == "Twemoji"
    assert manifest["artwork"]["version"] == "17.0.3"
    assert manifest["artwork"]["commit"] == "b6b55fef1e8636b540a6d016a4729ca8cdf2e60b"
    assert manifest["artwork"]["license"] == "CC-BY-4.0"
    assert manifest["artwork"]["covered_sequences"] == 3944
    assert manifest["artwork"]["curated_sequences"] == 253
    assert manifest["artwork"]["cell_size"] == 48
    assert manifest["general"]["count"] == 3691
    assert manifest["general"]["sheet_count"] == 8
    assert len(manifest["gaps"]) == 19
    assert {item["name"].split(":", 1)[0] for item in manifest["gaps"]} == {
        "cracking face",
        "leftwards thumb sign",
        "rightwards thumb sign",
        "monarch butterfly",
        "pickle",
        "lighthouse",
        "meteor",
        "eraser",
        "net with handle",
    }

    expected_files = {"curated.png", *(f"general-{index}.png" for index in range(8))}
    assert {item["name"] for item in manifest["files"]} == expected_files
    for item in manifest["files"]:
        path = ASSET_ROOT / item["name"]
        assert path.is_file()
        assert path.stat().st_size == item["bytes"]
        assert _sha256(path) == item["sha256"]
        expected_columns = 16 if item["name"] == "curated.png" else 32
        expected_rows = 16
        assert _png_dimensions(path) == (expected_columns * 48, expected_rows * 48)

    assert (ASSET_ROOT / "LICENSE-GRAPHICS.txt").stat().st_size > 10_000
    attribution = (ASSET_ROOT / "ATTRIBUTION.txt").read_text(encoding="utf-8")
    assert "Creative Commons Attribution 4.0" in attribution
    assert "b6b55fef1e8636b540a6d016a4729ca8cdf2e60b" in attribution


def test_generated_artwork_metadata_matches_manifest() -> None:
    generated = (ROOT / "src" / "emoji-artwork.generated.ts").read_text(encoding="utf-8")
    manifest_hash = _sha256(ASSET_ROOT / "manifest.json")
    assert f'TWEMOJI_ARTWORK_MANIFEST_SHA256 = "{manifest_hash}"' in generated
    assert 'TWEMOJI_ARTWORK_VERSION = "17.0.3"' in generated
    assert 'TWEMOJI_ARTWORK_COMMIT = "b6b55fef1e8636b540a6d016a4729ca8cdf2e60b"' in generated


def test_third_party_notice_attributes_twemoji() -> None:
    notice = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    assert "Twemoji" in notice
    assert "CC BY 4.0" in notice

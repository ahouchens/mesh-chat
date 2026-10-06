from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import subprocess
from pathlib import Path


UNICODE_VERSION = "18.0"
UNICODE_SOURCE_SHA256 = "8f3735cda1f92a779d78af67cf86066bb1f07143dc22f2ac29394d9bc57ab21a"
TWEMOJI_VERSION = "17.0.3"
TWEMOJI_COMMIT = "b6b55fef1e8636b540a6d016a4729ca8cdf2e60b"
TWEMOJI_SOURCE_URL = "https://github.com/jdecked/twemoji/releases/tag/v17.0.3"
CELL_SIZE = 48
CURATED_COLUMNS = 16
GENERAL_COLUMNS = 32
GENERAL_ROWS = 16
GENERAL_SHEET_CAPACITY = GENERAL_COLUMNS * GENERAL_ROWS
EXPECTED_CATALOG_SIZE = 3963
EXPECTED_CURATED_SIZE = 253
EXPECTED_COVERED_SIZE = 3944
EXPECTED_GAP_CODEPOINTS = {
    "1FAEB",
    "1FAF9",
    "1FAF9 1F3FB",
    "1FAF9 1F3FC",
    "1FAF9 1F3FD",
    "1FAF9 1F3FE",
    "1FAF9 1F3FF",
    "1FAFA",
    "1FAFA 1F3FB",
    "1FAFA 1F3FC",
    "1FAFA 1F3FD",
    "1FAFA 1F3FE",
    "1FAFA 1F3FF",
    "1FACC",
    "1FADD",
    "1F6D9",
    "1FA8B",
    "1FA8C",
    "1FA8D",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_emoji_test(source: bytes) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for raw_line in source.decode("utf-8").splitlines():
        data, marker, comment = raw_line.partition("#")
        codepoints_text, separator, status = data.strip().partition(";")
        if not separator or status.strip() != "fully-qualified":
            continue
        codepoints = " ".join(codepoints_text.split()).upper()
        emoji = "".join(chr(int(token, 16)) for token in codepoints.split())
        comment_parts = comment.strip().split(maxsplit=2) if marker else []
        name = comment_parts[2] if len(comment_parts) == 3 else codepoints
        if not emoji or emoji in seen:
            raise ValueError(f"Invalid or duplicate fully-qualified emoji: {codepoints}")
        seen.add(emoji)
        rows.append((emoji, name, codepoints))
    if len(rows) != EXPECTED_CATALOG_SIZE:
        raise ValueError(f"Expected {EXPECTED_CATALOG_SIZE} Emoji {UNICODE_VERSION} rows, got {len(rows)}")
    return rows


def parse_curated_reactions(source: str) -> list[str]:
    pattern = re.compile(
        r'emoji:\s*"([^"]+)"|\["([^"]+)",\s*"[^"]+"\]'
    )
    ordered: list[str] = []
    seen: set[str] = set()
    for match in pattern.finditer(source):
        emoji = match.group(1) or match.group(2)
        if emoji not in seen:
            seen.add(emoji)
            ordered.append(emoji)
    if len(ordered) != EXPECTED_CURATED_SIZE:
        raise ValueError(
            f"Expected {EXPECTED_CURATED_SIZE} curated reactions, got {len(ordered)}; "
            "update the artwork generator deliberately when the picker changes"
        )
    return ordered


def codepoint_filename(sequence: str, *, keep_variation_selectors: bool) -> str:
    codepoints = [ord(character) for character in sequence]
    if not keep_variation_selectors:
        codepoints = [value for value in codepoints if value != 0xFE0F]
    return "-".join(f"{value:x}" for value in codepoints) + ".png"


def resolve_twemoji_asset(sequence: str, source_directory: Path) -> Path | None:
    candidates = [
        codepoint_filename(sequence, keep_variation_selectors="\u200d" in sequence),
        codepoint_filename(sequence, keep_variation_selectors=False),
        codepoint_filename(sequence, keep_variation_selectors=True),
    ]
    for filename in dict.fromkeys(candidates):
        candidate = source_directory / filename
        if candidate.is_file():
            return candidate
    return None


def write_atlas(
    sequences: list[str],
    assets: dict[str, Path],
    output: Path,
    columns: int,
    rows: int,
) -> None:
    from PIL import Image

    atlas = Image.new("RGBA", (columns * CELL_SIZE, rows * CELL_SIZE), (0, 0, 0, 0))
    for index, sequence in enumerate(sequences):
        with Image.open(assets[sequence]) as source:
            icon = source.convert("RGBA")
            if icon.size != (CELL_SIZE, CELL_SIZE):
                icon = icon.resize((CELL_SIZE, CELL_SIZE), Image.Resampling.LANCZOS)
            column = index % columns
            row = index // columns
            atlas.alpha_composite(icon, (column * CELL_SIZE, row * CELL_SIZE))
    # Twemoji uses a deliberately compact flat-color palette. Re-indexing each
    # sheet preserves the artwork while avoiding a roughly 10 MB RGBA payload.
    indexed = atlas.quantize(
        colors=256,
        method=Image.Quantize.FASTOCTREE,
        dither=Image.Dither.NONE,
    )
    indexed.save(output, "PNG", optimize=True, compress_level=9)


def typescript_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def write_generated_typescript(
    output: Path,
    curated: list[str],
    general: list[str],
    gaps: list[tuple[str, str, str]],
    manifest_sha256: str,
) -> None:
    gap_rows = ",\n".join(
        f"  [{typescript_string(emoji)}, {typescript_string(name)}]"
        for emoji, name, _ in gaps
    )
    content = f'''// Generated by scripts/generate_emoji_artwork.py. Do not edit by hand.
export const TWEMOJI_ARTWORK_VERSION = {typescript_string(TWEMOJI_VERSION)};
export const TWEMOJI_ARTWORK_COMMIT = {typescript_string(TWEMOJI_COMMIT)};
export const TWEMOJI_ARTWORK_MANIFEST_SHA256 = {typescript_string(manifest_sha256)};
export const TWEMOJI_ARTWORK_CELL_SIZE = {CELL_SIZE};
export const TWEMOJI_CURATED_COLUMNS = {CURATED_COLUMNS};
export const TWEMOJI_CURATED_ROWS = {math.ceil(len(curated) / CURATED_COLUMNS)};
export const TWEMOJI_GENERAL_COLUMNS = {GENERAL_COLUMNS};
export const TWEMOJI_GENERAL_ROWS = {GENERAL_ROWS};
export const TWEMOJI_GENERAL_SHEET_CAPACITY = {GENERAL_SHEET_CAPACITY};

const TWEMOJI_CURATED_SEQUENCE_TEXT = {typescript_string(chr(10).join(curated))};
const TWEMOJI_GENERAL_SEQUENCE_TEXT = {typescript_string(chr(10).join(general))};

export const TWEMOJI_CURATED_SEQUENCES = Object.freeze(TWEMOJI_CURATED_SEQUENCE_TEXT.split("\\n"));
export const TWEMOJI_GENERAL_SEQUENCES = Object.freeze(TWEMOJI_GENERAL_SEQUENCE_TEXT.split("\\n"));
export const TWEMOJI_ARTWORK_GAPS = new Map<string, string>([
{gap_rows}
]);
'''
    output.write_text(content, encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build pinned, offline Twemoji sprite sheets for Mesh Chat"
    )
    parser.add_argument("emoji_test", type=Path)
    parser.add_argument("twemoji_checkout", type=Path)
    parser.add_argument("--workspace", type=Path, default=Path(__file__).resolve().parents[1])
    arguments = parser.parse_args()

    workspace = arguments.workspace.resolve()
    emoji_test = arguments.emoji_test.resolve()
    twemoji_checkout = arguments.twemoji_checkout.resolve()
    source_directory = twemoji_checkout / "assets" / "72x72"
    reactions_source = workspace / "src" / "reactions.ts"
    output_directory = workspace / "public" / "emoji" / "twemoji" / TWEMOJI_VERSION
    generated_typescript = workspace / "src" / "emoji-artwork.generated.ts"

    if sha256(emoji_test) != UNICODE_SOURCE_SHA256:
        raise ValueError("Unicode Emoji source checksum does not match the pinned 18.0 file")
    commit = subprocess.run(
        ["git", "-C", str(twemoji_checkout), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if commit != TWEMOJI_COMMIT:
        raise ValueError(f"Expected Twemoji commit {TWEMOJI_COMMIT}, got {commit}")
    if not source_directory.is_dir():
        raise ValueError("Twemoji 72x72 artwork directory is missing")

    source = emoji_test.read_bytes()
    catalog = parse_emoji_test(source)
    catalog_sequences = [emoji for emoji, _, _ in catalog]
    curated = parse_curated_reactions(reactions_source.read_text(encoding="utf-8"))
    catalog_set = set(catalog_sequences)
    if not set(curated).issubset(catalog_set):
        raise ValueError("The curated reaction picker includes an entry outside Emoji 18")

    assets: dict[str, Path] = {}
    gaps: list[tuple[str, str, str]] = []
    for emoji, name, codepoints in catalog:
        asset = resolve_twemoji_asset(emoji, source_directory)
        if asset is None:
            gaps.append((emoji, name, codepoints))
        else:
            assets[emoji] = asset

    if len(assets) != EXPECTED_COVERED_SIZE:
        raise ValueError(f"Expected {EXPECTED_COVERED_SIZE} covered sequences, got {len(assets)}")
    if {codepoints for _, _, codepoints in gaps} != EXPECTED_GAP_CODEPOINTS:
        raise ValueError("Twemoji coverage gap changed; review the new source deliberately")
    if any(emoji not in assets for emoji in curated):
        raise ValueError("Every curated reaction must have bundled artwork")

    general = [
        emoji for emoji in catalog_sequences
        if emoji in assets and emoji not in set(curated)
    ]
    if len(curated) + len(general) != EXPECTED_COVERED_SIZE:
        raise ValueError("Artwork ordering has duplicates or omissions")

    output_directory.mkdir(parents=True, exist_ok=True)
    for old_sheet in output_directory.glob("*.png"):
        old_sheet.unlink()

    curated_rows = math.ceil(len(curated) / CURATED_COLUMNS)
    write_atlas(
        curated,
        assets,
        output_directory / "curated.png",
        CURATED_COLUMNS,
        curated_rows,
    )

    general_sheet_count = math.ceil(len(general) / GENERAL_SHEET_CAPACITY)
    for sheet_index in range(general_sheet_count):
        start = sheet_index * GENERAL_SHEET_CAPACITY
        sheet_sequences = general[start : start + GENERAL_SHEET_CAPACITY]
        write_atlas(
            sheet_sequences,
            assets,
            output_directory / f"general-{sheet_index}.png",
            GENERAL_COLUMNS,
            GENERAL_ROWS,
        )

    shutil.copyfile(twemoji_checkout / "LICENSE-GRAPHICS", output_directory / "LICENSE-GRAPHICS.txt")
    attribution = (
        "Twemoji artwork\n"
        f"Version: {TWEMOJI_VERSION}\n"
        f"Commit: {TWEMOJI_COMMIT}\n"
        f"Source: {TWEMOJI_SOURCE_URL}\n"
        "Copyright Twitter, Inc. and other contributors.\n"
        "Graphics license: Creative Commons Attribution 4.0 International (CC BY 4.0).\n"
        "Mesh Chat resizes, palette-optimizes, and combines the original 72px PNG files into local sprite sheets.\n"
    )
    (output_directory / "ATTRIBUTION.txt").write_text(attribution, encoding="utf-8", newline="\n")

    sheet_paths = [output_directory / "curated.png"] + [
        output_directory / f"general-{index}.png" for index in range(general_sheet_count)
    ]
    manifest = {
        "schema": 1,
        "unicode": {
            "version": UNICODE_VERSION,
            "source_sha256": UNICODE_SOURCE_SHA256,
            "catalog_size": len(catalog),
        },
        "artwork": {
            "name": "Twemoji",
            "version": TWEMOJI_VERSION,
            "commit": TWEMOJI_COMMIT,
            "source": TWEMOJI_SOURCE_URL,
            "license": "CC-BY-4.0",
            "covered_sequences": len(assets),
            "curated_sequences": len(curated),
            "cell_size": CELL_SIZE,
        },
        "curated": {
            "file": "curated.png",
            "columns": CURATED_COLUMNS,
            "rows": curated_rows,
            "count": len(curated),
        },
        "general": {
            "file_pattern": "general-{index}.png",
            "columns": GENERAL_COLUMNS,
            "rows": GENERAL_ROWS,
            "capacity": GENERAL_SHEET_CAPACITY,
            "count": len(general),
            "sheet_count": general_sheet_count,
        },
        "gaps": [
            {"emoji": emoji, "name": name, "codepoints": codepoints}
            for emoji, name, codepoints in gaps
        ],
        "files": [
            {
                "name": path.name,
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
            for path in sheet_paths
        ],
    }
    manifest_path = output_directory / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    write_generated_typescript(
        generated_typescript,
        curated,
        general,
        gaps,
        sha256(manifest_path),
    )
    print(
        f"Generated {len(sheet_paths)} sprite sheets for {len(assets)} emoji "
        f"({len(curated)} curated, {len(general)} general, {len(gaps)} named fallbacks)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

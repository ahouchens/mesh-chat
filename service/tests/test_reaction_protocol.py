from __future__ import annotations

import base64
import hashlib
import os
import subprocess
import sys
import time
import uuid
import zlib

import LXMF
import pytest

from mesh_chat.app_protocol import (
    ALLOWED_REACTION_EMOJIS,
    META_FIELD,
    M_REACTION_ACTIVE,
    M_REACTION_EMOJI,
    M_REACTION_FOR,
    M_REACTION_REVISION,
    PAYLOAD_VERSION,
    build_fields,
    parse_payload,
)
from mesh_chat.emoji_validation import (
    LEGACY_REACTION_EMOJIS,
    MAX_REACTION_EMOJI_CODEPOINTS,
    MAX_REACTION_EMOJI_UTF8_BYTES,
    REACTION_EMOJI_CATALOG_SHA256,
    REACTION_EMOJI_CATALOG_SIZE,
    REACTION_EMOJI_SEQUENCES,
    UNICODE_EMOJI_SOURCE_SHA256,
    UNICODE_EMOJI_SOURCE_URL,
    UNICODE_EMOJI_VERSION,
    is_valid_reaction_emoji,
)
from mesh_chat.errors import ValidationError
from mesh_chat.models import MessageKind
from tools.generate_emoji_catalog import generated_metadata


def _native(fields: dict[int, object], text: str = "") -> LXMF.LXMessage:
    return LXMF.LXMessage(
        None,
        None,
        content=text,
        fields=fields,
        desired_method=LXMF.LXMessage.DIRECT,
        destination_hash=os.urandom(16),
        source_hash=os.urandom(16),
    )


def _common() -> dict[str, object]:
    return {
        "logical_id": str(uuid.uuid4()),
        "conversation": str(uuid.uuid4()),
        "expires_at": int(time.time()) + 60,
    }


def test_direct_reaction_v1_metadata_round_trip() -> None:
    target = str(uuid.uuid4())
    fields = build_fields(
        kind=MessageKind.REACTION,
        reaction_for=target,
        reaction_emoji="❤️",
        reaction_active=True,
        reaction_revision=4,
        **_common(),
    )

    parsed = parse_payload(_native(fields))

    assert PAYLOAD_VERSION == 1
    assert parsed.kind == MessageKind.REACTION
    assert parsed.reaction_for == target
    assert parsed.reaction_emoji == "❤️"
    assert parsed.reaction_active is True
    assert parsed.reaction_revision == 4
    assert set(fields[META_FIELD]) >= {
        M_REACTION_FOR,
        M_REACTION_EMOJI,
        M_REACTION_ACTIVE,
        M_REACTION_REVISION,
    }


@pytest.mark.parametrize(
    "emoji",
    [
        "👍",
        "❤️",
        "☕",
        "🫨",  # Unicode 15 shaking face: well beyond the legacy six.
        "\U0001FAEB",  # Unicode 18 cracking face, independent of runtime UCD.
        "👩🏽",
        "🧑🏽\u200d🌾",
        "👨\u200d👩\u200d👧\u200d👦",
        "🏳️\u200d🌈",
        "🏴\u200d☠️",
        "🇺🇸",
        "1️⃣",
        "#️⃣",
        # England subdivision flag: black flag + tag letters + cancel tag.
        "\U0001F3F4\U000E0067\U000E0062\U000E0065\U000E006E\U000E0067\U000E007F",
    ],
)
def test_reaction_validator_accepts_one_unicode_emoji_sequence(emoji: str) -> None:
    assert is_valid_reaction_emoji(emoji)
    fields = build_fields(
        kind=MessageKind.REACTION,
        reaction_for=str(uuid.uuid4()),
        reaction_emoji=emoji,
        reaction_active=True,
        reaction_revision=1,
        **_common(),
    )
    assert parse_payload(_native(fields)).reaction_emoji == emoji


@pytest.mark.parametrize(
    "value",
    [
        None,
        7,
        "",
        "A",
        "hello",
        "<script>alert(1)</script>",
        "👍 ",
        "👍\n",
        "👍\x00",
        "👍\u202e",
        "👍😂",
        "❤️😂",
        "❤",  # Unqualified text-default presentation.
        "🇺",
        "🇺🇸🇨",
        "1",
        "1️",
        "#⃣",  # Minimally-qualified keycap.
        "1⃣️",
        "🏽",
        "🚗🏽",
        "👍🏽🏻",
        "\u200d👩",
        "👩\u200d",
        "👩\u200d\u200d🌾",
        "️👍",
        "👍️️",
        "👍︎",
        "😀️",  # Redundant selector, not a fully-qualified row.
        "😀\u200d🚀",  # Invented, non-RGI ZWJ combination.
        "\U0001F3F4\U000E0067\U000E0062",  # Missing cancel tag.
        "\U0001F3F4\U000E0020\U000E0067\U000E007F",  # Tag-space.
        "\U0001F3F4\U000E007A\U000E007A\U000E007A\U000E007A\U000E007F",
        "👩\u200d" * 8 + "👩",  # 17 code points.
    ],
)
def test_reaction_validator_rejects_text_injection_and_malformed_unicode(
    value: object,
) -> None:
    assert not is_valid_reaction_emoji(value)


def test_reaction_validator_has_explicit_storage_bounds() -> None:
    assert MAX_REACTION_EMOJI_CODEPOINTS == 16
    assert MAX_REACTION_EMOJI_UTF8_BYTES == 64
    assert len(REACTION_EMOJI_SEQUENCES) == REACTION_EMOJI_CATALOG_SIZE == 3963
    assert set(LEGACY_REACTION_EMOJIS) <= REACTION_EMOJI_SEQUENCES
    assert max(map(len, REACTION_EMOJI_SEQUENCES)) == 10
    assert max(len(item.encode("utf-8")) for item in REACTION_EMOJI_SEQUENCES) == 35
    assert all(
        len(item) <= MAX_REACTION_EMOJI_CODEPOINTS
        and len(item.encode("utf-8")) <= MAX_REACTION_EMOJI_UTF8_BYTES
        for item in REACTION_EMOJI_SEQUENCES
    )


def test_reaction_catalog_has_pinned_unicode_provenance_and_cold_import() -> None:
    assert UNICODE_EMOJI_VERSION == "18.0"
    assert UNICODE_EMOJI_SOURCE_URL == (
        "https://www.unicode.org/Public/18.0.0/emoji/emoji-test.txt"
    )
    assert UNICODE_EMOJI_SOURCE_SHA256 == (
        "8f3735cda1f92a779d78af67cf86066bb1f07143dc22f2ac29394d9bc57ab21a"
    )
    assert REACTION_EMOJI_CATALOG_SHA256 == (
        "d4f4b496cf4a6f621575353540a4f778f3461535aeebb62de408369bd40608f9"
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "from mesh_chat.emoji_validation import REACTION_EMOJI_SEQUENCES; "
            "assert len(REACTION_EMOJI_SEQUENCES) == 3963",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_reaction_catalog_generator_includes_only_fully_qualified_rows() -> None:
    source = b"""# representative emoji-test rows
1F600 ; fully-qualified # grinning face
263A FE0F ; fully-qualified # smiling face
263A ; unqualified # smiling face without selector
1F3FB ; component # light skin tone
1F642 200D 2194 ; minimally-qualified # head shaking
"""
    metadata = generated_metadata(source)
    payload = zlib.decompress(
        base64.b85decode(str(metadata["base85_zlib"]))
    )

    assert payload.decode("utf-8").split("\n") == ["😀", "☺️"]
    assert metadata["catalog_size"] == 2
    assert metadata["source_sha256"] == hashlib.sha256(source).hexdigest()
    assert metadata["catalog_sha256"] == hashlib.sha256(payload).hexdigest()


def test_reaction_parser_rejects_tampered_unvalidated_emoji() -> None:
    fields = build_fields(
        kind=MessageKind.REACTION,
        reaction_for=str(uuid.uuid4()),
        reaction_emoji="👍",
        reaction_active=True,
        reaction_revision=1,
        **_common(),
    )
    fields[META_FIELD][M_REACTION_EMOJI] = "👍<script>"

    with pytest.raises(ValidationError, match="emoji"):
        parse_payload(_native(fields))


def test_group_reaction_event_and_target_ids_have_distinct_receipt_bindings() -> None:
    group_id = str(uuid.uuid4())
    delivery_id = str(uuid.uuid4())
    operation_id = str(uuid.uuid4())
    target_message_id = str(uuid.uuid4())
    conversation = str(uuid.uuid4())
    expires_at = int(time.time()) + 60
    fields = build_fields(
        kind=MessageKind.GROUP_REACTION,
        logical_id=delivery_id,
        conversation=conversation,
        expires_at=expires_at,
        group_id=group_id,
        group_epoch=2,
        group_manifest_hash="ab" * 32,
        group_message_id=operation_id,
        reaction_for=target_message_id,
        reaction_emoji="🎉",
        reaction_active=False,
        reaction_revision=9,
    )

    parsed = parse_payload(_native(fields))

    assert parsed.logical_id == delivery_id
    # group_message_id is the common mutation/event ID shared across recipient
    # legs; reaction_for is the visible chat message being reacted to.
    assert parsed.group_message_id == operation_id
    assert parsed.reaction_for == target_message_id
    assert parsed.group_message_id != parsed.reaction_for

    receipt = parse_payload(
        _native(
            build_fields(
                kind=MessageKind.GROUP_RECEIPT,
                logical_id=str(uuid.uuid4()),
                conversation=conversation,
                expires_at=expires_at,
                receipt_for=delivery_id,
                group_id=group_id,
                group_epoch=2,
                group_manifest_hash="ab" * 32,
                group_message_id=operation_id,
            )
        )
    )
    assert receipt.receipt_for == delivery_id
    assert receipt.group_message_id == operation_id


@pytest.mark.parametrize(
    "emoji,active,revision",
    [
        ("🚗🏻", True, 1),
        ("👍😂", True, 1),
        ("not-an-emoji", True, 1),
        ("👍", 1, 1),
        ("👍", True, 0),
        ("👍", True, True),
    ],
)
def test_reaction_builder_rejects_noncanonical_or_malformed_values(
    emoji: object, active: object, revision: object
) -> None:
    with pytest.raises(ValidationError):
        build_fields(
            kind=MessageKind.REACTION,
            reaction_for=str(uuid.uuid4()),
            reaction_emoji=emoji,  # type: ignore[arg-type]
            reaction_active=active,  # type: ignore[arg-type]
            reaction_revision=revision,  # type: ignore[arg-type]
            **_common(),
        )


def test_reaction_parser_rejects_partial_metadata_and_nonempty_content() -> None:
    fields = build_fields(
        kind=MessageKind.REACTION,
        reaction_for=str(uuid.uuid4()),
        reaction_emoji="👍",
        reaction_active=True,
        reaction_revision=1,
        **_common(),
    )
    del fields[META_FIELD][M_REACTION_REVISION]
    with pytest.raises(ValidationError, match="revision"):
        parse_payload(_native(fields))

    fields = build_fields(
        kind=MessageKind.REACTION,
        reaction_for=str(uuid.uuid4()),
        reaction_emoji="👍",
        reaction_active=True,
        reaction_revision=1,
        **_common(),
    )
    with pytest.raises(ValidationError, match="content must be empty"):
        parse_payload(_native(fields, "hidden text"))


def test_normal_chat_wire_shape_has_no_reaction_metadata() -> None:
    fields = build_fields(kind=MessageKind.CHAT, **_common())
    assert not set(fields[META_FIELD]) & {
        M_REACTION_FOR,
        M_REACTION_EMOJI,
        M_REACTION_ACTIVE,
        M_REACTION_REVISION,
    }
    parsed = parse_payload(_native(fields, "still compatible"))
    assert parsed.kind == MessageKind.CHAT
    assert parsed.reaction_for is None
    assert tuple(ALLOWED_REACTION_EMOJIS) == ("👍", "❤️", "😂", "😮", "😢", "🎉")

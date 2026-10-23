from __future__ import annotations

import re
from pathlib import Path

import pytest

from mesh_chat.service import MeshChatService


REPOSITORY = Path(__file__).resolve().parents[2]
APP = REPOSITORY / "src"
RUST = REPOSITORY / "src-tauri" / "src" / "lib.rs"


def _renderer_commands() -> set[str]:
    text = RUST.read_text(encoding="utf-8")
    start = text.index("fn allowed_renderer_command")
    end = text.index("\n}", start)
    return set(re.findall(r'"([a-z0-9_]+)"', text[start:end]))


def _app_commands() -> set[str]:
    commands: set[str] = set()
    for path in APP.rglob("*"):
        if path.suffix not in {".ts", ".tsx"} or ".test." in path.name:
            continue
        text = path.read_text(encoding="utf-8")
        commands.update(
            re.findall(
                r'serviceCommand(?:\s*<[^>]*>)?\s*\(\s*"([a-z0-9_]+)"',
                text,
            )
        )
    return commands


pytestmark = pytest.mark.skipif(
    not (APP.exists() and RUST.exists()),
    reason="Desktop source tree is unavailable",
)


def test_every_renderer_command_is_known_to_the_service() -> None:
    unknown = _renderer_commands() - set(MeshChatService.COMMANDS)
    assert unknown == set()


def test_every_literal_app_command_is_allowed_by_the_rust_shell() -> None:
    missing = _app_commands() - _renderer_commands()
    assert missing == set()


def test_contact_management_and_workspace_search_are_exposed() -> None:
    renderer = _renderer_commands()
    for command in (
        "update_contact",
        "rename_contact",
        "delete_contact",
        "unverify_contact",
        "unblock_contact",
        "search_workspace",
    ):
        assert command in renderer
        assert command in MeshChatService.COMMANDS

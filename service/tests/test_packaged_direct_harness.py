from __future__ import annotations

import os
from pathlib import Path

import pytest

from tools.packaged_direct_harness import (
    _message_with_reactions,
    run,
    run_mixed,
    run_workspace_admin,
)


PACKAGED_BINARY = os.environ.get("MESH_CHAT_PACKAGED_SIDECAR")
LEGACY_PACKAGED_BINARY = os.environ.get("MESH_CHAT_LEGACY_PACKAGED_SIDECAR")
LEGACY_EXPANDED_MODE = os.environ.get(
    "MESH_CHAT_LEGACY_EXPANDED_MODE", "either"
)


def test_message_with_reactions_requires_exact_aggregate_and_self_flag() -> None:
    snapshot = {
        "messages": [
            {
                "id": "shared-message",
                "text": "Reaction target",
                "direction": "inbound",
                "reactions": [
                    {"emoji": "👍", "count": 2, "reacted_by_self": True}
                ],
            }
        ]
    }

    assert _message_with_reactions(
        snapshot,
        text="Reaction target",
        direction="inbound",
        reactions=[{"emoji": "👍", "count": 2, "reacted_by_self": True}],
    ) == snapshot["messages"][0]
    assert (
        _message_with_reactions(
            snapshot,
            text="Reaction target",
            direction="inbound",
            reactions=[{"emoji": "👍", "count": 2, "reacted_by_self": False}],
        )
        is None
    )


@pytest.mark.skipif(
    not PACKAGED_BINARY,
    reason="Set MESH_CHAT_PACKAGED_SIDECAR to the exact release sidecar",
)
def test_exact_packaged_sidecar_phone_first_then_desktop_reply() -> None:
    result = run(Path(PACKAGED_BINARY).resolve())

    assert result["phone_send_within_desktop_deadline"] is True
    assert result["phone_message_id_preserved"] is True
    assert result["phone_message_delivered"] is True
    assert result["desktop_reply_within_desktop_deadline"] is True
    assert result["desktop_reply_id_preserved"] is True
    assert result["desktop_reply_delivered"] is True
    assert result["phone_reaction_within_desktop_deadline"] is True
    assert result["phone_reaction_command_preserved_target"] is True
    assert result["phone_reaction_converged"] is True
    assert result["desktop_reaction_add_converged"] is True
    assert result["desktop_reaction_replace_converged"] is True
    assert result["reaction_remove_converged"] is True
    assert result["delete_kept_contact"] is True
    assert result["delete_removed_visible_history"] is True
    assert result["delete_removed_saved_draft"] is True
    assert result["delete_hid_conversation"] is True
    assert result["fresh_inbound_reopened_conversation"] is True
    assert result["fresh_inbound_id_preserved"] is True
    assert result["clean_shutdown"] is True
    assert result["stderr_content_free"] is True


@pytest.mark.skipif(
    not PACKAGED_BINARY,
    reason="Set MESH_CHAT_PACKAGED_SIDECAR to the exact release sidecar",
)
def test_exact_packaged_sidecar_workspace_administrator_flow() -> None:
    result = run_workspace_admin(Path(PACKAGED_BINARY).resolve())

    assert result["admin_channel_converged"] is True
    assert result["admin_message_converged"] is True
    assert result["decline_no_effect"] is True
    assert result["approved_demotion_converged"] is True
    assert result["demotion_request_audited"] is True
    assert result["clean_shutdown"] is True
    assert result["stderr_content_free"] is True


@pytest.mark.skipif(
    not PACKAGED_BINARY or not LEGACY_PACKAGED_BINARY,
    reason=(
        "Set MESH_CHAT_PACKAGED_SIDECAR and "
        "MESH_CHAT_LEGACY_PACKAGED_SIDECAR to the exact release sidecars"
    ),
)
def test_current_sidecar_interoperates_with_legacy_sidecar() -> None:
    result = run_mixed(
        Path(PACKAGED_BINARY).resolve(),
        Path(LEGACY_PACKAGED_BINARY).resolve(),
    )

    assert result["initial_phone_message_id_preserved"] is True
    assert result["initial_phone_message_delivered"] is True
    assert result["initial_desktop_message_id_preserved"] is True
    assert result["initial_desktop_message_delivered"] is True
    assert result["legacy_quick_reaction_converged"] is True
    assert result["current_quick_reaction_converged"] is True
    assert result["current_quick_reaction_removal_converged"] is True
    assert result["expanded_reaction_command_preserved_target"] is True
    assert result["expanded_reaction_visible_on_current"] is True
    if LEGACY_EXPANDED_MODE == "ignore":
        assert result["legacy_safely_ignored_expanded_reaction"] is True
        assert result["legacy_expanded_reaction_converged"] is False
    elif LEGACY_EXPANDED_MODE == "converge":
        assert result["legacy_expanded_reaction_converged"] is True
        assert result["legacy_safely_ignored_expanded_reaction"] is False
    else:
        assert LEGACY_EXPANDED_MODE == "either"
        assert (
            result["legacy_safely_ignored_expanded_reaction"]
            or result["legacy_expanded_reaction_converged"]
        )
    assert result["post_emoji_desktop_message_id_preserved"] is True
    assert result["post_emoji_desktop_message_delivered"] is True
    assert result["post_emoji_phone_message_id_preserved"] is True
    assert result["post_emoji_phone_message_delivered"] is True
    assert result["current_alive_after_expanded_reaction"] is True
    assert result["legacy_alive_after_expanded_reaction"] is True
    assert result["clean_shutdown"] is True
    assert result["stderr_content_free"] is True

from __future__ import annotations

import os

import pytest

from tools.direct_lan_harness import run


@pytest.mark.integration
def test_real_signed_direct_lan_invitation_route() -> None:
    if os.environ.get("MESH_CHAT_RUN_DIRECT_LAN_TESTS") != "1":
        pytest.skip(
            "Set MESH_CHAT_RUN_DIRECT_LAN_TESTS=1 to launch isolated direct-LAN peers"
        )

    result = run()

    assert result["route"] == "signed_tcp_hint_only"
    assert result["hint"]["type"] == "tcp"
    assert result["inviter_nearby_discovery"] is False
    assert result["joiner_nearby_discovery"] is False
    assert result["inviter_auto_interface"] is False
    assert result["joiner_auto_interface"] is False
    assert result["inviter_tcp_server"] is True
    assert result["inviter_tcp_client"] is True
    assert result["joiner_tcp_server"] is True
    assert result["joiner_tcp_client"] is True
    assert result["pending_request"] is True
    assert result["acceptance_returned"] is True
    assert result["approval_elapsed_seconds"] < 20
    assert result["message_received"] is True
    assert result["sender_delivered"] is True
    assert result["phone_first_command_ok"] is True
    assert result["phone_first_command_elapsed_seconds"] < 20
    assert result["phone_first_command_id_preserved"] is True
    assert result["phone_first_received"] is True
    assert result["phone_first_sender_delivered"] is True
    assert result["phone_first_message_id_preserved"] is True
    assert result["desktop_reply_command_ok"] is True
    assert result["desktop_reply_command_elapsed_seconds"] < 20
    assert result["desktop_reply_command_id_preserved"] is True
    assert result["desktop_reply_received"] is True
    assert result["desktop_reply_sender_delivered"] is True
    assert result["desktop_reply_message_id_preserved"] is True
    assert result["direct_before_group_received"] is True
    assert result["direct_before_group_delivered"] is True
    assert result["direct_after_group_received"] is True
    assert result["direct_after_group_delivered"] is True
    assert result["group_invitation_received"] is True
    assert result["group_invitation_receipted"] is True
    assert result["group_joined"] is True
    assert result["group_message_received"] is True
    assert result["group_message_id_preserved"] is True
    assert result["group_sender_delivered"] is True
    assert result["group_single_recipient"] is True


@pytest.mark.integration
def test_real_phone_shaped_joiner_sends_without_reverse_listener() -> None:
    if os.environ.get("MESH_CHAT_RUN_DIRECT_LAN_TESTS") != "1":
        pytest.skip(
            "Set MESH_CHAT_RUN_DIRECT_LAN_TESTS=1 to launch isolated direct-LAN peers"
        )

    # Mobile operating systems commonly permit an outbound TCP client while
    # refusing unsolicited inbound connections to the app's listener. Match
    # the physical regression exactly: Android sends and receives its receipt
    # first, then desktop replies over that same full-duplex connection. The
    # two commands also cross the production frame codec and dispatch boundary.
    result = run(joiner_lan_fallback=False)

    assert result["route"] == "signed_tcp_hint_only"
    assert result["inviter_tcp_server"] is True
    assert result["inviter_tcp_client"] is False
    assert result["joiner_tcp_server"] is False
    assert result["joiner_tcp_client"] is True
    assert result["pending_request"] is True
    assert result["acceptance_returned"] is True
    assert result["phone_first_command_ok"] is True
    assert result["phone_first_command_elapsed_seconds"] < 20
    assert result["phone_first_command_id_preserved"] is True
    assert result["phone_first_received"] is True
    assert result["phone_first_sender_delivered"] is True
    assert result["phone_first_message_id_preserved"] is True
    assert result["desktop_reply_command_ok"] is True
    assert result["desktop_reply_command_elapsed_seconds"] < 20
    assert result["desktop_reply_command_id_preserved"] is True
    assert result["desktop_reply_received"] is True
    assert result["desktop_reply_sender_delivered"] is True
    assert result["desktop_reply_message_id_preserved"] is True
    assert result["direct_before_group_received"] is True
    assert result["direct_before_group_delivered"] is True
    assert result["direct_after_group_received"] is True
    assert result["direct_after_group_delivered"] is True

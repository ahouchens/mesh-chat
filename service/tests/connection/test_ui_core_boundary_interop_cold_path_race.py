"""Private-port controls for cold readiness after an actual native lease changes."""

import json
from uuid import uuid4

import pytest

from mesh_chat.errors import NativeUnavailable
from test_native_lease_retirement_composition import (
    await_retirement, manual_carriers, request_retirement, retirement_requests,
)
from test_pairing_runtime import native_pairing
from test_webrtc_interface import reticulum


@pytest.mark.parametrize("initiator", ["windows"])
def test_authorized_inventory_then_exact_retirement_rejects_old_private_path(
        manual_carriers, monkeypatch, initiator):
    """Real service, owner and native host; no controller or peer DTO shortcut."""
    state = manual_carriers
    requests = retirement_requests(state)
    role = "android"
    peer, service, host = state.peers[role], state.services[role], state.hosts[role]
    logical, physical = state.sessions[role], state.physical[role]
    before = peer.inventory()
    row, = [item for item in before["resources"] if item["logical_session"] == logical]
    assert row["physical_resource"] == physical
    assert row["adopted"] is True and row["owner_state"] == "authorized"

    # The same public code can also mean a native inspection error while this
    # exact resource and its service/profile incarnation remain current.
    with monkeypatch.context() as patch:
        patch.setattr(host, "pathEvidence", lambda *_: json.dumps({
            "ok": False, "error": "native_webrtc_inspection_busy"}))
        with pytest.raises(NativeUnavailable) as caught:
            peer.path(logical, physical, uuid4().hex)
    assert caught.value.code == "native_unavailable"
    still_current = peer.inventory()
    assert (still_current["service_incarnation"], still_current["profile_incarnation"]) == (
        before["service_incarnation"], before["profile_incarnation"])
    assert any(item["logical_session"] == logical and item["physical_resource"] == physical
               and item["owner_state"] == "authorized" for item in still_current["resources"])

    # A changed incarnation must be visible in a fresh private inventory even
    # when a path read produces the same redacted native_unavailable code.
    with monkeypatch.context() as patch:
        patch.setattr(service, "_runtime_incarnation", uuid4().hex)
        patch.setattr(host, "pathEvidence", lambda *_: json.dumps({
            "ok": False, "error": "native_webrtc_inspection_busy"}))
        with pytest.raises(NativeUnavailable) as caught:
            peer.path(logical, physical, uuid4().hex)
        changed = peer.inventory()
        assert changed["service_incarnation"] != before["service_incarnation"]
        assert changed["profile_incarnation"] != before["profile_incarnation"]
    assert caught.value.code == "native_unavailable"

    # Retire through the actual qualification authority. The stale inventory
    # tuple cannot license a later sample of the removed exact resource.
    request_retirement(state, requests)
    await_retirement(state, requests)
    retired = peer.inventory()
    assert (retired["service_incarnation"], retired["profile_incarnation"]) == (
        before["service_incarnation"], before["profile_incarnation"])
    assert not any(item["logical_session"] == logical and item["physical_resource"] == physical
                   for item in retired["resources"])
    with pytest.raises(NativeUnavailable) as caught:
        peer.path(logical, physical, uuid4().hex)
    assert caught.value.code == "native_unavailable"

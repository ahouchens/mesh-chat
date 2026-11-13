"""Private retained-SDP ICE summary; no native, network or packet access."""

from hashlib import sha256
import json
from types import SimpleNamespace
from time import monotonic
from uuid import uuid4

import pytest

from mesh_chat.connection.model import Phase

from mesh_chat.connection.pairing_ice_diagnostics import (
    ice_diagnostic, unavailable_ice_diagnostic, validated_pairing_ice_diagnostic,
)
from mesh_chat.core_api.qualification_host import QualificationControl
from mesh_chat.errors import ContactNotApproved
from test_pairing_runtime import SDP, native_pairing, run_until


def sdp(ufrag, *candidates):
    return "\r\n".join(("v=0", "m=application 9 UDP/DTLS/SCTP webrtc-datachannel",
                         "a=ice-ufrag:" + ufrag, *candidates, ""))


LOCAL = sdp("local1234",
    "a=candidate:1 1 udp 123 192.0.2.1 5000 typ host",
    "a=candidate:2 1 udp 122 198.51.100.2 5001 typ srflx")
REMOTE = sdp("remote5678",
    "a=candidate:3 1 tcp 121 peer.local 9 typ host tcptype active",
    "a=candidate:4 1 udp 120 2001:db8::1 5002 typ relay")


def test_fixed_candidate_counts_and_private_correlation_are_copies():
    result = ice_diagnostic(LOCAL, REMOTE)
    assert result["availability"] == "selected"
    assert result["local"] == {"total": 2,
        "types": {"host": 1, "srflx": 1, "prflx": 0, "relay": 0, "unknown": 0},
        "protocols": {"udp": 2, "tcp": 0, "unknown": 0},
        "families": {"ipv4": 2, "ipv6": 0, "mdns": 0, "unknown": 0}}
    assert result["remote"]["families"] == {"ipv4": 0, "ipv6": 1, "mdns": 1, "unknown": 0}
    assert result["correlation"] == {
        "local_ufrag_sha256": sha256(b"local1234").hexdigest(),
        "remote_ufrag_sha256": sha256(b"remote5678").hexdigest()}
    selected = validated_pairing_ice_diagnostic(result)
    selected["local"]["types"]["host"] = 99
    assert result["local"]["types"]["host"] == 1
    assert all(secret not in str(result) for secret in ("192.0.2.1", "peer.local", "local1234"))


def test_missing_malformed_and_overbound_sdp_is_unavailable():
    unavailable = unavailable_ice_diagnostic()
    assert ice_diagnostic(LOCAL, "bad") == unavailable
    assert ice_diagnostic(LOCAL.replace("a=ice-ufrag:local1234", ""), REMOTE) == unavailable
    assert ice_diagnostic(LOCAL.replace("a=ice-ufrag:local1234", "a=ice-ufrag:one\r\na=ice-ufrag:two"), REMOTE) == unavailable
    assert ice_diagnostic(LOCAL.replace("local1234", "local-1234"), REMOTE) == unavailable
    assert ice_diagnostic(LOCAL.replace("v=0\r\n", "v=0junk\r\n", 1), REMOTE) == unavailable
    assert ice_diagnostic(LOCAL, REMOTE + "a=candidate:bad\r\n") == unavailable
    assert ice_diagnostic(LOCAL + ("a=candidate:1 1 udp 1 192.0.2.1 5 typ host\r\n" * 257), REMOTE) == unavailable
    assert ice_diagnostic(LOCAL, sdp("local1234")) == unavailable


def test_validator_rejects_extra_fields_inconsistent_counts_and_raw_text():
    selected = ice_diagnostic(LOCAL, REMOTE)
    assert validated_pairing_ice_diagnostic({**selected, "sdp": LOCAL}) is None
    selected["local"]["total"] = 3
    assert validated_pairing_ice_diagnostic(selected) is None
    assert validated_pairing_ice_diagnostic({**unavailable_ice_diagnostic(), "local": LOCAL}) is None


def test_real_pairing_terminal_checking_timeout_retains_exact_sdp_once(native_pairing):
    create, _ = native_pairing
    first, first_host, *_ = create()
    second, second_host, *_ = create()
    def local_offer(host, sdp_value):
        host.createOffer = lambda *_: json.dumps({"ok": True, "sdp": sdp_value})
        host.acceptOffer = lambda *_: json.dumps({"ok": True, "sdp": sdp_value})
    first_sdp = SDP + "a=ice-ufrag:local1234\r\na=candidate:1 1 udp 123 192.0.2.1 5000 typ host\r\n"
    second_sdp = SDP + "a=ice-ufrag:remote5678\r\na=candidate:2 1 udp 122 198.51.100.2 5001 typ srflx\r\n"
    local_offer(first_host, first_sdp)
    local_offer(second_host, second_sdp)
    first_id, second_id = str(uuid4()), str(uuid4())
    first.native_pairing_begin(first_id, role="offer", authorized=lambda: True, allow_direct_ip_disclosure=True)
    run_until(first, lambda: first.native_pairing_status(first_id)["pairing_code"] is not None)
    code = first.native_pairing_status(first_id)["pairing_code"]
    second.native_pairing_begin(second_id, role="answer", pairing_code=code,
                                authorized=lambda: True, allow_direct_ip_disclosure=True)
    run_until(second, lambda: second.native_pairing_status(second_id)["state"] == "awaiting_approval")
    first._connection_runtime.now = lambda: monotonic() + 6
    run_until(first, lambda: first.native_pairing_status(first_id)["state"] == "awaiting_approval")
    for service, operation in ((first, first_id), (second, second_id)):
        run_until(service, lambda: next(state for state in service._connection_runtime.owner.snapshots()
                  if state.key.profile_id == operation).negotiation.phase is Phase.CHECKING)
        state = next(state for state in service._connection_runtime.owner.snapshots()
                     if state.key.profile_id == operation)
        assert state.negotiation.phase is Phase.CHECKING
        service._connection_runtime.now = lambda: monotonic() + 100
        run_until(service, lambda: service.native_pairing_status(operation)["state"] == "retired")
        observed = service.native_pairing_qualification_status(operation)
        assert observed["retirement"] == {"phase": "checking", "event": "tick", "reason": "phase_timeout"}
        assert observed["ice_diagnostic"]["availability"] == "selected"
        assert observed["ice_diagnostic"]["local"]["total"] == 1
        assert observed["ice_diagnostic"]["remote"]["total"] == 1
        observed["ice_diagnostic"]["local"]["types"]["host"] = 99
        assert service.native_pairing_qualification_status(operation)["ice_diagnostic"]["local"]["total"] == 1
        context = service._native_pairing_contexts[operation]
        assert "ice_diagnostic_snapshot" in context
        assert all(raw not in str(observed["ice_diagnostic"]) for raw in ("192.0.2.1", "198.51.100.2", "local1234"))
        other = {**context, "id": str(uuid4())}
        service._native_pairing_contexts[other["id"]] = other
        assert service.native_pairing_qualification_status(operation)["ice_diagnostic"] == unavailable_ice_diagnostic()
        del service._native_pairing_contexts[other["id"]]
        assert service.native_pairing_qualification_status(operation)["ice_diagnostic"]["availability"] == "selected"
        for field, replacement in (("runtime_epoch", "stale"), ("identity", lambda: None),
                                   ("host", object())):
            original = context[field]
            context[field] = replacement
            assert service._native_pairing_ice_diagnostic(operation, context) == unavailable_ice_diagnostic()
            context[field] = original
        original_doc = context["offer"]["document"]
        context["offer"]["document"] = "malformed"
        assert service._native_pairing_ice_diagnostic(operation, context) == unavailable_ice_diagnostic()
        context["offer"]["document"] = original_doc


def test_private_status_projects_only_valid_exact_timeout_summary():
    status = {"state": "retired", "retirement": {"phase": "checking", "event": "tick",
              "reason": "phase_timeout"}, "ice_diagnostic": ice_diagnostic(LOCAL, REMOTE)}
    service = SimpleNamespace(store=SimpleNamespace(opaque_id=lambda *_: "a" * 64),
                              native_pairing_qualification_status=lambda _: status)
    current = [service]
    port = QualificationControl(lambda: current[0])
    port._pairing_service = lambda: current[0]
    operation = str(uuid4())
    query = lambda: port._pairing(service, "qualification.pairing_status", {"operation_id": operation})
    assert query()["ice_diagnostic"] == status["ice_diagnostic"]
    status["ice_diagnostic"] = {**status["ice_diagnostic"], "sdp": LOCAL}
    assert query()["ice_diagnostic"] == unavailable_ice_diagnostic()
    status["retirement"] = {"phase": "gather_offer", "event": "tick", "reason": "phase_timeout"}
    assert "ice_diagnostic" not in query()
    status["retirement"] = {"phase": "checking", "event": "tick", "reason": "phase_timeout"}
    current[0] = object()
    with pytest.raises(ContactNotApproved):
        query()

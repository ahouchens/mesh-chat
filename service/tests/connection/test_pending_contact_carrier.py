import threading
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest

from mesh_chat.app_protocol import build_fields, conversation_id, M_KIND, META_FIELD
from mesh_chat.contact_bootstrap import ContactBootstrapScope
from mesh_chat.models import MessageKind
from mesh_chat.native_onboarding_bootstrap import PendingContactCarrier
from mesh_chat.native_webrtc_service import NativeWebRTCServiceMixin


@pytest.fixture
def carrier():
    contact = {"trust": "awaiting_consent", "destination_hash": "11" * 16}
    service = SimpleNamespace(_identity=object(), _shutdown=threading.Event(), _native_webrtc_live={"session"},
        _native_resources=SimpleNamespace(require=lambda _: "physical", current=lambda *_: True),
        _native_webrtc_peers={"session": contact["destination_hash"]}, _contact_by_destination=lambda _: contact)
    service._native_work_allowed = lambda: True
    service._require_native_work = NativeWebRTCServiceMixin._require_native_work.__get__(service)
    value = PendingContactCarrier(service, "session", b"p" * 64, int(time.time()) + 90)
    service._pending_contact_carriers = {"session": value}
    return value, service, contact


@pytest.mark.parametrize("change", ["blocked", "identity_changed", "locked", "shutdown", "retired", "replacement", "peer", "expired", "scope"])
def test_pending_authority_cannot_survive_revocation_or_resource_replacement(carrier, change):
    value, service, contact = carrier
    assert value.current()
    if change in {"blocked", "identity_changed"}: contact["trust"] = change
    elif change == "locked": service._identity = None
    elif change == "shutdown": service._shutdown.set()
    elif change == "retired": service._native_webrtc_live.clear()
    elif change == "replacement": service._native_resources.current = lambda *_: False
    elif change == "peer": service._native_webrtc_peers["session"] = "22" * 16
    elif change == "expired": value.deadline = time.monotonic() - 1
    else: service._pending_contact_carriers.clear()
    assert not value.current()


def test_pending_control_scope_cannot_send_chat_or_other_peer_messages(carrier):
    value, _, contact = carrier
    assert not value.send(contact, {"kind": "chat"})
    assert not value.send({"destination_hash": "22" * 16}, {"kind": "contact_request"})
    assert value.send(contact, {"kind": "contact_request"})  # Durable retry remains queued until keys exist.
    assert not value.transfer_ready


@pytest.mark.parametrize("kind", [kind.value for kind in MessageKind if kind.value not in ContactBootstrapScope.KINDS])
def test_pending_scope_rejects_every_other_application_kind(kind):
    local, peer = b"l" * 16, b"p" * 16
    fields = build_fields(kind=MessageKind.CONTACT_ACCEPT, logical_id=str(uuid4()),
        conversation=conversation_id(local, peer), expires_at=int(time.time()) + 30)
    fields[META_FIELD][M_KIND] = kind
    message = SimpleNamespace(source_hash=peer, destination_hash=local, get_fields=lambda: fields,
                              signature_validated=True, content=b"", content_as_string=lambda: "")
    assert not ContactBootstrapScope().accepts(message, local, peer)


def test_pending_worker_status_requires_a_sent_control(carrier):
    value, _, _ = carrier
    from mesh_chat.errors import ValidationError
    with pytest.raises(ValidationError):
        value._event({"kind": "status", "logical_id": "unrelated", "state": "delivered", "native_id": "x"})


def test_shutdown_never_reopens_vault_authority(carrier):
    value, service, _ = carrier
    service._shutdown.set()
    service._contact_by_destination = lambda _: pytest.fail("Vault queried after shutdown")
    assert not value.current()


def test_terminal_owner_denies_pending_scope_before_vault_or_worker_access(carrier):
    value, service, contact = carrier
    service._native_work_allowed = lambda: False
    service._contact_by_destination = lambda _: pytest.fail("Authority read after terminal fence")
    assert not value.current()
    assert not value.send(contact, {"kind": "contact_request"})
    value.receive("AQ==")
    assert not value._packets


def test_terminal_owner_discards_late_pending_send_status(carrier):
    value, service, contact = carrier
    value.ready = True
    def request(*_args, **_kwargs):
        service._native_work_allowed = lambda: False
        return "native-control"
    value._worker = SimpleNamespace(request=request)
    service._on_native_status_locked = lambda *_: pytest.fail("Status crossed terminal fence")
    assert not value.send(contact, {"kind": "contact_request", "id": "control", "expires_at": int(time.time()) + 30})
    assert not value._sent


def test_terminal_owner_prevents_pending_worker_activation(carrier):
    value, service, _ = carrier
    service._native_work_allowed = lambda: False
    service._dispatch_lock = threading.RLock()
    closed = []
    service.native_webrtc_close = lambda session, **kwargs: closed.append((session, kwargs))
    value._worker = SimpleNamespace(request=lambda *_: pytest.fail("Activated quarantined worker"), close=lambda: None)
    value.opened()
    value._run()
    assert closed == [("session", {"expected_physical": "physical"})]
    assert not service._pending_contact_carriers


def test_shutdown_during_packet_send_stops_remaining_packets_and_events(carrier):
    value, service, _ = carrier
    service._dispatch_lock = threading.RLock()
    sent = []

    def send(physical, packet):
        sent.append((physical, packet))
        service._shutdown.set()

    service._native_webrtc_host = lambda: SimpleNamespace(send=send)
    service._on_native_status_locked = lambda *_: pytest.fail("Status applied after shutdown")
    value._sent["control"] = "contact_accept"
    value._worker = SimpleNamespace(request=lambda *_args, **_kwargs: {
        "packets": ["01", "02"], "recipient_ready": True,
        "events": [{"kind": "status", "logical_id": "control", "state": "received_by_endpoint", "native_id": "x"}],
    })
    assert value._exchange() is False
    assert sent == [("physical", b"\x01")]
    assert not value.transfer_ready


def test_shutdown_discards_a_completed_control_event(carrier):
    value, service, _ = carrier
    value._sent["control"] = "contact_accept"
    service._shutdown.set()
    service._on_native_status_locked = lambda *_: pytest.fail("Status applied after shutdown")
    value._event({"kind": "status", "logical_id": "control", "state": "received_by_endpoint", "native_id": "x"})
    assert not value.transfer_ready


def test_execution_denial_stops_pending_contact_transport(carrier):
    value, service, _ = carrier
    service._workspace_lifecycle_state = lambda: {"state": "suspended"}
    service._background_availability_enabled = lambda: False
    assert not value.current()


def test_bootstrap_transport_status_cannot_claim_an_application_receipt(carrier):
    value, _, _ = carrier
    value._sent["control"] = "contact_accept"
    from mesh_chat.errors import ValidationError
    with pytest.raises(ValidationError):
        value._event({"kind": "status", "logical_id": "control", "state": "delivered", "native_id": "x"})


def test_verified_unpadded_signer_identity_is_preserved_at_worker_boundary(carrier, monkeypatch):
    import json
    import RNS
    from mesh_chat.invitations import _b64encode
    import mesh_chat.native_onboarding_bootstrap as module
    _, service, _ = carrier
    service._connection_policy = "shared-native"
    service.network = SimpleNamespace()
    service._pending_contact_carriers.clear()
    service._native_webrtc_descriptions = {"session": {}}
    key = RNS.Identity().get_public_key()
    checked = SimpleNamespace(signer_destination="11" * 16, expires_at=int(time.time()) + 90,
        serialized=json.dumps({"signer_public_key": _b64encode(key)}))
    captured = []
    monkeypatch.setattr(PendingContactCarrier, "start", lambda self: captured.append(self.public_identity))
    module.begin(service, "session", checked)
    assert captured == [key]


def test_blocked_contact_cannot_allocate_a_bootstrap_worker(carrier, monkeypatch):
    import mesh_chat.native_onboarding_bootstrap as module
    from mesh_chat.errors import ContactNotApproved
    _, service, contact = carrier
    service._connection_policy = "shared-native"
    service.network = SimpleNamespace()
    contact["trust"] = "blocked"
    monkeypatch.setattr(PendingContactCarrier, "start", lambda _: pytest.fail("Blocked scope allocated a process"))
    with pytest.raises(ContactNotApproved):
        module.begin(service, "session", SimpleNamespace(signer_destination="11" * 16))

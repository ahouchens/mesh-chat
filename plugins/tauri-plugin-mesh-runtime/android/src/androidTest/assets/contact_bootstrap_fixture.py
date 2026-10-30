"""Real Binder/RNS contact control, with packets routed by the test only.

This qualifies the isolated interpreter and signed scope, not JNI transport,
user approval, main-service ownership transfer or application receipts.
"""
import base64
import time
from uuid import uuid4

import LXMF
import RNS

from mesh_chat.app_protocol import parse_payload
from mesh_chat.contact_bootstrap import ContactBootstrapEngine
from mesh_chat.errors import ValidationError
from mesh_chat.invitations import create_invitation
from mesh_chat.network import validate_unknown_source_signature


def run(directory, factory=None):
    if factory is None:
        from mesh_chat.direct_bootstrap_mobile import AndroidBootstrapProcess
        factory = AndroidBootstrapProcess
    local, remote = RNS.Identity(), RNS.Identity()
    engine = ContactBootstrapEngine(local.get_private_key(), remote.get_public_key(),
                                    int(time.time()) + 120, directory=directory)
    worker = None
    try:
        main_reticulum = RNS.Reticulum.get_instance()
        worker = factory()
        # This must succeed with RNS already running in the calling interpreter.
        worker.request("initialize_contact", private_identity=remote.get_private_key().hex(),
                       peer_identity=local.get_public_key().hex(), expires_at=int(time.time()) + 120)
        worker.request("activate")
        engine.activate()
        incoming, observed, ready = [], [], [False, False]

        def exchange():
            result = engine.exchange(incoming)
            incoming.clear()
            ready[0] = result["recipient_ready"]
            observed.extend((0, event) for event in result["events"])
            result = worker.request("exchange", packets=[packet.hex() for packet in result["packets"]])
            incoming.extend(bytes.fromhex(packet) for packet in result["packets"])
            ready[1] = result["recipient_ready"]
            observed.extend((1, event) for event in result["events"])
            time.sleep(.02)

        def until(predicate):
            deadline = time.monotonic() + 30
            while not predicate() and time.monotonic() < deadline:
                exchange()
            assert predicate(), "Contact bootstrap exchange did not complete"

        until(lambda: all(ready))
        invitation = create_invitation(remote, "Synthetic contact bootstrap")["file"]
        request_id, accept_id = str(uuid4()), str(uuid4())
        worker.request("send", kind="contact_request", logical_id=request_id,
                       document=invitation, expires_at=int(time.time()) + 45)
        until(lambda: any(index == 0 and event["kind"] == "inbound" for index, event in observed))
        engine.send(kind="contact_accept", logical_id=accept_id, document="", expires_at=int(time.time()) + 45)
        until(lambda: any(index == 1 and event["kind"] == "inbound" for index, event in observed))
        for index, identity, kind, logical_id in ((0, remote, "contact_request", request_id),
                                                (1, local, "contact_accept", accept_id)):
            messages = [event for receiver, event in observed if receiver == index and event["kind"] == "inbound"]
            assert len(messages) == 1
            packed = messages[0]["packed"]
            if index == 1:
                packed = base64.b64decode(packed, validate=True)
            message = LXMF.LXMessage.unpack_from_bytes(packed)
            assert validate_unknown_source_signature(message, identity.get_public_key())
            message.signature_validated = True
            payload = parse_payload(message)
            assert (payload.kind.value, payload.logical_id) == (kind, logical_id)
            if index == 0:
                assert payload.invitation == invitation
        try:
            worker.request("send", kind="chat", logical_id=str(uuid4()), document="forbidden",
                           expires_at=int(time.time()) + 30)
        except ValidationError:
            pass
        else:
            raise AssertionError("Contact interpreter admitted ordinary chat")
        try:
            worker.request("exchange", packets=[])
        except ValidationError:
            pass
        else:
            raise AssertionError("Failed interpreter remained available")
        assert RNS.Reticulum.get_instance() is main_reticulum
        assert engine.exchange([])["recipient_ready"]
        return True
    finally:
        if worker is not None:
            worker.close()
        engine.close()

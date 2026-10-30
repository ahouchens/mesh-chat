"""Real isolated RNS workers; transport/scope evidence, not contact approval."""
import base64
import time
from uuid import uuid4

import LXMF
import pytest
import RNS

from mesh_chat.app_protocol import parse_payload
from mesh_chat.direct_bootstrap_process import BootstrapProcess
from mesh_chat.errors import ValidationError
from mesh_chat.invitations import create_invitation
from mesh_chat.network import validate_unknown_source_signature


def test_isolated_contact_workers_keep_existing_signed_payloads_and_reject_chat(tmp_path):
    identities = [RNS.Identity(), RNS.Identity()]
    workers = []
    try:
        for index in range(2):
            worker = BootstrapProcess(directory=tmp_path)
            workers.append(worker)
            worker.request("initialize_contact", private_identity=identities[index].get_private_key().hex(),
                peer_identity=identities[1-index].get_public_key().hex(), expires_at=int(time.time()) + 90)
            worker.request("activate")
        incoming, ready, observed = [[], []], [False, False], []
        def exchange():
            for index, worker in enumerate(workers):
                result = worker.request("exchange", packets=incoming[index])
                incoming[index] = []
                incoming[1-index].extend(result["packets"])
                ready[index] = result["recipient_ready"]
                observed.extend((index, event) for event in result["events"])
            time.sleep(.02)
        deadline = time.monotonic() + 15
        while not all(ready) and time.monotonic() < deadline: exchange()
        assert all(ready)
        logical_id = str(uuid4())
        invitation = create_invitation(identities[0], "Bootstrap peer")["file"]
        workers[0].request("send", kind="contact_request", logical_id=logical_id,
            document=invitation, expires_at=int(time.time()) + 30)
        deadline = time.monotonic() + 20
        while not any(index == 1 and event["kind"] == "inbound" for index, event in observed) and time.monotonic() < deadline:
            exchange()
        inbound = [event for index, event in observed if index == 1 and event["kind"] == "inbound"]
        assert len(inbound) == 1
        message = LXMF.LXMessage.unpack_from_bytes(base64.b64decode(inbound[0]["packed"]))
        assert validate_unknown_source_signature(message, identities[0].get_public_key())
        message.signature_validated = True
        payload = parse_payload(message)
        assert (payload.kind.value, payload.logical_id, payload.invitation) == ("contact_request", logical_id, invitation)
        # Invalid use retires this private interpreter; it cannot become a chat router.
        with pytest.raises(ValidationError):
            workers[0].request("send", kind="chat", logical_id=str(uuid4()), document="forbidden", expires_at=int(time.time()) + 30)
    finally:
        for worker in workers: worker.close()

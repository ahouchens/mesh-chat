import base64
import json
import time
import uuid

import pytest
import RNS

from mesh_chat.direct_binding import BindingAuthority, create_binding
from mesh_chat.direct_offer import OfferAuthority, create_offer
from mesh_chat.direct_exchange import create_answer, create_ready
from mesh_chat.direct_documents import PREFIX, MAX_BYTES, export_connection_document, verify_connection_document
from mesh_chat.errors import IdentityMismatch, ValidationError
from mesh_chat.invitations import canonical_bytes
from mesh_chat.workspace_protocol import _destination_for, verify_workspace_invitation, workspace_document_digest
from test_workspace_service import _service, _op


@pytest.fixture
def document(tmp_path):
    owner, joiner = RNS.Identity(), RNS.Identity()
    service, _ = _service(tmp_path, owner, "Owner")
    try:
        workspace = service.create_workspace(_op(97000), "Email setup", "")
        raw = service.create_workspace_invitation_command(workspace["id"], _op(97001))["text"]
        invite = verify_workspace_invitation(raw)
        now = int(time.time())
        scope = {"kind":"invitation", "digest":workspace_document_digest(invite.serialized), "expires_at":invite.expires_at}
        oa = OfferAuthority(owner.get_public_key(), scope, now+240, b"c"*32)
        aa = BindingAuthority(joiner.get_public_key(), _destination_for(owner), scope, now+240, b"c"*32)
        ra = BindingAuthority(owner.get_public_key(), _destination_for(joiner), scope, now+240, b"c"*32)
        options = dict(session_id=str(uuid.uuid4()), generation=1, candidates=[],
                       issued_at=now, expires_at=now+240, version=2)
        offer = create_offer(owner, oa, b"offer cert", **options)
        answer = create_answer(joiner, create_binding(joiner, aa, b"answer cert", challenge=b"c"*32, **options), offer)
        ready = create_ready(owner, create_binding(owner, ra, b"ready cert", challenge=b"c"*32,
            **{**options, "generation":2}), answer)
        return dict(invitation=invite.serialized, offer=offer, offer_certificate=b"offer cert",
                    answer=answer, answer_certificate=b"answer cert", ready=ready, ready_certificate=b"ready cert")
    finally:
        service.close()


@pytest.mark.parametrize("kind", ["offer", "answer", "ready"])
def test_public_email_and_file_roundtrip_without_hosting(document, kind):
    if kind != "ready":
        document.update(ready=None, ready_certificate=None)
    if kind == "offer":
        document.update(answer=None, answer_certificate=None)
    text = export_connection_document(**document)
    verified = verify_connection_document(text)
    assert verified.kind == kind
    assert verify_connection_document(verified.serialized) == verified
    preview = verified.preview()
    assert preview["candidate_count"] == 0 and preview["state"] == "no_public_candidate"
    assert not any(field in preview for field in ("certificate", "host", "port", "session", "private_key"))


@pytest.mark.parametrize("field", ["offer", "answer", "ready"])
def test_any_substituted_certificate_fails_full_chain(document, field):
    document[field+"_certificate"] = b"substituted"
    with pytest.raises(IdentityMismatch):
        export_connection_document(**document)


@pytest.mark.parametrize("fault", ["version", "unknown", "duplicate", "missing_parent", "legacy_inner", "base64", "oversize"])
def test_public_container_rejects_ambiguous_or_incompatible_documents(document, fault):
    text = export_connection_document(**document)
    raw = verify_connection_document(text).serialized
    value = json.loads(raw)
    if fault == "version": value["v"] = True
    elif fault == "unknown": value["socket"] = "renderer cannot choose a native socket"
    elif fault == "missing_parent": value["answer"] = None
    elif fault == "legacy_inner":
        inner = json.loads(value["offer"]["document"])
        inner["v"] = 1
        value["offer"]["document"] = canonical_bytes(inner).decode()
    changed = canonical_bytes(value).decode()
    if fault == "duplicate": changed = raw[:-1]+',"v":2}'
    elif fault == "base64": changed = text + "="
    elif fault == "oversize": changed = "x"*(MAX_BYTES*2)
    with pytest.raises((ValidationError, IdentityMismatch)):
        verify_connection_document(changed)


def test_delayed_mail_cannot_revive_expired_candidate_window(document):
    text = export_connection_document(**document)
    expiry = json.loads(document["offer"])["expires_at"]
    with pytest.raises(ValidationError):
        verify_connection_document(text, now=expiry)

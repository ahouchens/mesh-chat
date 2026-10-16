import json
import uuid

import pytest
import RNS

from mesh_chat.direct_binding import BindingAuthority, create_binding
from mesh_chat.direct_exchange import create_answer, create_ready, verify_answer, verify_ready
from mesh_chat.direct_offer import OfferAuthority, create_offer
from mesh_chat.errors import IdentityMismatch, ValidationError
from mesh_chat.workspace_protocol import _destination_for, _sign


@pytest.fixture
def chain():
    owner, joiner = RNS.Identity(), RNS.Identity()
    scope = {"kind": "invitation", "digest": "ab" * 32, "expires_at": 3000}
    offer_authority = OfferAuthority(owner.get_public_key(), scope, 2000, b"c" * 32)
    answer_authority = BindingAuthority(joiner.get_public_key(), _destination_for(owner), scope, 2000, b"c" * 32)
    ready_authority = BindingAuthority(owner.get_public_key(), _destination_for(joiner), scope, 2000, b"c" * 32)
    options = dict(session_id=str(uuid.uuid4()), generation=1,
                   candidates=[{"host": "8.8.8.8", "port": 12345, "expires_at": 2000}],
                   issued_at=1000, expires_at=1500)
    offer = create_offer(owner, offer_authority, b"owner cert", **options)
    answer_binding = create_binding(joiner, answer_authority, b"joiner cert", challenge=b"c" * 32, **options)
    answer = create_answer(joiner, answer_binding, offer)
    ready_binding = create_binding(owner, ready_authority, b"fresh owner cert", challenge=b"c" * 32,
                                   **{**options, "generation": 2})
    ready = create_ready(owner, ready_binding, answer)
    answer_args = dict(offer_raw=offer, offer_authority=offer_authority, offer_certificate_der=b"owner cert", now=1100)
    ready_args = dict(**answer_args, answer_raw=answer, answer_authority=answer_authority,
                      answer_certificate_der=b"joiner cert")
    return dict(owner=owner, joiner=joiner, answer=answer, ready=ready, offer=offer,
                answer_authority=answer_authority, ready_authority=ready_authority,
                answer_args=answer_args, ready_args=ready_args)


def check(chain, kind, raw=None, previous=None, **changes):
    verifier = verify_answer if kind == "answer" else verify_ready
    cert = b"joiner cert" if kind == "answer" else b"fresh owner cert"
    return verifier(raw or chain[kind], chain[kind + "_authority"], cert,
                    previous=previous, **{**chain[kind + "_args"], **changes})


def resign(identity, raw, **changes):
    value = json.loads(raw)
    value.pop("signature")
    return _sign(identity, {**value, **changes})


@pytest.mark.parametrize("kind", ["answer", "ready"])
def test_chain_and_identical_replay(chain, kind):
    result = check(chain, kind)
    assert check(chain, kind, previous=result) == result
    assert result.generation == (1 if kind == "answer" else 2)


@pytest.mark.parametrize("kind", ["answer", "ready"])
@pytest.mark.parametrize("changes", [{"v": True}, {"type": "workspace_join"},
    {"parent_digest": "ab" * 32}, {"extra": 1}, {"binding": []}])
def test_signed_invalid_envelopes(chain, kind, changes):
    signer = chain["joiner" if kind == "answer" else "owner"]
    with pytest.raises((ValidationError, IdentityMismatch)):
        check(chain, kind, resign(signer, chain[kind], **changes))


@pytest.mark.parametrize("kind", ["answer", "ready"])
def test_forged_signature_noncanonical_and_expiry(chain, kind):
    with pytest.raises(IdentityMismatch):
        check(chain, kind, resign(RNS.Identity(), chain[kind]))
    with pytest.raises(ValidationError):
        check(chain, kind, " " + chain[kind])
    with pytest.raises(ValidationError):
        check(chain, kind, now=1500)


def test_ready_requires_fresh_owner_generation_and_exact_answer(chain):
    binding = resign(chain["owner"], json.dumps(json.loads(chain["ready"])["binding"]), generation=1)
    with pytest.raises(IdentityMismatch):
        check(chain, "ready", create_ready(chain["owner"], binding, chain["answer"]))
    answer_binding = resign(chain["joiner"], json.dumps(json.loads(chain["answer"])["binding"]), generation=2)
    different = create_answer(chain["joiner"], answer_binding, chain["offer"])
    with pytest.raises(IdentityMismatch):
        check(chain, "ready", answer_raw=different)


def test_answer_cannot_extend_parent_or_change_audience(chain):
    binding = json.loads(chain["answer"])["binding"]
    for changes in ({"expires_at": 1600}, {"issued_at": 999}, {"audience_destination": "ab" * 16}):
        signed = resign(chain["joiner"], json.dumps(binding), **changes)
        with pytest.raises((ValidationError, IdentityMismatch)):
            check(chain, "answer", create_answer(chain["joiner"], signed, chain["offer"]))


def test_parent_certificate_substitution_and_response_conflict(chain):
    with pytest.raises(IdentityMismatch):
        check(chain, "ready", offer_certificate_der=b"substituted")
    first = check(chain, "answer")
    binding = resign(chain["joiner"], json.dumps(json.loads(chain["answer"])["binding"]), session_id=str(uuid.uuid4()))
    with pytest.raises(ValidationError):
        check(chain, "answer", create_answer(chain["joiner"], binding, chain["offer"]), previous=first)

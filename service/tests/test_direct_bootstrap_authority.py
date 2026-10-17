import pytest

from mesh_chat.direct_bootstrap_authority import BootstrapAuthority
from mesh_chat.direct_documents import verify_connection_document
from mesh_chat.errors import ValidationError
from test_direct_setup import peers
from test_workspace_service import _op, _deliver, _flush


def setup_pair(peers, clock):
    owner, joiner, workspace, invite = peers
    offer = owner._direct_setup.offer(invite["id"])
    answer = joiner._direct_setup.answer(offer["text"], _op(98002))
    ready = owner._direct_setup.ready(answer["text"])
    joiner._direct_setup.accept_ready(ready["text"])
    checked = verify_connection_document(ready["text"])
    return (BootstrapAuthority(owner, checked, owner=True, clock=clock),
            BootstrapAuthority(joiner, checked, owner=False, clock=clock))


def test_admission_handoff_is_short_and_requires_both_active_devices(peers):
    now = [100]
    owner, joiner, workspace, _ = peers
    oa, ja = setup_pair(peers, lambda:now[0])
    assert oa.stage == ja.stage == "pending"
    with pytest.raises(ValidationError, match="not admitted"):
        oa.admitted_authority()
    for sent in _flush(joiner, joiner.network):
        _deliver(owner, sent, source_profile=joiner._require_profile(), recipient_profile=owner._require_profile())
    request = next(item for item in owner.workspace_snapshot()["workspace_join_requests"] if item["state"] == "pending")
    owner.approve_workspace_join(workspace["id"], request["id"], _op(98003))
    oa.check()
    assert oa.stage == "admission_handoff" and ja.stage == "pending"
    assert oa.admitted_authority().scope["kind"] == "workspace"
    for sent in _flush(owner, owner.network):
        _deliver(joiner, sent, source_profile=owner._require_profile(), recipient_profile=joiner._require_profile())
    ja.check()
    assert ja.stage == "admission_handoff"
    assert ja.admitted_authority().challenge == oa.admitted_authority().challenge
    now[0] += 31
    for authority in (oa, ja):
        with pytest.raises(ValidationError, match="handoff expired"):
            authority.check()


@pytest.mark.parametrize("fault", ["revoked", "chain", "suspended"])
def test_pending_authority_rechecks_revocation_chain_and_lifecycle(peers, fault):
    owner, _, workspace, invite = peers
    oa, _ = setup_pair(peers, lambda:100)
    if fault == "revoked":
        owner.revoke_workspace_invitation(workspace["id"], invite["id"], _op(98003))
    elif fault == "chain":
        owner._direct_setup.offer(invite["id"])
    else:
        owner.mobile_lifecycle_transition("suspended", "test")
    with pytest.raises(ValidationError):
        oa.check()

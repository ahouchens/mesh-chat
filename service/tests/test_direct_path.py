import pytest
import uuid
import RNS

from mesh_chat.direct_path import client_role, native_parameters
from mesh_chat.direct_binding import BindingAuthority, create_binding
from mesh_chat.workspace_protocol import _destination_for
from mesh_chat.errors import ValidationError


@pytest.mark.parametrize("a,b", [(b"a",b"b"),(b"b",b"a")])
@pytest.mark.parametrize("a_candidates,b_candidates", [([],[]),([1],[]),([],[1]),([1],[1])])
def test_both_verified_sides_agree_on_client_role(a, b, a_candidates, b_candidates):
    role = client_role(a,b,a_candidates,b_candidates)
    assert role is not client_role(b,a,b_candidates,a_candidates)
    if bool(a_candidates) != bool(b_candidates):
        assert role == (not a_candidates)
    else:
        assert role == (a < b)


def test_role_rejects_self_connection():
    with pytest.raises(ValidationError):
        client_role(b"same",b"same",[],[1])


def parameters(local_candidates, remote_candidates, *, now=1100):
    local, remote = RNS.Identity(), RNS.Identity()
    authority = BindingAuthority(remote.get_public_key(), _destination_for(local), {
        "kind":"invitation", "digest":"ab"*32, "expires_at":3000,
    }, 3000, b"c"*32)
    certificate = b"test native public certificate"
    binding = create_binding(remote, authority, certificate, session_id=str(uuid.uuid4()),
        challenge=authority.challenge, generation=1, candidates=remote_candidates,
        issued_at=1000, expires_at=min([2000]+[item["expires_at"] for item in remote_candidates]), version=2)
    return native_parameters(local,local_candidates,binding,certificate,now=now)


def candidate(host="93.184.216.34", expiry=2000):
    return {"host":host,"port":45000,"expires_at":expiry}


@pytest.mark.parametrize("local,remote", [([candidate()],[]),([],[candidate()])])
def test_single_host_keeps_unhosted_side_as_client_and_bounds_window(local, remote):
    result = parameters(local,remote)
    assert result["client"] is (not bool(local))
    assert result["remaining_ms"] == 60_000
    assert all(item["remaining_ms"] <= 300_000 for item in result["candidates"])


@pytest.mark.parametrize("local,remote,now,reason", [
    ([],[],1100,"No public candidate"),
    ([candidate(expiry=1050)],[candidate()],1100,"expired"),
    ([candidate()],[candidate(expiry=1050)],1100,"expired"),
    ([candidate("2606:4700:4700::1111")],[candidate()],1100,"address families"),
    ([],[candidate()],2000,"expired"),
])
def test_activation_rejects_stale_or_incompatible_paths_without_role_reinterpretation(local, remote, now, reason):
    with pytest.raises(ValidationError, match=reason):
        parameters(local,remote,now=now)

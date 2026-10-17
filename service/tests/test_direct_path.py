import pytest

from mesh_chat.direct_path import client_role
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

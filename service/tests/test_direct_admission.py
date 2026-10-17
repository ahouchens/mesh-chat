import json

import pytest

from mesh_chat import direct_admission
from mesh_chat.errors import ValidationError
from mesh_chat.invitations import canonical_bytes


def control():
    # The codec only frames public controls. Durable signature/membership/replay
    # acceptance is independently exercised by workspace and pipeline tests.
    binding = canonical_bytes({"v":2,"scope":{"kind":"workspace"}}).decode()
    return direct_admission.encode(binding,b"certificate")


def test_public_admission_control_roundtrip():
    binding, certificate = direct_admission.decode(control())
    assert json.loads(binding)["scope"]["kind"] == "workspace"
    assert certificate == b"certificate"


@pytest.mark.parametrize("fault", ["version","unknown","duplicate","legacy","pending","scope-type","certificate","oversize"])
def test_malformed_or_wrong_scope_admission_controls_fail_closed(fault):
    raw = control()
    value = json.loads(raw)
    if fault == "version": value["v"] = True
    elif fault == "unknown": value["private_key"] = "forbidden"
    elif fault == "duplicate": raw = raw.replace('"v":2','"v":2,"v":2')
    elif fault == "certificate": value["certificate"] = "A1"
    elif fault == "oversize": raw = "x"*(direct_admission.MAX_BYTES+1)
    else:
        binding = json.loads(value["binding"])
        if fault == "legacy": binding["v"] = 1
        elif fault == "pending": binding["scope"]["kind"] = "invitation"
        else: binding["scope"] = []
        value["binding"] = canonical_bytes(binding).decode()
    if fault not in {"duplicate","oversize"}: raw = canonical_bytes(value).decode()
    with pytest.raises(ValidationError):
        direct_admission.decode(raw)

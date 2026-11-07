"""Private resource observations are not peer identity or permission to adopt."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from mesh_chat.errors import NativeUnavailable
from mesh_chat.native_carrier_evidence import description_hash, validate_inventory

CONTRACTS = Path(__file__).resolve().parents[3] / "contracts/connection"


@pytest.mark.parametrize("vector", json.loads((CONTRACTS / "native-carrier-sdp-v1.vectors.json").read_text()))
def test_sdp_binding_vectors_match_the_browser(vector):
    assert description_hash(vector["sdp"]) == vector["sha256"]


def observation():
    return {"v": 1, "adapter_epoch": "a" * 32, "resources": [{
        "resource": "native-physical-1", "ice_policy": "relay", "pending": False,
        "ice_connection_state": "connected", "signaling_state": "stable", "data_channel_state": "open",
        "local_type": "offer", "remote_type": "answer", "local_sdp_sha256": "b" * 64,
        "remote_sdp_sha256": "c" * 64,
        "channels": [{"label": "mesh-reticulum", "state": "open"}],
    }]}


def test_description_binding_normalizes_only_line_endings_and_end_of_candidates():
    first = "v=0\r\na=ice-ufrag:original\r\na=end-of-candidates\r\n"
    assert description_hash(first) == description_hash("v=0\na=ice-ufrag:original\n")
    assert description_hash(first) != description_hash("v=0\na=ice-ufrag:replacement\n")


def test_valid_inventory_is_copied_and_cannot_be_used_as_an_authority_claim():
    value = observation()
    result = validate_inventory(value)
    assert result == value
    value["resources"].clear()
    assert len(result["resources"]) == 1


def test_private_inventory_schema_accepts_the_validated_contract_and_rejects_extra_claims():
    schema = json.loads((CONTRACTS / "native-carrier-inventory-v1.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    contract = Draft202012Validator(schema)
    value = observation()
    contract.validate(validate_inventory(value))
    value["resources"][0]["authenticated"] = True
    assert not contract.is_valid(value)


@pytest.mark.parametrize("fault", ["version", "epoch", "duplicate", "capacity", "identity", "credential",
                                  "resource", "digest", "state", "pending", "channels", "role",
                                  "same_roles", "missing_digest", "channel_mismatch", "unhashable_state"])
def test_unbounded_or_ambiguous_observations_are_rejected(fault):
    value = observation()
    resource = value["resources"][0]
    if fault == "version": value["v"] = True
    elif fault == "epoch": value["adapter_epoch"] = "caller-selected"
    elif fault == "duplicate": value["resources"].append(deepcopy(resource))
    elif fault == "capacity":
        value["resources"] = [{**resource, "resource": f"native-{index}"} for index in range(17)]
    elif fault == "identity": resource["peer_destination"] = "trusted-peer"
    elif fault == "credential": resource["sdp"] = "a=ice-pwd:secret"
    elif fault == "resource": resource["resource"] = "wrong/resource"
    elif fault == "digest": resource["local_sdp_sha256"] = "invalid"
    elif fault == "state": resource["data_channel_state"] = "authenticated"
    elif fault == "pending": resource["pending"] = 0
    elif fault == "channels": resource["channels"] *= 2
    elif fault == "role": resource["local_type"] = "caller"
    elif fault == "same_roles": resource["remote_type"] = resource["local_type"]
    elif fault == "missing_digest": resource["local_sdp_sha256"] = None
    elif fault == "channel_mismatch": resource["channels"][0]["state"] = "closed"
    elif fault == "unhashable_state": resource["ice_connection_state"] = []
    with pytest.raises(NativeUnavailable):
        validate_inventory(value)

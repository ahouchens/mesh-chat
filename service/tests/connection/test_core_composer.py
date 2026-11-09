"""Composer wire contract vectors execute the production parser."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from mesh_chat.core_api.errors import ApiFailure
from mesh_chat.core_api.requests import COMPONENT_OPERATIONS, parse_request

CONTRACTS = Path(__file__).resolve().parents[3] / "contracts/core-api"
VECTORS = json.loads((CONTRACTS / "composer-vectors-v1.json").read_text())


@pytest.mark.parametrize("vector", VECTORS)
def test_composer_schema_and_production_parser_agree(vector):
    validator = Draft202012Validator(json.loads((CONTRACTS / "request-v1.schema.json").read_text()))
    value = vector["request"]
    assert validator.is_valid(value) is vector["valid"]
    if vector["valid"]:
        assert parse_request(value, COMPONENT_OPERATIONS) == (value["operation"], value["params"])
    else:
        with pytest.raises(ApiFailure):
            parse_request(value, COMPONENT_OPERATIONS)


def test_capabilities_contract_requires_complete_bound_composer_feature():
    from copy import deepcopy
    from mesh_chat.core_api.composer import COMPOSER_LIMITS
    from mesh_chat.core_api.session import CoreSession, Grant, Ports
    from test_core_api import Observations, request

    contract = Draft202012Validator(json.loads((CONTRACTS / "observation-result-v1.schema.json").read_text()))
    session = CoreSession(lambda: Grant("composer-test", frozenset({"observe"}), ("local",)),
        Observations(), handle_key=b"c" * 32, ports=Ports(composer=object()))
    reply = session.request(request("runtime.capabilities"))
    contract.validate(reply)
    assert reply["result"]["api_minor"] == 1
    for field in COMPOSER_LIMITS:
        broken = deepcopy(reply)
        del broken["result"]["limits"][field]
        assert not contract.is_valid(broken)
    broken = deepcopy(reply)
    broken["result"]["api_minor"] = 0
    assert not contract.is_valid(broken)

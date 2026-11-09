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

"""Serialized UI contract vectors must reach production admission and authority.

These tests deliberately stop at a denied caller grant. Domain effects need real
handles, but syntax and mutation identity must be admitted before that denial.
"""

from dataclasses import fields
import json
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest

from mesh_chat.core_api.requests import COMPONENT_OPERATIONS, parse_request
from mesh_chat.core_api.session import CoreSession, Grant, Ports


ROOT = Path(__file__).resolve().parents[3]
VECTORS = json.loads((ROOT / "tests/core-ui-boundary/request-vectors.json").read_text(encoding="utf-8"))
COMPONENT_VECTORS = [value for value in VECTORS if value["operation"] in COMPONENT_OPERATIONS]
CONTRACT = Draft202012Validator(json.loads(
    (ROOT / "contracts/core-api/request-v1.schema.json").read_text(encoding="utf-8")))


def wire_round_trip(value):
    return json.loads(json.dumps(value, ensure_ascii=False).encode("utf-8").decode("utf-8"))


class ForbiddenEffects:
    def __getattr__(self, name):
        raise AssertionError(f"Denied caller reached an effect: {name}")


def test_vectors_cover_every_advertised_component_operation():
    names = [value["operation"] for value in COMPONENT_VECTORS]
    assert len(names) == len(set(names))
    assert set(names) == set(COMPONENT_OPERATIONS)


@pytest.mark.parametrize("vector", COMPONENT_VECTORS, ids=lambda value: value["operation"])
def test_schema_valid_serialized_request_reaches_production_parser(vector):
    value = wire_round_trip(vector)
    CONTRACT.validate(value)
    operation, params = parse_request(value, COMPONENT_OPERATIONS)
    assert (operation, params) == (value["operation"], value["params"])


@pytest.mark.parametrize("vector", COMPONENT_VECTORS, ids=lambda value: value["operation"])
def test_serialized_request_reaches_session_authority_without_effects(vector):
    effects = ForbiddenEffects()
    ports = Ports(**{field.name: effects for field in fields(Ports)})
    session = CoreSession(lambda: Grant("denied-ui", frozenset(), ("local",)),
                          effects, handle_key=b"boundary-handle-key" * 2, ports=ports)
    reply = wire_round_trip(session.request(wire_round_trip(vector)))
    assert reply == {
        "api_version": 1, "request_id": vector["request_id"], "ok": False,
        "error": {"code": "forbidden", "retry_after_ms": None},
    }

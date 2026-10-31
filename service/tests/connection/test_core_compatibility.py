"""Declared compatibility rules and the packaged CLI entry point."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib
import types

import mesh_chat
import pytest

from mesh_chat.core_api import cli
from mesh_chat.core_api.client import CoreClient, CoreClientError
from mesh_chat.core_api.compatibility import check_capabilities
from mesh_chat.core_api.wire_codec import encode_frame
from test_core_client import Scripted, reply


ROOT = Path(__file__).resolve().parents[3]
CAPABILITIES = {"api_major": 1, "api_minor": 0, "stability": "experimental",
                "operations": ["runtime.capabilities"], "profiles": ["p" * 64],
                "limits": {"frame_bytes": 4194304}}


def test_declared_compatibility_matches_the_contract_inventory():
    declaration = json.loads((ROOT / "contracts/core-api/compatibility-v1.json").read_text())
    manifest = json.loads((ROOT / "contracts/core-api/operations-v1.json").read_text())
    assert declaration["public_api"]["major"] == manifest["api_major"]
    assert declaration["public_api"]["minor"] == manifest["api_minor"]
    assert declaration["status"] == "experimental_unfrozen"
    assert declaration["peer_wire"]["changed"] is False
    assert declaration["kotlin_client"]["exists"] is False
    assert declaration["incompatible_combination"] == "reject_before_side_effects"


@pytest.mark.parametrize("major,minor", [(1, 0), (1, 7), (1, 99)])
def test_supported_major_accepts_additive_minors(major, minor):
    assert check_capabilities({"api_major": major, "api_minor": minor}) == (major, minor)


@pytest.mark.parametrize("value", [
    {"api_major": 2, "api_minor": 0}, {"api_major": 0, "api_minor": 0},
    {"api_major": True, "api_minor": 0}, {"api_major": 1, "api_minor": -1},
    {"api_major": 1}, {"api_major": "1", "api_minor": 0}, None, [],
])
def test_incompatible_or_malformed_capabilities_are_rejected(value):
    with pytest.raises(ValueError):
        check_capabilities(value)


def test_client_refuses_an_unsupported_public_api_major_before_any_command():
    transport = Scripted(reply({**CAPABILITIES, "api_major": 2}))
    with pytest.raises(CoreClientError) as raised:
        CoreClient.open(transport.readline, transport.write)
    assert raised.value.code == "incompatible_version"
    assert len(transport.written) == 1


def test_python_module_entry_point_prints_usage_without_opening_a_pipe():
    source = Path(mesh_chat.__file__).resolve().parents[1]
    environment = {**os.environ, "PYTHONPATH": str(source)}
    result = subprocess.run([sys.executable, "-m", "mesh_chat.core_api", "--help"],
                            capture_output=True, text=True, env=environment, timeout=60)
    assert result.returncode == 0
    assert "mesh-chat-core" in result.stdout
    assert "--pipe" in result.stdout


def test_packaging_declares_the_console_entry_point():
    project = tomllib.loads((ROOT / "service/pyproject.toml").read_text())
    assert project["project"]["scripts"]["mesh-chat-core"] == "mesh_chat.core_api.cli:main"


def test_cli_maps_a_platform_or_transport_failure_to_a_typed_exit(monkeypatch, capsys):
    fake = types.ModuleType("mesh_chat.core_api.pipe_client")
    fake.connect = lambda _name: (_ for _ in ()).throw(RuntimeError("unsupported"))
    monkeypatch.setitem(sys.modules, "mesh_chat.core_api.pipe_client", fake)
    assert cli.main(["--pipe", r"\\.\pipe\mesh-chat-test", "capabilities"]) == 2
    assert json.loads(capsys.readouterr().err)["error"] == "unsupported_platform"

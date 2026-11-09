"""Actual pinned artifacts in both client directions and durable vault upgrade.

Network startup alone is suppressed in component hosts. These tests qualify
encrypted storage/parser/SDK behavior, never a retained Windows/Android binary.
"""
import hashlib
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading

import pytest

from mesh_chat.core_api.composition import bind_service_session
from mesh_chat.core_api.session import Grant
from mesh_chat.service import MeshChatService
from mesh_chat.vault import VaultStore
from test_core_messages import host
from test_core_sdk_distribution import (ROOT, NODE, installed_consumer, isolated_project,
                                        run_consumer)

FIXTURES = ROOT / "tests/core-sdk-upgrade"
ARTIFACTS = Path(os.environ.get("MESH_CORE_SDK_UPGRADE_ARTIFACTS", ROOT / "dist/sdk-upgrade"))


@pytest.fixture(scope="module")
def pinned_install():
    metadata = json.loads((ARTIFACTS / "upgrade-artifacts.json").read_text())
    expected = json.loads((FIXTURES / "fixtures.json").read_text())
    assert metadata["baseline_source"] == expected["baseline_source"]
    assert metadata["baseline_tree"] == expected["baseline_tree"]
    assert {kind: item["filename"] for kind, item in metadata["artifacts"].items()} == {
        "python_service_carrier": "mesh_chat_service-0.9.66-py3-none-any.whl",
        "typescript": "mesh-chat-core-client-0.2.0-experimental.tgz"}
    for item in metadata["artifacts"].values():
        assert hashlib.sha256((ARTIFACTS / item["filename"]).read_bytes()).hexdigest() == item["sha256"]
    with isolated_project() as work:
        env = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "NODE_PATH", "NODE_OPTIONS"}}
        env.update(PYTHONDONTWRITEBYTECODE="1", PIP_DISABLE_PIP_VERSION_CHECK="1",
                   PIP_CACHE_DIR=str(work / "pip-cache"), npm_config_cache=str(work / "npm-cache"),
                   npm_config_update_notifier="false")
        site = work / "baseline-site"
        subprocess.run([sys.executable, "-m", "pip", "install", str(ARTIFACTS / metadata["artifacts"]["python_service_carrier"]["filename"]),
            "--target", str(site), "--no-deps", "--no-index", "--no-compile"], cwd=work, env=env,
            check=True, capture_output=True, timeout=60)
        project = work / "typescript"
        project.mkdir()
        (project / "package.json").write_text('{"private":true,"type":"module"}')
        npm = os.environ.get("MESH_NPM_CLI")
        if not npm:
            shim = Path(shutil.which("npm.cmd" if os.name == "nt" else "npm"))
            npm = str(shim.parent / "node_modules/npm/bin/npm-cli.js" if os.name == "nt" else shim.resolve())
        subprocess.run([NODE, npm, "install", str(ARTIFACTS / metadata["artifacts"]["typescript"]["filename"]),
            "--offline", "--ignore-scripts", "--no-audit", "--no-fund", "--package-lock=false"],
            cwd=project, env=env, check=True, capture_output=True, timeout=60)
        shutil.copyfile(FIXTURES / "legacy_consumer.py", work / "legacy_consumer.py")
        shutil.copyfile(FIXTURES / "legacy_consumer.mjs", project / "legacy_consumer.mjs")
        shutil.copyfile(FIXTURES / "host_worker.py", work / "host_worker.py")
        yield work, site, project, env, metadata


def old_consumer(pinned, language):
    work, site, project, env, metadata = pinned
    if language == "python":
        script = "import runpy,sys;sys.path.insert(0,sys.argv.pop(1));runpy.run_path('legacy_consumer.py',run_name='__main__')"
        return language, work, [sys.executable, "-I", "-S", "-B", "-c", script, str(site)], env, metadata["artifacts"]["python_service_carrier"]["sha256"]
    return language, project, [NODE, "legacy_consumer.mjs"], env, metadata["artifacts"]["typescript"]["sha256"]


class PinnedHost:
    def __init__(self, pinned, directory, key_file, *, refusal_only=False):
        work, site, _, env, _ = pinned
        self.process = subprocess.Popen([sys.executable, "-I", "-B", "host_worker.py", str(site)],
            cwd=work, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.responses = queue.Queue()
        self.operations = []
        self.closed = False
        def read():
            while frame := self.process.stdout.readline(4194305):
                self.responses.put(frame)
            self.responses.put(b"")
        self.reader = threading.Thread(target=read, daemon=True)
        self.reader.start()
        config = {"profile_dir": str(directory), "key_file": str(key_file), "refusal_only": refusal_only}
        self.process.stdin.write(json.dumps(config).encode() + b"\n")
        self.process.stdin.flush()
        self.admission = json.loads(self._read())
        assert self.admission.get("ready") or "refused_before_service_construction" in self.admission

    def _read(self):
        try:
            frame = self.responses.get(timeout=20)
        except queue.Empty:
            self.process.kill()
            raise AssertionError("Pinned host exceeded bounded response deadline")
        if not frame:
            raise AssertionError("Pinned host closed before response: " + self.process.stderr.read().decode("utf-8", "replace")[-2000:])
        return frame

    def exchange(self, frame):
        self.operations.append(json.loads(frame)["operation"])
        self.process.stdin.write(frame)
        self.process.stdin.flush()
        return self._read()

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.process.stdin.close()
        try:
            self.process.wait(timeout=10)
        finally:
            if self.process.poll() is None:
                self.process.kill()
                self.process.wait(timeout=5)
        self.reader.join(5)
        diagnostics = self.process.stderr.read().decode("utf-8", "replace")
        self.process.stdout.close()
        self.process.stderr.close()
        assert self.process.returncode == 0, diagnostics[-2000:]


@pytest.mark.parametrize("language", ["python", "typescript"])
def test_actual_old_sdk_to_candidate_core(pinned_install, host, language):
    service = host()
    report = run_consumer(old_consumer(pinned_install, language), service, "--old")
    assert report["accepted"] and report["api_minor"] == 1
    if language == "python":
        assert report["sdk_version"] == "0.2.0-experimental"
    else:
        assert report["installed_package"] is True
    assert len(service.store.list("message")) == 1
    assert not service._store_closed


def test_actual_candidate_sdk_to_pinned_old_host_with_local_composer_refusal(installed_consumer, pinned_install, tmp_path):
    language, work, command, env, digest = installed_consumer
    key_file = tmp_path / "synthetic-key"
    key_file.write_bytes(os.urandom(32))
    remote = PinnedHost(pinned_install, tmp_path / "old-vault", key_file)
    if language == "python":
        shutil.copyfile(FIXTURES / "legacy_consumer.py", work / "upgrade_consumer.py")
        command = [part.replace("consumer.py", "upgrade_consumer.py") for part in command]
    else:
        shutil.copyfile(FIXTURES / "legacy_consumer.mjs", work / "upgrade_consumer.mjs")
        command = [NODE, "upgrade_consumer.mjs"]
    try:
        report = run_consumer((language, work, command, env, digest), None, "--expect-no-composer", session=remote)
        assert report["accepted"] and report["api_minor"] == 0 and report["composer_locally_refused"]
        assert not any("composer" in operation or operation == "message.enqueue_draft" for operation in remote.operations)
    finally:
        remote.close()


def test_pinned_v1_vault_forward_migration_and_old_installed_component_format_refusal(pinned_install, tmp_path, monkeypatch):
    key = os.urandom(32)
    key_file = tmp_path / "synthetic-key"
    key_file.write_bytes(key)
    old_root = tmp_path / "baseline-vault"
    remote = PinnedHost(pinned_install, old_root, key_file)
    try:
        assert run_consumer(old_consumer(pinned_install, "python"), None, "--old", session=remote)["accepted"]
    finally:
        remote.close()
    upgraded_root = tmp_path / "upgraded-copy"
    shutil.copytree(old_root, upgraded_root)
    monkeypatch.setattr(MeshChatService, "_start_network", lambda *_: None)
    monkeypatch.setattr(MeshChatService, "_prepare_lan_fallback", lambda *_: None)

    def open_candidate():
        store = VaultStore(upgraded_root, key, allow_unprotected_for_tests=True)
        return MeshChatService(store, upgraded_root, lambda _: None)

    def open_session(service):
        session = bind_service_session(service, lambda: Grant("sdk-distribution-qualification",
            frozenset({"observe", "read", "send"}), ("local",)), private_composer_legacy=True)
        def invoke(operation, params=None, key=None):
            value = {"api_version": 1, "request_id": "upgrade:1", "operation": operation, "params": params or {}}
            if key is not None:
                value["idempotency_key"] = key
            return session.request(value)
        profile = invoke("runtime.capabilities")["result"]["profiles"][0]
        peer = invoke("profile.query", {"profile": profile})["result"]["peers"][0]
        return invoke, {"profile": profile, "peer": peer}

    service = open_candidate()
    try:
        invoke, scope = open_session(service)
        before = service.store.list("message")[0]["id"]
        current = invoke("peer.composer_query", scope)["result"]
        assert current["text"] == "Upgrade legacy draft"
        original = service.store._write_records_locked
        def fail(*args):
            original(*args)
            raise OSError("injected migration commit failure")
        service.store._write_records_locked = fail
        response = invoke("peer.composer_update", {**scope, "expected_revision": current["revision"], "text": current["text"]}, current["update_key"])
        assert response["error"]["code"] == "unavailable"
        service.store._write_records_locked = original
        assert service.store.get("draft", "internal-peer")["text"] == "Upgrade legacy draft"
        assert service.store._db.execute("SELECT value FROM meta WHERE name='schema_version'").fetchone()[0] == "1"
    finally:
        service.close()

    old_reader = PinnedHost(pinned_install, upgraded_root, key_file, refusal_only=True)
    assert old_reader.admission == {"refused_before_service_construction": False}
    old_reader.close()
    service = open_candidate()
    try:
        invoke, scope = open_session(service)
        current = invoke("peer.composer_query", scope)["result"]
        saved = invoke("peer.composer_update", {**scope, "expected_revision": current["revision"], "text": current["text"]}, current["update_key"])
        assert saved["ok"], saved
        revision = saved["result"]["applied_revision"]
        accepted = invoke("message.enqueue_draft", {"profile": scope["profile"], "recipient": scope["peer"], "draft_revision": revision}, revision)
        assert accepted["ok"] and accepted["result"]["composer"]["text"] == ""
        replay = invoke("message.enqueue", {"profile": scope["profile"], "recipient": scope["peer"], "kind": "text", "text": "Upgrade legacy enqueue"}, "upgrade-legacy-message-key-0001")
        assert replay["ok"] and len(service.store.list("message")) == 2
        assert any(item["id"] == before for item in service.store.list("message"))
        assert service.store._db.execute("SELECT value FROM meta WHERE name='schema_version'").fetchone()[0] == "2"
    finally:
        service.close()
    old_reader = PinnedHost(pinned_install, upgraded_root, key_file, refusal_only=True)
    assert old_reader.admission == {"refused_before_service_construction": True}
    old_reader.close()
    service = open_candidate()
    try:
        invoke, scope = open_session(service)
        assert invoke("peer.composer_query", scope)["result"]["text"] == ""
        replay = invoke("message.enqueue_draft", {"profile": scope["profile"], "recipient": scope["peer"], "draft_revision": revision}, revision)
        assert replay["ok"] and replay["result"]["message"] == accepted["result"]["message"]
        assert len(service.store.list("message")) == 2
    finally:
        service.close()


@pytest.mark.parametrize("failure", ["wrong_key", "corrupt_database", "corrupt_record"])
def test_other_pinned_storage_failures_cannot_qualify_as_schema_refusal(pinned_install, tmp_path, failure):
    work, site, _, env, _ = pinned_install
    key = os.urandom(32)
    root = tmp_path / "invalid-baseline-vault"
    with VaultStore(root, key, allow_unprotected_for_tests=True) as store:
        store.put("profile", "local", {"display_name": "Synthetic negative control"})
        if failure == "corrupt_record":
            store._db.execute("UPDATE records SET sealed=? WHERE kind='profile'", (b"invalid",))
    if failure == "corrupt_database":
        (root / "mesh-chat.vault").write_bytes(b"not sqlite")
    key_file = tmp_path / "synthetic-negative-key"
    key_file.write_bytes(os.urandom(32) if failure == "wrong_key" else key)
    config = {"profile_dir": str(root), "key_file": str(key_file), "refusal_only": True}
    result = subprocess.run([sys.executable, "-I", "-B", "host_worker.py", str(site)], cwd=work, env=env,
        input=json.dumps(config).encode() + b"\n", capture_output=True, timeout=30)
    assert result.returncode != 0
    assert b'"refused_before_service_construction": true' not in result.stdout.lower()


"""Installed public artifacts against real Core/vault over inherited OS pipes.

Only the parent imports host implementation. Child programs are copied outside
the checkout and resolve an installed wheel/tarball, with source search paths
removed. These component tests do not substitute for packaged platform hosts.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager

import pytest

from mesh_chat.core_api.composition import bind_service_stream
from mesh_chat.core_api.session import Grant
from test_core_messages import host
from test_core_profile_bootstrap import empty_host
from test_core_workspace import workspaces

ROOT = Path(__file__).resolve().parents[3]
NODE = os.environ.get("MESH_NODE") or shutil.which("node")
ARTIFACTS = Path(os.environ.get("MESH_CORE_SDK_ARTIFACTS", ROOT / "dist/sdk"))


@contextmanager
def isolated_project():
    parent = Path(os.environ.get("MESH_CORE_CONSUMER_TMP") or tempfile.gettempdir()).resolve()
    work = Path(tempfile.mkdtemp(prefix="mesh-core-installed-consumer-", dir=parent)).resolve()
    assert work.parent == parent and work.name.startswith("mesh-core-installed-consumer-")
    assert not work.is_relative_to(ROOT)
    try:
        yield work
    finally:
        # npm's content hashes exceed MAX_PATH under long workspace temp roots.
        # Use the Windows extended absolute form only after containment checks.
        target = str(work)
        if os.name == "nt":
            target = "\\\\?\\UNC\\" + target[2:] if target.startswith("\\\\") else "\\\\?\\" + target
        # Retry only our exact created root; persistent cleanup failure fails.
        for attempt in range(5):
            try:
                shutil.rmtree(target)
                break
            except OSError:
                if attempt == 4:
                    raise
                time.sleep(0.1 * (attempt + 1))


@pytest.fixture(scope="module", params=["python", "typescript"])
def installed_consumer(request):
    language = request.param
    with isolated_project() as work:
        assert not work.resolve().is_relative_to(ROOT)
        env = {key: value for key, value in os.environ.items()
               if key not in {"PYTHONPATH", "NODE_PATH", "NODE_OPTIONS"}}
        env.update(PYTHONDONTWRITEBYTECODE="1", PIP_CACHE_DIR=str(work / "cache"),
                   npm_config_cache=str(work / "npm-cache"), npm_config_update_notifier="false")
        if language == "python":
            artifact = ARTIFACTS / "python/mesh_chat_core_client-0.3.0.dev0-py3-none-any.whl"
            site = work / "site"
            subprocess.run([sys.executable, "-m", "pip", "install", str(artifact), "--target", str(site),
                            "--no-deps", "--no-index", "--no-compile"], env=env, cwd=work,
                           check=True, capture_output=True, timeout=60)
            shutil.copyfile(ROOT / "examples/python-core-consumer/consumer.py", work / "consumer.py")
            bootstrap = "import runpy,sys;sys.path.insert(0,sys.argv.pop(1));runpy.run_path('consumer.py',run_name='__main__')"
            command = [sys.executable, "-I", "-S", "-B", "-c", bootstrap, str(site)]
        else:
            assert int(subprocess.check_output([NODE, "--version"], text=True).strip()[1:].split(".")[0]) >= 22
            artifact = ARTIFACTS / "typescript/mesh-chat-core-client-0.3.0-experimental.tgz"
            npm = os.environ.get("MESH_NPM_CLI")
            if not npm:
                shim = Path(shutil.which("npm.cmd" if os.name == "nt" else "npm"))
                npm = str(shim.parent / "node_modules/npm/bin/npm-cli.js" if os.name == "nt" else shim.resolve())
            (work / "package.json").write_text('{"private":true,"type":"module"}')
            subprocess.run([NODE, npm, "install", str(artifact), "--offline", "--ignore-scripts",
                            "--no-audit", "--no-fund", "--package-lock=false"], env=env, cwd=work,
                           check=True, capture_output=True, timeout=60)
            shutil.copyfile(ROOT / "examples/typescript-core-consumer/index.mjs", work / "consumer.mjs")
            command = [NODE, "consumer.mjs"]
        yield language, work, command, env, hashlib.sha256(artifact.read_bytes()).hexdigest()


def run_consumer(installed, service, mode, *, drop_commit_reply=False, drop_operation="message.enqueue_draft", extra_args=(), bootstrap=False, session=None):
    _, work, command, env, _ = installed
    if session is None:
        session = bind_service_stream(service, lambda: Grant("sdk-distribution-qualification",
            frozenset({"observe", "read", "send", "pair", "approve", "profile_owner"}), ("local",)),
            private_profile_bootstrap=bootstrap)
    child = subprocess.Popen([*command, mode, *extra_args], cwd=work, env=env,
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    failures, dropped = [], []

    def serve():
        try:
            while frame := child.stdout.readline(4194305):
                response = session.exchange(frame)
                if drop_commit_reply and json.loads(frame)["operation"] == drop_operation:
                    assert json.loads(response)["ok"] is True
                    dropped.append(True)
                    return  # Commit happened. No response byte reaches the client.
                child.stdin.write(response)
                child.stdin.flush()
        except BaseException as error:
            failures.append(error)
        finally:
            child.stdin.close()
            session.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        code = child.wait(timeout=45)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
    thread.join(5)
    diagnostics = child.stderr.read().decode("utf-8", "replace")
    child.stdout.close()
    child.stderr.close()
    assert not thread.is_alive()
    assert not failures, failures
    assert bool(dropped) == drop_commit_reply
    assert code == (2 if drop_commit_reply else 0), diagnostics[-2000:]
    return json.loads(diagnostics.splitlines()[-1])


@pytest.mark.parametrize("mode", ["--legacy", "--exercise-composer"])
def test_installed_sdk_uses_real_core_without_owning_runtime(installed_consumer, host, mode, record_property):
    record_property("sdk_sha256", installed_consumer[-1])
    service = host()
    report = run_consumer(installed_consumer, service, mode)
    assert report["sdk_only"] and report["accepted"]
    if mode == "--exercise-composer":
        assert report["draft_empty"] and report["replay_same_message"]
    messages = service.store.list("message")
    assert len(messages) == 1
    assert messages[0]["text"] == "SDK qualification " + ("legacy" if mode == "--legacy" else "composer")
    assert not service._store_closed  # Client detach is not runtime.stop.


def test_installed_sdk_recovers_lost_committed_reply_after_vault_reopen(installed_consumer, host, record_property):
    record_property("sdk_sha256", installed_consumer[-1])
    service = host()
    lost = run_consumer(installed_consumer, service, "--exercise-composer", drop_commit_reply=True)
    assert lost["uncertain"] is True
    original = service.store.list("message")
    assert len(original) == 1
    service.close()
    reopened = host()
    report = run_consumer(installed_consumer, reopened, "--recover-composer")
    assert report["sdk_only"] and report["recovered_acceptance"] and report["draft_empty"]
    assert [item["id"] for item in reopened.store.list("message")] == [original[0]["id"]]
    assert not reopened._store_closed


def test_installed_sdk_profile_helper_supplies_real_required_key(installed_consumer, empty_host):
    service = empty_host()
    report = run_consumer(installed_consumer, service, "--create-profile", bootstrap=True)
    assert report["sdk_only"] and report["created"]
    assert len(service.store.list("identity")) == 1
    assert len(service.store.list("workspace_operation")) == 1


def test_installed_sdk_admission_list_helper_supplies_real_required_key(installed_consumer, host):
    service = host()
    report = run_consumer(installed_consumer, service, "--keyed-owner")
    assert report["sdk_only"] and report["listed"]
    assert len(service.store.list("workspace")) == 1


def test_installed_sdk_join_helper_supplies_real_required_key(installed_consumer, workspaces):
    _, joiner, _, document = workspaces
    path = installed_consumer[1] / "synthetic-invitation.txt"
    path.write_text(document)
    try:
        report = run_consumer(installed_consumer, joiner, "--keyed-join", extra_args=("--document-file", str(path)))
        assert report["sdk_only"] and report["joined"]
        assert len(joiner.store.list("workspace")) == 1
    finally:
        path.unlink()

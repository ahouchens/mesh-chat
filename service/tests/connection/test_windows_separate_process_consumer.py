"""Focused fresh-profile process fixture checks; no packaged host claim."""

import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "examples/typescript-independent-consumer/separate-process-check.mjs"

PRELOADER = r'''
import { registerHooks } from "node:module";
import { existsSync, writeFileSync } from "node:fs";

// Only synthetic execution gets Windows admission; production script stays Windows-only.
if (process.env.FIXTURE_MOCK_WINDOWS === "1") {
  Object.defineProperty(process, "platform", {value: "win32"});
}

let created = false;
const profile = "PRIVATE_PROFILE";
const destination = "PRIVATE_DESTINATION";
const snapshot = () => ({profile: created ? {destination_hash: destination,
  display_name: "Separate process"} : null, contacts: [], messages: []});
globalThis.__separate = {
  launchRuntime: async (_executable, _directory, options) => {
    if (process.env.FIXTURE_MODE === "wall_clock_jump") {
      Date.now = () => 8_000_000_000_000_000;
    }
    const runtime = {pipe: "PRIVATE_PIPE", async stop() {
      writeFileSync(process.env.FIXTURE_MARKER, "stopped");
      if (process.env.FIXTURE_MODE === "early_exit") {
        await new Promise(resolve => setTimeout(resolve, 150));
      }
      return process.env.FIXTURE_MODE === "stop_fail"
        ? {stopped: false, exit_code: 1} : {stopped: true, exit_code: 0};
    }};
    options.onOwned(runtime);
    return runtime;
  },
  connectNamedPipe: async () => ({}),
  CoreClient: {open: async () => ({
    capabilities: {profiles: [profile], operations: ["profile.create", "profile.query", "application.snapshot"]},
    close() {},
    async request(operation, params, options) {
      if (operation === "application.snapshot") return snapshot();
      if (operation === "runtime.capabilities") return {profiles: [profile],
        operations: ["profile.create", "profile.query", "application.snapshot"]};
      if (operation === "profile.create") {
        if (!options?.idempotencyKey || params.display_name !== "Separate process") throw new Error();
        created = true;
        return {profile};
      }
      if (operation === "profile.query") return {destination};
      throw new Error("PRIVATE_UNEXPECTED_OPERATION");
    },
  })},
};
const sources = {
  "@mesh-chat/core-client": "export const {CoreClient}=globalThis.__separate;",
  "@mesh-chat/core-client/node": "export const {connectNamedPipe}=globalThis.__separate;",
  "./runtime.mjs": "export const {launchRuntime}=globalThis.__separate;",
};
registerHooks({resolve(specifier, context, nextResolve) {
  if (Object.hasOwn(sources, specifier)) return {
    url: "data:text/javascript," + encodeURIComponent(sources[specifier]), shortCircuit: true,
  };
  return nextResolve(specifier, context);
}});
'''

CHILD = r'''
import { appendFileSync, existsSync } from "node:fs";
import { createInterface } from "node:readline";
const log = value => appendFileSync(process.env.FIXTURE_LOG, JSON.stringify(value) + "\n");
log({event: "start", pid: process.pid, parent: process.ppid});
process.on("exit", code => log({event: "exit", pid: process.pid, code}));
if (process.env.FIXTURE_MODE === "early_exit") {
  const watcher = setInterval(() => {
    if (existsSync(process.env.FIXTURE_MARKER)) process.exit(1);
  }, 5);
  watcher.unref();
}
for await (const line of createInterface({input: process.stdin})) {
  if (existsSync(process.env.FIXTURE_MARKER)) {
    process.stderr.write("Independent public consumer failed.\n");
    process.exit(1);
  }
  const request = JSON.parse(line);
  if (process.env.FIXTURE_MODE === "bad_reply") {
    process.stdout.write("PRIVATE_UNFRAMED_OUTPUT\n");
    process.exit(0);
  }
  let result;
  if (request.operation === "runtime.capabilities") result = {profiles: ["PRIVATE_PROFILE"], operations: []};
  else if (request.operation === "application.snapshot") result = {
    profile: {destination_hash: "PRIVATE_DESTINATION", display_name: "Separate process"},
    contacts: [], messages: []};
  else if (request.operation === "profile.query") result = {destination: "PRIVATE_DESTINATION"};
  else process.exit(2);
  process.stdout.write(JSON.stringify({id: request.id, ok: true, result}) + "\n");
}
'''

REAL_CONSUMER_PRELOADER = r'''
import { registerHooks } from "node:module";
import { sep, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const source = pathToFileURL(resolve(process.env.FIXTURE_SDK_SOURCE) + sep).href;
const nodeModule = `
  import {NodeStreamTransport} from "${new URL("node.ts", source).href}";
  import {Duplex} from "node:stream";
  import {existsSync} from "node:fs";
  const capabilities = {api_major:1,api_minor:0,stability:"experimental",
    operations:["runtime.capabilities"],profiles:["PRIVATE_PROFILE"],limits:{frame_bytes:262144}};
  export async function connectNamedPipe() {
    const socket = new Duplex({
      read() {},
      write(chunk, _encoding, done) {
        if (existsSync(process.env.FIXTURE_MARKER)) { this.destroy(); done(); return; }
        const request = JSON.parse(chunk.toString("utf8"));
        this.push(JSON.stringify({api_version:1,request_id:request.request_id,ok:true,
          result:capabilities}) + "\\n");
        done();
      },
    });
    return new NodeStreamTransport(socket);
  }
`;
registerHooks({resolve(specifier, context, nextResolve) {
  if (specifier === "@mesh-chat/core-client") return {
    url: new URL("index.ts", source).href, shortCircuit: true,
  };
  if (specifier === "@mesh-chat/core-client/node") return {
    url: "data:text/javascript," + encodeURIComponent(nodeModule), shortCircuit: true,
  };
  if (specifier === "./runtime.mjs" && context.parentURL?.endsWith("consumer.mjs")) return {
    url: "data:text/javascript,export async function launchRuntime(){throw new Error()}", shortCircuit: true,
  };
  if (context.parentURL?.startsWith(source) && specifier.startsWith("./") && specifier.endsWith(".js")) {
    return {url: new URL(specifier.slice(0, -3) + ".ts", context.parentURL).href, shortCircuit: true};
  }
  return nextResolve(specifier, context);
}});
'''


def node():
    selected = os.environ.get("MESH_CHAT_TEST_NODE") or shutil.which("node")
    if not selected:
        pytest.skip("Node >=22 unavailable")
    version = subprocess.run([selected, "--version"], capture_output=True, text=True, timeout=5)
    if version.returncode != 0 or int(version.stdout.strip().lstrip("v").split(".")[0]) < 22:
        pytest.skip("Node >=22 unavailable")
    return selected


def execute(tmp_path, mode="normal", *, mock_windows=True, relative_paths=False):
    shutil.copyfile(SCRIPT, tmp_path / SCRIPT.name)
    shutil.copyfile(SCRIPT.with_name("public-process-helper.mjs"), tmp_path / "public-process-helper.mjs")
    (tmp_path / "preloader.mjs").write_text(PRELOADER, encoding="utf-8")
    (tmp_path / "consumer.mjs").write_text(CHILD, encoding="utf-8")
    marker = tmp_path / "stopped"
    log = tmp_path / "children.jsonl"
    env = {**os.environ, "FIXTURE_MARKER": str(marker), "FIXTURE_LOG": str(log),
           "FIXTURE_MODE": mode, "FIXTURE_MOCK_WINDOWS": "1" if mock_windows else "0"}
    completed = subprocess.run([node(), "--import", (tmp_path / "preloader.mjs").as_uri(),
        str(tmp_path / SCRIPT.name), "--runtime", "host.exe" if relative_paths else str(tmp_path / "host.exe"),
        "--data-directory", "data" if relative_paths else str(tmp_path / "data")], cwd=tmp_path,
        env=env, capture_output=True, text=True, timeout=25)
    return completed, [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def test_fresh_profile_helpers_detach_reattach_and_owner_stop(tmp_path):
    completed, events = execute(tmp_path)
    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    result = json.loads(completed.stdout)
    assert result["passed"] is True
    assert result["checks"] == {
        "normal_owners": 1, "distinct_helper_processes": 2, "clean_helper_detaches": 1,
        "owner_survived_detach": True, "replacement_shared_fresh_state": True,
        "positive_owner_stop": True, "post_stop_helper_request_rejected": True,
        "bounded_helper_exit": True,
    }
    starts = [item for item in events if item["event"] == "start"]
    exits = [item for item in events if item["event"] == "exit"]
    assert len(starts) == len(exits) == 2
    assert len({item["pid"] for item in starts}) == 2
    assert all(item["pid"] != item["parent"] for item in starts)
    assert [item["code"] for item in exits] == [0, 1]
    assert (tmp_path / "stopped").is_file()
    assert "PRIVATE_" not in completed.stdout
    assert set(result) == {"v", "passed", "scope", "checks", "duration_ms"}


def test_failed_owner_retirement_never_becomes_fixture_success(tmp_path):
    completed, events = execute(tmp_path, "stop_fail")
    assert completed.returncode == 1
    assert completed.stderr == ""
    result = json.loads(completed.stdout)
    assert result["passed"] is False and result["phase"] == "owner_stop"
    assert set(result) == {"v", "passed", "scope", "phase", "duration_ms"}
    assert "PRIVATE_" not in completed.stdout
    assert [item["code"] for item in events if item["event"] == "exit"] == [0, 0]


def test_malformed_helper_output_fails_closed_without_retaining_payload(tmp_path):
    completed, events = execute(tmp_path, "bad_reply")
    assert completed.returncode == 1
    result = json.loads(completed.stdout)
    assert result["passed"] is False and result["phase"] == "first_helper_attach"
    assert "PRIVATE_" not in completed.stdout + completed.stderr
    assert (tmp_path / "stopped").is_file()
    assert [item["code"] for item in events if item["event"] == "exit"] == [0]


def test_early_helper_exit_cannot_count_as_post_stop_request_rejection(tmp_path):
    completed, events = execute(tmp_path, "early_exit")
    assert completed.returncode == 1
    result = json.loads(completed.stdout)
    assert result["passed"] is False and result["phase"] == "helper_after_stop"
    assert [item["code"] for item in events if item["event"] == "exit"] == [0, 1]


def test_wall_clock_jump_does_not_consume_monotonic_fixture_budget(tmp_path):
    completed, _ = execute(tmp_path, "wall_clock_jump")
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["passed"] is True and 0 <= result["duration_ms"] < 10000


def test_fixture_rejects_relative_host_and_data_before_launch(tmp_path):
    completed, events = execute(tmp_path, relative_paths=True)
    assert completed.returncode == 1
    assert json.loads(completed.stdout)["phase"] == "arguments"
    assert events == [] and not (tmp_path / "stopped").exists()


@pytest.mark.skipif(os.name == "nt", reason="native platform refusal is specific to non-Windows")
def test_unmodified_platform_guard_refuses_linux_before_launch(tmp_path):
    completed, events = execute(tmp_path, mock_windows=False)
    assert completed.returncode == 1
    assert json.loads(completed.stdout)["phase"] == "arguments"
    assert events == [] and not (tmp_path / "stopped").exists()


def test_unchanged_consumer_and_sdk_exit_after_post_stop_transport_close(tmp_path):
    """Exercise real consumer.mjs and TypeScript SDK source over a synthetic Duplex."""
    selected = node()
    version = subprocess.run([selected, "--version"], capture_output=True, text=True, timeout=5)
    if int(version.stdout.strip().lstrip("v").split(".")[0]) < 24:
        pytest.skip("Node TypeScript transform unavailable")
    preloader = tmp_path / "sdk-preloader.mjs"
    preloader.write_text(REAL_CONSUMER_PRELOADER, encoding="utf-8")
    marker = tmp_path / "host-stopped"
    env = {**os.environ, "FIXTURE_MARKER": str(marker),
           "FIXTURE_SDK_SOURCE": str(ROOT / "sdk/typescript/src"), "NODE_NO_WARNINGS": "1"}
    child = subprocess.Popen([selected, "--experimental-transform-types", "--import", preloader.as_uri(),
        str(SCRIPT.parent / "consumer.mjs"), "--pipe", "PRIVATE_PIPE"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", env=env)
    try:
        first = {"id": "one", "operation": "runtime.capabilities", "params": {}}
        child.stdin.write(json.dumps(first) + "\n")
        child.stdin.flush()
        replies = queue.Queue(maxsize=1)
        threading.Thread(target=lambda: replies.put(child.stdout.readline()), daemon=True).start()
        line = replies.get(timeout=10)
        assert json.loads(line)["id"] == "one"
        marker.write_text("stopped", encoding="utf-8")
        second = {"id": "two", "operation": "runtime.capabilities", "params": {}}
        child.stdin.write(json.dumps(second) + "\n")
        child.stdin.flush()
        assert child.wait(timeout=10) == 1
        assert child.stdout.read() == ""
        assert child.stderr.read() == "Independent public consumer failed.\n"
    finally:
        if child.poll() is None:
            child.kill()
        child.wait(timeout=5)


def test_fixture_uses_only_attach_only_public_helper_and_fixed_report():
    source = SCRIPT.read_text(encoding="utf-8")
    helper = SCRIPT.with_name("public-process-helper.mjs").read_text(encoding="utf-8")
    consumer = (SCRIPT.parent / "consumer.mjs").read_text(encoding="utf-8")
    assert '["consumer.mjs", "--pipe", pipe]' in helper
    assert 'spawn(process.execPath' in helper
    assert 'args.length === 2 && args[0] === "--pipe"' in consumer
    assert 'if (runtime) await runtime.stop()' in consumer
    assert 'const completion = await runtime.stop' in source
    assert 'completion?.stopped !== true || completion.exit_code !== 0' in source
    assert 'native.command' in source
    checked = subprocess.run([node(), "--check", str(SCRIPT)], capture_output=True, text=True, timeout=10)
    assert checked.returncode == 0, checked.stderr

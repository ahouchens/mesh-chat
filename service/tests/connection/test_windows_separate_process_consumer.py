"""Focused fresh-profile process fixture checks; no packaged host claim."""

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "examples/typescript-independent-consumer/separate-process-check.mjs"

PRELOADER = r'''
import { registerHooks } from "node:module";
import { existsSync, writeFileSync } from "node:fs";

let created = false;
const profile = "PRIVATE_PROFILE";
const destination = "PRIVATE_DESTINATION";
const snapshot = () => ({profile: created ? {destination_hash: destination,
  display_name: "Separate process"} : null, contacts: [], messages: []});
globalThis.__separate = {
  launchRuntime: async (_executable, _directory, options) => {
    const runtime = {pipe: "PRIVATE_PIPE", async stop() {
      writeFileSync(process.env.FIXTURE_MARKER, "stopped");
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
for await (const line of createInterface({input: process.stdin})) {
  if (existsSync(process.env.FIXTURE_MARKER)) {
    process.stderr.write("PRIVATE_HOST_CLOSED\n");
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


def node():
    selected = os.environ.get("MESH_CHAT_TEST_NODE") or shutil.which("node")
    if not selected:
        pytest.skip("Node >=22 unavailable")
    version = subprocess.run([selected, "--version"], capture_output=True, text=True, timeout=5)
    if version.returncode != 0 or int(version.stdout.strip().lstrip("v").split(".")[0]) < 22:
        pytest.skip("Node >=22 unavailable")
    return selected


def execute(tmp_path, mode="normal"):
    shutil.copyfile(SCRIPT, tmp_path / SCRIPT.name)
    (tmp_path / "preloader.mjs").write_text(PRELOADER, encoding="utf-8")
    (tmp_path / "consumer.mjs").write_text(CHILD, encoding="utf-8")
    marker = tmp_path / "stopped"
    log = tmp_path / "children.jsonl"
    env = {**os.environ, "FIXTURE_MARKER": str(marker), "FIXTURE_LOG": str(log), "FIXTURE_MODE": mode}
    completed = subprocess.run([node(), "--import", (tmp_path / "preloader.mjs").as_uri(),
        str(tmp_path / SCRIPT.name), "--runtime", str(tmp_path / "host.exe"),
        "--data-directory", str(tmp_path / "data")], cwd=tmp_path,
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


def test_fixture_uses_only_attach_only_public_helper_and_fixed_report():
    source = SCRIPT.read_text(encoding="utf-8")
    consumer = (SCRIPT.parent / "consumer.mjs").read_text(encoding="utf-8")
    assert '["consumer.mjs", "--pipe", pipe]' in source
    assert 'spawn(process.execPath' in source
    assert 'args.length === 2 && args[0] === "--pipe"' in consumer
    assert 'if (runtime) await runtime.stop()' in consumer
    assert 'const completion = await runtime.stop' in source
    assert 'completion?.stopped !== true || completion.exit_code !== 0' in source
    assert 'native.command' in source
    checked = subprocess.run([node(), "--check", str(SCRIPT)], capture_output=True, text=True, timeout=10)
    assert checked.returncode == 0, checked.stderr

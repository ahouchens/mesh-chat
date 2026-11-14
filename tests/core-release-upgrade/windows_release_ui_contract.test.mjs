import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { runInNewContext } from "node:vm";
import { checkedConfig, checkedReadback, compareReports, EVIDENCE_LEVEL, projectReadback, RELEASE_SOURCE, sameReadback } from "../../scripts/windows_release_ui_contract.mjs";
import { readInstalledUi, settledUiReadback } from "../../scripts/windows_release_ui_readback.mjs";

const markers = {
  phase: "seed", expected_source: "7c40f7b23eab3e9d83ff7ca1075c90c4d84ce516",
  expected_version: "0.9.66", workspace_name: "R8 CI space 001",
  message_text: "R8 CI message 001", draft_text: "R8 CI draft 001",
};
const hash = (value) => createHash("sha256").update(value).digest("hex");

function sample() {
  return {
    snapshot: {
      profile: { destination_hash: "a".repeat(32) },
      workspaces: [{ id: "workspace-1", name: markers.workspace_name, state: "active" }],
      workspace_channels: [{ id: "channel-1", workspace_id: "workspace-1", name: "general" }],
      workspace_drafts: [{ workspace_id: "workspace-1", conversation_id: "channel-1",
        text: markers.draft_text }],
    },
    page: { messages: [{ id: "message-1", text: markers.message_text }] },
  };
}

function readbackHost(candidate, overrides = {}) {
  const value = sample();
  value.snapshot.workspaces[0].core_handle = "b".repeat(64);
  value.snapshot.workspace_channels[0].core_handle = "c".repeat(64);
  const profile = { profile: "d".repeat(64), destination: "a".repeat(32) };
  const calls = [];
  const invoke = async (command, payload) => {
    calls.push({ command, payload });
    if (command in overrides) return overrides[command](payload, calls);
    if (candidate) {
      assert.notEqual(command, "service_command");
      if (command === "core_api_profile") return profile;
      assert.equal(command, "core_api_request");
      assert.equal(payload.idempotencyKey, null);
      if (payload.operation === "application.snapshot") {
        assert.deepEqual(JSON.parse(JSON.stringify(payload.params)), {});
        return value.snapshot;
      }
      assert.deepEqual(JSON.parse(JSON.stringify(payload)), { operation: "workspace.timeline_query",
        params: { profile: profile.profile, workspace: "b".repeat(64), view: "channel_messages",
          channel: "channel-1", cursor: null, limit: 50 }, idempotencyKey: null });
      return { profile: profile.profile, workspace: "b".repeat(64), result: value.page };
    }
    assert.equal(command, "service_command");
    if (payload.command === "snapshot") return value.snapshot;
    assert.deepEqual(JSON.parse(JSON.stringify(payload)), { command: "list_workspace_messages",
      payload: { workspace_id: "workspace-1", channel_id: "channel-1", cursor: null, limit: 50 } });
    return value.page;
  };
  return { ...value, profile, calls, invoke };
}

test("released and candidate readback use their supported read-only APIs and preserve IDs", async () => {
  const hashes = [];
  for (const candidate of [false, true]) {
    const host = readbackHost(candidate);
    const isolated = runInNewContext(`(${readInstalledUi.toString()})`);
    const result = await isolated(host.invoke, { ...markers, phase: candidate ? "observe" : "seed" }, projectReadback);
    assert.deepEqual(Object.keys(result), ["hashes"]);
    hashes.push(result.hashes);
    assert.equal(host.calls.length, candidate ? 4 : 2);
  }
  assert.deepEqual(hashes[0], hashes[1]);
});

test("candidate readback fails closed on missing handles and profile changes", async () => {
  for (const field of ["handle", "snapshot", "after", "response"]) {
    const host = readbackHost(true);
    if (field === "handle") delete host.snapshot.workspaces[0].core_handle;
    if (field === "snapshot") host.snapshot.profile.destination_hash = "e".repeat(32);
    const invoke = async (command, payload) => {
      const result = await host.invoke(command, payload);
      if (field === "after" && command === "core_api_profile" && host.calls.length === 4) {
        return { ...result, profile: "f".repeat(64) };
      }
      if (field === "response" && payload?.operation === "workspace.timeline_query") {
        return { ...result, workspace: "f".repeat(64) };
      }
      return result;
    };
    const result = await readInstalledUi(invoke, { ...markers, phase: "observe" }, projectReadback);
    assert.deepEqual(result, { failure_kind: "ui_profile_changed" });
    assert.equal(host.calls.some(call => call.command === "service_command"), false);
  }
});

test("readback retains a fixed failing operation without raw bridge errors or retained content", async () => {
  for (const operation of ["profile", "application.snapshot", "workspace.timeline_query"]) {
    const host = readbackHost(true);
    const result = await readInstalledUi(async (command, payload) => {
      if ((operation === "profile" && command === "core_api_profile") || payload?.operation === operation) {
        throw new Error("private native path and message text");
      }
      return host.invoke(command, payload);
    }, { ...markers, phase: "observe" }, projectReadback);
    assert.deepEqual(result, { failure_kind: { profile: "ui_profile_unavailable",
      "application.snapshot": "ui_snapshot_unavailable", "workspace.timeline_query": "ui_timeline_unavailable" }[operation] });
  }
  const host = readbackHost(true);
  host.snapshot.workspace_drafts = [];
  assert.deepEqual(await readInstalledUi(host.invoke, { ...markers, phase: "observe" }, projectReadback),
    { failure_kind: "ui_draft_missing" });
});

test("bounded readback retries initialization but retains the last failure at its deadline", async () => {
  let time = 0, attempts = 0;
  const clock = { now: () => time, pause: async ms => { time += ms; } };
  await assert.rejects(settledUiReadback(async remaining => {
    assert.equal(remaining, 400 - time);
    attempts++;
    throw new Error("ui_snapshot_unavailable");
  }, 400, clock), /ui_snapshot_unavailable/);
  assert.equal(attempts, 2);
  assert.equal(time, 400);
  attempts = 0;
  assert.equal(await settledUiReadback(async () => {
    if (++attempts === 1) throw new Error("ui_profile_unavailable");
    return "ready";
  }, 400, clock), "ready");
});

test("configuration accepts only bounded synthetic markers and exact source", () => {
  assert.deepEqual(checkedConfig({ ...markers }), markers);
  assert.equal(checkedConfig({ ...markers, workspace_name: "W".repeat(64) }).workspace_name.length, 64);
  for (const bad of [
    { ...markers, expected_source: "0".repeat(40), extra: "secret" },
    { ...markers, expected_source: "0".repeat(40) },
    { ...markers, phase: "observe", expected_source: "174728edad62aae6ef16e95b075183d06c5cdda3" },
    { ...markers, workspace_name: "x".repeat(65) },
    { ...markers, draft_text: markers.message_text },
    { ...markers, message_text: "private\ntext" },
    { ...markers, phase: "mutate" },
  ]) assert.throws(() => checkedConfig(bad));
  assert.equal(EVIDENCE_LEVEL, "windows_release_ui_seed_readback_contract_only");
});

test("projection returns only hashes and is self-contained in the app origin", async () => {
  const { snapshot, page } = sample();
  const projected = await projectReadback(snapshot, page, markers);
  assert.deepEqual(checkedReadback(projected), projected);
  assert.equal(projected.profile, hash("a".repeat(32)));
  assert.equal(projected.message_text, hash(markers.message_text));
  assert.equal(projected.draft_text, hash(markers.draft_text));
  assert.equal(JSON.stringify(projected).includes(markers.message_text), false);
  const isolated = runInNewContext(`(${projectReadback.toString()})`, {
    crypto: globalThis.crypto, TextEncoder, Uint8Array, Array,
  });
  assert.equal(JSON.stringify(await isolated(snapshot, page, markers)), JSON.stringify(projected));
});

test("projection refuses missing or ambiguous retained state", async () => {
  const changes = [
    ({ snapshot }) => { snapshot.profile.destination_hash = "wrong"; },
    ({ snapshot }) => { snapshot.workspaces.push({ ...snapshot.workspaces[0] }); },
    ({ snapshot }) => { snapshot.workspace_channels = []; },
    ({ snapshot }) => { snapshot.workspace_drafts[0].text = "other"; },
    ({ page }) => { page.messages[0].text = "other"; },
    ({ page }) => { page.messages.push({ ...page.messages[0] }); },
  ];
  for (const change of changes) {
    const value = sample();
    change(value);
    await assert.rejects(projectReadback(value.snapshot, value.page, markers));
  }
});

test("before and after hashes must agree in every field", async () => {
  const { snapshot, page } = sample();
  const before = await projectReadback(snapshot, page, markers);
  assert.equal(sameReadback(before, { ...before }), true);
  for (const field of Object.keys(before)) {
    assert.equal(sameReadback(before, { ...before, [field]: "0".repeat(64) }), false);
  }
  assert.throws(() => sameReadback(before, { ...before, path: "C:\\secret" }));
});

test("comparison preserves every unqualified installed and release claim", async () => {
  const { snapshot, page } = sample();
  const hashes = await projectReadback(snapshot, page, markers);
  const candidate = "d".repeat(40);
  const common = { v: 1, passed: true, evidence_level: EVIDENCE_LEVEL,
    installed_version: "0.9.66", hashes, native_upgrade_qualified: false,
    peer_receipt_qualified: false, schema_refusal_qualified: false,
    physical_device_identity_qualified: false };
  const before = { ...common, source_commit: markers.expected_source, phase: "seed" };
  const after = { ...common, source_commit: candidate, phase: "observe" };
  const result = compareReports(before, after, { ...after }, candidate);
  assert.equal(result.identity_workspace_message_draft_hashes_equal, true);
  assert.equal(result.candidate_reopen_hashes_equal, true);
  assert.equal(result.installed_continuity_qualified, false);
  assert.equal(result.installer_upgrade_qualified, false);
  for (const bad of [
    { ...after, hashes: { ...hashes, message_id: "0".repeat(64) } },
    { ...after, phase: "seed" },
    { ...after, peer_receipt_qualified: true },
    { ...after, raw_text: markers.message_text },
  ]) assert.throws(() => compareReports(before, bad, after, candidate));
  assert.throws(() => compareReports(before, after, { ...after, hashes: { ...hashes, draft_text: "0".repeat(64) } }, candidate));
  assert.throws(() => compareReports(before, after, after, markers.expected_source));
});

test("execution manifest stays bound to release pins and marks the switch unproven", () => {
  const manifest = JSON.parse(readFileSync(new URL("./windows-ui-execution-manifest.json", import.meta.url)));
  const pins = JSON.parse(readFileSync(new URL("./fixtures.json", import.meta.url)));
  assert.equal(manifest.baseline.source_commit, pins.source_commit);
  assert.equal(RELEASE_SOURCE, pins.source_commit);
  assert.equal(manifest.baseline.source_tree, pins.source_tree);
  assert.equal(manifest.baseline.msi_sha256, pins.assets["Mesh-Chat_0.9.66_x64_en-US.msi"].sha256);
  assert.equal(manifest.baseline.nsis_sha256, pins.assets["Mesh-Chat_0.9.66_x64-setup.exe"].sha256);
  assert.equal(manifest.status, "contract_only_switch_unproven");
  assert.equal(manifest.candidate.installer_sha256, null);
  assert.equal(manifest.claims.installed_continuity_executed, false);
  assert.equal(manifest.claims.installer_upgrade_qualified, false);
  assert.equal(manifest.claims.peer_receipt_qualified, false);
  assert.equal(manifest.claims.full_r8_qualified, false);
});

import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { runInNewContext } from "node:vm";
import { checkedConfig, checkedReadback, compareReports, EVIDENCE_LEVEL, projectReadback, RELEASE_SOURCE, sameReadback } from "../../scripts/windows_release_ui_contract.mjs";

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

test("configuration accepts only bounded synthetic markers and exact source", () => {
  assert.deepEqual(checkedConfig({ ...markers }), markers);
  for (const bad of [
    { ...markers, expected_source: "0".repeat(40), extra: "secret" },
    { ...markers, expected_source: "0".repeat(40) },
    { ...markers, phase: "observe", expected_source: "174728edad62aae6ef16e95b075183d06c5cdda3" },
    { ...markers, workspace_name: "x".repeat(97) },
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

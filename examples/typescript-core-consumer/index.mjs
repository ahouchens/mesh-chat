// Run only with host-inherited streams or an explicitly selected trusted pipe.
import { CoreClient } from "@mesh-chat/core-client";
import { readFileSync } from "node:fs";
import { connectNamedPipe, createStdioTransport } from "@mesh-chat/core-client/node";

const pipe = process.argv.indexOf("--pipe");
const transport = pipe >= 0 ? await connectNamedPipe(process.argv[pipe + 1]) : createStdioTransport();
const client = await CoreClient.open(transport);
try {
  const profile = client.capabilities.profiles[0];
  const report = { api_major: client.capabilities.api_major, api_minor: client.capabilities.api_minor,
    installed_package: import.meta.resolve("@mesh-chat/core-client").includes("node_modules"), sdk_only: true };
  if (process.argv.includes("--create-profile")) {
    report.created = (await client.createProfile("SDK qualification", "sdk-create-profile-key-0001")).display_name === "SDK qualification";
  } else if (process.argv.includes("--recover-call")) {
    const operation = (await client.callOperationList(profile)).operations[0].operation;
    const queried = (await client.callOperationQuery(profile, operation)).operation;
    const abandoned = (await client.callOperationAbandon(profile, operation, "sdk-call-abandon-key-0001")).operation;
    const repeated = (await client.callOperationAbandon(profile, operation, "sdk-call-abandon-key-0001")).operation;
    report.recovered = queried.operation === operation;
    report.cleanup_pending = abandoned.disposition === "cleanup_pending";
    report.replacement_blocked = !abandoned.replacement_safe;
    report.same_operation = JSON.stringify(repeated) === JSON.stringify(abandoned);
  } else if (process.argv.includes("--exercise-keyed-group-create")) {
    const peer = (await client.profileQuery(profile)).peers[0];
    const first = await client.createGroup(profile, "SDK qualification group", "members", [peer], "sdk-group-create-key-0001");
    const repeated = await client.createGroup(profile, "SDK qualification group", "members", [peer], "sdk-group-create-key-0001");
    report.same_group = first.group === repeated.group;
  } else if (process.argv.includes("--exercise-keyed-group-send")) {
    const group = (await client.groups(profile)).groups[0].group;
    const first = await client.sendGroup(profile, group, "SDK qualification group message", "sdk-group-send-key-0001");
    const repeated = await client.sendGroup(profile, group, "SDK qualification group message", "sdk-group-send-key-0001");
    report.accepted = first.accepted; report.same_message = first.message === repeated.message;
  } else if (process.argv.includes("--exercise-profile-lock")) {
    const selected = (await client.profileCatalog()).selected_profile;
    const result = await client.lockProfile(selected, "sdk-profile-lock-key-0001");
    report.locked = result.profiles.find(row => row.profile === selected).state === "locked";
  } else if (process.argv.includes("--exercise-profile-unlock")) {
    const selected = (await client.profileCatalog()).selected_profile;
    const result = await client.unlockProfile(selected, process.env.MESH_CORE_TEST_UNLOCK_CREDENTIAL, "sdk-profile-unlock-key-0001");
    report.unlocked = result.profiles.find(row => row.profile === selected).state === "unlocked";
  } else if (process.argv.includes("--keyed-owner")) {
    await client.createWorkspace(profile, "SDK qualification", "", "sdk-workspace-create-key-0001");
    const workspace = (await client.workspaceList(profile)).workspaces[0].workspace;
    report.listed = typeof await client.workspaceAdmissionGrantList(profile, workspace, "sdk-admission-list-key-0001") === "object";
  } else if (process.argv.includes("--keyed-join")) {
    const document = readFileSync(process.argv[process.argv.indexOf("--document-file") + 1], "utf8");
    const result = await client.workspaceJoin(profile, document, "sdk-workspace-join-key-0001");
    report.joined = ["joining", "active", "pending"].includes(result.state);
  } else if (process.argv.includes("--exercise-composer")) {
    const peer = (await client.profileQuery(profile)).peers[0];
    let current = await client.composerQuery(profile, peer);
    const update = await client.composerUpdate(profile, peer, current.revision, "SDK qualification composer", current.update_key);
    const accepted = await client.enqueueDraft(profile, peer, update.applied_revision);
    report.accepted = accepted.accepted;
    report.draft_empty = accepted.composer.text === "";
    report.replay_same_message = (await client.enqueueDraft(profile, peer, update.applied_revision)).message === accepted.message;
  } else if (process.argv.includes("--recover-composer")) {
    const peer = (await client.profileQuery(profile)).peers[0];
    const current = await client.composerQuery(profile, peer);
    if (current.last_send?.status !== "accepted") throw new Error("No accepted outcome to recover");
    const accepted = await client.enqueueDraft(profile, peer, current.last_send.revision);
    report.recovered_acceptance = accepted.message === current.last_send.acceptance.message;
    report.draft_empty = accepted.composer.text === "";
  } else if (process.argv.includes("--legacy")) {
    const peer = (await client.profileQuery(profile)).peers[0];
    const accepted = await client.enqueue(profile, peer, "SDK qualification legacy", "sdk-legacy-caller-key-0001");
    report.accepted = accepted.accepted;
  }
  console.error(JSON.stringify(report));
} catch (error) {
  // Codes only; no draft text, revision, replay key or upstream exception body.
  console.error(JSON.stringify({ failure: error.code ?? error.name, uncertain: true }));
  process.exitCode = 2;
} finally { client.close(); }

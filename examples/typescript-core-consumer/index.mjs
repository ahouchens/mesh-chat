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

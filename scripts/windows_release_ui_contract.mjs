// Fixed, read-only projection for a disposable installed-app continuity run.
export const EVIDENCE_LEVEL = "windows_release_ui_seed_readback_contract_only";
export const HASH_FIELDS = ["profile", "workspace", "channel", "message_id", "message_text", "draft_text"];
export const RELEASE_SOURCE = "7c40f7b23eab3e9d83ff7ca1075c90c4d84ce516";
const SDK_FIXTURE_SOURCE = "174728edad62aae6ef16e95b075183d06c5cdda3";

const HEX40 = /^[a-f0-9]{40}$/;
const MARKER = /^[A-Za-z0-9][A-Za-z0-9 .:_-]{0,95}$/;

export function checkedConfig(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)
      || Object.keys(value).sort().join(",") !==
        "draft_text,expected_source,expected_version,message_text,phase,workspace_name"
      || !["seed", "observe"].includes(value.phase)
      || typeof value.expected_source !== "string" || !HEX40.test(value.expected_source)
      || (value.phase === "seed" && value.expected_source !== RELEASE_SOURCE)
      || (value.phase === "observe" && [RELEASE_SOURCE, SDK_FIXTURE_SOURCE].includes(value.expected_source))
      || value.expected_version !== "0.9.66"
      || ![value.workspace_name, value.message_text, value.draft_text].every(
        (item) => typeof item === "string" && MARKER.test(item))) {
    throw new Error("ui_config_invalid");
  }
  if (new Set([value.workspace_name, value.message_text, value.draft_text]).size !== 3) {
    throw new Error("ui_markers_not_distinct");
  }
  return value;
}

export async function projectReadback(snapshot, page, markers) {
  // Keep dependencies local so this exact function can run in the app origin.
  const boundedId = (value) => typeof value === "string"
    && /^[A-Za-z0-9:_-]{1,128}$/.test(value);
  const sha = async (value) => {
    const bytes = new TextEncoder().encode(value);
    const digest = new Uint8Array(await globalThis.crypto.subtle.digest("SHA-256", bytes));
    return Array.from(digest, (part) => part.toString(16).padStart(2, "0")).join("");
  };
  if (!snapshot || typeof snapshot !== "object" || !snapshot.profile
      || !/^[a-f0-9]{32}$/.test(snapshot.profile.destination_hash)
      || !Array.isArray(snapshot.workspaces) || !Array.isArray(snapshot.workspace_channels)
      || !Array.isArray(snapshot.workspace_drafts) || !page || !Array.isArray(page.messages)) {
    throw new Error("ui_readback_invalid");
  }
  const matches = snapshot.workspaces.filter((item) => item?.name === markers.workspace_name);
  if (matches.length !== 1 || !boundedId(matches[0].id) || matches[0].state !== "active") {
    throw new Error("ui_workspace_missing");
  }
  const workspace = matches[0];
  const channels = snapshot.workspace_channels.filter(
    (item) => item?.workspace_id === workspace.id && item.name === "general");
  if (channels.length !== 1 || !boundedId(channels[0].id)) {
    throw new Error("ui_channel_missing");
  }
  const channel = channels[0];
  const drafts = snapshot.workspace_drafts.filter(
    (item) => item?.workspace_id === workspace.id && item.conversation_id === channel.id);
  if (drafts.length !== 1 || drafts[0].text !== markers.draft_text) {
    throw new Error("ui_draft_missing");
  }
  if (page.messages.length !== 1 || page.messages[0]?.text !== markers.message_text
      || !boundedId(page.messages[0].id)) {
    throw new Error("ui_message_missing");
  }
  return {
    profile: await sha(snapshot.profile.destination_hash),
    workspace: await sha(workspace.id),
    channel: await sha(channel.id),
    message_id: await sha(page.messages[0].id),
    message_text: await sha(page.messages[0].text),
    draft_text: await sha(drafts[0].text),
  };
}

export function checkedReadback(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)
      || Object.keys(value).sort().join(",") !== [...HASH_FIELDS].sort().join(",")
      || !HASH_FIELDS.every((field) => typeof value[field] === "string"
        && /^[a-f0-9]{64}$/.test(value[field]))) {
    throw new Error("ui_hashes_invalid");
  }
  return value;
}

export function sameReadback(before, after) {
  checkedReadback(before);
  checkedReadback(after);
  return HASH_FIELDS.every((field) => before[field] === after[field]);
}

export function compareReports(before, after, reopened, candidateSource) {
  const fields = "evidence_level,hashes,installed_version,native_upgrade_qualified,passed,peer_receipt_qualified,phase,physical_device_identity_qualified,schema_refusal_qualified,source_commit,v";
  const valid = (report, phase, source) => report && typeof report === "object"
    && !Array.isArray(report) && Object.keys(report).sort().join(",") === fields
    && report.v === 1 && report.passed === true && report.evidence_level === EVIDENCE_LEVEL
    && report.phase === phase && report.source_commit === source
    && report.installed_version === "0.9.66"
    && report.native_upgrade_qualified === false
    && report.peer_receipt_qualified === false
    && report.schema_refusal_qualified === false
    && report.physical_device_identity_qualified === false;
  if (typeof candidateSource !== "string" || !HEX40.test(candidateSource)
      || [RELEASE_SOURCE, SDK_FIXTURE_SOURCE].includes(candidateSource)
      || !valid(before, "seed", RELEASE_SOURCE)
      || !valid(after, "observe", candidateSource)
      || !valid(reopened, "observe", candidateSource)
      || !sameReadback(before.hashes, after.hashes)
      || !sameReadback(after.hashes, reopened.hashes)) {
    throw new Error("ui_reports_not_continuous");
  }
  return { v: 1, passed: true,
    evidence_level: "windows_release_ui_readback_comparison_only",
    baseline_source: RELEASE_SOURCE, candidate_source: candidateSource,
    identity_workspace_message_draft_hashes_equal: true,
    candidate_reopen_hashes_equal: true,
    installed_continuity_qualified: false,
    installer_upgrade_qualified: false,
    peer_receipt_qualified: false,
    schema_refusal_qualified: false,
    physical_device_identity_qualified: false,
    full_r8_qualified: false };
}

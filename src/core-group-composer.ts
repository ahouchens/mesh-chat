import { coreApiCapabilities, coreApiProfile, coreApiRequest, ServiceCommandError } from "./api";
import type { ComposerControllerPort, ComposerSnapshot, ComposerDraftEnqueue, ComposerDraftUpdate, ComposerSendOutcome, AcceptedComposerSend } from "./core-composer";

const OPERATIONS = ["group.composer_query", "group.composer_update", "group.message_enqueue_draft"];
const LIMITS = ["group_composer_text_utf8_bytes", "group_composers_per_caller_profile", "group_composers_per_vault",
  "group_composer_update_idempotency_seconds", "group_composer_update_keys_per_caller_profile", "group_composer_update_keys_per_vault",
  "group_composer_send_idempotency_seconds", "group_composer_send_keys_per_caller_profile", "group_composer_send_keys_per_vault"];
const token = (value: unknown): value is string => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
const protocol = (): never => { throw new ServiceCommandError("core_api_protocol"); };

export interface GroupComposer extends ComposerSnapshot { group: string; }
export interface GroupComposerUpdate extends ComposerDraftUpdate { composer: GroupComposer; }
export interface GroupComposerEnqueue extends ComposerDraftEnqueue { group: string; composer: GroupComposer; }

/** Absence is the only legacy decision; a partial or failing advertised family cannot downgrade. */
export async function openCoreGroupComposer(group: string): Promise<{ port: ComposerControllerPort; textUtf8Bytes: number } | null> {
  const caps = await coreApiCapabilities();
  if (!Array.isArray(caps.operations)) throw new ServiceCommandError("core_api_protocol");
  if (!OPERATIONS.some((operation) => caps.operations.includes(operation))) return null;
  if (caps.api_major !== 1 || !Number.isSafeInteger(caps.api_minor) || caps.api_minor < 1
      || !OPERATIONS.every((operation) => caps.operations.includes(operation))
      || !LIMITS.every((name) => Number.isSafeInteger(caps.limits?.[name]) && caps.limits![name] > 0)) throw new ServiceCommandError("unsupported_operation");
  const profile = await coreApiProfile();
  const textUtf8Bytes = caps.limits!.group_composer_text_utf8_bytes;
  return { port: groupComposerRequests({ profile: profile.profile, group }, textUtf8Bytes), textUtf8Bytes };
}

function validTimes(value: { accepted_at: number; idempotency_expires_at: number }): boolean {
  return Number.isFinite(value.accepted_at) && Number.isFinite(value.idempotency_expires_at) && value.idempotency_expires_at >= value.accepted_at;
}
function validateOutcome(value: ComposerSendOutcome | null, profile: string): void {
  if (value === null) return;
  if (!value || !token(value.revision)) protocol();
  if (value.status === "expired") { if (!validTimes(value)) protocol(); return; }
  if (value.status !== "accepted" || typeof value.text !== "string" || !["cleared", "superseded"].includes(value.draft_disposition)
      || !value.acceptance || value.acceptance.profile !== profile || value.acceptance.accepted !== true
      || typeof value.acceptance.message !== "string" || !value.acceptance.message || !validTimes(value.acceptance)) protocol();
}
function parseComposer(value: unknown, scope: { profile: string; group: string }, limit: number): GroupComposer {
  const result = value as GroupComposer;
  if (!result || result.profile !== scope.profile || result.group !== scope.group
      || !(result.revision === null || token(result.revision)) || !token(result.update_key) || typeof result.text !== "string"
      || new TextEncoder().encode(result.text).byteLength > limit) protocol();
  validateOutcome(result.last_send, scope.profile);
  const lookup = result.send_lookup;
  if (lookup !== null) {
    if (!lookup || !token(lookup.revision)) protocol();
    if (lookup.status === "accepted") validateOutcome(lookup as AcceptedComposerSend, scope.profile);
    else if (lookup.status !== "not_accepted") protocol();
  }
  return result;
}

/** The bound group identity stays distinct from every direct-peer handle. */
export function groupComposerRequests(target: { profile: string; group: string }, textUtf8Bytes: number): ComposerControllerPort {
  const scope = Object.freeze({ profile: target.profile, group: target.group });
  return {
    query: async (sendRevision) => {
      const result = parseComposer(await coreApiRequest("group.composer_query", { ...scope, ...(sendRevision ? { send_revision: sendRevision } : {}) }), scope, textUtf8Bytes);
      if (result.send_lookup && result.send_lookup.revision !== sendRevision) protocol();
      return result;
    },
    update: async (expectedRevision, text, updateKey) => {
      const result = await coreApiRequest<GroupComposerUpdate>("group.composer_update", { ...scope, expected_revision: expectedRevision, text }, updateKey);
      if (!result || !token(result.applied_revision) || typeof result.changed !== "boolean") protocol();
      parseComposer(result.composer, scope, textUtf8Bytes);
      return result;
    },
    enqueue: async (draftRevision) => {
      const result = await coreApiRequest<GroupComposerEnqueue>("group.message_enqueue_draft", { ...scope, draft_revision: draftRevision }, draftRevision);
      if (!result || result.profile !== scope.profile || result.group !== scope.group || result.accepted !== true
          || result.draft_revision !== draftRevision || typeof result.message !== "string" || !result.message || !validTimes(result)
          || !["cleared", "superseded"].includes(result.draft_disposition)) protocol();
      parseComposer(result.composer, scope, textUtf8Bytes);
      return result;
    },
  };
}

import { coreApiCapabilities, coreApiPeerForDestination, coreApiProfile, coreApiRequest, ServiceCommandError } from "./api";
import type { CoreRequestAdmission } from "./core-admission";

type GroupOperation = "group.create" | "group.message_enqueue";
const LIMITS = ["optional_key_idempotency_seconds", "optional_keys_per_caller_profile", "optional_keys_per_vault"];

async function supportsKeyedGroups(operation: GroupOperation): Promise<boolean> {
  const caps = await coreApiCapabilities();
  if (!Array.isArray(caps.optional_keyed_operations) || !caps.optional_keyed_operations.includes(operation)) return false;
  if (caps.api_major !== 1 || !Number.isSafeInteger(caps.api_minor) || caps.api_minor < 1
    || !Array.isArray(caps.operations) || !caps.operations.includes(operation)
    || !LIMITS.every((name) => Number.isSafeInteger(caps.limits?.[name]) && caps.limits![name] > 0)) {
    throw new ServiceCommandError("unsupported_operation");
  }
  return true;
}

export interface GroupCreationTicket {
  readonly key: string;
  readonly params: Readonly<{ profile: string; title: string; posting_policy: "members" | "owner_admins"; members: readonly string[] }>;
}
export interface GroupSendTicket {
  readonly key: string;
  readonly params: Readonly<{ profile: string; group: string; text: string }>;
}
export interface GroupAcceptance {
  sent: true;
  accepted: true;
  message: string;
  accepted_at: number;
  idempotency_expires_at: number;
}

/** The UI owns the key. Preparation is read-only and never downgrades a keyed ticket. */
export async function prepareKeyedGroupCreation(title: string, policy: "members" | "owner_admins", destinations: string[], key: string): Promise<GroupCreationTicket | null> {
  if (!await supportsKeyedGroups("group.create")) return null;
  const profile = await coreApiProfile();
  const members: string[] = [];
  for (const destination of destinations) {
    const target = await coreApiPeerForDestination(destination);
    if (target.profile !== profile.profile) throw new ServiceCommandError("resync_required");
    members.push(target.peer);
  }
  return Object.freeze({ key, params: Object.freeze({ profile: profile.profile, title, posting_policy: policy, members: Object.freeze(members) }) });
}

export async function submitKeyedGroupCreation(ticket: GroupCreationTicket, admit: CoreRequestAdmission): Promise<{ group: string; name: string }> {
  const result = await admit(() => coreApiRequest<{ group: string; name: string }>("group.create", { ...ticket.params }, ticket.key));
  if (typeof result?.group !== "string" || typeof result.name !== "string") throw new ServiceCommandError("core_api_protocol");
  return result;
}

export async function prepareKeyedGroupSend(group: string, text: string, key: string): Promise<GroupSendTicket | null> {
  if (!await supportsKeyedGroups("group.message_enqueue")) return null;
  const profile = await coreApiProfile();
  return Object.freeze({ key, params: Object.freeze({ profile: profile.profile, group, text }) });
}

export async function submitKeyedGroupSend(ticket: GroupSendTicket, admit: CoreRequestAdmission): Promise<GroupAcceptance> {
  const result = await admit(() => coreApiRequest<GroupAcceptance>("group.message_enqueue", { ...ticket.params }, ticket.key));
  if (result?.sent !== true || result.accepted !== true || typeof result.message !== "string"
    || !Number.isFinite(result.accepted_at) || !Number.isFinite(result.idempotency_expires_at)
    || result.idempotency_expires_at < result.accepted_at) throw new ServiceCommandError("core_api_protocol");
  return result;
}

import { coreApiCapabilities, coreApiPeerForDestination, coreApiRequest, ServiceCommandError } from "./api";

const COMPOSER_OPERATIONS = ["peer.composer_query", "peer.composer_update", "message.enqueue_draft"];
const COMPOSER_LIMITS = [
  "composer_text_utf8_bytes", "composers_per_caller_profile", "composers_per_vault",
  "composer_update_idempotency_seconds", "composer_update_keys_per_caller_profile", "composer_update_keys_per_vault",
  "composer_send_idempotency_seconds", "composer_send_keys_per_caller_profile", "composer_send_keys_per_vault",
];

export async function openCoreComposer(destination: string): Promise<{ port: ComposerPort; textUtf8Bytes: number }> {
  const capabilities = await coreApiCapabilities();
  if (capabilities.api_major !== 1 || !Number.isSafeInteger(capabilities.api_minor) || capabilities.api_minor < 1
    || !Array.isArray(capabilities.operations)
    || !COMPOSER_OPERATIONS.every((operation) => capabilities.operations.includes(operation))
    || !COMPOSER_LIMITS.every((limit) => Number.isSafeInteger(capabilities.limits?.[limit]) && capabilities.limits![limit] > 0)) {
    throw new ServiceCommandError("unsupported_operation");
  }
  const target = await coreApiPeerForDestination(destination);
  return { port: composerRequests(target), textUtf8Bytes: capabilities.limits!.composer_text_utf8_bytes };
}

export interface MessageAcceptance {
  profile: string;
  message: string;
  accepted: true;
  accepted_at: number;
  idempotency_expires_at: number;
}

export interface AcceptedComposerSend {
  revision: string;
  status: "accepted";
  acceptance: MessageAcceptance;
  text: string;
  draft_disposition: "cleared" | "superseded";
}

export interface ExpiredComposerSend {
  revision: string;
  status: "expired";
  accepted_at: number;
  idempotency_expires_at: number;
}

export type ComposerSendOutcome = AcceptedComposerSend | ExpiredComposerSend;

export interface ComposerSnapshot {
  profile: string;
  revision: string | null;
  text: string;
  update_key: string;
  last_send: ComposerSendOutcome | null;
  send_lookup: AcceptedComposerSend | { revision: string; status: "not_accepted" } | null;
}
export interface CoreComposer extends ComposerSnapshot { peer: string; }

export interface ComposerDraftUpdate {
  applied_revision: string;
  changed: boolean;
  composer: ComposerSnapshot;
}
export interface ComposerUpdate extends ComposerDraftUpdate { composer: CoreComposer; }

export interface ComposerDraftEnqueue extends MessageAcceptance {
  draft_revision: string;
  draft_disposition: "cleared" | "superseded";
  composer: ComposerSnapshot;
}
export interface ComposerEnqueue extends ComposerDraftEnqueue { peer: string; composer: CoreComposer; }

export interface ComposerControllerPort {
  query(sendRevision?: string): Promise<ComposerSnapshot>;
  update(expectedRevision: string | null, text: string, updateKey: string): Promise<ComposerDraftUpdate>;
  updateForRetirement?(expectedRevision: string | null, text: string, updateKey: string): Promise<ComposerDraftUpdate>;
  enqueue(draftRevision: string): Promise<ComposerDraftEnqueue>;
}

export interface ComposerPort extends ComposerControllerPort {
  query(sendRevision?: string): Promise<CoreComposer>;
  update(expectedRevision: string | null, text: string, updateKey: string): Promise<ComposerUpdate>;
  updateForRetirement?(expectedRevision: string | null, text: string, updateKey: string): Promise<ComposerUpdate>;
  enqueue(draftRevision: string): Promise<ComposerEnqueue>;
}

export function composerRequests(target: { profile: string; peer: string }): ComposerPort {
  const scope = { profile: target.profile, peer: target.peer };
  return {
    query: (sendRevision) => coreApiRequest("peer.composer_query", {
      ...scope, ...(sendRevision ? { send_revision: sendRevision } : {}),
    }),
    update: (expectedRevision, text, updateKey) => coreApiRequest("peer.composer_update", {
      ...scope, expected_revision: expectedRevision, text,
    }, updateKey),
    enqueue: (draftRevision) => coreApiRequest("message.enqueue_draft", {
      profile: target.profile, recipient: target.peer, draft_revision: draftRevision,
    }, draftRevision),
  };
}

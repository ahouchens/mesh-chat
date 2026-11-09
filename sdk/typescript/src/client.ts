/**
 * Experimental client for the private Mesh Chat Core API.
 *
 * This wraps the versioned frame contract only. It does not authenticate a host
 * endpoint, start a runtime, implement peer retry policy or own a data directory.
 * Until a supported Windows/Android host binding ships, the surface stays
 * experimental and is not a redistribution promise.
 */

import { AbortError, CoreError, ProtocolError, TimeoutError, TransportClosedError } from "./errors.js";
import { decodeResponse, encodeRequest, type RequestEnvelope } from "./framing.js";
import type { LineTransport } from "./transport.js";
import type {
  Acceptance,
  Acknowledgment,
  Capabilities,
  ProfileCatalog,
  CallOperationCatalog,
  CallOperationResult,
  PairingIntent,
  PairingBeginOptions,
  ConnectionView,
  DiagnosticsView,
  EventPage,
  ProfileView,
  InvitationView,
  PairingRequestView,
  PairingView,
  ReceivedPage,
  RelationshipView,
  StopView,
  WorkspaceChannelCreateView,
  WorkspaceChannelArchiveView,
  WorkspaceChannelMembersView,
  WorkspaceChannelTransferAcceptView,
  WorkspaceChannelTransferOfferView,
  WorkspaceChannelUpdateView,
  WorkspaceChannelsView,
  WorkspaceDeclineView,
  ConnectionIntentView,
  MessageListView,
  SnapshotMessage,
  PeerView,
  WorkspaceApproveView,
  WorkspaceJoinRequestSummary,
  WorkspaceListView,
  WorkspacePolicyView,
  WorkspaceRequestsView,
  WorkspaceDeviceLinkDecisionView,
  WorkspaceDeviceLinkPreviewView,
  WorkspaceDeviceLinkSubmitView,
  WorkspaceDeviceRemoveView,
  WorkspaceDevicesView,
  WorkspaceDeviceLinksView,
  WorkspaceDeviceLinkView,
  WorkspaceJoinView,
  WorkspaceMemberRoleView,
  WorkspaceMembersView,
  WorkspacePreviewView,
  WorkspaceInvitationView,
} from "./types.js";

export const DEFAULT_TIMEOUT_MS = 30_000;
export const MAX_BATCH = 128;
export const MAX_DIAGNOSTICS = 256;

export interface CoreClientOptions {
  requestTimeoutMs?: number;
}

export interface RequestOptions {
  idempotencyKey?: string;
  timeoutMs?: number;
  signal?: AbortSignal;
}

const REQUIRED_KEYS = new Set(["call.control", "call.operation_abandon", "connection.retry", "events.ack", "message.enqueue", "message.enqueue_draft", "peer.composer_update", "peer.pairing_begin", "peer.pairing_cancel", "profile.create", "profile.lock", "profile.select", "profile.unlock", "remote_profile.mutate", "route.update", "runtime.mutate", "workspace.admin_request_approve", "workspace.admin_request_cancel", "workspace.admin_request_decline", "workspace.admin_request_dismiss", "workspace.admin_request_submit", "workspace.admission_grant_accept", "workspace.admission_grant_create", "workspace.admission_grant_end", "workspace.admission_grant_list", "workspace.authority_accept", "workspace.authority_finalize", "workspace.authority_loss_report", "workspace.authority_offer", "workspace.channel_archive", "workspace.channel_create", "workspace.channel_members_update", "workspace.channel_recover", "workspace.channel_state", "workspace.channel_transfer_accept", "workspace.channel_transfer_offer", "workspace.channel_update", "workspace.close", "workspace.create", "workspace.device_link_approve", "workspace.device_link_create", "workspace.device_link_decline", "workspace.device_link_submit", "workspace.device_remove", "workspace.direct_open", "workspace.display_name_decide", "workspace.display_name_request", "workspace.draft_set", "workspace.invitation_create", "workspace.invitation_revoke", "workspace.join", "workspace.join_approve", "workspace.join_decline", "workspace.join_prompt", "workspace.leave", "workspace.member_remove", "workspace.member_role", "workspace.metadata_update", "workspace.policy_update", "workspace.read_hint_sync", "workspace.remove_data", "workspace.retention_update", "workspace.timeline_mutation"]);
const KEYED_ACTIONS: Record<string, string[]> = {"workspace.connection": ["invite_contact", "prompt_dismiss", "prompt_submit", "reconnect_consent"], "workspace.history": ["cancel", "hide_direct", "hide_message", "prune", "start"], "workspace.access_recommendation": ["apply", "apply_by_id", "create", "send"]};

export class CoreClient {
  readonly #transport: LineTransport;
  readonly #timeoutMs: number;
  #tail: Promise<unknown> = Promise.resolve();
  #capabilities: Capabilities | null = null;
  #sequence = 0;
  #closed = false;

  private constructor(transport: LineTransport, options: CoreClientOptions) {
    this.#transport = transport;
    this.#timeoutMs = options.requestTimeoutMs ?? DEFAULT_TIMEOUT_MS;
  }

  /** Negotiate once, then expose the negotiated capabilities and limits. */
  static async open(transport: LineTransport, options: CoreClientOptions = {}): Promise<CoreClient> {
    const client = new CoreClient(transport, options);
    const capabilities = await client.request<Capabilities>("runtime.capabilities", {});
    if (capabilities.api_major !== 1) {
      client.close();
      throw new ProtocolError("unsupported public API major");
    }
    client.#capabilities = capabilities;
    return client;
  }

  get capabilities(): Capabilities {
    if (this.#capabilities === null) {
      throw new ProtocolError("client is not negotiated");
    }
    return this.#capabilities;
  }

  get closed(): boolean {
    return this.#closed;
  }

  close(): void {
    if (!this.#closed) {
      this.#closed = true;
      this.#transport.close();
    }
  }

  /**
   * Send one request. Requests are serialized because the host binding reads one
   * frame at a time; results keep their submission order.
   */
  async request<T>(operation: string, params: Record<string, unknown> = {}, options: RequestOptions = {}): Promise<T> {
    if (this.#closed) {
      throw new TransportClosedError();
    }
    if ((options.idempotencyKey !== undefined || REQUIRED_KEYS.has(operation) || (KEYED_ACTIONS[operation] ?? []).includes(String(params.action))) &&
        (typeof options.idempotencyKey !== "string" || !/^[A-Za-z0-9._:-]{16,128}$/.test(options.idempotencyKey))) {
      throw new ProtocolError("operation requires a caller-provided idempotency key");
    }
    const requestId = `client:${(++this.#sequence).toString(36)}`;
    const envelope: RequestEnvelope = { api_version: 1, request_id: requestId, operation, params };
    if (options.idempotencyKey !== undefined) {
      envelope.idempotency_key = options.idempotencyKey;
    }
    const line = encodeRequest(envelope);
    const timeoutMs = options.timeoutMs ?? this.#timeoutMs;
    if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 3600000) throw new ProtocolError("invalid request timeout");
    const run = (): Promise<unknown> =>
      this.#exchange(line, requestId, timeoutMs, options.signal);
    const result = this.#tail.then(run, run);
    this.#tail = result.then(
      () => undefined,
      () => undefined,
    );
    return (await result) as T;
  }

  async #exchange(
    line: string,
    requestId: string,
    timeoutMs: number,
    signal?: AbortSignal,
  ): Promise<unknown> {
    if (this.#closed || signal?.aborted) {
      throw this.#closed ? new TransportClosedError() : new AbortError(requestId);
    }
    let response: ReturnType<typeof decodeResponse>;
    try {
      response = decodeResponse(await this.#read(line, requestId, timeoutMs, signal));
    } catch (error) {
      this.close();
      throw error;
    }
    if (response.request_id !== requestId) {
      this.close();
      if (!response.ok && response.request_id === null &&
          ["forbidden", "invalid_request", "resource_exhausted", "unavailable"].includes(response.error.code)) {
        throw new CoreError(response.error.code, null, response.error.retry_after_ms, response.error);
      }
      throw new ProtocolError("response does not correlate with the dispatched request");
    }
    if (!response.ok) {
      throw new CoreError(response.error.code, response.request_id, response.error.retry_after_ms, response.error);
    }
    return response.result;
  }

  async #read(request: string, requestId: string, timeoutMs: number, signal?: AbortSignal): Promise<string> {
    let timer: ReturnType<typeof setTimeout> | undefined;
    let detach: (() => void) | undefined;
    try {
      const deadline = new Promise<never>((_, reject) => {
        timer = setTimeout(() => reject(new TimeoutError(requestId)), timeoutMs);
      });
      const exchange = (async () => {
        await this.#transport.writeLine(request);
        return this.#transport.readLine();
      })();
      const racers: Promise<string | null>[] = [exchange, deadline];
      if (signal !== undefined) {
        racers.push(new Promise<never>((_, reject) => {
          const onAbort = (): void => reject(new AbortError(requestId));
          signal.addEventListener("abort", onAbort, { once: true });
          detach = () => signal.removeEventListener("abort", onAbort);
        }));
      }
      const line = await Promise.race(racers);
      if (line === null) {
        this.close();
        throw new TransportClosedError();
      }
      return line;
    } catch (error) {
      this.close();
      throw error;
    } finally {
      if (timer !== undefined) {
        clearTimeout(timer);
      }
      if (detach !== undefined) {
        detach();
      }
    }
  }

  async nativeCommand(command: string, payload: Record<string, unknown> = {}): Promise<unknown> {
    return this.request<unknown>("native.command", { command, payload });
  }

  async applicationSnapshot(): Promise<Record<string, unknown>> {
    return this.request<Record<string, unknown>>("application.snapshot", {});
  }

  #requireProfileRuntime(): void {
    const names = ["profile.catalog", "profile.lock", "profile.select", "profile.unlock"];
    const limits = ["profile_slots", "profile_lifecycle_keys_per_host", "profile_lifecycle_keys_per_caller_profile", "profile_unlock_credentials"];
    if (this.capabilities.api_minor < 1 || !names.every(name => this.capabilities.operations.includes(name)) ||
        !limits.every(name => Number.isSafeInteger(this.capabilities.limits[name]) && this.capabilities.limits[name]! > 0)) {
      throw new CoreError("unsupported_operation", null, null);
    }
  }

  async profileCatalog(): Promise<ProfileCatalog> {
    this.#requireProfileRuntime(); return this.request("profile.catalog", {});
  }

  async lockProfile(profile: string, idempotencyKey: string): Promise<ProfileCatalog> {
    this.#requireProfileRuntime(); return this.request("profile.lock", { profile }, { idempotencyKey });
  }

  async selectProfile(profile: string, idempotencyKey: string): Promise<ProfileCatalog> {
    this.#requireProfileRuntime(); return this.request("profile.select", { profile }, { idempotencyKey });
  }

  async unlockProfile(profile: string, credentialHandle: string, idempotencyKey: string): Promise<ProfileCatalog> {
    this.#requireProfileRuntime(); return this.request("profile.unlock", { profile, credential_handle: credentialHandle }, { idempotencyKey });
  }

  #requireCallRecovery(): void {
    const caps = this.capabilities;
    const operations = ["call.operation_list", "call.operation_query", "call.operation_abandon"];
    const limits = ["call_operations_per_caller_profile", "call_operations_per_vault", "call_operation_retention_seconds",
      "call_operation_keys_per_caller_profile", "call_operation_keys_per_vault"];
    if (!Number.isSafeInteger(caps.api_minor) || caps.api_minor < 1 || !Array.isArray(caps.operations) ||
        operations.some(name => !caps.operations.includes(name)) || typeof caps.limits !== "object" || caps.limits === null ||
        limits.some(name => !Number.isSafeInteger(caps.limits[name]) || caps.limits[name]! <= 0)) {
      throw new CoreError("unsupported_operation", null, null);
    }
  }

  async callOperationList(profile: string): Promise<CallOperationCatalog> {
    this.#requireCallRecovery(); return this.request("call.operation_list", { profile });
  }

  async callOperationQuery(profile: string, operation: string): Promise<CallOperationResult> {
    this.#requireCallRecovery(); return this.request("call.operation_query", { profile, operation });
  }

  async callOperationAbandon(profile: string, operation: string, idempotencyKey: string): Promise<CallOperationResult> {
    this.#requireCallRecovery(); return this.request("call.operation_abandon", { profile, operation }, { idempotencyKey });
  }

  #requirePairingIntents(): void {
    const caps = this.capabilities;
    const operations = ["peer.pairing_begin", "peer.pairing_query", "peer.pairing_cancel"];
    const limits = ["pairing_intents_per_runtime", "pairing_active_intents", "pairing_intent_seconds", "pairing_code_utf8_bytes",
      "pairing_key_idempotency_seconds", "pairing_keys_per_caller_profile", "pairing_keys_per_vault"];
    if (!Number.isSafeInteger(caps.api_minor) || caps.api_minor < 1 || !Array.isArray(caps.operations) ||
        operations.some(name => !caps.operations.includes(name)) || typeof caps.limits !== "object" || caps.limits === null ||
        limits.some(name => !Number.isSafeInteger(caps.limits[name]) || caps.limits[name]! <= 0)) {
      throw new CoreError("unsupported_operation", null, null);
    }
  }

  async pairingBegin(profile: string, role: "offer" | "answer", idempotencyKey: string,
                     options: PairingBeginOptions = {}): Promise<PairingIntent> {
    this.#requirePairingIntents();
    const consent = options.allowDirectIpDisclosure === undefined ? false : options.allowDirectIpDisclosure;
    if (!["offer", "answer"].includes(role) || typeof consent !== "boolean" ||
        (role === "offer" && options.pairingCode !== undefined) ||
        (role === "answer" && (typeof options.pairingCode !== "string" || options.pairingCode.length === 0 ||
          new TextEncoder().encode(options.pairingCode).length > this.capabilities.limits.pairing_code_utf8_bytes!))) {
      throw new ProtocolError("pairing role, code or disclosure consent is invalid");
    }
    return this.request("peer.pairing_begin", { profile, role, allow_direct_ip_disclosure: consent,
      ...(options.pairingCode !== undefined ? { pairing_code: options.pairingCode } : {}) }, { idempotencyKey });
  }

  async pairingQuery(profile: string, pairing: string): Promise<PairingIntent> {
    this.#requirePairingIntents(); return this.request("peer.pairing_query", { profile, pairing });
  }

  async pairingCancel(profile: string, pairing: string, idempotencyKey: string): Promise<PairingIntent> {
    this.#requirePairingIntents(); return this.request("peer.pairing_cancel", { profile, pairing }, { idempotencyKey });
  }

  async profileQuery(profile: string): Promise<ProfileView> {
    return this.request<ProfileView>("profile.query", { profile });
  }

  async connectionSnapshot(profile: string, connection: string): Promise<ConnectionView> {
    return this.request<ConnectionView>("connection.snapshot", { profile, connection });
  }

  async received(profile: string, cursor: string | null = null, limit = MAX_BATCH): Promise<ReceivedPage> {
    bounded(limit, MAX_BATCH, "received page");
    return this.request<ReceivedPage>("message.received", { profile, cursor, limit });
  }

  async enqueue(
    profile: string,
    recipient: string,
    text: string,
    idempotencyKey: string,
  ): Promise<Acceptance> {
    if (idempotencyKey.length < 16) {
      throw new ProtocolError("mutations require a caller-scoped idempotency key");
    }
    return this.request<Acceptance>(
      "message.enqueue",
      { profile, recipient, kind: "text", text },
      { idempotencyKey },
    );
  }

  async pollEvents(profile: string, cursor: string | null = null, limit = MAX_BATCH): Promise<EventPage> {
    bounded(limit, MAX_BATCH, "event page");
    return this.request<EventPage>("events.poll", { profile, cursor, limit });
  }

  async acknowledge(profile: string, cursor: string, idempotencyKey: string): Promise<Acknowledgment> {
    if (idempotencyKey.length < 16) {
      throw new ProtocolError("acknowledgments require a caller-scoped idempotency key");
    }
    return this.request<Acknowledgment>("events.ack", { profile, cursor }, { idempotencyKey });
  }

  async diagnostics(profile: string, limit = MAX_DIAGNOSTICS): Promise<DiagnosticsView> {
    bounded(limit, MAX_DIAGNOSTICS, "diagnostic page");
    return this.request<DiagnosticsView>("diagnostics.query", { profile, limit });
  }

  async approve(profile: string, peer: string): Promise<RelationshipView> {
    return this.request<RelationshipView>("peer.approve", { profile, peer });
  }

  async unblock(profile: string, peer: string): Promise<RelationshipView> {
    return this.request<RelationshipView>("peer.unblock", { profile, peer });
  }

  async createGroup(profile: string, title: string,
                    postingPolicy: "members" | "owner_admins",
                    members: string[], idempotencyKey?: string): Promise<unknown> {
    if (idempotencyKey !== undefined) this.#requireOptionalKeyed("group.create");
    return this.request("group.create", { profile, title, posting_policy: postingPolicy, members },
      idempotencyKey === undefined ? {} : { idempotencyKey });
  }

  #requireOptionalKeyed(operation: string): void {
    const caps = this.capabilities;
    const names = ["optional_key_idempotency_seconds", "optional_keys_per_caller_profile", "optional_keys_per_vault"];
    if (!Number.isSafeInteger(caps.api_minor) || caps.api_minor < 1 || !Array.isArray(caps.optional_keyed_operations) ||
        !caps.optional_keyed_operations.includes(operation) || !Array.isArray(caps.operations) || !caps.operations.includes(operation) || !caps.limits || !names.every(name =>
        Number.isSafeInteger(caps.limits[name]) && caps.limits[name]! > 0)) {
      throw new CoreError("unsupported_operation", null, null);
    }
  }

  async retryGroupInvitation(profile: string, group: string, member: string): Promise<unknown> {
    return this.request("group.invitation_retry", { profile, group, member });
  }

  async groupInvitation(profile: string, invitation: string, accept: boolean): Promise<unknown> {
    return this.request(accept ? "group.invitation_accept" : "group.invitation_decline", {
      profile, invitation,
    });
  }

  async leaveGroup(profile: string, group: string): Promise<unknown> {
    return this.request("group.leave", { profile, group });
  }

  async closeGroup(profile: string, group: string): Promise<unknown> {
    return this.request("group.close", { profile, group });
  }

  async removeGroupMember(profile: string, group: string, member: string): Promise<unknown> {
    return this.request("group.member_remove", { profile, group, member });
  }

  async sendGroup(profile: string, group: string, text: string, idempotencyKey?: string): Promise<unknown> {
    if (idempotencyKey !== undefined) this.#requireOptionalKeyed("group.message_enqueue");
    return this.request("group.message_enqueue", { profile, group, text },
      idempotencyKey === undefined ? {} : { idempotencyKey });
  }

  async groups(profile: string): Promise<unknown> {
    return this.request("group.query", { profile });
  }

  async reactionSet(profile: string, message: string, emoji: string, active: boolean): Promise<unknown> {
    return this.request("message.reaction_set", { profile, message, emoji, active });
  }

  async networkSettings(profile: string): Promise<{ profile: string; settings: Record<string, unknown> }> {
    return this.request("settings.query", { profile });
  }

  async updateNetworkSettings(profile: string, settings: Record<string, unknown>): Promise<{ profile: string; settings: Record<string, unknown> }> {
    return this.request("settings.update", { profile, settings });
  }

  async callControl(profile: string, action: string, params: Record<string, unknown>,
                      idempotencyKey: string): Promise<unknown> {
    return this.request("call.control", { profile, action, ...params }, { idempotencyKey });
  }

  async callMedia(profile: string, call: string): Promise<{ profile: string; call: string; media: Record<string, unknown> }> {
    return this.request("call.media_query", { profile, call });
  }

  async callIceServers(profile: string): Promise<{ profile: string; ice: Record<string, unknown> }> {
    return this.request("call.ice_servers", { profile });
  }

  async callSettingsGet(profile: string): Promise<{ profile: string; settings: Record<string, unknown> }> {
    return this.request("call.settings_query", { profile });
  }

  async callSettingsUpdate(profile: string, settings: Record<string, unknown>): Promise<{ profile: string; settings: Record<string, unknown> }> {
    return this.request("call.settings_update", { profile, settings });
  }

  async draftGet(profile: string, peer: string): Promise<{ profile: string; peer: string; text: string }> {
    return this.request("peer.draft_get", { profile, peer });
  }

  async composerQuery(profile: string, peer: string, send_revision?: string): Promise<import("./types.js").Composer> {
    this.#requireComposer();
    return this.request("peer.composer_query", { profile, peer, ...(send_revision === undefined ? {} : { send_revision }) });
  }

  async composerUpdate(profile: string, peer: string, expected_revision: string | null, text: string, update_key: string): Promise<import("./types.js").ComposerUpdate> {
    this.#requireComposer();
    if (Buffer.byteLength(text, "utf8") > this.capabilities.limits.composer_text_utf8_bytes!) {
      throw new ProtocolError("composer text exceeds the negotiated byte limit");
    }
    return this.request("peer.composer_update", { profile, peer, expected_revision, text }, { idempotencyKey: update_key });
  }

  async enqueueDraft(profile: string, recipient: string, draft_revision: string): Promise<import("./types.js").DraftAcceptance> {
    this.#requireComposer();
    return this.request("message.enqueue_draft", { profile, recipient, draft_revision }, { idempotencyKey: draft_revision });
  }

  #requireComposer(): void {
    const caps = this.capabilities;
    const names = ["composer_text_utf8_bytes", "composers_per_caller_profile", "composers_per_vault",
      "composer_update_idempotency_seconds", "composer_update_keys_per_caller_profile", "composer_update_keys_per_vault",
      "composer_send_idempotency_seconds", "composer_send_keys_per_caller_profile", "composer_send_keys_per_vault"];
    if (!Number.isSafeInteger(caps.api_minor) || caps.api_minor < 1 ||
        !Array.isArray(caps.operations) ||
        !["peer.composer_query", "peer.composer_update", "message.enqueue_draft"].every(name => caps.operations.includes(name)) ||
        !caps.limits || !names.every(name => Number.isSafeInteger(caps.limits[name]) && caps.limits[name]! > 0)) {
      throw new CoreError("unsupported_operation", null, null);
    }
  }

  async draftSet(profile: string, peer: string, text: string): Promise<{ profile: string; peer: string; text: string }> {
    return this.request("peer.draft_set", { profile, peer, text });
  }

  async deletePeer(profile: string, peer: string): Promise<{ profile: string; peer: string; deleted: boolean }> {
    return this.request("peer.delete", { profile, peer });
  }

  async revoke(profile: string, peer: string): Promise<RelationshipView> {
    return this.request<RelationshipView>("peer.revoke", { profile, peer });
  }

  async pairingCreate(profile: string, options: Record<string, unknown> = {}): Promise<InvitationView> {
    return this.request<InvitationView>("peer.pairing_create", { ...options, profile });
  }

  async pairingAccept(profile: string, document: string, i2pConsent = false): Promise<PairingView> {
    if (document.length === 0) {
      throw new ProtocolError("pairing requires signed invitation material");
    }
    const params: Record<string, unknown> = { profile, document };
    if (i2pConsent) params.i2p_consent = true;
    return this.request<PairingView>("peer.pairing_accept", params);
  }

  async workspacePreview(profile: string, document: string): Promise<WorkspacePreviewView> {
    if (document.length === 0) {
      throw new ProtocolError("workspace invitations require material");
    }
    return this.request<WorkspacePreviewView>("workspace.invitation_preview", { profile, document });
  }

  async workspaceJoin(profile: string, document: string, idempotencyKey?: string): Promise<WorkspaceJoinView> {
    if (document.length === 0) {
      throw new ProtocolError("workspace joins require signed material");
    }
    return this.request<WorkspaceJoinView>("workspace.join", { profile, document }, idempotencyKey === undefined ? {} : { idempotencyKey });
  }

  async workspaceChannels(profile: string, workspace: string): Promise<WorkspaceChannelsView> {
    return this.request<WorkspaceChannelsView>("workspace.channels", { profile, workspace });
  }

  async workspaceInvitationCreate(
    profile: string,
    workspace: string,
    idempotencyKey: string,
    connectionMode?: "webrtc" | "email" | "i2p" | "participant",
    i2pAccessPoint?: string,
    i2pLabel?: string,
  ): Promise<WorkspaceInvitationView> {
    if (idempotencyKey.length < 16) {
      throw new ProtocolError("workspace invitations require a caller key");
    }
    const params: Record<string, unknown> = { profile, workspace };
    if (connectionMode !== undefined) {
      params.connection_mode = connectionMode;
    }
    if (i2pAccessPoint !== undefined) {
      params.i2p_access_point = i2pAccessPoint;
    }
    if (i2pLabel !== undefined) {
      params.i2p_label = i2pLabel;
    }
    return this.request<WorkspaceInvitationView>(
      "workspace.invitation_create",
      params,
      { idempotencyKey },
    );
  }

  async workspaceChannelCreate(
    profile: string,
    workspace: string,
    name: string,
    idempotencyKey: string,
    options: {
      visibility?: "public" | "private";
      members?: string[];
    } = {},
  ): Promise<WorkspaceChannelCreateView> {
    const visibility = options.visibility ?? "public";
    const members = options.members ?? [];
    if (name.length === 0 || name.length > 64 || idempotencyKey.length < 16) {
      throw new ProtocolError("channel creation requires a name and caller key");
    }
    if (visibility === "private" && (members.length < 1 || members.length > 8)) {
      throw new ProtocolError("private channels require one to eight members");
    }
    if (visibility === "public" && members.length > 0) {
      throw new ProtocolError("public channels do not take a member list");
    }
    const params: Record<string, unknown> = {
      profile,
      workspace,
      name,
      visibility,
    };
    if (visibility === "private") params.members = members;
    return this.request<WorkspaceChannelCreateView>(
      "workspace.channel_create",
      params,
      { idempotencyKey },
    );
  }

  async workspaceChannelMembers(
    profile: string,
    workspace: string,
    channel: string,
  ): Promise<WorkspaceChannelMembersView> {
    return this.request<WorkspaceChannelMembersView>("workspace.channel_members", {
      profile,
      workspace,
      channel,
    });
  }

  async workspaceChannelMembersUpdate(
    profile: string,
    workspace: string,
    channel: string,
    members: string[],
    idempotencyKey: string,
  ): Promise<WorkspaceChannelMembersView> {
    if (members.length < 1 || members.length > 8 || idempotencyKey.length < 16) {
      throw new ProtocolError("channel membership requires members and a caller key");
    }
    return this.request<WorkspaceChannelMembersView>(
      "workspace.channel_members_update",
      { profile, workspace, channel, members },
      { idempotencyKey },
    );
  }

  async workspaceChannelTransferOffer(
    profile: string,
    workspace: string,
    channel: string,
    member: string,
    idempotencyKey: string,
  ): Promise<WorkspaceChannelTransferOfferView> {
    if (idempotencyKey.length < 16) {
      throw new ProtocolError("channel transfers require a caller key");
    }
    return this.request<WorkspaceChannelTransferOfferView>(
      "workspace.channel_transfer_offer",
      { profile, workspace, channel, member },
      { idempotencyKey },
    );
  }

  async workspaceChannelTransferAccept(
    profile: string,
    workspace: string,
    channel: string,
    idempotencyKey: string,
  ): Promise<WorkspaceChannelTransferAcceptView> {
    if (idempotencyKey.length < 16) {
      throw new ProtocolError("channel transfers require a caller key");
    }
    return this.request<WorkspaceChannelTransferAcceptView>(
      "workspace.channel_transfer_accept",
      { profile, workspace, channel },
      { idempotencyKey },
    );
  }

  async workspaceChannelUpdate(
    profile: string,
    workspace: string,
    channel: string,
    name: string,
    topic: string,
    idempotencyKey: string,
    posting?: "inherit" | "all_members" | "owner_and_admins",
  ): Promise<WorkspaceChannelUpdateView> {
    if (name.length === 0 || name.length > 64 || topic.length > 1024 || idempotencyKey.length < 16) {
      throw new ProtocolError("channel edits require a name, topic and caller key");
    }
    const params: Record<string, string> = { profile, workspace, channel, name, topic };
    if (posting !== undefined) params.posting = posting;
    return this.request<WorkspaceChannelUpdateView>(
      "workspace.channel_update",
      params,
      { idempotencyKey },
    );
  }

  async workspaceChannelArchive(
    profile: string,
    workspace: string,
    channel: string,
    idempotencyKey: string,
  ): Promise<WorkspaceChannelArchiveView> {
    if (idempotencyKey.length < 16) {
      throw new ProtocolError("channel archive requires a caller key");
    }
    return this.request<WorkspaceChannelArchiveView>(
      "workspace.channel_archive",
      { profile, workspace, channel },
      { idempotencyKey },
    );
  }

  async workspaceConnection(profile: string, action: string,
                            params: Record<string, unknown> = {},
                            idempotencyKey?: string): Promise<unknown> {
    return this.request("workspace.connection", { profile, action, ...params },
      idempotencyKey ? { idempotencyKey } : undefined);
  }

  async workspaceHistory(profile: string, workspace: string, action: string,
                         params: Record<string, unknown> = {},
                         idempotencyKey?: string): Promise<unknown> {
    return this.request("workspace.history", { profile, workspace, action, ...params },
      idempotencyKey ? { idempotencyKey } : undefined);
  }

  async workspaceAccessRecommendation(profile: string, workspace: string,
                                      action: string, params: Record<string, unknown> = {},
                                      idempotencyKey?: string): Promise<unknown> {
    return this.request("workspace.access_recommendation",
      { profile, workspace, action, ...params },
      idempotencyKey ? { idempotencyKey } : undefined);
  }

  async runtimeQuery(profile: string, action: string): Promise<unknown> {
    return this.request("runtime.query", { profile, action });
  }

  async runtimeMutate(profile: string, action: string, params: Record<string, unknown>,
                      idempotencyKey: string): Promise<unknown> {
    return this.request("runtime.mutate", { profile, action, ...params },
      { idempotencyKey });
  }

  async peerDecide(profile: string, peer: string, accept: boolean): Promise<unknown> {
    return this.request("peer.decide", { profile, peer, accept });
  }

  async remoteProfiles(profile: string): Promise<unknown> {
    return this.request("remote_profile.query", { profile });
  }

  async createWorkspace(profile: string, name: string, description: string,
                         idempotencyKey: string): Promise<unknown> {
    return this.request("workspace.create", { profile, name, description },
      { idempotencyKey });
  }

  async createProfile(displayName: string, idempotencyKey?: string): Promise<unknown> {
    return this.request("profile.create", { display_name: displayName }, idempotencyKey === undefined ? {} : { idempotencyKey });
  }

  async workspaceJoinPrompt(profile: string, prompt: string,
                            idempotencyKey: string): Promise<unknown> {
    return this.request("workspace.join_prompt", { profile, prompt },
      { idempotencyKey });
  }

  async pairingPreview(profile: string, document: string): Promise<unknown> {
    return this.request("peer.pairing_preview", { profile, document });
  }

  async connectionDocument(profile: string, action: string,
                           params: Record<string, unknown>): Promise<unknown> {
    return this.request("connection.document", { profile, action, ...params });
  }

  async connectionSupport(profile: string, action: string,
                          params: Record<string, unknown>): Promise<unknown> {
    return this.request("connection.support", { profile, action, ...params });
  }

  async recoveryTransfer(profile: string, action: string,
                          params: Record<string, unknown>): Promise<unknown> {
    return this.request("recovery.transfer", { profile, action, ...params });
  }

  async contactInvitation(profile: string, action: string,
                           params: Record<string, unknown>): Promise<unknown> {
    return this.request("contact.invitation", { profile, action, ...params });
  }

  async linkPreview(profile: string, provider: string, identifier: string): Promise<unknown> {
    return this.request("link.preview", { profile, provider, identifier });
  }

  async conversation(profile: string, action: string, kind: string,
                     targetId: string, extra: Record<string, unknown> = {}): Promise<unknown> {
    return this.request("conversation.mutate",
      { profile, action, kind, target_id: targetId, ...extra });
  }

  async peerUpdate(profile: string, peer: string, action: string,
                   displayName?: string): Promise<unknown> {
    return this.request("peer.update", { profile, peer, action,
      ...(displayName !== undefined ? { display_name: displayName } : {}) });
  }

  async routeUpdate(profile: string, action: string, params: Record<string, unknown>,
                    idempotencyKey: string): Promise<unknown> {
    return this.request("route.update", { profile, action, ...params },
      { idempotencyKey });
  }

  async workspaceDirectOpen(profile: string, workspace: string, member: string,
                            idempotencyKey: string): Promise<unknown> {
    return this.request("workspace.direct_open",
      { profile, workspace, member }, { idempotencyKey });
  }

  async workspaceDisplayNameDecide(profile: string, workspace: string, request: string,
                                    approve: boolean, idempotencyKey: string): Promise<unknown> {
    return this.request("workspace.display_name_decide",
      { profile, workspace, request, approve }, { idempotencyKey });
  }

  async remoteProfile(profile: string, action: string, params: Record<string, unknown>,
                      idempotencyKey: string): Promise<unknown> {
    return this.request("remote_profile.mutate", { profile, action, ...params },
      { idempotencyKey });
  }

  async workspaceDraftSet(profile: string, workspace: string, conversation: string,
                           text: string, idempotencyKey: string,
                           extra: { threadRoot?: string; mentions?: string[] } = {}): Promise<unknown> {
    return this.request("workspace.draft_set", { profile, workspace, conversation, text,
      ...(extra.threadRoot ? { thread_root: extra.threadRoot } : {}),
      ...(extra.mentions?.length ? { mention_member_ids: extra.mentions } : {}) },
    { idempotencyKey });
  }

  async groupDraftSet(profile: string, group: string, text: string): Promise<unknown> {
    return this.request("group.draft_set", { profile, group, text });
  }

  async workspaceMemberRemove(profile: string, workspace: string, member: string,
                               idempotencyKey: string): Promise<unknown> {
    return this.request("workspace.member_remove",
      { profile, workspace, member }, { idempotencyKey });
  }

  async workspaceChannelState(profile: string, workspace: string, action: string,
                              params: Record<string, unknown>, idempotencyKey: string): Promise<unknown> {
    return this.request("workspace.channel_state",
      { profile, workspace, action, ...params }, { idempotencyKey });
  }

  async workspaceChannelRecover(profile: string, workspace: string, channel: string,
                                  idempotencyKey: string): Promise<unknown> {
    return this.request("workspace.channel_recover",
      { profile, workspace, channel }, { idempotencyKey });
  }

  async workspaceSnapshot(profile: string): Promise<unknown> {
    return this.request("workspace.snapshot", { profile });
  }

  async workspaceTimelineQuery(profile: string, workspace: string, view: string,
                               params: Record<string, unknown> = {}): Promise<unknown> {
    return this.request("workspace.timeline_query",
      { profile, workspace, view, ...params });
  }

  async workspaceTimelineMutation(profile: string, workspace: string, action: string,
                                  params: Record<string, unknown>,
                                  idempotencyKey: string): Promise<unknown> {
    return this.request("workspace.timeline_mutation",
      { profile, workspace, action, ...params }, { idempotencyKey });
  }

  async workspaceInvitationRevoke(profile: string, workspace: string, invitation: string,
                                  idempotencyKey: string): Promise<unknown> {
    return this.request("workspace.invitation_revoke",
      { profile, workspace, invitation }, { idempotencyKey });
  }

  async workspaceAdmissionGrantList(profile: string, workspace: string, idempotencyKey?: string): Promise<unknown> {
    return this.request("workspace.admission_grant_list", { profile, workspace }, idempotencyKey === undefined ? {} : { idempotencyKey });
  }

  async workspaceAdmissionGrantCreate(profile: string, workspace: string, member: string,
                                      device: string, maxAdmissions: number,
                                      lifetimeDays: number, v2Ready: boolean,
                                      idempotencyKey: string): Promise<unknown> {
    return this.request("workspace.admission_grant_create", {
      profile, workspace, admin_member: member, admin_device: device,
      max_admissions: maxAdmissions, lifetime_days: lifetimeDays, v2_ready: v2Ready,
    }, { idempotencyKey });
  }

  async workspaceAdmissionGrantAccept(profile: string, workspace: string, grant: string,
                                      idempotencyKey: string): Promise<unknown> {
    return this.request("workspace.admission_grant_accept",
      { profile, workspace, grant }, { idempotencyKey });
  }

  async workspaceAdmissionGrantEnd(profile: string, workspace: string, grant: string,
                                   idempotencyKey: string): Promise<unknown> {
    return this.request("workspace.admission_grant_end",
      { profile, workspace, grant }, { idempotencyKey });
  }

  async workspaceAuthorityOffer(profile: string, workspace: string,
                                transitionKind: "ownership_transfer" | "same_owner_rotation",
                                successorMember: string, successorDevice: string,
                                outgoingRole: "admin" | "member" | null,
                                idempotencyKey: string): Promise<unknown> {
    return this.request("workspace.authority_offer", {
      profile, workspace, transition_kind: transitionKind,
      successor_member: successorMember, successor_device: successorDevice,
      outgoing_owner_role: outgoingRole,
    }, { idempotencyKey });
  }

  async workspaceAuthorityAccept(profile: string, workspace: string, transition: string,
                                 idempotencyKey: string): Promise<unknown> {
    return this.request("workspace.authority_accept",
      { profile, workspace, transition }, { idempotencyKey });
  }

  async workspaceAuthorityFinalize(profile: string, workspace: string, transition: string,
                                   idempotencyKey: string): Promise<unknown> {
    return this.request("workspace.authority_finalize",
      { profile, workspace, transition }, { idempotencyKey });
  }

  async workspaceReportAuthorityLoss(profile: string, workspace: string,
                                     idempotencyKey: string): Promise<unknown> {
    return this.request("workspace.authority_loss_report",
      { profile, workspace }, { idempotencyKey });
  }

  async workspaceClose(profile: string, workspace: string, idempotencyKey: string): Promise<unknown> {
    return this.request("workspace.close", { profile, workspace }, { idempotencyKey });
  }

  async workspaceLeave(profile: string, workspace: string, idempotencyKey: string): Promise<unknown> {
    return this.request("workspace.leave", { profile, workspace }, { idempotencyKey });
  }

  async workspaceRemoveData(profile: string, workspace: string, confirmation: string,
                            idempotencyKey: string): Promise<unknown> {
    return this.request("workspace.remove_data",
      { profile, workspace, confirmation }, { idempotencyKey });
  }

  async workspaceAdminRequestSubmit(profile: string, workspace: string,
                                     requestKind: "invitation" | "member_removal" | "role_change",
                                     targetMember: string | null,
                                     requestedRole: "admin" | "member" | null,
                                     note: string, idempotencyKey: string): Promise<unknown> {
    const params: Record<string, unknown> = { profile, workspace, request_kind: requestKind };
    if (targetMember) params.target_member = targetMember;
    if (requestedRole) params.requested_role = requestedRole;
    if (note) params.note = note;
    return this.request("workspace.admin_request_submit", params, { idempotencyKey });
  }

  async workspaceDisplayNameRequest(profile: string, workspace: string, displayName: string,
                                    idempotencyKey: string): Promise<unknown> {
    return this.request("workspace.display_name_request",
      { profile, workspace, display_name: displayName }, { idempotencyKey });
  }

  async workspaceReadHintSync(profile: string, workspace: string, enabled: boolean,
                              idempotencyKey: string): Promise<unknown> {
    return this.request("workspace.read_hint_sync",
      { profile, workspace, enabled }, { idempotencyKey });
  }

  async workspaceAdminRequest(profile: string, workspace: string, request: string,
                              action: "approve" | "decline" | "cancel" | "dismiss",
                              idempotencyKey: string): Promise<unknown> {
    const operations = {
      approve: "workspace.admin_request_approve",
      decline: "workspace.admin_request_decline",
      cancel: "workspace.admin_request_cancel",
      dismiss: "workspace.admin_request_dismiss",
    } as const;
    return this.request(operations[action],
      { profile, workspace, request }, { idempotencyKey });
  }

  async workspaceMetadata(profile: string, workspace: string, name: string,
                           description: string, idempotencyKey: string): Promise<unknown> {
    return this.request("workspace.metadata_update",
      { profile, workspace, name, description }, { idempotencyKey });
  }

  async workspaceRetention(profile: string, workspace: string, retentionDays: number | null,
                           idempotencyKey: string): Promise<unknown> {
    return this.request("workspace.retention_update",
      { profile, workspace, retention_days: retentionDays }, { idempotencyKey });
  }

  async workspaceDeviceLinkCreate(
    profile: string,
    workspace: string,
    idempotencyKey: string,
  ): Promise<WorkspaceDeviceLinkView> {
    if (idempotencyKey.length < 16) {
      throw new ProtocolError("device links require a caller key");
    }
    return this.request<WorkspaceDeviceLinkView>(
      "workspace.device_link_create",
      { profile, workspace },
      { idempotencyKey },
    );
  }

  async workspaceDeviceLinkSubmit(
    profile: string,
    document: string,
    idempotencyKey: string,
  ): Promise<WorkspaceDeviceLinkSubmitView> {
    if (document.length === 0 || idempotencyKey.length < 16) {
      throw new ProtocolError("device link submission requires material and a caller key");
    }
    return this.request<WorkspaceDeviceLinkSubmitView>(
      "workspace.device_link_submit",
      { profile, document },
      { idempotencyKey },
    );
  }

  async workspaceDeviceRemovalRequest(
    profile: string,
    workspace: string,
    device: string,
    idempotencyKey: string,
  ): Promise<unknown> {
    if (idempotencyKey.length < 16) throw new ProtocolError("device removal requires a caller key");
    return this.request("workspace.device_removal_request",
      { profile, workspace, device }, { idempotencyKey });
  }

  async workspaceDeviceRemovalDecide(
    profile: string,
    workspace: string,
    requestHandle: string,
    approve: boolean,
    idempotencyKey: string,
  ): Promise<unknown> {
    if (idempotencyKey.length < 16) throw new ProtocolError("device removal requires a caller key");
    return this.request(
      approve ? "workspace.device_removal_approve" : "workspace.device_removal_decline",
      { profile, workspace, request: requestHandle },
      { idempotencyKey },
    );
  }

  async workspaceDeviceLinks(profile: string, workspace: string): Promise<WorkspaceDeviceLinksView> {
    return this.request<WorkspaceDeviceLinksView>("workspace.device_links", { profile, workspace });
  }

  async workspaceDeviceLinkApprove(
    profile: string,
    workspace: string,
    request: string,
    idempotencyKey: string,
  ): Promise<WorkspaceDeviceLinkDecisionView> {
    return this.deviceLinkDecision("workspace.device_link_approve", profile, workspace,
      request, idempotencyKey);
  }

  async workspaceDeviceLinkDecline(
    profile: string,
    workspace: string,
    request: string,
    idempotencyKey: string,
  ): Promise<WorkspaceDeviceLinkDecisionView> {
    return this.deviceLinkDecision("workspace.device_link_decline", profile, workspace,
      request, idempotencyKey);
  }

  private async deviceLinkDecision(
    operation: "workspace.device_link_approve" | "workspace.device_link_decline",
    profile: string,
    workspace: string,
    request: string,
    idempotencyKey: string,
  ): Promise<WorkspaceDeviceLinkDecisionView> {
    if (idempotencyKey.length < 16) {
      throw new ProtocolError("device-link decisions require a caller key");
    }
    return this.request<WorkspaceDeviceLinkDecisionView>(
      operation,
      { profile, workspace, request },
      { idempotencyKey },
    );
  }

  async workspaceDeviceLinkPreview(
    profile: string,
    document: string,
  ): Promise<WorkspaceDeviceLinkPreviewView> {
    if (document.length === 0) {
      throw new ProtocolError("device link material is required");
    }
    return this.request<WorkspaceDeviceLinkPreviewView>(
      "workspace.device_link_preview",
      { profile, document },
    );
  }

  async workspaceDevices(profile: string, workspace: string): Promise<WorkspaceDevicesView> {
    return this.request<WorkspaceDevicesView>("workspace.devices", { profile, workspace });
  }

  async workspaceDeviceRemove(
    profile: string,
    workspace: string,
    device: string,
    idempotencyKey: string,
  ): Promise<WorkspaceDeviceRemoveView> {
    if (idempotencyKey.length < 16) {
      throw new ProtocolError("device removal requires a caller key");
    }
    return this.request<WorkspaceDeviceRemoveView>(
      "workspace.device_remove",
      { profile, workspace, device },
      { idempotencyKey },
    );
  }

  async workspacePolicyUpdate(
    profile: string,
    workspace: string,
    channelCreation: "all_members" | "owner_and_admins",
    posting: "all_members" | "owner_and_admins",
    invitationRequests: "owner_only" | "owner_and_admins" | "all_members_request",
    idempotencyKey: string,
  ): Promise<WorkspacePolicyView> {
    if (idempotencyKey.length < 16) {
      throw new ProtocolError("workspace policies require a caller key");
    }
    return this.request<WorkspacePolicyView>(
      "workspace.policy_update",
      {
        profile,
        workspace,
        channel_creation: channelCreation,
        posting,
        invitation_requests: invitationRequests,
      },
      { idempotencyKey },
    );
  }

  async workspaceList(profile: string): Promise<WorkspaceListView> {
    return this.request<WorkspaceListView>("workspace.query", { profile });
  }

  async workspaceJoinRequests(
    profile: string,
    workspace: string,
  ): Promise<WorkspaceRequestsView> {
    return this.request<WorkspaceRequestsView>("workspace.join_requests", {
      profile,
      workspace,
    });
  }

  async workspaceJoinApprove(
    profile: string,
    workspace: string,
    request: string,
    idempotencyKey: string,
  ): Promise<WorkspaceApproveView> {
    if (idempotencyKey.length < 16) {
      throw new ProtocolError("workspace approvals require a caller key");
    }
    return this.request<WorkspaceApproveView>(
      "workspace.join_approve",
      { profile, workspace, request },
      { idempotencyKey },
    );
  }

  async messageQuery(profile: string, message: string): Promise<SnapshotMessage> {
    return this.request<SnapshotMessage>("message.query", { profile, message });
  }

  async messageList(
    profile: string,
    cursor: string | null = null,
    limit = MAX_BATCH,
  ): Promise<MessageListView> {
    bounded(limit, MAX_BATCH, "message list");
    return this.request<MessageListView>("message.list", { profile, cursor, limit });
  }

  async connectionStart(profile: string, peer: string): Promise<ConnectionIntentView> {
    return this.request<ConnectionIntentView>("connection.start", { profile, peer });
  }

  async connectionStop(profile: string, peer: string): Promise<ConnectionIntentView> {
    return this.request<ConnectionIntentView>("connection.stop", { profile, peer });
  }

  async peerQuery(profile: string, peer: string): Promise<PeerView> {
    return this.request<PeerView>("peer.query", { profile, peer });
  }

  async workspaceMembers(profile: string, workspace: string): Promise<WorkspaceMembersView> {
    return this.request<WorkspaceMembersView>("workspace.members", { profile, workspace });
  }

  async workspaceJoinDecline(
    profile: string,
    workspace: string,
    request: string,
    idempotencyKey: string,
  ): Promise<WorkspaceDeclineView> {
    if (idempotencyKey.length < 16) {
      throw new ProtocolError("workspace declines require a caller key");
    }
    return this.request<WorkspaceDeclineView>(
      "workspace.join_decline",
      { profile, workspace, request },
      { idempotencyKey },
    );
  }

  async workspaceMemberRole(
    profile: string,
    workspace: string,
    member: string,
    role: "admin" | "member",
    idempotencyKey: string,
  ): Promise<WorkspaceMemberRoleView> {
    if (idempotencyKey.length < 16) {
      throw new ProtocolError("role changes require a caller key");
    }
    return this.request<WorkspaceMemberRoleView>(
      "workspace.member_role",
      { profile, workspace, member, role },
      { idempotencyKey },
    );
  }

  async pairingRequest(profile: string, peer: string): Promise<PairingRequestView> {
    return this.request<PairingRequestView>("peer.pairing_request", { profile, peer });
  }

  /** Ask the owning host to stop; the stream closes after this reply. */
  async stopRuntime(): Promise<StopView> {
    return this.request<StopView>("runtime.stop", {});
  }
}

function bounded(limit: number, maximum: number, what: string): void {
  if (!Number.isInteger(limit) || limit < 1 || limit > maximum) {
    throw new ProtocolError(`${what} is outside the declared bounds`);
  }
}

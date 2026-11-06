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
    const requestId = `client:${(++this.#sequence).toString(36)}`;
    const envelope: RequestEnvelope = { api_version: 1, request_id: requestId, operation, params };
    if (options.idempotencyKey !== undefined) {
      envelope.idempotency_key = options.idempotencyKey;
    }
    const line = encodeRequest(envelope);
    const run = (): Promise<unknown> =>
      this.#exchange(line, requestId, options.timeoutMs ?? this.#timeoutMs, options.signal);
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
    await this.#transport.writeLine(line);
    const response = decodeResponse(await this.#read(requestId, timeoutMs, signal));
    if (response.request_id !== requestId) {
      throw new ProtocolError("response does not correlate with the dispatched request");
    }
    if (!response.ok) {
      throw new CoreError(response.error.code, response.request_id, response.error.retry_after_ms);
    }
    return response.result;
  }

  async #read(requestId: string, timeoutMs: number, signal?: AbortSignal): Promise<string> {
    let timer: ReturnType<typeof setTimeout> | undefined;
    let detach: (() => void) | undefined;
    try {
      const deadline = new Promise<never>((_, reject) => {
        timer = setTimeout(() => reject(new TimeoutError(requestId)), timeoutMs);
      });
      const racers: Promise<string | null>[] = [this.#transport.readLine(), deadline];
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
    } finally {
      if (timer !== undefined) {
        clearTimeout(timer);
      }
      if (detach !== undefined) {
        detach();
      }
    }
  }

  async applicationCommand(command: string, payload: Record<string, unknown> = {}): Promise<unknown> {
    return this.request<unknown>("application.command", { command, payload });
  }

  async applicationSnapshot(): Promise<Record<string, unknown>> {
    return this.request<Record<string, unknown>>("application.snapshot", {});
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
                    members: string[]): Promise<unknown> {
    return this.request("group.create", { profile, title, posting_policy: postingPolicy, members });
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

  async sendGroup(profile: string, group: string, text: string): Promise<unknown> {
    return this.request("group.message_enqueue", { profile, group, text });
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

  async workspaceJoin(profile: string, document: string): Promise<WorkspaceJoinView> {
    if (document.length === 0) {
      throw new ProtocolError("workspace joins require signed material");
    }
    return this.request<WorkspaceJoinView>("workspace.join", { profile, document });
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

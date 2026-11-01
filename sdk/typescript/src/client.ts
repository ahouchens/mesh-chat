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
  WorkspacePolicyView,
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

  async revoke(profile: string, peer: string): Promise<RelationshipView> {
    return this.request<RelationshipView>("peer.revoke", { profile, peer });
  }

  async pairingCreate(profile: string): Promise<InvitationView> {
    return this.request<InvitationView>("peer.pairing_create", { profile });
  }

  async pairingAccept(profile: string, document: string): Promise<PairingView> {
    if (document.length === 0) {
      throw new ProtocolError("pairing requires signed invitation material");
    }
    return this.request<PairingView>("peer.pairing_accept", { profile, document });
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
  ): Promise<WorkspaceChannelUpdateView> {
    if (name.length === 0 || name.length > 64 || topic.length > 1024 || idempotencyKey.length < 16) {
      throw new ProtocolError("channel edits require a name, topic and caller key");
    }
    return this.request<WorkspaceChannelUpdateView>(
      "workspace.channel_update",
      { profile, workspace, channel, name, topic },
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

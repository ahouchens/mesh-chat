import { invoke } from "@tauri-apps/api/core";
import { onBackButtonPress } from "@tauri-apps/api/app";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { getCurrent, onOpenUrl } from "@tauri-apps/plugin-deep-link";
import type { AdmissionGrant, NotificationCapability, Snapshot } from "./types";
import { clearPairingResume } from "./pairing-resume";

export interface ServiceEvent {
  type: "event";
  event: "state_changed" | "service_error" | "message_status" | "workspace_changed" | "webrtc_packet" | "webrtc_control" | "webrtc_control_open" | "webrtc_native_open" | "webrtc_native_state";
  message_id?: string;
  state?: string;
  workspace_id?: string;
  conversation_id?: string | null;
  resource_kind?: string;
  generation?: number;
  overflow?: boolean;
  bridge_id?: string;
  session_id?: string;
  label?: string;
  detail?: string;
  data?: string;
}

let platformPromise: Promise<"desktop" | "android" | "ios"> | null = null;

const mobileEventSubscribers = new Set<(event: ServiceEvent) => void>();
let mobileEventTimer: number | null = null;
let mobileEventPollInFlight = false;

async function pollMobileServiceEvents(): Promise<void> {
  if (mobileEventSubscribers.size === 0 || mobileEventPollInFlight || document.visibilityState === "hidden") return;
  mobileEventPollInFlight = true;
  try {
    const events = await invoke<ServiceEvent[]>("poll_mobile_events");
    for (const event of events) {
      for (const subscriber of [...mobileEventSubscribers]) {
        if (!mobileEventSubscribers.has(subscriber)) continue;
        try {
          subscriber(event);
        } catch (reason) {
          // One consumer must not discard packets or receipts for the others.
          console.error("Service event subscriber failed", reason);
        }
      }
    }
  } catch {
    // Initialization and lock transitions can briefly leave no service.
  } finally {
    mobileEventPollInFlight = false;
  }
}

function mobileEventsVisibilityChanged(): void {
  if (document.visibilityState === "visible") void pollMobileServiceEvents();
}

function subscribeMobileServiceEvents(callback: (event: ServiceEvent) => void): UnlistenFn {
  // Each subscription has its own identity, even if callbacks are reused.
  const subscriber = (event: ServiceEvent) => callback(event);
  mobileEventSubscribers.add(subscriber);
  if (mobileEventTimer === null) {
    mobileEventTimer = window.setInterval(() => void pollMobileServiceEvents(), 750);
    document.addEventListener("visibilitychange", mobileEventsVisibilityChanged);
  }
  return () => {
    mobileEventSubscribers.delete(subscriber);
    if (mobileEventSubscribers.size !== 0) return;
    if (mobileEventTimer !== null) window.clearInterval(mobileEventTimer);
    mobileEventTimer = null;
    document.removeEventListener("visibilitychange", mobileEventsVisibilityChanged);
    // Leave the in-flight guard set until its native request finishes, so a
    // replacement subscriber cannot start a competing drain of the same queue.
  };
}

export class ServiceCommandError extends Error {
  code: string;
  details?: Record<string, string>;

  constructor(code: string, details?: Record<string, string>) {
    super(code);
    this.name = "ServiceCommandError";
    this.code = code;
    this.details = details;
  }
}

function normalizedServiceError(reason: unknown): ServiceCommandError {
  const text = String(reason);
  try {
    const parsed = JSON.parse(text) as { code?: unknown; details?: unknown };
    if (typeof parsed.code === "string") {
      const details = parsed.details && typeof parsed.details === "object"
        ? Object.fromEntries(Object.entries(parsed.details).filter(
          (entry): entry is [string, string] => typeof entry[1] === "string",
        ))
        : undefined;
      return new ServiceCommandError(parsed.code, details);
    }
  } catch {
    // Existing sidecars return a plain allowlisted error code.
  }
  return new ServiceCommandError(text);
}

export function runtimePlatform(): Promise<"desktop" | "android" | "ios"> {
  platformPromise ??= invoke<"desktop" | "android" | "ios">("runtime_platform");
  return platformPromise;
}

export function appBuildInfo(): Promise<unknown> {
  return invoke("app_build_info");
}

export function setNativeTheme(theme: "dark" | "light"): Promise<void> {
  return invoke<void>("set_native_theme", { theme });
}

export async function initializeService(displayName?: string): Promise<Snapshot> {
  return invoke<Snapshot>("initialize_service", { displayName: displayName ?? null });
}

export async function serviceCommand<T>(
  command: string,
  payload: Record<string, unknown> = {},
): Promise<T> {
  try {
    if (command === "snapshot") {
      return await coreApiRequest<T>("application.snapshot");
    }
    return await coreApiRequest<T>("application.command", { command, payload });
  } catch (reason) {
    if (!String(reason).includes("core_api_unavailable")) throw reason;
  }
  try {
    return await invoke<T>("service_command", { command, payload });
  } catch (reason) {
    throw normalizedServiceError(reason);
  }
}

export async function coreApiCapabilities(): Promise<{
  api_major: number;
  api_minor: number;
  stability: string;
  operations: string[];
  profiles: string[];
}> {
  return invoke("core_api_capabilities");
}

export async function coreApiProfile(): Promise<{
  profile: string;
  display_name: string;
  destination: string;
  connections: string[];
  peers: string[];
}> {
  return invoke("core_api_profile");
}

export async function coreApiSendMessage(
  destination: string,
  text: string,
  idempotencyKey: string,
): Promise<unknown> {
  return invoke("core_api_send_message", {
    destination,
    text,
    idempotencyKey,
  });
}

export async function coreApiRequest<T>(
  operation: string,
  params: Record<string, unknown> = {},
  idempotencyKey?: string,
): Promise<T> {
  return invoke("core_api_request", { operation, params, idempotencyKey: idempotencyKey ?? null });
}

export async function coreApiPeerForDestination(destination: string): Promise<{
  profile: string;
  peer: string;
  destination: string;
}> {
  return invoke("core_api_peer_for_destination", { destination });
}

export async function coreApiCreateInvitation(
  options: Record<string, unknown> = {},
): Promise<{
  profile: string;
  file: string;
  link: string;
  text: string;
  expires_at: number;
  host_session_id?: string;
}> {
  const profile = await coreApiProfile();
  return coreApiRequest("peer.pairing_create", { ...options, profile: profile.profile });
}

export async function coreApiPreviewInvitation(
  document: string,
): Promise<Record<string, unknown>> {
  const profile = await coreApiProfile();
  return await coreApiRequest("peer.pairing_preview",
    { profile: profile.profile, document }) as Record<string, unknown>;
}

export async function coreApiAcceptInvitation(
  document: string,
  i2pConsent = false,
): Promise<{ profile: string; peer: string; trust: string }> {
  const profile = await coreApiProfile();
  return coreApiRequest("peer.pairing_accept", {
    profile: profile.profile,
    document,
    i2p_consent: i2pConsent,
  });
}

export async function coreApiDraftSet(destination: string, text: string): Promise<unknown> {
  return invoke("core_api_draft_set", { destination, text });
}

export async function coreApiDraftGet(destination: string): Promise<unknown> {
  return invoke("core_api_draft_get", { destination });
}

export async function coreApiCallSettings(): Promise<Record<string, unknown>> {
  const profile = await coreApiProfile();
  const result = await coreApiRequest("call.settings_query", { profile: profile.profile }) as {
    settings?: Record<string, unknown>;
  };
  return result.settings ?? {};
}

export async function coreApiUpdateCallSettings(
  settings: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const profile = await coreApiProfile();
  const result = await coreApiRequest("call.settings_update", {
    profile: profile.profile,
    settings,
  }) as { settings?: Record<string, unknown> };
  return result.settings ?? {};
}

export async function coreApiCallControl(
  action: string,
  params: Record<string, unknown>,
  idempotencyKey: string,
): Promise<Record<string, unknown>> {
  const profile = await coreApiProfile();
  return coreApiRequest("call.control",
    { profile: profile.profile, action, ...params }, idempotencyKey) as Promise<Record<string, unknown>>;
}

export async function coreApiCallMedia(call: string): Promise<Record<string, unknown>> {
  const profile = await coreApiProfile();
  const result = await coreApiRequest("call.media_query", {
    profile: profile.profile,
    call,
  }) as { media?: Record<string, unknown> };
  return result.media ?? {};
}

export async function coreApiCallIceServers(): Promise<Record<string, unknown>> {
  const profile = await coreApiProfile();
  const result = await coreApiRequest("call.ice_servers", { profile: profile.profile }) as {
    ice?: Record<string, unknown>;
  };
  return result.ice ?? {};
}

export async function loadCallIceServers(): Promise<Record<string, unknown>> {
  return await coreApiCallIceServers();
}

export async function loadCallSettings(): Promise<Record<string, unknown>> {
  return await coreApiCallSettings();
}

export async function saveCallSettings(
  settings: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  return await coreApiUpdateCallSettings(settings);
}

export async function coreApiNetworkSettings(): Promise<Record<string, unknown>> {
  const profile = await coreApiProfile();
  const result = await coreApiRequest("settings.query", { profile: profile.profile }) as {
    settings?: Record<string, unknown>;
  };
  return result.settings ?? {};
}

export async function coreApiUpdateNetworkSettings(
  settings: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const profile = await coreApiProfile();
  const result = await coreApiRequest("settings.update", {
    profile: profile.profile,
    settings,
  }) as { settings?: Record<string, unknown> };
  return result.settings ?? {};
}

export async function loadNetworkSettings(): Promise<Record<string, unknown>> {
  try {
    return await coreApiNetworkSettings();
  } catch (reason) {
    if (!String(reason).includes("core_api_unavailable")) throw reason;
    const snapshot = await serviceCommand<{ settings?: Record<string, unknown> }>("snapshot");
    return snapshot.settings ?? {};
  }
}

export async function saveNetworkSettings(
  settings: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  return await coreApiUpdateNetworkSettings(settings);
}

export async function coreApiCreateGroup(
  title: string,
  postingPolicy: "members" | "owner_admins",
  memberDestinations: string[],
): Promise<{ group: string; name: string; posting_policy: string }> {
  const profile = await coreApiProfile();
  const members: string[] = [];
  for (const destination of memberDestinations) {
    const target = await coreApiPeerForDestination(destination);
    members.push(target.peer);
  }
  return coreApiRequest("group.create", {
    profile: profile.profile,
    title,
    posting_policy: postingPolicy,
    members,
  });
}

export async function coreApiSendGroupMessage(group: string, text: string): Promise<unknown> {
  const profile = await coreApiProfile();
  return coreApiRequest("group.message_enqueue", {
    profile: profile.profile,
    group,
    text,
  });
}

export async function coreApiJoinWorkspace(
  document: string, idempotencyKey: string, i2pConsent = false,
): Promise<unknown> {
  const profile = await coreApiProfile();
  return coreApiRequest("workspace.join",
    { profile: profile.profile, document,
      ...(i2pConsent ? { i2p_consent: true } : {}) }, idempotencyKey);
}

export async function coreApiPreviewWorkspaceInvitation(
  document: string,
): Promise<unknown> {
  const profile = await coreApiProfile();
  return coreApiRequest("workspace.invitation_preview",
    { profile: profile.profile, document });
}

export async function coreApiCreateWorkspaceInvitation(
  workspace: string, connection: Record<string, unknown>, idempotencyKey: string,
): Promise<unknown> {
  const profile = await coreApiProfile();
  return coreApiRequest("workspace.invitation_create",
    { profile: profile.profile, workspace, ...connection }, idempotencyKey);
}

export async function coreApiWorkspaceJoinDecision(
  workspace: string,
  request: string,
  accept: boolean,
  idempotencyKey: string,
): Promise<unknown> {
  const profile = await coreApiProfile();
  return coreApiRequest(
    accept ? "workspace.join_approve" : "workspace.join_decline",
    { profile: profile.profile, workspace, request },
    idempotencyKey,
  );
}

export async function coreApiCreateWorkspaceChannel(
  workspace: string,
  name: string,
  topic: string,
  visibility: "public" | "private",
  members: string[],
  idempotencyKey: string,
): Promise<{ channel: string; name: string }> {
  const profile = await coreApiProfile();
  const params: Record<string, unknown> = {
    profile: profile.profile,
    workspace,
    name,
    visibility,
  };
  if (visibility === "private" && members.length) params.members = members;
  const created = await coreApiRequest<{ channel: string; name: string }>(
    "workspace.channel_create", params, idempotencyKey);
  if (topic) {
    await coreApiRequest(
      "workspace.channel_update",
      { profile: profile.profile, workspace, channel: created.channel, name, topic },
      idempotencyKey + ":topic",
    );
  }
  return created;
}

export async function coreApiSubmitDeviceLink(
  document: string,
  idempotencyKey: string,
): Promise<NonNullable<Snapshot["workspaces"]>[number]> {
  const profile = await coreApiProfile();
  const submitted = await coreApiRequest<{ workspace: string; name: string }>(
    "workspace.device_link_submit",
    { profile: profile.profile, document },
    idempotencyKey,
  );
  const snapshot = await serviceCommand<Snapshot>("snapshot");
  const workspace = (snapshot.workspaces ?? []).find((item) => item.name === submitted.name);
  if (!workspace) throw new Error("workspace_not_found");
  return workspace;
}

export async function coreApiCreateWorkspaceDeviceLink(
  workspace: string,
  idempotencyKey: string,
): Promise<{ id: string; workspace_id: string; link: string; text: string; value: string; expires_at: number }> {
  const profile = await coreApiProfile();
  const created = await coreApiRequest<{ document: string; link: string; expires_at: number }>(
    "workspace.device_link_create",
    { profile: profile.profile, workspace },
    idempotencyKey,
  );
  return {
    id: created.link,
    workspace_id: workspace,
    link: created.link,
    text: created.document,
    value: created.document,
    expires_at: created.expires_at,
  };
}

export async function coreApiWorkspaceConnection(
  workspace: string | null,
  action: string,
  params: Record<string, unknown>,
  idempotencyKey?: string,
): Promise<Record<string, unknown>> {
  const profile = await coreApiProfile();
  const payload: Record<string, unknown> = { profile: profile.profile, action, ...params };
  if (workspace) payload.workspace = workspace;
  const result = await coreApiRequest("workspace.connection", payload,
    idempotencyKey) as { result?: Record<string, unknown> };
  return result.result ?? {};
}

export async function coreApiWorkspaceHistory(
  workspace: string,
  action: "status" | "prune" | "revisions" | "tombstones" | "hide_message" | "hide_direct",
  params: Record<string, unknown>,
  idempotencyKey?: string,
): Promise<Record<string, unknown>> {
  const profile = await coreApiProfile();
  const result = await coreApiRequest("workspace.history",
    { profile: profile.profile, workspace, action, ...params },
    idempotencyKey) as { result?: Record<string, unknown> };
  return result.result ?? {};
}

export async function coreApiWorkspaceAccessRecommendation(
  workspace: string,
  action: "list" | "create" | "send" | "preview" | "preview_by_id" | "apply" | "apply_by_id",
  params: Record<string, unknown>,
  idempotencyKey?: string,
): Promise<Record<string, unknown>> {
  const profile = await coreApiProfile();
  const result = await coreApiRequest("workspace.access_recommendation",
    { profile: profile.profile, workspace, action, ...params }, idempotencyKey) as { result?: Record<string, unknown> };
  return result.result ?? {};
}

export async function coreApiRuntimeQuery(
  action: "background" | "notifications",
): Promise<Record<string, unknown>> {
  const profile = await coreApiProfile();
  const result = await coreApiRequest("runtime.query",
    { profile: profile.profile, action }) as { result?: Record<string, unknown> };
  return result.result ?? {};
}

export async function coreApiRuntimeMutate(
  action: "background_set" | "notification_previews" | "notification_open",
  params: Record<string, unknown>,
  idempotencyKey: string,
): Promise<Record<string, unknown>> {
  const profile = await coreApiProfile();
  const result = await coreApiRequest("runtime.mutate",
    { profile: profile.profile, action, ...params }, idempotencyKey) as { result?: Record<string, unknown> };
  return result.result ?? {};
}

export async function coreApiRemoveWorkspaceMember(
  workspace: string, member: string, idempotencyKey: string,
): Promise<unknown> {
  const profile = await coreApiProfile();
  return coreApiRequest("workspace.member_remove",
    { profile: profile.profile, workspace, member }, idempotencyKey);
}

export async function coreApiWorkspaceChannelState(
  workspace: string, action: "subscribe" | "mute" | "leave" | "sync",
  params: Record<string, unknown>, idempotencyKey: string,
): Promise<unknown> {
  const profile = await coreApiProfile();
  return coreApiRequest("workspace.channel_state",
    { profile: profile.profile, workspace, action, ...params }, idempotencyKey);
}

export async function coreApiRecoverWorkspaceChannel(
  workspace: string, channel: string, idempotencyKey: string,
): Promise<unknown> {
  const profile = await coreApiProfile();
  return coreApiRequest("workspace.channel_recover",
    { profile: profile.profile, workspace, channel }, idempotencyKey);
}

export async function coreApiWorkspaceSnapshot(): Promise<Record<string, unknown>> {
  const profile = await coreApiProfile();
  return coreApiRequest("workspace.snapshot", { profile: profile.profile });
}

export async function coreApiTimelineQuery(
  workspace: string, view: "threads" | "thread_messages" | "mentions" | "search" | "channel_messages" | "direct_messages",
  params: Record<string, unknown> = {},
): Promise<Record<string, unknown>> {
  const profile = await coreApiProfile();
  const result = await coreApiRequest("workspace.timeline_query",
    { profile: profile.profile, workspace, view, ...params }) as { result?: Record<string, unknown> };
  return result.result ?? {};
}

export async function coreApiTimelineMutation(
  workspace: string,
  action: "thread_reply" | "thread_read" | "mentions_read" | "notification_preference" | "workspace_read" | "direct_read" | "channel_message" | "direct_message" | "message_edit" | "message_delete" | "reaction_set",
  params: Record<string, unknown>,
  idempotencyKey: string,
): Promise<Record<string, unknown>> {
  const profile = await coreApiProfile();
  const result = await coreApiRequest("workspace.timeline_mutation",
    { profile: profile.profile, workspace, action, ...params }, idempotencyKey) as { result?: Record<string, unknown> };
  return result.result ?? {};
}

export async function coreApiWorkspaceInvitationRevoke(
  workspace: string, invitation: string, idempotencyKey: string,
): Promise<unknown> {
  const profile = await coreApiProfile();
  return coreApiRequest("workspace.invitation_revoke",
    { profile: profile.profile, workspace, invitation }, idempotencyKey);
}

export async function coreApiAdmissionGrantList(
  workspace: string,
): Promise<{ grants: AdmissionGrant[] }> {
  const profile = await coreApiProfile();
  return coreApiRequest("workspace.admission_grant_list",
    { profile: profile.profile, workspace }) as Promise<{ grants: AdmissionGrant[] }>;
}

export async function coreApiAdmissionGrantCreate(
  workspace: string, member: string, device: string, v2Ready: boolean,
  idempotencyKey: string,
): Promise<unknown> {
  const profile = await coreApiProfile();
  return coreApiRequest("workspace.admission_grant_create", {
    profile: profile.profile, workspace, admin_member: member, admin_device: device,
    max_admissions: 5, lifetime_days: 7, v2_ready: v2Ready,
  }, idempotencyKey);
}

export async function coreApiAdmissionGrantAccept(
  workspace: string, grant: string, idempotencyKey: string,
): Promise<unknown> {
  const profile = await coreApiProfile();
  return coreApiRequest("workspace.admission_grant_accept",
    { profile: profile.profile, workspace, grant }, idempotencyKey);
}

export async function coreApiAdmissionGrantEnd(
  workspace: string, grant: string, idempotencyKey: string,
): Promise<unknown> {
  const profile = await coreApiProfile();
  return coreApiRequest("workspace.admission_grant_end",
    { profile: profile.profile, workspace, grant }, idempotencyKey);
}

export async function coreApiWorkspaceAdminSubmit(
  workspace: string,
  requestKind: "invitation" | "member_removal" | "role_change",
  targetMember: string | null,
  requestedRole: "admin" | "member" | null,
  note: string,
  idempotencyKey: string,
): Promise<unknown> {
  const profile = await coreApiProfile();
  const params: Record<string, unknown> = {
    profile: profile.profile, workspace, request_kind: requestKind,
  };
  if (targetMember) params.target_member = targetMember;
  if (requestedRole) params.requested_role = requestedRole;
  if (note) params.note = note;
  return coreApiRequest("workspace.admin_request_submit", params, idempotencyKey);
}

export async function coreApiWorkspaceDisplayNameRequest(
  workspace: string, displayName: string, idempotencyKey: string,
): Promise<unknown> {
  const profile = await coreApiProfile();
  return coreApiRequest("workspace.display_name_request",
    { profile: profile.profile, workspace, display_name: displayName }, idempotencyKey);
}

export async function coreApiWorkspaceReadHintSync(
  workspace: string, enabled: boolean, idempotencyKey: string,
): Promise<unknown> {
  const profile = await coreApiProfile();
  return coreApiRequest("workspace.read_hint_sync",
    { profile: profile.profile, workspace, enabled }, idempotencyKey);
}

export async function coreApiWorkspaceAuthorityOffer(
  workspace: string,
  transitionKind: "ownership_transfer" | "same_owner_rotation",
  successorMember: string,
  successorDevice: string,
  outgoingRole: "admin" | "member" | null,
  idempotencyKey: string,
): Promise<unknown> {
  const profile = await coreApiProfile();
  return coreApiRequest("workspace.authority_offer", {
    profile: profile.profile,
    workspace,
    transition_kind: transitionKind,
    successor_member: successorMember,
    successor_device: successorDevice,
    outgoing_owner_role: outgoingRole,
  }, idempotencyKey);
}

export async function coreApiWorkspaceAuthority(
  workspace: string,
  transition: string,
  action: "accept" | "finalize",
  idempotencyKey: string,
): Promise<unknown> {
  const profile = await coreApiProfile();
  return coreApiRequest(
    action === "accept" ? "workspace.authority_accept" : "workspace.authority_finalize",
    { profile: profile.profile, workspace, transition },
    idempotencyKey,
  );
}

export async function coreApiReportAuthorityLoss(
  workspace: string,
  idempotencyKey: string,
): Promise<unknown> {
  const profile = await coreApiProfile();
  return coreApiRequest(
    "workspace.authority_loss_report",
    { profile: profile.profile, workspace },
    idempotencyKey,
  );
}

export async function coreApiWorkspaceLifecycle(
  workspace: string,
  action: "close" | "leave" | "remove",
  idempotencyKey: string,
  confirmation?: string,
): Promise<unknown> {
  const profile = await coreApiProfile();
  const operation = action === "close" ? "workspace.close"
    : action === "leave" ? "workspace.leave" : "workspace.remove_data";
  const params: Record<string, unknown> = { profile: profile.profile, workspace };
  if (action === "remove") params.confirmation = confirmation ?? "";
  return coreApiRequest(operation, params, idempotencyKey);
}

export async function coreApiWorkspaceAdminRequest(
  workspace: string,
  request: string,
  action: "approve" | "decline" | "cancel" | "dismiss",
  idempotencyKey: string,
): Promise<unknown> {
  const profile = await coreApiProfile();
  return coreApiRequest(
    "workspace.admin_request_" + action,
    { profile: profile.profile, workspace, request },
    idempotencyKey,
  );
}

export async function coreApiWorkspaceMetadata(
  workspace: string,
  name: string,
  description: string,
  idempotencyKey: string,
): Promise<unknown> {
  const profile = await coreApiProfile();
  return coreApiRequest(
    "workspace.metadata_update",
    { profile: profile.profile, workspace, name, description },
    idempotencyKey,
  );
}

export async function coreApiWorkspaceRetention(
  workspace: string,
  retentionDays: number | null,
  idempotencyKey: string,
): Promise<unknown> {
  const profile = await coreApiProfile();
  return coreApiRequest(
    "workspace.retention_update",
    { profile: profile.profile, workspace, retention_days: retentionDays },
    idempotencyKey,
  );
}

export async function coreApiRequestDeviceRemoval(
  workspace: string,
  device: string,
  idempotencyKey: string,
): Promise<unknown> {
  const profile = await coreApiProfile();
  return coreApiRequest(
    "workspace.device_removal_request",
    { profile: profile.profile, workspace, device },
    idempotencyKey,
  );
}

export async function coreApiDecideDeviceRemoval(
  workspace: string,
  request: string,
  approve: boolean,
  idempotencyKey: string,
): Promise<unknown> {
  const profile = await coreApiProfile();
  return coreApiRequest(
    approve ? "workspace.device_removal_approve" : "workspace.device_removal_decline",
    { profile: profile.profile, workspace, request },
    idempotencyKey,
  );
}

export async function coreApiWorkspaceDeviceLinkDecision(
  workspace: string,
  request: string,
  approve: boolean,
  idempotencyKey: string,
): Promise<unknown> {
  const profile = await coreApiProfile();
  return coreApiRequest(
    approve ? "workspace.device_link_approve" : "workspace.device_link_decline",
    { profile: profile.profile, workspace, request },
    idempotencyKey,
  );
}

export async function coreApiUpdateChannelMembers(
  workspace: string,
  channel: string,
  members: string[],
  idempotencyKey: string,
): Promise<unknown> {
  const profile = await coreApiProfile();
  return coreApiRequest(
    "workspace.channel_members_update",
    { profile: profile.profile, workspace, channel, members },
    idempotencyKey,
  );
}

export async function coreApiOfferChannelTransfer(
  workspace: string,
  channel: string,
  member: string,
  idempotencyKey: string,
): Promise<unknown> {
  const profile = await coreApiProfile();
  return coreApiRequest(
    "workspace.channel_transfer_offer",
    { profile: profile.profile, workspace, channel, member },
    idempotencyKey,
  );
}

export async function coreApiAcceptChannelTransfer(
  workspace: string,
  channel: string,
  idempotencyKey: string,
): Promise<unknown> {
  const profile = await coreApiProfile();
  return coreApiRequest(
    "workspace.channel_transfer_accept",
    { profile: profile.profile, workspace, channel },
    idempotencyKey,
  );
}

export async function coreApiUpdateWorkspaceChannel(
  workspace: string,
  channel: string,
  name: string,
  topic: string,
  archived: boolean,
  idempotencyKey: string,
): Promise<unknown> {
  const profile = await coreApiProfile();
  if (archived) {
    return coreApiRequest(
      "workspace.channel_archive",
      { profile: profile.profile, workspace, channel },
      idempotencyKey,
    );
  }
  return coreApiRequest(
    "workspace.channel_update",
    { profile: profile.profile, workspace, channel, name, topic },
    idempotencyKey,
  );
}

export async function coreApiWorkspacePolicy(
  workspace: string,
  channelCreation: string,
  posting: string,
  invitationRequests: string,
  idempotencyKey: string,
): Promise<unknown> {
  const profile = await coreApiProfile();
  return coreApiRequest(
    "workspace.policy_update",
    {
      profile: profile.profile,
      workspace,
      channel_creation: channelCreation,
      posting,
      invitation_requests: invitationRequests,
    },
    idempotencyKey,
  );
}

export async function coreApiWorkspaceMemberRole(
  workspace: string,
  member: string,
  role: "member" | "admin",
  idempotencyKey: string,
): Promise<unknown> {
  const profile = await coreApiProfile();
  return coreApiRequest(
    "workspace.member_role",
    { profile: profile.profile, workspace, member, role },
    idempotencyKey,
  );
}

export async function coreApiConnectionDocument(
  action: "preview_direct" | "create_reply" | "preview_reply",
  params: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const profile = await coreApiProfile();
  return await coreApiRequest("connection.document",
    { profile: profile.profile, action, ...params }) as Record<string, unknown>;
}

export async function coreApiConnectionSupport(
  action: "help" | "diagnostics" | "clear", params: Record<string, unknown> = {},
): Promise<Record<string, unknown>> {
  const profile = await coreApiProfile();
  return await coreApiRequest("connection.support",
    { profile: profile.profile, action, ...params }) as Record<string, unknown>;
}

export async function coreApiRecoveryTransfer(
  action: "export" | "import", params: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const profile = await coreApiProfile();
  return await coreApiRequest("recovery.transfer",
    { profile: profile.profile, action, ...params }) as Record<string, unknown>;
}

export async function coreApiContactInvitation(
  action: "receive" | "decide", params: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const profile = await coreApiProfile();
  const result = await coreApiRequest("contact.invitation",
    { profile: profile.profile, action, ...params }) as {
      contact_invitation?: Record<string, unknown> };
  return result.contact_invitation ?? {};
}

export async function coreApiLinkPreview(
  provider: string, identifier: string,
): Promise<Record<string, unknown>> {
  const profile = await coreApiProfile();
  return await coreApiRequest("link.preview",
    { profile: profile.profile, provider, identifier }) as Record<string, unknown>;
}

export async function coreApiDecidePeerRequest(
  destination: string, accept: boolean,
): Promise<unknown> {
  const target = await coreApiPeerForDestination(destination);
  return coreApiRequest("peer.decide",
    { profile: target.profile, peer: target.peer, accept });
}

export async function coreApiConversation(
  action: "delete" | "restore", kind: "direct" | "group", targetId: string,
): Promise<Record<string, unknown>> {
  const profile = await coreApiProfile();
  const result = await coreApiRequest("conversation.mutate",
    { profile: profile.profile, action, kind, target_id: targetId }) as {
      conversation?: Record<string, unknown> };
  return result.conversation ?? {};
}

export async function coreApiUpdatePeer(
  destination: string, action: "rename" | "verify" | "unverify",
  displayName?: string,
): Promise<unknown> {
  const target = await coreApiPeerForDestination(destination);
  return coreApiRequest("peer.update", {
    profile: target.profile, peer: target.peer, action,
    ...(displayName !== undefined ? { display_name: displayName } : {}),
  });
}

export async function coreApiRouteUpdate(
  action: "preview" | "apply" | "create", params: Record<string, unknown>,
  idempotencyKey: string = crypto.randomUUID(),
): Promise<Record<string, unknown>> {
  const profile = await coreApiProfile();
  const result = await coreApiRequest("route.update",
    { profile: profile.profile, action, ...params }, idempotencyKey) as { route?: Record<string, unknown> };
  return result.route ?? {};
}

export async function coreApiOpenWorkspaceDirect(
  workspace: string, member: string, idempotencyKey: string,
): Promise<unknown> {
  const profile = await coreApiProfile();
  return coreApiRequest("workspace.direct_open",
    { profile: profile.profile, workspace, member }, idempotencyKey);
}

export async function coreApiWorkspaceDisplayNameDecision(
  workspace: string, request: string, approve: boolean, idempotencyKey: string,
): Promise<unknown> {
  const profile = await coreApiProfile();
  return coreApiRequest("workspace.display_name_decide",
    { profile: profile.profile, workspace, request, approve }, idempotencyKey);
}

export async function coreApiRemoteProfiles(): Promise<Record<string, unknown>> {
  const profile = await coreApiProfile();
  return await coreApiRequest("remote_profile.query",
    { profile: profile.profile }) as Record<string, unknown>;
}

export async function coreApiRemoteProfile(
  action: "create" | "test" | "retry" | "remove" | "remove_propagation" | "approve_propagation",
  params: Record<string, unknown>, idempotencyKey: string = crypto.randomUUID(),
): Promise<unknown> {
  const profile = await coreApiProfile();
  return coreApiRequest("remote_profile.mutate",
    { profile: profile.profile, action, ...params }, idempotencyKey);
}

export async function coreApiWorkspaceDraftSet(
  workspace: string, conversation: string, text: string, idempotencyKey: string,
  extra: { threadRoot?: string; mentions?: string[] } = {},
): Promise<unknown> {
  const profile = await coreApiProfile();
  return coreApiRequest("workspace.draft_set", {
    profile: profile.profile, workspace, conversation, text,
    ...(extra.threadRoot ? { thread_root: extra.threadRoot } : {}),
    ...(extra.mentions?.length ? { mention_member_ids: extra.mentions } : {}),
  }, idempotencyKey);
}

export async function coreApiGroupDraftSet(group: string, text: string): Promise<unknown> {
  const profile = await coreApiProfile();
  return coreApiRequest("group.draft_set", { profile: profile.profile, group, text });
}

export async function coreApiGroupInvitation(
  invitation: string,
  accept: boolean,
): Promise<unknown> {
  const profile = await coreApiProfile();
  return coreApiRequest(accept ? "group.invitation_accept" : "group.invitation_decline", {
    profile: profile.profile,
    invitation,
  });
}

export async function coreApiRetryGroupInvitation(
  group: string,
  destination: string,
): Promise<unknown> {
  const profile = await coreApiProfile();
  const member = await coreApiPeerForDestination(destination);
  return coreApiRequest("group.invitation_retry", {
    profile: profile.profile,
    group,
    member: member.peer,
  });
}

export async function coreApiLeaveGroup(group: string): Promise<unknown> {
  const profile = await coreApiProfile();
  return coreApiRequest("group.leave", { profile: profile.profile, group });
}

export async function coreApiCloseGroup(group: string): Promise<unknown> {
  const profile = await coreApiProfile();
  return coreApiRequest("group.close", { profile: profile.profile, group });
}

export async function coreApiRemoveGroupMember(
  group: string,
  destination: string,
): Promise<unknown> {
  const profile = await coreApiProfile();
  const member = await coreApiPeerForDestination(destination);
  return coreApiRequest("group.member_remove", {
    profile: profile.profile,
    group,
    member: member.peer,
  });
}

export async function lockService(): Promise<void> {
  clearPairingResume();
  return invoke<void>("lock_service");
}

export function desktopServiceHealth(): Promise<{
  running: boolean | null;
  last_unexpected_exit: { reason: string; exit_code: number | null; signal: number | null; recorded_at: number | null } | null;
}> {
  return invoke("desktop_service_health");
}

/**
 * Start or stop the Android foreground availability service.
 *
 * This is deliberately separate from the Python opt-in command: Python owns
 * the durable preference, Android owns whether the service is actually alive.
 */
export function setNativeBackgroundAvailability(
  enabled: boolean,
): Promise<{ enabled: boolean }> {
  return invoke<{ enabled: boolean }>("set_background_availability", { enabled });
}

export function notificationCapability(): Promise<NotificationCapability> {
  return invoke<NotificationCapability>("notification_capability");
}

export function requestNotificationPermission(): Promise<NotificationCapability> {
  return invoke<NotificationCapability>("request_notification_permission");
}

export function requestMediaPermission(media: "audio" | "video"): Promise<{ audio: boolean; camera: boolean }> {
  return invoke<{ audio: boolean; camera: boolean }>("request_media_permission", { media });
}

export function beginCallAudio(media: "audio" | "video"): Promise<{ granted: boolean }> {
  return invoke<{ granted: boolean }>("begin_call_audio", { media });
}

export function endCallAudio(): Promise<{ active: boolean }> {
  return invoke<{ active: boolean }>("end_call_audio");
}

export function openNotificationSettings(): Promise<NotificationCapability> {
  return invoke<NotificationCapability>("open_notification_settings");
}

export function openBatterySettings(): Promise<{ opened: boolean }> {
  return invoke<{ opened: boolean }>("open_battery_settings");
}

/**
 * Open Android's document picker and return a native-validated Mesh Chat
 * invitation. Cancellation resolves to null; validation and provider failures
 * reject with a stable invitation_file_* error code.
 */
export async function pickInvitationFile(): Promise<string | null> {
  try {
    return await invoke<string | null>("pick_invitation_file");
  } catch (reason) {
    throw normalizedServiceError(reason);
  }
}

/**
 * Temporarily take ownership of Android's system back action.
 *
 * Callers should only keep this listener mounted while they have an in-app
 * layer to dismiss. Once it is removed, Tauri resumes the platform default so
 * Back at the conversation list can leave the app normally.
 */
export async function onMobileBackButton(callback: () => void): Promise<UnlistenFn> {
  if (await runtimePlatform() !== "android") return () => undefined;
  const listener = await onBackButtonPress(callback);
  return () => { void listener.unregister(); };
}

export function onServiceEvent(callback: (event: ServiceEvent) => void): Promise<UnlistenFn> {
  return Promise.all([
    listen<ServiceEvent>("mesh-chat://service-event", (event) => callback(event.payload)),
    runtimePlatform(),
  ]).then(([unlisten, platform]) => {
    if (platform === "desktop") return unlisten;
    const stopMobileEvents = subscribeMobileServiceEvents(callback);
    let active = true;
    return () => {
      if (!active) return;
      active = false;
      stopMobileEvents();
      unlisten();
    };
  });
}

export function onInvitation(callback: (invitation: string) => void): Promise<UnlistenFn> {
  const delivered = new Set<string>();
  const deliver = (invitation: string | null | undefined) => {
    if (!invitation || delivered.has(invitation)) return;
    callback(invitation);
    delivered.add(invitation);
  };
  const accept = (urls: string[] | null) => {
    const invitation = urls?.find((value) =>
      value.startsWith("meshchat://invite/") || value.startsWith("meshchat://workspace/") || value.startsWith("meshchat://workspace-device/") || value.startsWith("meshchat://connect/") || value.startsWith("meshchat://route/"),
    );
    deliver(invitation);
  };
  return runtimePlatform().then(async (platform) => {
    if (platform === "android") {
      let active = true;
      let polling = false;
      const poll = async () => {
        if (!active || polling || document.visibilityState === "hidden") return;
        polling = true;
        try { deliver(await invoke<string | null>("take_pending_invitation")); }
        catch { /* A delayed native runtime or lock transition is retried. */ }
        finally { polling = false; }
      };
      await poll();
      const timer = window.setInterval(() => void poll(), 750);
      const visible = () => { if (document.visibilityState === "visible") void poll(); };
      const focused = () => void poll();
      document.addEventListener("visibilitychange", visible);
      window.addEventListener("focus", focused);
      return () => {
        active = false;
        window.clearInterval(timer);
        document.removeEventListener("visibilitychange", visible);
        window.removeEventListener("focus", focused);
      };
    }

    const [unlistenFile, unlistenLink] = await Promise.all([
      listen<string>("mesh-chat://invitation", (event) => deliver(event.payload)),
      onOpenUrl(accept),
      getCurrent().then(accept),
      invoke<string | null>("take_pending_invitation").then(deliver),
    ]);
    return () => { unlistenFile(); unlistenLink(); };
  });
}

export function onNotificationOpen(callback: (notificationId: string) => void): Promise<UnlistenFn> {
  const accept = (urls: string[] | null) => {
    for (const value of urls ?? []) {
      const match = /^meshchat:\/\/notification\/([0-9a-f]{64})$/.exec(value);
      if (match) callback(match[1]);
    }
  };
  return Promise.all([
    onOpenUrl(accept),
    getCurrent().then(accept),
  ]).then(([unlisten]) => () => unlisten());
}

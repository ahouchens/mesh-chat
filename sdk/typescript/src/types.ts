/** Selected public shapes; every field is explicitly chosen by the facade. */

export type ComposerSendOutcome =
  | { revision: string; status: "accepted"; acceptance: Acceptance; text: string; draft_disposition: "cleared" | "superseded" }
  | { revision: string; status: "expired"; accepted_at: number; idempotency_expires_at: number };
export interface Composer {
  profile: string; peer: string; revision: string | null; text: string; update_key: string;
  last_send: ComposerSendOutcome | null;
  send_lookup: Exclude<ComposerSendOutcome, { status: "expired" }> | { revision: string; status: "not_accepted" } | null;
}
export interface ComposerUpdate { applied_revision: string; changed: boolean; composer: Composer }
export interface DraftAcceptance extends Acceptance {
  peer: string; draft_revision: string; draft_disposition: "cleared" | "superseded"; composer: Composer;
}

export interface Capabilities {
  api_major: number;
  api_minor: number;
  stability: string;
  operations: string[];
  profiles: string[];
  limits: Record<string, number>;
}

export interface ProfileCatalog {
  profiles: { profile: string; display_name: string; selected: boolean; state: "locked" | "unlocked" | "retiring" }[];
  selected_profile: string | null;
  revision: number;
}

export interface ProfileView {
  profile: string;
  display_name: string;
  destination: string;
  connections: string[];
  peers?: string[];
}

export interface ConnectionView {
  profile: string;
  connection: string;
  observation: Record<string, unknown>;
}

export interface SnapshotMessage {
  profile: string;
  message: string;
  recipient: string;
  kind: "text";
  text: string;
  state: string;
  created_at: number;
}

export interface ReceivedMessage {
  profile: string;
  message: string;
  peer: string;
  kind: "text";
  text: string;
  state: string;
  created_at: number;
}

export interface ReceivedPage {
  profile: string;
  messages: ReceivedMessage[];
  next_cursor: string | null;
  more: boolean;
}

export interface MessageEvent {
  id: string;
  message: string;
  type: "message.changed" | "message.removed";
  state: string | null;
  timestamp: number;
  direction: "inbound" | "outbound";
}

export interface EventPage {
  profile: string;
  events: MessageEvent[];
  next_cursor: string;
  more: boolean;
}

export interface Acceptance {
  profile: string;
  message: string;
  accepted: true;
  accepted_at: number;
  idempotency_expires_at: number;
}

export interface Acknowledgment {
  profile: string;
  checkpoint: string;
  acknowledged: true;
  acknowledged_at: number;
  expires_at: number;
}

export interface DiagnosticsView {
  profile: string;
  captured_at?: number;
  available?: boolean;
  runtime_failure?: string | null;
  connections?: Record<string, unknown>[];
  total_connections?: number;
  truncated?: boolean;
}

export interface RelationshipView {
  profile: string;
  peer: string;
  trust: "approved" | "verified" | "blocked";
}

export interface PairingView {
  profile: string;
  peer: string;
  trust: "awaiting_consent" | "pending_request" | "approved" | "verified";
}

export interface InvitationView {
  profile: string;
  file: string;
  link: string;
  expires_at: number;
}

export interface StopView {
  stopping: true;
  already_stopping: boolean;
}

export interface PairingRequestView {
  profile: string;
  peer: string;
  state: "requested";
  document: string;
}

export interface WorkspacePreviewView {
  profile: string;
  name: string;
  description: string;
  member_count: number;
  retention_days: number;
  expires_at: number;
  requires_i2p_consent: boolean;
}

export interface WorkspaceJoinView {
  profile: string;
  workspace: string;
  name: string;
  state: "joining" | "active" | "pending" | "left";
}

export interface WorkspaceMember {
  member: string;
  display_name: string;
  role: "owner" | "admin" | "member";
  status: "active" | "invited" | "leaving" | "left" | "removed";
}

export interface WorkspaceMembersView {
  profile: string;
  workspace: string;
  members: WorkspaceMember[];
}

export interface WorkspaceDeclineView {
  profile: string;
  workspace: string;
  decision: "declined";
}

export interface WorkspaceMemberRoleView {
  profile: string;
  workspace: string;
  member: string;
  role: "admin" | "member";
}

export interface WorkspaceChannel {
  channel: string;
  name: string;
  visibility: "public" | "private";
  state: "active" | "archived" | "left";
}

export interface WorkspaceChannelsView {
  profile: string;
  workspace: string;
  channels: WorkspaceChannel[];
}

export interface WorkspaceInvitationView {
  profile: string;
  workspace: string;
  document: string;
  link: string;
  expires_at: number;
  connection_mode?: "webrtc" | "email" | "i2p" | "participant";
  i2p_access_point?: string;
}

export interface WorkspaceChannelCreateView {
  profile: string;
  workspace: string;
  channel: string;
  name: string;
  visibility: "public" | "private";
}

export interface WorkspaceChannelMembersView {
  profile: string;
  workspace: string;
  channel: string;
  members: string[];
}

export interface WorkspaceChannelUpdateView {
  profile: string;
  workspace: string;
  channel: string;
  name: string;
  topic: string;
  visibility: "public" | "private";
  posting: "all_members" | "owner_and_admins" | null;
}

export interface WorkspaceChannelArchiveView {
  profile: string;
  workspace: string;
  channel: string;
  state: "archived";
}

export interface WorkspaceDeviceLinkView {
  profile: string;
  workspace: string;
  document: string;
  link: string;
  expires_at: number;
}

export interface WorkspaceDeviceLinkPreviewView {
  profile: string;
  workspace: string;
  name: string;
  member_display_name: string;
  device_count: number;
  expires_at: number;
}

export interface WorkspaceDeviceLinkSubmitView {
  profile: string;
  workspace: string;
  name: string;
  state: "linking";
}

export interface WorkspaceDeviceLinksView {
  profile: string;
  workspace: string;
  links: Array<{ request: string; state: "pending" }>;
}

export interface WorkspaceDeviceLinkDecisionView {
  profile: string;
  workspace: string;
  link: string;
  state: "approved" | "declined";
}

export interface WorkspaceChannelTransferOfferView {
  profile: string;
  workspace: string;
  channel: string;
  member: string;
  state: "offered";
}

export interface WorkspaceChannelTransferAcceptView {
  profile: string;
  workspace: string;
  channel: string;
  state: "accepted";
}

export interface WorkspacePolicyView {
  profile: string;
  workspace: string;
  channel_creation: "all_members" | "owner_and_admins";
  posting: "all_members" | "owner_and_admins";
  invitation_requests: "owner_only" | "owner_and_admins" | "all_members_request";
}

export interface WorkspaceDevicesView {
  profile: string;
  workspace: string;
  devices: Array<{ device: string; member: string; current: boolean }>;
}

export interface WorkspaceDeviceRemoveView {
  profile: string;
  workspace: string;
  device: string;
  state: "removed";
}

export interface WorkspaceSummary {
  workspace: string;
  name: string;
  role: "owner" | "admin" | "member";
  state: string;
}

export interface WorkspaceListView {
  profile: string;
  workspaces: WorkspaceSummary[];
}

export interface WorkspaceJoinRequestSummary {
  request: string;
  display_name: string;
  created_at: number;
}

export interface WorkspaceRequestsView {
  profile: string;
  workspace: string;
  requests: WorkspaceJoinRequestSummary[];
}

export interface WorkspaceApproveView {
  profile: string;
  workspace: string;
  state: "active" | "joining" | "linking" | "left" | "removed" | "device_removed" | "revoked" | "archived";
}

export interface ConnectionIntentView {
  profile: string;
  peer: string;
  desired: "enabled" | "stopped";
  active: boolean;
}

export interface PeerView {
  profile: string;
  peer: string;
  display_name: string;
  destination: string;
  trust: string;
}

export interface MessageListView {
  profile: string;
  messages: SnapshotMessage[];
  next_cursor: string | null;
  events_cursor: string | null;
}

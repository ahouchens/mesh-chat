export type TrustState =
  | "awaiting_consent"
  | "pending_request"
  | "approved"
  | "verified"
  | "identity_changed"
  | "blocked";

export type DeliveryState =
  | "waiting_for_keys"
  | "queued"
  | "sending"
  | "stored_for_delivery"
  | "received_by_endpoint"
  | "delivered"
  | "expired"
  | "failed"
  | "cancelled";

export interface Profile {
  display_name: string;
  public_identity: string;
  identity_hash: string;
  destination_hash: string;
  fingerprint: string;
  created_at: number;
}

export interface Contact {
  id: string;
  display_name: string;
  public_identity: string;
  identity_hash: string;
  destination_hash: string;
  fingerprint: string;
  trust: TrustState;
  /** Signed name from the invitation, retained when a local label is edited. */
  profile_name?: string;
  /** Previous state used to safely restore a locally blocked contact. */
  trust_before_block?: Exclude<TrustState, "blocked">;
  request_state?: DeliveryState;
  route_kind?: "nearby" | "signed_direct" | "participant_direct" | "remote" | "unavailable";
  route_status?: "reconnecting_automatically" | "reconnect_update_required";
  connection_results?: ParticipantCandidateResult[];
  connection_hints: Array<{ type: "tcp"; host: string; port: number }>;
  created_at: number;
  updated_at: number;
}

export interface ChatMessage {
  id: string;
  conversation_id: string;
  contact_id: string;
  direction: "inbound" | "outbound";
  kind: "chat";
  text: string;
  state: DeliveryState;
  created_at: number;
  expires_at: number;
  native_message_id?: string;
  failure_code?: string;
  reactions?: MessageReaction[];
}

export interface MessageReaction {
  emoji: string;
  count: number;
  reacted_by_self: boolean;
}

export type GroupPostingPolicy = "members" | "owner_admins";
export type GroupRole = "owner" | "admin" | "member";
export type GroupMemberStatus = "invited" | "invite_expired" | "joining" | "active" | "left" | "removed";
export type GroupStatus = "active" | "joining" | "left" | "removed" | "forked" | "closed";

export interface GroupMember {
  destination_hash: string;
  display_name: string;
  role: GroupRole;
  status: GroupMemberStatus;
  fingerprint: string;
  contact_id?: string;
  public_identity?: string;
  identity_hash?: string;
  connection_hints?: Array<{ type: "tcp"; host: string; port: number }>;
  joined_epoch?: number;
  removed_epoch?: number;
  invite_delivery_state?: DeliveryState;
  invite_attempt_count?: number;
  invite_last_attempt_at?: number;
  invite_failure_code?: string;
}

export interface Group {
  id: string;
  title: string;
  owner_destination: string;
  posting_policy: GroupPostingPolicy;
  status: GroupStatus;
  local_role?: GroupRole | null;
  security_warning?: string;
  epoch: number;
  manifest_hash: string;
  members: GroupMember[];
  created_at: number;
  updated_at: number;
  membership_update_pending?: boolean;
}

export interface GroupMessageDelivery {
  recipient_destination: string;
  recipient_display_name: string;
  state: DeliveryState;
}

export interface GroupDeliverySummary {
  total: number;
  delivered: number;
  pending: number;
  failed: number;
  expired: number;
}

export interface GroupMessage {
  id: string;
  group_id: string;
  sender_destination: string;
  sender_display_name: string;
  direction: "inbound" | "outbound";
  kind?: "group_chat" | "group_event";
  text: string;
  state?: DeliveryState;
  group_epoch: number;
  group_manifest_hash: string;
  sender_sequence: number;
  created_at: number;
  expires_at: number;
  delivery_summary?: GroupDeliverySummary;
  deliveries?: GroupMessageDelivery[];
  failure_code?: string;
  reactions?: MessageReaction[];
}

export interface GroupDraft {
  group_id: string;
  text: string;
}

export interface GroupInvitation {
  id: string;
  group_id: string;
  title: string;
  owner_display_name: string;
  owner_destination: string;
  owner_fingerprint: string;
  member_count: number;
  posting_policy: GroupPostingPolicy;
  expires_at: number;
  members?: GroupMember[];
  state?: "pending" | "accepted" | "declined";
  created_at?: number;
  updated_at?: number;
}

export type WorkspaceRole = "owner" | "admin" | "member";
export type WorkspaceNotificationPreference = "all" | "mentions_only" | "muted";
export type NotificationPermissionState = "unsupported" | "not_requested" | "allowed" | "denied" | "settings_required";

export interface WorkspaceNotificationState {
  supported: boolean;
  platform: "desktop" | "android" | "ios";
  permission_state: NotificationPermissionState;
  hide_previews: boolean;
  lifecycle_state: "foreground" | "background" | "suspended" | "reconciling" | "caught_up";
  reconciling: boolean;
  caught_up: boolean;
  invalidation_overflow: boolean;
  pending_native_count: number;
  guidance: string;
}

export interface NotificationCapability {
  supported: boolean;
  platform: "desktop" | "android" | "ios";
  permission_state: NotificationPermissionState;
}

export interface NotificationOpenTarget {
  available: boolean;
  reason?: "unavailable" | "authorization_changed";
  message?: string;
  scope?: "workspace" | "personal_direct" | "personal_group";
  target_id?: string;
  workspace_id?: string;
  conversation_id?: string;
  conversation_kind?: "channel" | "direct" | "group";
  thread_root_id?: string | null;
  event_id?: string;
}
export type WorkspaceState =
  | "joining"
  | "linking"
  | "active"
  | "leaving"
  | "left"
  | "removed"
  | "device_removed"
  | "closed"
  | "forked"
  | "incomplete_sync";

export interface WorkspaceMember {
  id: string;
  display_name: string;
  role: WorkspaceRole;
  status: "joining" | "active" | "left" | "removed";
  short_id: string;
  device: {
    id: string;
    destination_hash: string;
    fingerprint: string;
  };
  devices?: Array<{
    id: string;
    destination_hash: string;
    fingerprint: string;
  }>;
}

export interface Workspace {
  id: string;
  name: string;
  description: string;
  state: WorkspaceState;
  local_role: WorkspaceRole;
  local_member_id: string;
  local_device_id: string;
  owner_member_id: string;
  authority_device_id: string;
  epoch: number;
  manifest_hash: string;
  genesis_digest: string;
  general_channel_id: string | null;
  channel_discovery: "incomplete" | "converged";
  retention_days: 30 | 90 | 365 | null;
  policies: {
    channel_creation: "all_members" | "owner_and_admins";
    posting: "all_members" | "owner_and_admins";
    invitation_requests: "owner_only" | "owner_and_admins" | "all_members_request";
  };
  members: WorkspaceMember[];
  authorization_generation: number;
  retention_generation: number;
  mention_unread_count: number;
  thread_unread_count: number;
  pending_owner_review_count?: number;
  search_index?: {
    status: "ready" | "rebuilding" | "incomplete" | "indexing";
    indexed_events: number;
    target_events: number;
    incomplete: boolean;
  };
  retention_pruning_state?: "pending" | "running" | "complete" | "disabled" | "restart_required";
  retention_pruning_updated_at?: number;
  security_error?: string;
  sync_issue?: "missing_controls" | "missing_predecessor" | "missing_manifest" | "missing_manifest_predecessor" | "queue_pressure" | string;
  authority_loss?: boolean;
  authority_administration_state?: "permanently_frozen";
  authority_loss_guidance?: string;
  read_hint_sync?: boolean;
  notification_preference?: WorkspaceNotificationPreference;
  /** Transport evidence for this device's initial join request. */
  join_delivery_state?: DeliveryState;
  join_acknowledged?: boolean;
  connection_setup_failed?: boolean;
  connection_results?: ParticipantCandidateResult[];
  created_at: number;
  updated_at: number;
}

export interface WorkspaceChannel {
  id: string;
  workspace_id: string;
  name: string;
  name_key: string;
  display_name: string;
  short_id: string;
  topic: string;
  visibility: "public" | "private";
  state: "active" | "archived" | "forked" | "leaving" | "left" | "removed";
  manager_member_id: string;
  manager_device_id: string;
  member_ids: string[];
  version: number;
  head_hash: string;
  manifest_digest: string;
  unread_count: number;
  subscribed: boolean;
  mentions_muted: boolean;
  notification_preference?: WorkspaceNotificationPreference;
  is_general: boolean;
  duplicate_name: boolean;
  created_at: number;
  updated_at: number;
}

export interface WorkspaceDirect {
  id: string;
  workspace_id: string;
  participant_member_ids: string[];
  peer_member_id: string;
  peer_display_name: string;
  peer_short_id: string;
  state: "open" | "read_only";
  unread_count: number;
  notification_preference?: WorkspaceNotificationPreference;
  created_at: number;
  updated_at: number;
}

export interface WorkspaceChannelTransfer {
  id: string;
  workspace_id: string;
  channel_id: string;
  channel_head: string;
  manifest_digest: string;
  manager_member_id: string;
  successor_member_id: string;
  successor_device_id: string;
  state: "offered";
  created_at: number;
  expires_at: number;
}

export interface WorkspaceDeliverySummary {
  people_total: number;
  people_reached: number;
  people_partial?: number;
  people_pending?: number;
  people_failed?: number;
  devices_total: number;
  devices_reached: number;
  devices_pending: number;
  devices_failed: number;
  devices_expired?: number;
  devices_cancelled?: number;
}

export interface WorkspaceDelivery {
  member_id: string;
  member_display_name: string;
  device_id: string;
  device_short_id: string;
  state:
    | "waiting_for_keys"
    | "queued"
    | "sending"
    | "stored_for_delivery"
    | "received_by_endpoint"
    | "delivered"
    | "expired"
    | "failed"
    | "cancelled";
}

export interface WorkspaceMessage {
  id: string;
  workspace_id: string;
  conversation_id: string;
  direction: "inbound" | "outbound";
  author_member_id: string;
  author_display_name: string;
  text: string;
  revision?: number;
  deleted?: boolean;
  edited_at?: number;
  mutation_conflict?: boolean;
  mutation_frozen?: boolean;
  reactions?: MessageReaction[];
  mention_member_ids?: string[];
  mention_position?: number;
  thread_root?: string | null;
  thread_position?: number;
  reply_count?: number;
  thread_unread_count?: number;
  latest_reply_at?: number;
  sequence: number;
  event_digest: string;
  created_at: number;
  delivery_summary?: WorkspaceDeliverySummary;
  deliveries?: WorkspaceDelivery[];
}

export interface WorkspaceMessagePage {
  messages: WorkspaceMessage[];
  next_cursor: string | null;
  high_water: number;
  history_status?: "complete" | "pruned" | "permanent_gap";
  pruned_count?: number;
  permanent_gaps?: Array<{ start?: number; end?: number; reason?: string }>;
}

export interface WorkspaceMessageRevision {
  event_id: string;
  event_type: "edit" | "delete" | "reaction";
  revision: number;
  author_member_id: string;
  created_at: number;
  text?: string;
  mention_member_ids?: string[];
  emoji?: string;
  active?: boolean;
}

export interface WorkspaceRevisionPage {
  message: WorkspaceMessage;
  revisions: WorkspaceMessageRevision[];
  next_cursor: string | null;
  high_water: number;
  history_status: "complete" | "pruned";
}

export interface WorkspaceTombstone {
  position: number;
  deleted_at: number;
  message: WorkspaceMessage;
}

export interface WorkspaceTombstonePage {
  tombstones: WorkspaceTombstone[];
  next_cursor: string | null;
  high_water: number;
  history_status: "complete" | "pruned";
}

export interface WorkspaceRetentionPruneResult {
  workspace_id: string;
  status: "disabled" | "pending" | "running" | "complete" | "restart_required";
  scanned: number;
  pruned: number;
  scanned_this_batch?: number;
  pruned_this_batch?: number;
  needs_more: boolean;
  retention_generation?: number;
  cutoff?: number | null;
}

export type WorkspaceHistoryJobState =
  | "available"
  | "requesting"
  | "waiting_peer"
  | "verifying"
  | "paused_offline"
  | "missing_prerequisites"
  | "peer_limited"
  | "complete_known"
  | "cancelled"
  | "dismissed"
  | "authorization_changed"
  | "fork_suspended"
  | "expired"
  | "failed";

export interface WorkspaceHistoryJob {
  workspace_id: string;
  conversation_id: string;
  conversation_kind: "public" | "private" | "direct";
  status: WorkspaceHistoryJobState;
  recovered_events: number;
  verified_pages: number;
  received_bytes: number;
  peer_count: number;
  peers_exhausted: number;
  missing_prerequisites: number;
  permanent_gaps: number;
  peer_limited: boolean;
  failure?: string | null;
  updated_at: number;
  known_complete: boolean;
  notice: string;
}

export interface WorkspaceHistoryStatus {
  workspace_id: string;
  conversation_id: string;
  conversation_kind: "public" | "private" | "direct";
  eligible: boolean;
  status: WorkspaceHistoryJobState;
  job: WorkspaceHistoryJob | null;
  streams: Array<{
    known_high_water: number;
    retained_floor: number;
    seen_ranges: number[][];
    gaps: number[][];
  }>;
  known_complete: boolean;
  notice: string;
}

export interface WorkspaceMention {
  position: number;
  read: boolean;
  conversation: {
    id: string;
    kind: "channel" | "direct";
    name: string;
    visibility: "public" | "private" | "direct";
  };
  message: WorkspaceMessage;
  thread_root_id?: string;
}

export interface WorkspaceMentionPage {
  mentions: WorkspaceMention[];
  next_cursor: string | null;
  high_water: number;
  unread_count: number;
}

export interface WorkspaceDraft {
  workspace_id: string;
  conversation_id: string;
  thread_root_id?: string;
  text: string;
  mention_member_ids?: string[];
}

export interface WorkspaceThreadConversation {
  id: string;
  kind: "channel" | "direct";
  name: string;
  visibility: "public" | "private" | "direct";
  state: "active" | "archived" | "open" | "read_only";
}

export interface WorkspaceThreadPage {
  root: WorkspaceMessage;
  replies: WorkspaceMessage[];
  next_cursor: string | null;
  high_water: number;
  unread_count: number;
  conversation: WorkspaceThreadConversation;
}

export interface WorkspaceThreadActivity {
  root: WorkspaceMessage;
  conversation: WorkspaceThreadConversation;
  reply_count: number;
  unread_count: number;
  high_water: number;
  updated_at: number;
}

export interface WorkspaceThreadActivityPage {
  threads: WorkspaceThreadActivity[];
  next_cursor: string | null;
  high_water: number;
  unread_count: number;
}

export type WorkspaceSearchScope = "all" | "messages" | "threads" | "people" | "channels";

export interface WorkspaceSearchResult {
  id: string;
  kind: "message" | "thread" | "person" | "channel";
  title: string;
  snippet: string;
  created_at?: number;
  member_id?: string;
  event_id?: string;
  is_reply?: boolean;
  thread_root_id?: string | null;
  conversation?: WorkspaceThreadConversation;
}

export interface WorkspaceSearchPage {
  results: WorkspaceSearchResult[];
  next_cursor: string | null;
  scope: WorkspaceSearchScope;
  coverage: "retained" | "indexing" | "pruned" | "incomplete";
  indexing: boolean;
  indexed_events: number;
  target_events: number;
  candidate_count: number;
  candidate_limit_reached: boolean;
  shard_pages_opened: number;
  search_generation: number;
}

export interface WorkspaceJoinRequest {
  id: string;
  workspace_id: string;
  member_id: string;
  display_name: string;
  device_id: string;
  destination_hash: string;
  fingerprint: string;
  invitation_id: string;
  state: "pending";
  created_at: number;
}

export interface WorkspaceInvitation {
  id: string;
  workspace_id: string;
  offered_manifest_digest: string;
  state: "active";
  created_at: number;
  expires_at: number;
}

export interface WorkspaceInvitationPreview {
  workspace_id: string;
  existing_workspace?: Workspace;
  can_resume_join?: boolean;
  join_resume_reason?: "invitation_mismatch" | "request_stopped" | "request_expired" | "identity_mismatch" | "saved_request_invalid";
  name: string;
  description: string;
  owner_fingerprint: string;
  member_count: number;
  retention_days: 30 | 90 | 365 | null;
  expires_at: number;
  remote_profile?: RemoteProfilePreview;
  participant_access?: ParticipantAccessPreview;
  connection_reply_available?: boolean;
  invitation_digest?: string;
  requires_network_consent?: boolean;
  i2p_access_point?: { b32: string; label: string; relay: string };
  requires_i2p_consent?: boolean;
}

export interface WorkspaceInvitationFormats {
  id: string;
  workspace_id: string;
  link: string;
  text: string;
  value: string;
  expires_at: number;
  remote_profile_id?: string;
  access_point_reachable?: boolean;
  connection_mode?: "participant" | "email" | "i2p";
  connection_reply_available?: boolean;
  host_session_id?: string;
  methods?: ParticipantHosting["methods"];
}

export interface WorkspaceDeviceLinkPreview {
  workspace_id: string;
  name: string;
  member_display_name: string;
  sponsor_fingerprint: string;
  device_count: number;
  expires_at: number;
}

export interface WorkspaceDeviceLinkFormats {
  id: string;
  workspace_id: string;
  link: string;
  text: string;
  value: string;
  expires_at: number;
}

export interface WorkspaceDeviceTransition {
  id: string;
  workspace_id: string;
  direction: "incoming" | "outgoing";
  transition_kind: "link" | "removal";
  state: "offered" | "waiting_for_approval" | "pending";
  member_id: string;
  sponsor_device_id?: string;
  device_id?: string;
  fingerprint?: string;
  created_at: number;
  expires_at: number;
  updated_at: number;
}

export interface WorkspaceDisplayNameRequest {
  id: string;
  workspace_id: string;
  manifest_digest: string;
  member_id: string;
  device_id: string;
  display_name: string;
  state: "pending";
  created_at: number;
}

export type WorkspaceAdminRequestState =
  | "pending"
  | "approved"
  | "declined"
  | "stale"
  | "superseded"
  | "expired"
  | "cancelled"
  | "failed";

export interface WorkspaceAdminRequest {
  id: string;
  workspace_id: string;
  direction: "incoming" | "outgoing";
  request_kind: "invitation" | "member_removal" | "role_change";
  state: WorkspaceAdminRequestState;
  requester_display_name: string;
  requester_role?: WorkspaceRole;
  target_member_id?: string | null;
  target_display_name?: string | null;
  effective_role?: WorkspaceRole | null;
  requested_role?: "admin" | "member" | null;
  note: string;
  created_at: number;
  expires_at: number;
  updated_at: number;
  delivery_state?: "waiting_for_route" | "delivered_to_owner" | "failed_retryable";
  failure?: string | null;
  dismissed?: boolean;
  invitation?: WorkspaceInvitationFormats;
}

export interface WorkspaceAdminRequestPage {
  requests: WorkspaceAdminRequest[];
  next_cursor: string | null;
  pending_count: number;
}

export type WorkspaceAuthorityTransitionState =
  | "waiting_for_delivery"
  | "waiting_for_acceptance"
  | "accepted_waiting_finalization"
  | "finalizing"
  | "applied"
  | "expired"
  | "stale"
  | "superseded"
  | "cancelled"
  | "incomplete_control_state"
  | "forked";

export interface WorkspaceAuthorityTransition {
  id: string;
  workspace_id: string;
  direction: "incoming" | "outgoing";
  transition_kind: "same_owner_rotation" | "ownership_transfer";
  state: WorkspaceAuthorityTransitionState;
  current_owner_display_name: string;
  successor_member_id: string;
  successor_display_name: string;
  successor_fingerprint: string;
  outgoing_owner_role: "admin" | "member" | null;
  general_disposition: "unchanged" | "recover";
  created_at: number;
  expires_at: number;
  updated_at: number;
  delivery_state?: string;
  failure?: string | null;
}

export interface WorkspaceSnapshot {
  workspaces: Workspace[];
  workspace_channels: WorkspaceChannel[];
  workspace_directs: WorkspaceDirect[];
  workspace_channel_transfers: WorkspaceChannelTransfer[];
  workspace_join_requests: WorkspaceJoinRequest[];
  workspace_display_name_requests: WorkspaceDisplayNameRequest[];
  workspace_admin_requests: WorkspaceAdminRequest[];
  workspace_authority_transitions?: WorkspaceAuthorityTransition[];
  workspace_device_transitions?: WorkspaceDeviceTransition[];
  workspace_invitations: WorkspaceInvitation[];
  workspace_drafts: WorkspaceDraft[];
  workspace_notification_state?: WorkspaceNotificationState;
}

export interface NetworkSettings {
  nearby_discovery: boolean;
  lan_fallback: boolean;
  lan_listener_port: number | null;
  allowed_interfaces: string[];
  tcp_clients: Array<{ type: "tcp"; host: string; port: number }>;
  tcp_listener: { host: string; port: number } | null;
  help_route: boolean;
  store_for_offline: boolean;
  approved_propagation_nodes: string[];
  i2p_enabled: boolean;
  i2p_connectable: boolean;
  i2p_managed: boolean;
  i2p_peers: string[];
}

export interface I2PStatus {
  enabled: boolean;
  connectable: boolean;
  managed: boolean;
  peer_count: number;
  interface_count: number;
  online_count: number;
  online: boolean;
  state: "disabled" | "not_started" | "starting" | "online" | "unavailable";
  b32: string | null;
  router: {
    state: string;
    available: boolean;
    managed: boolean;
    sam_ready: boolean;
    reason: string | null;
  };
}

export interface NetworkInterfaceState {
  name: string;
  online: boolean;
  receives: boolean;
  type: string;
  adopted_interface_count?: number;
  self_echo_seen?: boolean;
  carrier_timed_out?: boolean;
  peer_count?: number;
  client_count?: number;
}

export type RemoteProfileState = "approved" | "connecting" | "connected" | "access_point_unavailable" | "expired";

export interface RemoteProfile {
  id: string;
  label: string;
  origin: "manual" | "personal_invitation" | "workspace_invitation";
  expires_at: number;
  endpoint_count: number;
  connected_endpoint_count: number;
  state: RemoteProfileState;
  path_available: boolean;
  ratchet_ready: boolean;
  offline_delivery_recommended: boolean;
  offline_delivery_approved: boolean;
  offline_delivery_available: boolean;
  propagation_identifier: string | null;
  scope_count: number;
  retry_count: number;
  last_error: string | null;
  last_connected_at: number | null;
  capabilities: string[];
  allow_private: boolean;
}

export interface RemoteProfilePreview {
  id: string;
  label: string;
  endpoint_count: number;
  expires_at: number;
  capabilities: string[];
  private_endpoint_warning: boolean;
  propagation_identifier: string | null;
  privacy_disclosure: string;
}

export interface ParticipantAccessPreview {
  id: string;
  mode: "participant_direct" | "participant_callback";
  operator: "inviter";
  endpoint_count: number;
  expires_at: number;
  privacy_disclosure: string;
}

export interface ParticipantHosting {
  id: string;
  purpose: "personal" | "workspace";
  scope_id: string;
  endpoint_count: number;
  methods: Array<"public_ipv4" | "public_ipv6" | "upnp" | "nat_pmp" | "pcp" | "manual">;
  expires_at: number;
  state: "manual_setup" | "prepared_unverified" | "recipient_connected" | "unavailable" | "expired";
  reason?: string | null;
  firewall_configured: boolean;
}

export type DirectDoctorPhase = "precondition" | "ipv6" | "upnp" | "nat_pmp" | "pcp" | "firewall" | "listener";
export type DirectDoctorResult = "available" | "unavailable" | "blocked" | "unsupported" | "prepared_unverified";
export interface DirectDoctorStep {
  phase: DirectDoctorPhase;
  result: DirectDoctorResult;
  reason: string;
  recommended_action: string;
}
export interface DirectDoctorReport {
  summary: DirectDoctorStep;
  checks: DirectDoctorStep[];
}
export interface ManualParticipantSetup {
  setup_id: string;
  device_label: string;
  tcp_port: number;
  expires_at: number;
  warning: "manual_rule_not_removed_automatically";
  upstream_warning?: "upnp_wan_private" | "upnp_wan_shared" | "upstream_nat_detected" | null;
}
export interface ParticipantCandidateResult {
  candidate: number;
  path: "public_ipv4" | "public_ipv6" | "upnp" | "nat_pmp" | "pcp" | "manual";
  result: "connected" | "refused" | "timed_out" | "no_ipv6_route" | "unresolved";
}
export interface ParticipantConnectionSummary {
  id: string;
  candidate_results: ParticipantCandidateResult[];
  all_failed: boolean;
}

export type CallState =
  | "dialing"
  | "ringing"
  | "connecting"
  | "in_call"
  | "ended"
  | "declined"
  | "busy"
  | "no_answer"
  | "failed";

export interface CallSummary {
  id: string;
  contact_id: string;
  role: "caller" | "callee";
  media: "audio" | "video";
  state: CallState;
  direction: "outbound" | "inbound";
  created_at: number;
  updated_at: number;
  expires_at: number;
  ring_expires_at?: number | null;
  candidate_count: number;
  has_local_sdp: boolean;
  has_remote_sdp: boolean;
}

export interface CallMedia extends CallSummary {
  local_sdp: string | null;
  remote_sdp: string | null;
  candidates: string[];
  restart_offer: string | null;
  restart_answer: string | null;
}

export interface CallSettings {
  stun_urls: string[];
  turn_configured: boolean;
  relay_only: boolean;
}

export interface CallIceConfiguration {
  iceServers: Array<{
    urls: string | string[];
    username?: string;
    credential?: string;
  }>;
  iceTransportPolicy: "all" | "relay";
}

export interface Snapshot {
  profile: Profile | null;
  contacts: Contact[];
  messages: ChatMessage[];
  drafts: Array<{ contact_id: string; text: string }>;
  /** Locally deleted threads; trust and group membership remain available for restore. */
  hidden_conversations?: Array<{ kind: "direct" | "group"; id: string }>;
  /** Optional during migration so older encrypted vaults and services remain readable. */
  groups?: Group[];
  group_messages?: GroupMessage[];
  group_drafts?: GroupDraft[];
  group_invitations?: GroupInvitation[];
  /** Desktop workspace summaries. Message bodies remain paged separately. */
  workspaces?: Workspace[];
  workspace_channels?: WorkspaceChannel[];
  workspace_directs?: WorkspaceDirect[];
  workspace_channel_transfers?: WorkspaceChannelTransfer[];
  workspace_join_requests?: WorkspaceJoinRequest[];
  workspace_display_name_requests?: WorkspaceDisplayNameRequest[];
  workspace_admin_requests?: WorkspaceAdminRequest[];
  workspace_authority_transitions?: WorkspaceAuthorityTransition[];
  workspace_device_transitions?: WorkspaceDeviceTransition[];
  workspace_invitations?: WorkspaceInvitation[];
  workspace_drafts?: WorkspaceDraft[];
  workspace_notification_state?: WorkspaceNotificationState;
  settings: NetworkSettings;
  remote_profiles?: RemoteProfile[];
  participant_hosting?: ParticipantHosting[];
  participant_connections?: ParticipantConnectionSummary[];
  calls?: CallSummary[];
  network: {
    transport_enabled: boolean;
    propagation_enabled: boolean;
    interface_available: boolean;
    interfaces: NetworkInterfaceState[];
    outbound_propagation_node: string | null;
  } | null;
  service_error: string | null;
}

export interface InvitationPreview {
  display_name: string;
  identity_hash: string;
  destination_hash: string;
  fingerprint: string;
  hints: Array<{ type: "tcp"; host: string; port: number }>;
  expires_at: number;
  remote_profile?: RemoteProfilePreview;
  participant_access?: ParticipantAccessPreview;
  connection_reply_available?: boolean;
  invitation_digest?: string;
  requires_network_consent?: boolean;
  i2p_access_point?: { b32: string; label: string; relay: string };
  requires_i2p_consent?: boolean;
}

export interface InvitationFormats {
  link: string;
  text: string;
  file: string;
  expires_at: number;
  remote_profile_id?: string;
  access_point_reachable?: boolean;
  connection_mode?: "participant" | "email" | "i2p";
  connection_reply_available?: boolean;
  host_session_id?: string;
  methods?: ParticipantHosting["methods"];
}

export interface ConnectionDocumentFormats {
  link: string;
  text: string;
  file: string;
  purpose?: "personal" | "workspace";
  expires_at: number;
  host_session_id?: string;
  methods?: ParticipantHosting["methods"];
}

export interface ConnectionReplyPreview {
  purpose: "personal" | "workspace";
  invitation_digest: string;
  responder_destination: string;
  responder_fingerprint: string;
  endpoint_count: number;
  expires_at: number;
  connection_results?: ParticipantCandidateResult[];
}

export interface RouteUpdatePreview {
  scope_kind: "contact" | "workspace_device";
  scope_id: string;
  issuer_destination: string;
  issuer_fingerprint: string;
  issuer_display_name: string;
  generation: number;
  endpoint_count: number;
  expires_at: number;
  connection_results?: ParticipantCandidateResult[];
}

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
  | "failed";

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
  settings: NetworkSettings;
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
}

export interface InvitationFormats {
  link: string;
  text: string;
  file: string;
  expires_at: number;
}

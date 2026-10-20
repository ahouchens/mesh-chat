import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type ReactNode } from "react";
import {
  BookUser,
  Bell,
  BellOff,
  Building2,
  ArrowLeft,
  AtSign,
  Ban,
  Check,
  Clock3,
  ChevronRight,
  CircleHelp,
  Copy,
  EllipsisVertical,
  FileUp,
  Hash,
  EyeOff,
  LogIn,
  LogOut,
  LockKeyhole,
  Megaphone,
  MessageCircleMore,
  Mic,
  MicOff,
  Moon,
  Phone,
  PhoneOff,
  Plus,
  QrCode,
  RefreshCw,
  Search,
  Send,
  Share2,
  SmilePlus,
  Settings,
  ShieldCheck,
  ShieldOff,
  Sun,
  Trash2,
  UserMinus,
  UserRoundPlus,
  Users,
  Video,
  VideoOff,
  WifiOff,
  X,
} from "lucide-react";
import {
  beginCallAudio,
  initializeService,
  lockService,
  notificationCapability,
  onInvitation,
  onMobileBackButton,
  onNotificationOpen,
  onServiceEvent,
  openNotificationSettings,
  requestNotificationPermission,
  requestMediaPermission,
  runtimePlatform,
  setNativeTheme,
  serviceCommand,
  endCallAudio,
} from "./api";
import type { ServiceEvent } from "./api";
import { contactConnectionLabel, deliveryLabel, workspaceJoinStatus } from "./status";
import { EmojiGlyph } from "./EmojiGlyph";
import { ConnectionDiagnostics } from "./ConnectionDiagnostics";
import { DirectConnectionSetup } from "./DirectConnectionSetup";
import { DirectRecovery } from "./DirectRecovery";
import { WebRTCOnboardingDialog } from "./WebRTCOnboarding";
import { closeWebRTCSession, getWebRTCSession } from "./webrtc-session";
import { getEmojiFallbackName } from "./emoji-artwork";
import {
  QUICK_REACTION_OPTIONS,
  REACTION_CATEGORIES,
  REACTION_OPTION_BY_EMOJI,
  validateSingleEmoji,
} from "./reactions";
import { InvitationImportActions, InvitationQrCode } from "./InvitationTransfer";
import { classifyInvitationInput, InvitationTransferError, normalizeInvitationInput } from "./invitation-transfer";
import packageInfo from "../package.json";
import type {
  CallIceConfiguration,
  CallMedia,
  CallSettings,
  CallSummary,
  ChatMessage,
  ConnectionDocumentFormats,
  ConnectionReplyPreview,
  Contact,
  DirectDoctorReport,
  DirectDoctorStep,
  Group,
  GroupInvitation,
  GroupMember,
  GroupMessage,
  GroupPostingPolicy,
  I2PStatus,
  InvitationFormats,
  InvitationPreview,
  ManualParticipantSetup,
  MessageReaction,
  NetworkSettings,
  ParticipantHosting,
  ParticipantCandidateResult,
  RemoteProfile,
  RouteUpdatePreview,
  NotificationCapability,
  NotificationOpenTarget,
  Snapshot,
  Workspace,
  WorkspaceAdminRequest,
  WorkspaceAuthorityTransition,
  WorkspaceChannel,
  WorkspaceChannelTransfer,
  WorkspaceDisplayNameRequest,
  WorkspaceDeviceLinkFormats,
  WorkspaceDeviceLinkPreview,
  WorkspaceDeviceTransition,
  WorkspaceDirect,
  WorkspaceInvitation,
  WorkspaceInvitationFormats,
  WorkspaceInvitationPreview,
  WorkspaceJoinRequest,
  WorkspaceMessage,
  WorkspaceNotificationPreference,
  WorkspaceNotificationState,
  WorkspaceMessagePage,
  WorkspaceHistoryStatus,
  WorkspaceMentionPage,
  WorkspaceRetentionPruneResult,
  WorkspaceRevisionPage,
  WorkspaceSearchPage,
  WorkspaceSearchResult,
  WorkspaceSearchScope,
  WorkspaceSnapshot,
  WorkspaceTombstonePage,
  WorkspaceThreadActivityPage,
  WorkspaceThreadPage,
} from "./types";
import "./styles.css";

type OnboardingMode = "home" | "start" | "join";
type OnboardingWorkspaceContext =
  | { kind: "workspace"; name: string; description: string }
  | { kind: "device"; name: string; memberDisplayName: string };
type Theme = "dark" | "light";

const THEME_STORAGE_KEY = "mesh-chat-theme";

function initialTheme(): Theme {
  try {
    return window.localStorage.getItem(THEME_STORAGE_KEY) === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}

function initials(name: string): string {
  return name
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("");
}

function formatTime(timestamp: number): string {
  const date = safeDate(timestamp);
  if (!date) return "Unknown time";
  return new Intl.DateTimeFormat(undefined, {
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

function formatExpiry(timestamp: number): string {
  const date = safeDate(timestamp);
  if (!date) return "Unknown expiry";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function safeDate(timestamp: number): Date | null {
  if (!Number.isFinite(timestamp)) return null;
  const date = new Date(timestamp * 1000);
  return Number.isNaN(date.getTime()) ? null : date;
}

function machineTime(timestamp: number): string | undefined {
  return safeDate(timestamp)?.toISOString();
}

function isWorkspaceInvitationValue(value: string): boolean {
  const kind = classifyInvitationInput(value);
  return kind === "workspace" || kind === "workspace_device" || kind === "direct_connection";
}

function isWorkspacePrefixOnly(value: string): boolean {
  return /^MESHWORKSPACE(?:DEVICE)?\d+$/i.test(value.trim());
}

function incompleteWorkspacePrefixMessage(value: string): string {
  const prefix = value.trim();
  return `This is only the ${prefix} prefix. Copy the complete invitation, including the colon and all signed text after it.`;
}

function connectionDocumentKind(value: string): "reply" | "route" | null {
  const kind = classifyInvitationInput(value);
  if (kind === "connection_reply") return "reply";
  if (kind === "route_update") return "route";
  return null;
}

function pluralize(count: number, singular: string, plural = `${singular}s`): string {
  return `${count} ${count === 1 ? singular : plural}`;
}

function groupPolicyLabel(policy: GroupPostingPolicy): string {
  return policy === "owner_admins" ? "Only the owner can post" : "Everyone can post";
}

function contactTrustLabel(contact: Contact): string {
  switch (contact.trust) {
    case "verified": return "Verified";
    case "approved": return "Approved";
    case "awaiting_consent": return "Waiting for acceptance";
    case "pending_request": return "Incoming request";
    case "identity_changed": return "Identity changed";
    case "blocked": return "Blocked";
  }
}

function contactTrustDescription(contact: Contact): string {
  switch (contact.trust) {
    case "verified": return "You compared this fingerprint with the contact through another trusted channel.";
    case "approved": return "This contact accepted your connection, but the fingerprint has not been independently compared.";
    case "awaiting_consent": return "Your connection request is still waiting for this person to accept it.";
    case "pending_request": return "This person is waiting for you to accept or decline their request.";
    case "identity_changed": return "Messaging is paused because this destination presented different identity material.";
    case "blocked": return "Direct messages and connection requests from this contact are ignored.";
  }
}

function groupInviteDeliveryLabel(member: GroupMember): string {
  switch (member.invite_delivery_state) {
    case "delivered": return "Invitation ready for review";
    case "received_by_endpoint": return "Reached device · confirming receipt";
    case "stored_for_delivery": return "Stored securely for delivery";
    case "sending": return "Sending invitation";
    case "waiting_for_keys": return "Trying to find device";
    case "expired": return "Invitation expired";
    case "failed": return "Invitation needs attention";
    default: return "Invitation queued";
  }
}

function groupInvitationBanner(members: GroupMember[]): string {
  const awaiting = members.filter((member) => member.invite_delivery_state === "delivered");
  const confirming = members.filter((member) => member.invite_delivery_state === "received_by_endpoint");
  const unreachable = members.filter((member) => !["delivered", "received_by_endpoint", "stored_for_delivery"].includes(member.invite_delivery_state ?? "queued"));
  if (unreachable.length > 0) {
    const names = unreachable.map((member) => member.display_name).join(", ");
    return `Trying to reach ${names}. Keep Mesh Chat open on both devices and use the same non-guest network.`;
  }
  if (confirming.length > 0) return `${pluralize(confirming.length, "invitation")} reached the device and is waiting for app confirmation.`;
  if (awaiting.length > 0) return `${pluralize(awaiting.length, "invitation")} ready for review · waiting for acceptance.`;
  return `${pluralize(members.length, "invitation")} stored for delivery.`;
}

function groupComposerState(group: Group, selfDestination: string): { canPost: boolean; reason: string } {
  const activeMembers = group.members.filter((member) => member.status === "active");
  const self = activeMembers.find((member) => member.destination_hash === selfDestination);
  const hasRecipient = activeMembers.some((member) => member.destination_hash !== selfDestination);
  const policyAllowsPosting = group.posting_policy === "members" || self?.role === "owner";
  const canPost = group.status === "active"
    && Boolean(self)
    && !group.membership_update_pending
    && hasRecipient
    && policyAllowsPosting;
  const reason = group.status === "closed"
    ? "This group is closed. Messages already received remain on this device."
    : group.status === "forked"
      ? "Messaging is paused because conflicting membership information was detected."
      : group.status === "joining"
        ? "Waiting for the owner to accept you and publish the next membership update."
        : group.status === "removed" || group.status === "left" || !self
          ? "You are no longer an active member of this group."
          : group.membership_update_pending
            ? "Messaging is paused until the signed membership update reaches every current member."
            : !hasRecipient
              ? "There are no other active members to receive a message."
              : !policyAllowsPosting
                ? "Only the owner can post in this announcement channel."
                : "";
  return { canPost, reason };
}

function groupDeliveryLabel(message: GroupMessage): string {
  const summary = message.delivery_summary;
  if (!summary) return message.state ? deliveryLabel[message.state] : "Saved on this device";
  const total = Math.max(0, summary.total);
  const delivered = Math.max(0, summary.delivered);
  const pending = Math.max(0, summary.pending);
  const failed = Math.max(0, summary.failed);
  const expired = Math.max(0, summary.expired);
  if (total === 0) return "Saved on this device";
  if (delivered >= total) return "Delivered to everyone";
  if (expired > 0 && delivered + expired >= total) return `Expired for ${expired}`;
  if (failed + expired > 0 && pending === 0) return `Partially delivered · ${delivered} of ${total}`;
  if (delivered > 0) return `Delivered to ${delivered} of ${total}${pending > 0 ? ` · ${pending} pending` : ""}`;
  return `Sending to ${total}`;
}

function errorMessage(error: unknown): string {
  const raw = String(error);
  if (raw.includes("direct_connection_unavailable")) {
    return "This device could not open a direct Internet path through the current network. Check whether the router permits UPnP, NAT-PMP, PCP, or inbound IPv6; otherwise use nearby access or explicitly choose an approved access point.";
  }
  if (raw.includes("profile_in_use")) {
    return "Your encrypted profile is still in use by another Mesh Chat process. Close any other Mesh Chat window, wait a moment, and reopen the app. Your existing encrypted data is unchanged.";
  }
  if (raw.includes("protected_storage_unavailable")) {
    return "Protected storage is unavailable. Turn on FileVault (macOS), use an EFS-capable NTFS profile (Windows), or place the profile on fscrypt/LUKS storage (Linux), then reopen Mesh Chat. No private data was written.";
  }
  if (raw.includes("credential_store_unavailable")) {
    return "The operating-system credential store is unavailable. Unlock Keychain, Credential Manager, or your Linux Secret Service, then reopen Mesh Chat.";
  }
  if (raw.includes("mobile_runtime_unavailable") || raw.includes("service_start_failed")) {
    return "The mobile messaging runtime could not start. Reopen Mesh Chat after unlocking the device and granting local-network access.";
  }
  if (raw.includes("service_timeout")) {
    return "Mesh Chat did not respond in time. Check the conversation before trying again.";
  }
  if (raw.includes("service_busy")) {
    return "Mesh Chat is finishing earlier delivery work. Wait a moment and try again.";
  }
  if (raw.includes("service_stopped") || raw.includes("service_not_running")) {
    return "The messaging service stopped. Reopen Mesh Chat and try again.";
  }
  if (raw.includes("native_unavailable")) {
    return "The on-device connection service stopped responding. Close and reopen Mesh Chat, then try again. Your saved request and messages are unchanged.";
  }
  if (raw.includes("workspace_already_known")) {
    return "This workspace is already saved on this device. Open it from the workspace switcher to check its status. A different invitation cannot replace an existing join request.";
  }
  if (raw.includes("identity_mismatch")) {
    return "This invitation’s identity check failed.";
  }
  if (raw.includes("invitation_expired")) {
    return "This invitation has expired. Ask the sender to create a new one.";
  }
  if (raw.includes("invitation_invalid")) {
    return "This does not appear to be a complete Mesh Chat invitation or connection document. Open the original Mesh Chat file or copy the entire value, including its prefix and everything after the colon.";
  }
  if (raw.includes("invitation_file_type_invalid")) {
    return "Choose a .meshchat-invite, .meshchat-connect, .meshchat-route, .meshchat, or JSON invitation file.";
  }
  if (raw.includes("invitation_file_too_large")) {
    return "That invitation file is larger than Mesh Chat can open safely.";
  }
  if (raw.includes("invitation_file_encoding_invalid")) {
    return "That invitation file is not valid UTF-8 text. Ask the sender to share the original Mesh Chat file again.";
  }
  if (raw.includes("invitation_file_invalid")) {
    return "That file does not contain a complete Mesh Chat invitation or connection document.";
  }
  if (raw.includes("invitation_file_unavailable")) {
    return "Android could not read that file. Download it to this device and try again.";
  }
  if (raw.includes("contact_not_approved")) {
    return "This contact is not approved for that action.";
  }
  if (raw.includes("contact_in_use")) {
    return "Remove this contact from any pending group invitations before deleting them.";
  }
  if (raw.includes("stale_cursor")) {
    return "History changed while this page was open. Reload from the newest retained page.";
  }
  if (raw.includes("history_pruned")) {
    return "That history was pruned from this device under the active retention preference.";
  }
  if (raw.includes("workspace_limit_reached")) {
    return "This device already has 16 workspaces. Remove a workspace you have left or closed before joining another.";
  }
  if (raw.includes("invalid_request")) {
    return "That information could not be validated.";
  }
  return "Something went wrong. Your saved messages were not discarded.";
}

function workspaceInvitationErrorMessage(error: unknown, value: string): string {
  if (error instanceof InvitationTransferError) return error.message;
  const raw = String(error);
  if (raw.includes("invitation_invalid")) {
    const trimmed = value.trim();
    if (isWorkspacePrefixOnly(trimmed)) return incompleteWorkspacePrefixMessage(trimmed);
    return "This is not a complete workspace invitation. It must include the full MESHWORKSPACE prefix, the colon, and all signed text after it. You can also open the original .meshchat-invite file.";
  }
  return errorMessage(error);
}

function importedDocumentErrorMessage(error: unknown): string {
  return error instanceof InvitationTransferError ? error.message : errorMessage(error);
}

function Button({
  children,
  variant = "primary",
  className = "",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
}) {
  return (
    <button className={`button button--${variant} ${className}`} {...props}>
      {children}
    </button>
  );
}

const directPhaseLabel: Record<DirectDoctorStep["phase"], string> = {
  precondition: "Internet route", ipv6: "Native IPv6", upnp: "UPnP",
  nat_pmp: "NAT-PMP", pcp: "PCP", firewall: "Host firewall",
  listener: "Invitation listener",
};

function directReasonLabel(reason: string): string {
  const labels: Record<string, string> = {
    ready_to_prepare: "Ready to prepare",
    no_default_route: "No active default Internet route",
    no_global_ipv4: "No directly assigned public IPv4",
    no_global_ipv6: "No usable global IPv6 on the active route",
    upnp_no_discovery: "No UPnP Internet gateway discovered",
    upnp_wan_private: "Upstream or double NAT detected",
    upnp_wan_shared: "Provider/shared NAT likely",
    upnp_mapping_denied: "The router denied the UPnP mapping",
    upnp_unsupported_lease: "The router does not support the requested UPnP lease",
    nat_pmp_no_response: "No NAT-PMP response",
    nat_pmp_mapping_denied: "The router denied the NAT-PMP mapping",
    pcp_no_response: "No PCP response",
    pcp_mapping_denied: "The router denied the PCP mapping",
    upstream_nat_detected: "Upstream or double NAT detected",
    listener_bind_failed: "The temporary listener could not start",
    windows_firewall_blocked: "Windows Firewall needs attention",
    windows_firewall_permission_required: "Permission will be requested after preparing",
    firewall_check_unsupported: "Check this device’s firewall manually",
    session_limit: "Too many temporary invitations are active",
    direct_public_ipv4: "Public IPv4 is assigned directly to this device",
    global_ipv6_available: "Usable global IPv6 is present",
    mapping_prepared: "Prepared, not externally verified",
    router_state_changed: "The router or address changed; create a new invitation",
    manual_setup_required: "Automatic setup is unavailable",
  };
  return labels[reason] ?? "Unavailable on this network";
}

function directActionLabel(action: string): string {
  const labels: Record<string, string> = {
    retry: "Retry after checking this network.",
    continue: "Continue to the remaining checks.",
    prepare_direct: "Prepare the invitation, then keep Mesh Chat open.",
    share_invitation: "Share the invitation and keep Mesh Chat open.",
    wait_for_recipient: "Keep Mesh Chat open while the recipient connects.",
    configure_firewall_after_prepare: "After preparing, allow only its temporary TCP port.",
    connect_to_internet: "Connect this device to the Internet and retry.",
    try_router_mapping: "Try a supported automatic router mapping or manual forward.",
    try_another_method: "Try another listed mapping method or manual forwarding.",
    check_host_firewall: "Check this device’s inbound firewall for the temporary TCP port.",
    configure_upstream_router_or_bridge_mode: "Forward through both routers or use modem bridge/passthrough mode.",
    contact_provider_or_use_approved_access_point: "Ask the provider about inbound service or choose an approved participant access point.",
    set_up_manual_forward_or_choose_explicit_fallback: "Set up a manual TCP forward, choose same-network mode, or explicitly select an approved access point.",
    stop_an_active_invitation: "Stop an older hosted invitation and retry.",
    check_active_network_profile: "Connect using the intended Windows network profile and retry.",
    retry_or_check_firewall: "Retry, then check the host firewall if binding still fails.",
    restart_app: "Restart Mesh Chat and try again.",
    follow_guided_firewall_instructions: "Use the guided narrow firewall rule or configure it manually.",
    use_ipv6_firewall_instructions: "Allow only the temporary TCP port in the IPv6 firewall, then retry.",
  };
  return labels[action] ?? "Retry after checking this network.";
}

function sanitizedDoctorSummary(report: DirectDoctorReport): string {
  return [
    `Mesh Chat direct connection: ${directReasonLabel(report.summary.reason)}`,
    ...report.checks.map((step) => `${directPhaseLabel[step.phase]}: ${step.result} — ${directReasonLabel(step.reason)}`),
    `Next action: ${directActionLabel(report.summary.recommended_action)}`,
  ].join("\n");
}

function canPrepareDirectHost(report: DirectDoctorReport): boolean {
  return report.summary.result === "available"
    || report.summary.result === "prepared_unverified";
}

function directFailureReport(reason: unknown): DirectDoctorReport | null {
  const details = (reason as { details?: Record<string, string> })?.details;
  if (!details?.phase || !details.result || !details.reason || !details.recommended_action) return null;
  const step = details as unknown as DirectDoctorStep;
  return { summary: step, checks: [step] };
}

function ReturnConnectionUnavailable({ report, busy, onRetry }: {
  report: DirectDoctorReport;
  busy: boolean;
  onRetry: () => void;
}) {
  return <section className="direct-host-warning" role="status" aria-label="Return connection unavailable">
    <h3>Automatic return connection unavailable</h3>
    <p>The invitation is valid, but Mesh Chat could not prepare an automatic inbound return connection on this device.</p>
    <p>Inbound traffic may be blocked by a Wi-Fi router or mobile carrier, or the device may be unable to prepare another listener. Changing between paste, file, or QR only changes how the invitation is transferred.</p>
    <details className="direct-help">
      <summary><CircleHelp size={17} /> Technical check</summary>
      <div className="direct-help__content">
        <p><strong>{directReasonLabel(report.summary.reason)}</strong></p>
        <p>{report.checks.map((step) => `${directPhaseLabel[step.phase]}: ${directReasonLabel(step.reason)}`).join(" · ")}</p>
      </div>
    </details>
    <Button variant="secondary" disabled={busy} onClick={onRetry}><RefreshCw size={17} /> {busy ? "Checking…" : "Check this network again"}</Button>
  </section>;
}

function DirectDoctorPanel({
  report,
  onRetry,
  onManualSetup,
  busy = false,
}: {
  report: DirectDoctorReport;
  onRetry: () => void;
  onManualSetup?: () => void;
  busy?: boolean;
}) {
  const [copied, setCopied] = useState(false);
  const automaticSetupUnavailable = report.summary.recommended_action === "set_up_manual_forward_or_choose_explicit_fallback"
    || [
      "manual_setup_required", "no_global_ipv6", "upnp_no_discovery",
      "upnp_mapping_denied", "upnp_unsupported_lease", "nat_pmp_no_response",
      "nat_pmp_mapping_denied", "pcp_no_response", "pcp_mapping_denied",
      "upnp_wan_private", "upnp_wan_shared", "upstream_nat_detected",
    ].includes(report.summary.reason);
  return <section className="direct-doctor" aria-label="Direct Internet connection check">
    <h3>{directReasonLabel(report.summary.reason)}</h3>
    <ul>{report.checks.map((step, index) => <li key={`${step.phase}-${index}`}><span>{directPhaseLabel[step.phase]}</span><strong>{directReasonLabel(step.reason)}</strong></li>)}</ul>
    <p>{directActionLabel(report.summary.recommended_action)}</p>
    <details className="direct-help" open={automaticSetupUnavailable}>
      <summary><CircleHelp size={17} /> What should I do next?</summary>
      <div className="direct-help__content">
        <section>
          <h4>Option 1 — Check automatic router access</h4>
          <ol>
            <li>Open your router’s mobile app or administration page. This is usually provided by your router or Internet provider.</li>
            <li>On a network you trust, look under <strong>Advanced</strong>, <strong>NAT</strong>, or <strong>Port forwarding</strong> and enable <strong>UPnP</strong>, <strong>PCP</strong>, or <strong>NAT-PMP</strong> if your router offers it.</li>
            <li>Make sure this device is on the main network—not a guest network—and then choose <strong>Retry</strong> below.</li>
          </ol>
          <p className="direct-help__note">Enabling UPnP lets other software on this local network request mappings too. Use it only on a network you control and trust.</p>
        </section>
        <section>
          <h4>Option 2 — Create one manual TCP rule</h4>
          <p>Choose <strong>Start guided manual setup</strong>. Mesh Chat will start a temporary authenticated listener and show the exact device and TCP port to enter in your router.</p>
          {onManualSetup && <Button variant="secondary" disabled={busy} onClick={onManualSetup}>{busy ? "Starting…" : "Start guided manual setup"}</Button>}
        </section>
        <section>
          <h4>If neither option is available</h4>
          <p>Use <strong>Same network only</strong> when both people are on the same network, or explicitly choose an approved access point. Provider/shared NAT may require your Internet provider.</p>
        </section>
      </div>
    </details>
    <div className="dialog-actions"><Button variant="secondary" disabled={busy} onClick={onRetry}><RefreshCw size={17} /> Retry</Button><Button variant="ghost" onClick={async () => { await navigator.clipboard.writeText(sanitizedDoctorSummary(report)); setCopied(true); }}><Copy size={17} /> {copied ? "Copied" : "Copy diagnostic summary"}</Button></div>
  </section>;
}

function ManualForwardingPanel({
  setup,
  host,
  port,
  busy,
  onHostChange,
  onPortChange,
  onCreate,
}: {
  setup: ManualParticipantSetup;
  host: string;
  port: string;
  busy: boolean;
  onHostChange: (value: string) => void;
  onPortChange: (value: string) => void;
  onCreate: () => void;
}) {
  return <section className="manual-forward" aria-labelledby={`manual-forward-${setup.setup_id}`}>
    <h3 id={`manual-forward-${setup.setup_id}`}>Manual TCP forwarding</h3>
    <p>Keep this screen and Mesh Chat open. The temporary listener is ready; complete these steps before creating the invitation.</p>
    <ol className="manual-forward__steps">
      <li>
        <div><strong>Reserve this device in your router</strong><span>In the router’s app or administration page, open DHCP reservations, IP reservations, or connected devices. Reserve <b>{setup.device_label}</b> so its local address does not change.</span></div>
      </li>
      <li>
        <div><strong>Add one port-forwarding rule</strong><span>Open Port forwarding, NAT, or Virtual server and enter these exact values:</span>
          <dl className="manual-forward__rule">
            <div><dt>Device</dt><dd>{setup.device_label}</dd></div>
            <div><dt>Protocol</dt><dd>TCP only</dd></div>
            <div><dt>Internal port</dt><dd>{setup.tcp_port}</dd></div>
            <div><dt>External port</dt><dd>{port || setup.tcp_port}</dd></div>
          </dl>
        </div>
      </li>
      <li>
        <div><strong>Find the router’s Internet address</strong><span>In the router’s Internet, WAN, or status page, copy its public IPv4 address. You may use a global IPv6 address or a hostname you control instead.</span></div>
      </li>
      <li>
        <div><strong>Enter that address below and create the invitation</strong><span>Create a separate invitation for each person, then keep Mesh Chat open until that person connects and you approve them.</span></div>
      </li>
    </ol>
    <p className="direct-help__note"><strong>Check before continuing:</strong> if the router’s WAN address begins with 10, 192.168, 172.16–172.31, or 100.64–100.127, this router is behind another NAT. You also need a matching rule on the upstream router, bridge/passthrough mode, or help from your provider.</p>
    {setup.upstream_warning && <p className="direct-host-warning">Mesh Chat found evidence of another private or shared network upstream. This rule alone may not be reachable from the Internet; carrier-grade NAT usually requires your provider or an approved access point.</p>}
    <label className="field"><span>Router-reported public IPv4, global IPv6, or your hostname</span><input value={host} onChange={(event) => onHostChange(event.target.value)} autoCapitalize="off" autoCorrect="off" spellCheck={false} placeholder="Example: chat.example.net" /></label>
    <label className="field"><span>External TCP port</span><input inputMode="numeric" value={port} onChange={(event) => onPortChange(event.target.value.replace(/\D/g, ""))} /></label>
    <Button disabled={busy || !host.trim() || !Number(port)} onClick={onCreate}>{busy ? "Creating…" : "Create manual direct invitation"}</Button>
    <p className="manual-forward__cleanup"><strong>Afterward:</strong> remove this manual rule in the router when the invitation is no longer needed. Mesh Chat cannot remove a rule created in the router.</p>
  </section>;
}

function candidateSummary(results: ParticipantCandidateResult[]): string {
  const labels: Record<ParticipantCandidateResult["result"], string> = {
    connected: "connected", refused: "connection refused", timed_out: "timed out",
    no_ipv6_route: "no IPv6 route", unresolved: "hostname did not resolve safely",
  };
  return results.map((item) => `Candidate ${item.candidate} (${participantMethodLabel(item.path)}): ${labels[item.result]}`).join("\n");
}

function InvitationShare({ formats, onShared }: { formats: InvitationFormats; onShared?: () => void }) {
  const [feedback, setFeedback] = useState("");
  const [hostingStopped, setHostingStopped] = useState(false);
  const [firewallBusy, setFirewallBusy] = useState(false);

  const copyInvite = async () => {
    try {
      await navigator.clipboard.writeText(formats.text);
      onShared?.();
      setFeedback("Invitation copied.");
    } catch {
      setFeedback("Copy was unavailable. Select the invitation text above and copy it manually.");
    }
  };

  const shareInvite = async () => {
    if (typeof navigator.share !== "function") {
      await copyInvite();
      return;
    }
    try {
      await navigator.share({
        title: "Mesh Chat invitation",
        text: formats.text,
      });
      onShared?.();
      setFeedback("Invitation shared.");
    } catch (reason) {
      if (reason instanceof DOMException && reason.name === "AbortError") return;
      await copyInvite();
    }
  };

  const saveInvite = () => {
    const blob = new Blob([formats.file], { type: "application/json" });
    const anchor = document.createElement("a");
    anchor.href = URL.createObjectURL(blob);
    anchor.download = "mesh-chat-invite.meshchat-invite";
    anchor.click();
    URL.revokeObjectURL(anchor.href);
    setFeedback("Invitation file saved.");
    onShared?.();
  };

  const configureFirewall = async () => {
    if (!formats.host_session_id || firewallBusy) return;
    setFirewallBusy(true);
    try {
      const result = await serviceCommand<DirectDoctorStep>("configure_participant_firewall", { access_id: formats.host_session_id });
      setFeedback(result.result === "prepared_unverified"
        ? "Temporary Windows Firewall rule added for this invitation only."
        : `${directReasonLabel(result.reason)} ${directActionLabel(result.recommended_action)}`);
    } catch (reason) { setFeedback(errorMessage(reason)); }
    finally { setFirewallBusy(false); }
  };

  const stopHosting = async () => {
    if (!formats.host_session_id) return;
    try {
      await serviceCommand("stop_participant_host", { access_id: formats.host_session_id });
      setHostingStopped(true);
      setFeedback("Direct hosting stopped. Create a new Internet invitation to reconnect.");
    } catch (reason) {
      setFeedback(errorMessage(reason));
    }
  };

  return (
    <section className="invite-share" aria-label="Invitation details to share">
      <label className="field invite-details">
        <span>Invitation details to share</span>
        <textarea
          readOnly
          rows={5}
          value={formats.text}
          onFocus={(event) => event.currentTarget.select()}
          aria-describedby="invite-safety-note invite-expiry-note"
        />
      </label>
      <p id="invite-safety-note" className="muted invite-safety">
        Send everything in this box. It contains your public identity and connection hints, never your private key.
      </p>
      {formats.connection_mode === "participant" && <p className={hostingStopped ? "direct-host-warning" : "direct-host-status"} role="status">{hostingStopped ? <WifiOff size={17} /> : <ShieldCheck size={17} />} {hostingStopped ? "Direct hosting is stopped; this invitation cannot connect over the Internet." : "Prepared — waiting for recipient verification. Keep Mesh Chat open until they connect. No transport node is being used."}</p>}
      {formats.connection_mode === "email" && <p className="direct-host-status" role="status"><ShieldCheck size={17} /> Email-ready invitation. {formats.host_session_id ? "The recipient will try this device first and may check their device for a return connection if that path fails." : "This device could not host an inbound path. The recipient can still try an existing or same-network Mesh route, and may create a return reply only if their network accepts inbound traffic."} Mesh Chat never accesses either person’s email account.</p>}
      {formats.methods?.includes("manual") && <p className="muted">This invitation uses your manual router rule. Mesh Chat stops its listener when hosting ends, but cannot remove the rule from your router.</p>}
      <p id="invite-expiry-note" className="invite-expiry">
        Expires <time dateTime={new Date(formats.expires_at * 1000).toISOString()}>{formatExpiry(formats.expires_at)}</time>
      </p>
      <div className="invite-actions">
        <Button onClick={() => void copyInvite()}><Copy size={17} /> Copy details</Button>
        <Button variant="secondary" onClick={() => void shareInvite()}><Share2 size={17} /> Share invite</Button>
        <Button variant="ghost" onClick={saveInvite}><FileUp size={17} /> Save invite file</Button>
        {formats.host_session_id && !hostingStopped && <Button variant="ghost" disabled={firewallBusy} onClick={() => void configureFirewall()}><ShieldCheck size={17} /> {firewallBusy ? "Requesting permission…" : "Allow through Windows Firewall"}</Button>}
        {formats.host_session_id && !hostingStopped && <Button variant="ghost" onClick={() => void stopHosting()}><WifiOff size={17} /> Stop hosting</Button>}
      </div>
      <p className="invite-feedback" aria-live="polite">{feedback}</p>
      <InvitationQrCode document={formats.file} destination="chat" />
    </section>
  );
}

function ConnectionDocumentShare({ formats, kind, onShared }: { formats: ConnectionDocumentFormats; kind: "reply" | "route"; onShared?: () => void }) {
  const [feedback, setFeedback] = useState("");
  const label = kind === "reply" ? "connection reply" : "reconnect update";
  const copy = async () => {
    try { await navigator.clipboard.writeText(formats.text); setFeedback(`${kind === "reply" ? "Connection reply" : "Reconnect update"} copied.`); onShared?.(); }
    catch { setFeedback("Copy was unavailable. Select the complete text and copy it manually."); }
  };
  const share = async () => {
    if (typeof navigator.share !== "function") { await copy(); return; }
    try { await navigator.share({ title: `Mesh Chat ${label}`, text: formats.text }); setFeedback("Shared."); onShared?.(); }
    catch (reason) { if (!(reason instanceof DOMException && reason.name === "AbortError")) await copy(); }
  };
  const save = () => {
    const anchor = document.createElement("a");
    anchor.href = URL.createObjectURL(new Blob([formats.file], { type: "application/json" }));
    anchor.download = kind === "reply" ? "mesh-chat-connection.meshchat-connect" : "mesh-chat-reconnect.meshchat-route";
    anchor.click(); URL.revokeObjectURL(anchor.href); setFeedback("File saved."); onShared?.();
  };
  return <section className="invite-share" aria-label={`Signed ${label}`}>
    <label className="field"><span>Signed {label}</span><textarea readOnly rows={5} value={formats.text} onFocus={(event) => event.currentTarget.select()} /></label>
    <p className="muted">Share this small signed bootstrap document through email or any app you choose. Mesh Chat does not send it or read an inbox.</p>
    {kind === "reply" && <p className="direct-host-warning" role="status">This return listener is prepared locally but cannot verify itself from outside your network. Keep Mesh Chat open and, on a phone, foregrounded until the inviter connects. If sharing opens another app, return to Mesh Chat immediately.</p>}
    <p>Expires <time dateTime={new Date(formats.expires_at * 1000).toISOString()}>{formatExpiry(formats.expires_at)}</time></p>
    <div className="invite-actions"><Button onClick={() => void copy()}><Copy size={17} /> Copy</Button><Button variant="secondary" onClick={() => void share()}><Share2 size={17} /> Share</Button><Button variant="ghost" onClick={save}><FileUp size={17} /> Save file</Button></div>
    <p className="invite-feedback" aria-live="polite">{feedback}</p>
    <InvitationQrCode document={formats.file} destination={kind === "reply" ? "connection reply" : "reconnect update"} />
  </section>;
}

function Dialog({
  title,
  onClose,
  children,
  wide = false,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
  wide?: boolean;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLElement>(null);
  const onCloseRef = useRef(onClose);
  const titleId = useId();
  useEffect(() => { onCloseRef.current = onClose; }, [onClose]);
  useEffect(() => {
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      const currentDialog = dialogRef.current;
      if (!currentDialog || currentDialog.closest('[aria-hidden="true"]')) return;
      const visibleDialogs = [...document.querySelectorAll<HTMLElement>('[role="dialog"][aria-modal="true"]')]
        .filter((dialog) => !dialog.closest('[aria-hidden="true"]'));
      if (visibleDialogs.at(-1) !== currentDialog) return;
      if (event.key === "Escape" && !event.defaultPrevented) {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab" || event.defaultPrevented) return;
      const focusable = [...currentDialog.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), summary, [href], [tabindex]:not([tabindex="-1"])')]
        .filter((element) => element.getAttribute("aria-hidden") !== "true");
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable.at(-1)!;
      if (event.shiftKey && (document.activeElement === first || !currentDialog.contains(document.activeElement))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (document.activeElement === last || !currentDialog.contains(document.activeElement))) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      if (previousFocus?.isConnected) previousFocus.focus();
    };
  }, []);
  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        ref={dialogRef}
        className={`dialog ${wide ? "dialog--wide" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="dialog__header">
          <h2 id={titleId}>{title}</h2>
          <button ref={closeRef} className="icon-button" onClick={onClose} aria-label="Close">
            <X size={20} />
          </button>
        </div>
        {children}
      </section>
    </div>
  );
}

function callFingerprint(sdp: string): string {
  for (const line of sdp.split(/\r?\n/)) {
    if (line.startsWith("a=fingerprint:")) return line.slice("a=fingerprint:".length).trim();
  }
  throw new Error("The call could not be secured (no DTLS fingerprint).");
}

function CallDialog({
  contact,
  initialCall,
  onClose,
  onChanged,
}: {
  contact: Contact;
  initialCall?: CallSummary;
  onClose: () => void;
  onChanged: () => Promise<void>;
}) {
  const [call, setCall] = useState<CallSummary | undefined>(initialCall);
  const [media, setMedia] = useState<CallMedia | null>(null);
  const [phase, setPhase] = useState<"idle" | "preparing" | "calling" | "ringing" | "connecting" | "in_call" | "ended" | "error">(
    initialCall?.direction === "inbound" && initialCall.state === "ringing" ? "ringing" : "idle",
  );
  const [muted, setMuted] = useState(false);
  const [videoEnabled, setVideoEnabled] = useState(initialCall?.media === "video");
  const [path, setPath] = useState<"direct" | "relay" | "unknown">("unknown");
  const [quality, setQuality] = useState<"good" | "fair" | "poor" | "unknown">("unknown");
  const [error, setError] = useState("");
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const localVideoRef = useRef<HTMLVideoElement | null>(null);
  const remoteVideoRef = useRef<HTMLVideoElement | null>(null);
  const callIdRef = useRef<string | undefined>(initialCall?.id);
  const roleRef = useRef<"caller" | "callee" | undefined>(initialCall?.role);
  const remoteSetRef = useRef(false);
  const pollRef = useRef<number | null>(null);
  const pollBusyRef = useRef(false);
  const restartInFlightRef = useRef(false);
  const restartAnswerInFlightRef = useRef(false);
  const lastRestartOfferRef = useRef("");
  const lastRestartAnswerRef = useRef("");
  const restartRef = useRef<() => void>(() => undefined);

  const cleanup = useCallback(() => {
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    pcRef.current?.close();
    pcRef.current = null;
    if (audioRef.current) audioRef.current.srcObject = null;
    if (localVideoRef.current) localVideoRef.current.srcObject = null;
    if (remoteVideoRef.current) remoteVideoRef.current.srcObject = null;
    void endCallAudio().catch(() => undefined);
  }, []);

  useEffect(() => cleanup, [cleanup]);

  useEffect(() => {
    const onOnline = () => {
      if (!callIdRef.current) return;
      window.setTimeout(() => restartRef.current(), 1000);
    };
    window.addEventListener("online", onOnline);
    return () => window.removeEventListener("online", onOnline);
  }, []);

  const inspectPath = useCallback(async (pc: RTCPeerConnection) => {
    try {
      const stats = await pc.getStats();
      let relayed = false;
      let selectedPairId: string | null = null;
      stats.forEach((report) => {
        if (report.type === "transport" && report.selectedCandidatePairId) {
          selectedPairId = report.selectedCandidatePairId;
        }
      });
      stats.forEach((report) => {
        if (report.type === "candidate-pair" && (report.id === selectedPairId || report.selected)) {
          const local = stats.get(report.localCandidateId);
          const remote = stats.get(report.remoteCandidateId);
          if (local?.candidateType === "relay" || remote?.candidateType === "relay") relayed = true;
        }
      });
      setPath(relayed ? "relay" : "direct");
    } catch {
      setPath("unknown");
    }
  }, []);

  const inspectQuality = useCallback(async (pc: RTCPeerConnection) => {
    try {
      const stats = await pc.getStats();
      let lost = 0;
      let received = 0;
      let jitter = 0;
      stats.forEach((report) => {
        const value = report as unknown as Record<string, unknown>;
        if (value.type !== "inbound-rtp") return;
        lost += Number(value.packetsLost ?? 0);
        received += Number(value.packetsReceived ?? 0);
        jitter = Math.max(jitter, Number(value.jitter ?? 0));
      });
      const total = lost + received;
      const loss = total > 0 ? lost / total : 0;
      setQuality(loss > 0.08 || jitter > 0.08 ? "poor" : loss > 0.02 || jitter > 0.03 ? "fair" : total > 0 ? "good" : "unknown");
    } catch {
      setQuality("unknown");
    }
  }, []);

  const attachPeer = useCallback((configuration: CallIceConfiguration) => {
    const pc = new RTCPeerConnection({
      iceServers: configuration.iceServers,
      iceTransportPolicy: configuration.iceTransportPolicy,
    });
    pc.ontrack = (event) => {
      const stream = event.streams[0] ?? new MediaStream([event.track]);
      if (audioRef.current) {
        audioRef.current.srcObject = stream;
        void audioRef.current.play().catch(() => undefined);
      }
      if (event.track.kind === "video" && remoteVideoRef.current) {
        remoteVideoRef.current.srcObject = stream;
        setVideoEnabled(true);
        void remoteVideoRef.current.play().catch(() => undefined);
      }
    };
    pc.onconnectionstatechange = () => {
      if (pc.connectionState === "connected") {
        setPhase("in_call");
        setError("");
        void inspectPath(pc);
        void inspectQuality(pc);
        window.setTimeout(() => { void inspectQuality(pc); }, 3000);
      }
      if (pc.connectionState === "disconnected") {
        setPhase("connecting");
        window.setTimeout(() => restartRef.current(), 1500);
      }
      if (pc.connectionState === "failed") {
        setError("The media path could not be established.");
        setPhase("error");
      }
    };
    pcRef.current = pc;
    return pc;
  }, [inspectPath, inspectQuality]);

  const startPolling = useCallback((callId: string) => {
    if (pollRef.current !== null) window.clearInterval(pollRef.current);
    pollRef.current = window.setInterval(async () => {
      if (pollBusyRef.current) return;
      pollBusyRef.current = true;
      try {
        const latest = await serviceCommand<CallMedia>("call_media", { call_id: callId });
        setMedia(latest);
        setCall((current) => current ? { ...current, ...latest } : current);
        if (
          latest.restart_answer &&
          lastRestartAnswerRef.current !== latest.restart_answer &&
          pcRef.current?.signalingState === "have-local-offer"
        ) {
          await pcRef.current.setRemoteDescription({ type: "answer", sdp: latest.restart_answer });
          lastRestartAnswerRef.current = latest.restart_answer;
          remoteSetRef.current = true;
          setPhase("connecting");
          void inspectPath(pcRef.current);
        }
        if (
          latest.restart_offer &&
          roleRef.current === "callee" &&
          lastRestartOfferRef.current !== latest.restart_offer &&
          !restartAnswerInFlightRef.current
        ) {
          restartAnswerInFlightRef.current = true;
          try {
            const pc = pcRef.current;
            if (pc) {
              await pc.setRemoteDescription({ type: "offer", sdp: latest.restart_offer });
              const answer = await pc.createAnswer();
              await pc.setLocalDescription(answer);
              if (pc.iceGatheringState !== "complete") {
                await new Promise<void>((resolve) => {
                  const timeout = window.setTimeout(resolve, 3000);
                  const onChange = () => {
                    if (pc.iceGatheringState === "complete") {
                      window.clearTimeout(timeout);
                      pc.removeEventListener("icegatheringstatechange", onChange);
                      resolve();
                    }
                  };
                  pc.addEventListener("icegatheringstatechange", onChange);
                });
              }
              const sdp = pc.localDescription?.sdp;
              if (sdp) {
                await serviceCommand("answer_call_restart", {
                  call_id: callId,
                  sdp,
                  dtls_fingerprint: callFingerprint(sdp),
                });
                lastRestartOfferRef.current = latest.restart_offer;
                setPhase("connecting");
              }
            }
          } catch (reason) {
            setError(errorMessage(reason));
            setPhase("error");
          } finally {
            restartAnswerInFlightRef.current = false;
          }
        }
        if (latest.remote_sdp && !remoteSetRef.current && pcRef.current?.signalingState === "have-local-offer") {
          await pcRef.current.setRemoteDescription({ type: "answer", sdp: latest.remote_sdp });
          remoteSetRef.current = true;
          setPhase("connecting");
        }
        if (latest.state === "in_call") setPhase("in_call");
        if (["ended", "declined", "busy", "no_answer", "failed"].includes(latest.state)) {
          setPhase(latest.state === "failed" ? "error" : "ended");
          if (latest.state === "failed") setError("The call ended unexpectedly.");
        }
      } catch {
        // Keep the last safe state; the next event or explicit hangup updates it.
      } finally {
        pollBusyRef.current = false;
      }
    }, 1000);
  }, [inspectPath]);

  const prepareMedia = useCallback(async (media: "audio" | "video") => {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error("This device does not expose a microphone to Mesh Chat.");
    }
    if (await runtimePlatform() !== "desktop") {
      const permission = await requestMediaPermission();
      if (!permission.audio || (media === "video" && !permission.camera)) {
        throw new Error(media === "video" ? "Microphone and camera access are required for a video call." : "Microphone access is required for an audio call.");
      }
    }
    return navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      video: media === "video" ? { facingMode: "user", width: { ideal: 640 }, height: { ideal: 480 } } : false,
    });
  }, []);

  const waitForCandidates = useCallback(async (pc: RTCPeerConnection) => {
    if (pc.iceGatheringState === "complete") return;
    await new Promise<void>((resolve) => {
      const timeout = window.setTimeout(resolve, 3000);
      const onChange = () => {
        if (pc.iceGatheringState === "complete") {
          window.clearTimeout(timeout);
          pc.removeEventListener("icegatheringstatechange", onChange);
          resolve();
        }
      };
      pc.addEventListener("icegatheringstatechange", onChange);
    });
  }, []);

  const attemptRestart = useCallback(async () => {
    const callId = callIdRef.current;
    const pc = pcRef.current;
    if (!callId || !pc || restartInFlightRef.current) return;
    if (roleRef.current !== "caller" || pc.connectionState === "closed") return;
    restartInFlightRef.current = true;
    try {
      setPhase("connecting");
      const offer = await pc.createOffer({ iceRestart: true });
      await pc.setLocalDescription(offer);
      await waitForCandidates(pc);
      const sdp = pc.localDescription?.sdp;
      if (!sdp) throw new Error("The reconnecting call offer could not be created.");
      await serviceCommand("restart_call", {
        call_id: callId,
        sdp,
        dtls_fingerprint: callFingerprint(sdp),
      });
      setPhase("connecting");
    } catch (reason) {
      setError(errorMessage(reason));
      setPhase("error");
    } finally {
      restartInFlightRef.current = false;
    }
  }, [waitForCandidates]);
  restartRef.current = () => { void attemptRestart(); };

  const configureVideoSender = useCallback(async (pc: RTCPeerConnection, stream: MediaStream) => {
    const track = stream.getVideoTracks()[0];
    if (!track) return;
    const sender = pc.getSenders().find((candidate) => candidate.track === track);
    if (!sender) return;
    try {
      const capabilities = RTCRtpSender.getCapabilities("video");
      if (capabilities) {
        const codecs = [...capabilities.codecs].sort((left, right) => {
          const score = (mime: string) => mime === "video/VP8" ? 0 : mime === "video/VP9" ? 1 : 2;
          return score(left.mimeType) - score(right.mimeType);
        });
        pc.getTransceivers().find((transceiver) => transceiver.sender === sender)?.setCodecPreferences(codecs);
      }
    } catch {
      // The platform may not expose codec preferences; keep its default.
    }
    try {
      const parameters = sender.getParameters();
      if (parameters.encodings[0]) {
        parameters.encodings[0].maxBitrate = 500_000;
        await sender.setParameters(parameters);
      }
    } catch {
      // Bitrate shaping is best-effort; the call still proceeds.
    }
  }, []);

  const startCall = useCallback(async (media: "audio" | "video") => {
    setError("");
    setPhase("preparing");
    try {
      const stream = await prepareMedia(media);
      streamRef.current = stream;
      if (localVideoRef.current) localVideoRef.current.srcObject = stream;
      const focus = await beginCallAudio();
      if (!focus.granted) throw new Error("Android could not take call-audio focus.");
      const configuration = await serviceCommand<CallIceConfiguration>("call_ice_servers");
      const pc = attachPeer(configuration);
      stream.getTracks().forEach((track) => pc.addTrack(track, stream));
      void configureVideoSender(pc, stream);
      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      await waitForCandidates(pc);
      const sdp = pc.localDescription?.sdp;
      if (!sdp) throw new Error("The call offer could not be created.");
      const result = await serviceCommand<CallSummary>("start_call", {
        contact_id: contact.id,
        media,
        sdp,
        dtls_fingerprint: callFingerprint(sdp),
      });
      callIdRef.current = result.id;
      roleRef.current = result.role;
      setCall(result);
      setVideoEnabled(media === "video");
      setPhase("calling");
      startPolling(result.id);
      await onChanged();
    } catch (reason) {
      cleanup();
      setError(errorMessage(reason));
      setPhase("error");
    }
  }, [attachPeer, cleanup, configureVideoSender, contact.id, onChanged, prepareMedia, startPolling, waitForCandidates]);

  const acceptCall = useCallback(async () => {
    if (!call) return;
    setError("");
    setPhase("preparing");
    try {
      const details = await serviceCommand<CallMedia>("call_media", { call_id: call.id });
      if (!details.remote_sdp) throw new Error("This call invitation has no media description.");
      const stream = await prepareMedia(call.media);
      streamRef.current = stream;
      if (localVideoRef.current) localVideoRef.current.srcObject = stream;
      const focus = await beginCallAudio();
      if (!focus.granted) throw new Error("Android could not take call-audio focus.");
      const configuration = await serviceCommand<CallIceConfiguration>("call_ice_servers");
      const pc = attachPeer(configuration);
      await pc.setRemoteDescription({ type: "offer", sdp: details.remote_sdp });
      stream.getTracks().forEach((track) => pc.addTrack(track, stream));
      void configureVideoSender(pc, stream);
      const answer = await pc.createAnswer();
      await pc.setLocalDescription(answer);
      await waitForCandidates(pc);
      const sdp = pc.localDescription?.sdp;
      if (!sdp) throw new Error("The call answer could not be created.");
      const result = await serviceCommand<CallSummary>("answer_call", {
        call_id: call.id,
        sdp,
        dtls_fingerprint: callFingerprint(sdp),
      });
      setCall(result);
      roleRef.current = result.role;
      setMedia(details);
      setVideoEnabled(call.media === "video");
      setPhase("connecting");
      startPolling(call.id);
      await onChanged();
    } catch (reason) {
      cleanup();
      setError(errorMessage(reason));
      setPhase("error");
    }
  }, [attachPeer, call, cleanup, configureVideoSender, onChanged, prepareMedia, startPolling, waitForCandidates]);

  const hangup = useCallback(async (reason: "completed" | "declined" | "cancelled") => {
    const callId = callIdRef.current;
    cleanup();
    setPhase("ended");
    if (callId) {
      try {
        await serviceCommand("end_call", { call_id: callId, reason });
        await onChanged();
      } catch {
        // The call may already have ended on the other side.
      }
    }
    onClose();
  }, [cleanup, onChanged, onClose]);

  const toggleMute = useCallback(() => {
    const next = !muted;
    streamRef.current?.getAudioTracks().forEach((track) => { track.enabled = !next; });
    setMuted(next);
  }, [muted]);

  const toggleCamera = useCallback(() => {
    const next = !videoEnabled;
    streamRef.current?.getVideoTracks().forEach((track) => { track.enabled = next; });
    setVideoEnabled(next);
  }, [videoEnabled]);

  const incoming = call?.direction === "inbound";
  const active = phase === "in_call";

  return (
    <Dialog title={incoming ? `Call from ${contact.display_name}` : `Call ${contact.display_name}`} onClose={() => void hangup("cancelled")}>
      <div className="stack">
        <audio ref={audioRef} autoPlay playsInline hidden />
        <video ref={localVideoRef} className="call-video call-video--local" autoPlay muted playsInline hidden={!videoEnabled} />
        <video ref={remoteVideoRef} className="call-video" autoPlay playsInline hidden={!videoEnabled} />
        {phase === "idle" && (
          <>
            <p className="muted">Audio and video are sent directly to {contact.display_name} over the authenticated call path. Your microphone and camera start only after you choose a call.</p>
            <div className="dialog-actions">
              <Button variant="secondary" onClick={onClose}>Cancel</Button>
              <Button onClick={() => void startCall("audio")}><Phone size={17} /> Audio call</Button>
              <Button onClick={() => void startCall("video")}><Video size={17} /> Video call</Button>
            </div>
          </>
        )}
        {phase === "ringing" && (
          <>
            <p className="direct-host-status" role="status"><Phone size={17} /> Incoming {call?.media === "video" ? "video" : "audio"} call</p>
            <p className="muted">Your microphone and camera stay off until you accept.</p>
            <div className="dialog-actions">
              <Button variant="danger" onClick={() => void hangup("declined")}>Decline</Button>
              <Button onClick={() => void acceptCall()}><Phone size={17} /> Accept</Button>
            </div>
          </>
        )}
        {(phase === "preparing" || phase === "calling" || phase === "connecting") && (
          <>
            <p className="direct-host-status" role="status">
              <RefreshCw size={17} /> {phase === "preparing" ? "Preparing media…" : phase === "calling" ? "Calling and waiting for an answer…" : "Connecting the media path…"}
            </p>
            <p className="muted">The call uses the signed Reticulum signaling path; the media path is direct when the network allows it.</p>
            <div className="dialog-actions">
              <Button variant="secondary" onClick={() => void hangup("cancelled")}>Cancel</Button>
            </div>
          </>
        )}
        {active && (
          <>
            <p className="direct-host-status" role="status"><Phone size={17} /> In call · {path === "relay" ? "Relayed via TURN" : path === "direct" ? "Direct media" : "Checking media path"} · {quality === "unknown" ? "Measuring quality" : quality === "good" ? "Good quality" : quality === "fair" ? "Fair quality" : "Poor quality"}</p>
            <div className="dialog-actions">
              <Button variant="secondary" onClick={toggleMute}>{muted ? <MicOff size={17} /> : <Mic size={17} />} {muted ? "Unmute" : "Mute"}</Button>
              {call?.media === "video" && <Button variant="secondary" onClick={toggleCamera}>{videoEnabled ? <Video size={17} /> : <VideoOff size={17} />} {videoEnabled ? "Camera off" : "Camera on"}</Button>}
              <Button variant="danger" onClick={() => void hangup("completed")}><PhoneOff size={17} /> Hang up</Button>
            </div>
          </>
        )}
        {phase === "ended" && <p className="muted">Call ended.</p>}
        {phase === "error" && <p className="form-error" role="alert">{error || "The call could not connect."}</p>}
        {media && active && <p className="muted">{media.candidate_count} network candidate{media.candidate_count === 1 ? "" : "s"} exchanged.</p>}
        {phase === "error" && <div className="dialog-actions">{call && <Button onClick={() => void startCall(call.media)}>Try again</Button>}<Button variant="secondary" onClick={onClose}>Close</Button></div>}
      </div>
    </Dialog>
  );
}

function Onboarding({
  initialInvitation,
  onReady,
}: {
  initialInvitation: string;
  onReady: (snapshot: Snapshot, pendingInvitation?: string) => void;
}) {
  const initialWorkspacePrefixOnly = isWorkspaceInvitationValue(initialInvitation) && isWorkspacePrefixOnly(initialInvitation);
  const [mode, setMode] = useState<OnboardingMode>(initialInvitation ? "join" : "home");
  const [name, setName] = useState("");
  const [invitation, setInvitation] = useState(initialInvitation);
  const [pendingWorkspaceInvitation, setPendingWorkspaceInvitation] = useState("");
  const [workspaceContext, setWorkspaceContext] = useState<OnboardingWorkspaceContext | null>(null);
  const [preview, setPreview] = useState<InvitationPreview | null>(null);
  const [formats, setFormats] = useState<InvitationFormats | null>(null);
  const [remoteConsent, setRemoteConsent] = useState(false);
  const [i2pConsent, setI2PConsent] = useState(false);
  const [reachabilityWarning, setReachabilityWarning] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(() => initialWorkspacePrefixOnly ? incompleteWorkspacePrefixMessage(initialInvitation) : "");
  const previewGeneration = useRef(0);

  const inspectInvitation = useCallback(async (candidate: string) => {
    const generation = ++previewGeneration.current;
    setBusy(true);
    setError("");
    setPreview(null);
    setPendingWorkspaceInvitation("");
    setWorkspaceContext(null);
    let normalized = candidate;
    try {
      normalized = await normalizeInvitationInput(candidate);
      if (generation !== previewGeneration.current) return;
      setInvitation(normalized);
      const kind = classifyInvitationInput(normalized);
      if (kind === "workspace" || kind === "workspace_device") {
        if (isWorkspacePrefixOnly(normalized)) {
          setMode("join");
          setError(incompleteWorkspacePrefixMessage(normalized));
          return;
        }
        if (kind === "workspace_device") {
          const checked = await serviceCommand<WorkspaceDeviceLinkPreview>(
            "preview_workspace_device_link",
            { device_link: normalized },
          );
          if (generation !== previewGeneration.current) return;
          setWorkspaceContext({
            kind: "device",
            name: checked.name,
            memberDisplayName: checked.member_display_name,
          });
        } else {
          const checked = await serviceCommand<WorkspaceInvitationPreview>(
            "preview_workspace_invitation",
            { invitation: normalized },
          );
          if (generation !== previewGeneration.current) return;
          setWorkspaceContext({
            kind: "workspace",
            name: checked.name,
            description: checked.description,
          });
        }
        setPendingWorkspaceInvitation(normalized);
        setMode("start");
        return;
      }
      const checked = await serviceCommand<InvitationPreview>("preview_invitation", {
        invitation: normalized,
      });
      if (generation !== previewGeneration.current) return;
      setPreview(checked);
      setRemoteConsent(false); setI2PConsent(false);
      setMode("join");
    } catch (reason) {
      if (generation !== previewGeneration.current) return;
      setMode("join");
      setPreview(null);
      setPendingWorkspaceInvitation("");
      setWorkspaceContext(null);
      setError(isWorkspaceInvitationValue(normalized)
        ? workspaceInvitationErrorMessage(reason, normalized)
        : importedDocumentErrorMessage(reason));
    } finally {
      if (generation === previewGeneration.current) setBusy(false);
    }
  }, []);

  useEffect(() => {
    if (!initialInvitation) return;
    setInvitation(initialInvitation);
    setMode("join");
    void inspectInvitation(initialInvitation);
    return () => { previewGeneration.current += 1; };
  }, [initialInvitation, inspectInvitation]);

  const createProfile = async () => {
    setBusy(true);
    setError("");
    try {
      await serviceCommand("create_profile", { display_name: name });
      if (mode === "join") {
        await serviceCommand("accept_invitation", { invitation, ...(preview?.i2p_access_point ? { i2p_consent: i2pConsent } : {}) });
        onReady(await serviceCommand<Snapshot>("snapshot"));
      } else {
        onReady(await serviceCommand<Snapshot>("snapshot"), pendingWorkspaceInvitation || undefined);
      }
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const previewInvite = async () => {
    await inspectInvitation(invitation);
  };

  if (formats) {
    return (
      <main className="onboarding">
        <div className="onboarding__brand"><Brand /></div>
        <section className="invite-card panel">
          <div className="success-mark"><Check size={28} /></div>
          <p className="eyebrow">You’re ready</p>
          <h1>Invite someone you trust</h1>
          <p className="muted">They can open this on a device that already has Mesh Chat.</p>
          {reachabilityWarning && <p className="direct-host-warning" role="status"><WifiOff size={17} /> {reachabilityWarning}</p>}
          <InvitationShare formats={formats} />
          <Button variant="ghost" onClick={async () => onReady(await serviceCommand("snapshot"))}>
            Open Mesh Chat <ChevronRight size={18} />
          </Button>
        </section>
      </main>
    );
  }

  return (
    <main className="onboarding">
      <div className="onboarding__brand"><Brand /></div>
      <section className="welcome-card">
        {mode !== "home" && (
          <button className="back-link" onClick={() => { previewGeneration.current += 1; setBusy(false); setMode("home"); setPreview(null); setRemoteConsent(false); setI2PConsent(false); setPendingWorkspaceInvitation(""); setWorkspaceContext(null); setInvitation(""); setError(""); }}>
            <ArrowLeft size={18} /> Back
          </button>
        )}
        {mode === "home" && (
          <>
            <div className="welcome-art" aria-hidden="true">
              <div className="node node--one" /><div className="node node--two" />
              <div className="node node--three" /><div className="mesh-line mesh-line--one" />
              <div className="mesh-line mesh-line--two" /><LockKeyhole size={34} />
            </div>
            <p className="eyebrow">Private by design</p>
            <h1>Chat without a central server.</h1>
            <p className="lede">
              Messages move directly through devices you choose and stay encrypted along the way.
            </p>
            <div className="welcome-actions">
              <Button onClick={() => setMode("start")}><MessageCircleMore size={19} /> Start a chat</Button>
              <Button variant="secondary" onClick={() => setMode("join")}><UserRoundPlus size={19} /> Join a chat</Button>
            </div>
            <p className="privacy-note"><ShieldCheck size={17} /> No account, phone number, telemetry, or cloud backup.</p>
          </>
        )}

        {mode === "start" && (
          <form onSubmit={(event) => { event.preventDefault(); void createProfile(); }}>
            <p className="eyebrow">{workspaceContext?.kind === "device" ? "Link a device" : pendingWorkspaceInvitation ? "Join a workspace" : "Start a chat"}</p>
            <h1>{workspaceContext ? `Set up this device for ${workspaceContext.name}` : "What should people call you?"}</h1>
            <p className="muted">{workspaceContext?.kind === "device"
              ? `This signed link is for ${workspaceContext.memberDisplayName}. Choose the name the workspace owner will review for this device.`
              : workspaceContext
                ? `${workspaceContext.description || `You’re joining ${workspaceContext.name}.`} Choose the name the workspace owner will review with your signed join request.`
                : "This name is shared only in invitations and connection requests."}</p>
            <label className="field">
              <span>Display name</span>
              <input autoFocus value={name} onChange={(event) => setName(event.target.value)} maxLength={64} autoComplete="name" />
            </label>
            {error && <p className="form-error" role="alert">{error}</p>}
            <Button type="submit" disabled={!name.trim() || busy}>{busy ? "Creating…" : pendingWorkspaceInvitation ? "Create profile and continue" : "Create my invite"}</Button>
          </form>
        )}

        {mode === "join" && !preview && (
          <form onSubmit={(event) => { event.preventDefault(); void previewInvite(); }}>
            <p className="eyebrow">Join a chat</p>
            <h1>Open an invitation</h1>
            <p className="muted">Paste the invitation you received. It never looks anything up online.</p>
            <label className="field">
              <span>Invitation</span>
              <textarea autoFocus autoCapitalize="off" autoCorrect="off" spellCheck={false} rows={5} value={invitation} onChange={(event) => { previewGeneration.current += 1; setBusy(false); setInvitation(event.target.value); setError(""); }} placeholder="Paste a Mesh Chat invitation" />
            </label>
            <InvitationImportActions onValue={(value) => { previewGeneration.current += 1; setBusy(false); setInvitation(value); setError(""); }} />
            {error && <p className="form-error" role="alert">{error}</p>}
            <Button type="submit" disabled={!invitation.trim() || busy}>{busy ? "Checking…" : "Continue"}</Button>
          </form>
        )}

        {mode === "join" && preview && (
          <form onSubmit={(event) => { event.preventDefault(); void createProfile(); }}>
            <p className="eyebrow">Invitation checked</p>
            <div className="person-preview"><Avatar name={preview.display_name} /><div><h1>Connect to {preview.display_name}</h1><p>Claimed name · identity signature valid</p></div></div>
            <label className="field">
              <span>Your display name</span>
              <input autoFocus value={name} onChange={(event) => setName(event.target.value)} maxLength={64} />
            </label>
            <SecurityDetails fingerprint={preview.fingerprint} destination={preview.destination_hash} />
            {preview.participant_access && <section className="direct-consent" aria-labelledby="onboarding-direct-connection"><h3 id="onboarding-direct-connection">Direct connection to the inviter</h3><p>{preview.participant_access.privacy_disclosure}</p><p>They must keep Mesh Chat open until this device connects.</p></section>}
            {preview.remote_profile && <section className="remote-consent" aria-labelledby="onboarding-remote-consent"><h3 id="onboarding-remote-consent">Remote connection requested</h3><p><strong>{preview.remote_profile.label}</strong> · {preview.remote_profile.endpoint_count} access-point {preview.remote_profile.endpoint_count === 1 ? "endpoint" : "endpoints"}</p><p>{preview.remote_profile.privacy_disclosure}</p><label className="checkbox-line"><input type="checkbox" checked={remoteConsent} onChange={(event) => setRemoteConsent(event.target.checked)} /> Connect to this access point after I create my profile</label></section>}
            {preview.i2p_access_point && <section className="remote-consent" aria-labelledby="onboarding-i2p-consent"><h3 id="onboarding-i2p-consent">I2P relay requested</h3><p>Traffic will be relayed through <code>{preview.i2p_access_point.b32}</code>. This is not a direct connection.</p><label className="checkbox-line"><input type="checkbox" checked={i2pConsent} onChange={(event) => setI2PConsent(event.target.checked)} /> Use this I2P access point after I create my profile</label></section>}
            {error && <p className="form-error" role="alert">{error}</p>}
            <Button type="submit" disabled={!name.trim() || busy || Boolean(preview.remote_profile) && !remoteConsent || Boolean(preview.i2p_access_point) && !i2pConsent}>{busy ? "Connecting…" : preview.remote_profile ? "Create profile and connect" : preview.participant_access ? `Connect directly to ${preview.display_name}` : `Connect to ${preview.display_name}`}</Button>
          </form>
        )}
      </section>
    </main>
  );
}

function Brand() {
  return <div className="brand"><span className="brand__mark"><MessageCircleMore size={21} /></span><span>Mesh Chat</span></div>;
}

function Avatar({ name, small = false }: { name: string; small?: boolean }) {
  const hue = [...name].reduce((sum, char) => sum + char.charCodeAt(0), 0) % 5;
  return <span className={`avatar avatar--${hue} ${small ? "avatar--small" : ""}`} aria-hidden="true">{initials(name)}</span>;
}

function GroupAvatar({ group, small = false }: { group: Group; small?: boolean }) {
  const channel = group.posting_policy === "owner_admins";
  return (
    <span className={`avatar group-avatar ${channel ? "group-avatar--channel" : ""} ${small ? "avatar--small" : ""}`} aria-hidden="true">
      {channel ? <Megaphone size={small ? 18 : 22} /> : <Users size={small ? 19 : 23} />}
    </span>
  );
}

function SecurityDetails({ fingerprint, destination, open, onOpenChange }: { fingerprint: string; destination: string; open?: boolean; onOpenChange?: (open: boolean) => void }) {
  const controlled = open === undefined ? {} : { open };
  return (
    <details className="security-details" {...controlled}>
      <summary onClick={open === undefined ? undefined : (event) => { event.preventDefault(); onOpenChange?.(!open); }}><ShieldCheck size={17} /> Security details</summary>
      <p>Compare this fingerprint independently when a conversation needs stronger identity assurance.</p>
      <code>{fingerprint}</code>
      <span>Address</span><code>{destination}</code>
    </details>
  );
}

function NewChatDialog({ initialInvitation, remoteProfiles, onClose, onChanged, onWorkspaceInvitation }: { initialInvitation: string; remoteProfiles: RemoteProfile[]; onClose: () => void; onChanged: () => Promise<void>; onWorkspaceInvitation: (value: string) => void }) {
  const [tab, setTab] = useState<"invite" | "join">(initialInvitation ? "join" : "invite");
  const [formats, setFormats] = useState<InvitationFormats | null>(null);
  const [raw, setRaw] = useState(initialInvitation);
  const [preview, setPreview] = useState<InvitationPreview | null>(null);
  const [error, setError] = useState("");
  const [inviteError, setInviteError] = useState("");
  const [busy, setBusy] = useState(false);
  const [connectionChoice, setConnectionChoice] = useState(() => getWebRTCSession() ? "webrtc" : "participant");
  const [remoteConsent, setRemoteConsent] = useState(false);
  const [i2pConsent, setI2PConsent] = useState(false);
  const [doctor, setDoctor] = useState<DirectDoctorReport | null>(null);
  const [manualSetup, setManualSetup] = useState<ManualParticipantSetup | null>(null);
  const [manualHost, setManualHost] = useState("");
  const [manualPort, setManualPort] = useState("");
  const [i2pAccessPoint, setI2PAccessPoint] = useState("");
  const [shared, setShared] = useState(false);
  const [candidateResults, setCandidateResults] = useState<ParticipantCandidateResult[]>([]);
  const [replyFormats, setReplyFormats] = useState<ConnectionDocumentFormats | null>(null);
  const [replyShared, setReplyShared] = useState(false);
  const [replyDoctor, setReplyDoctor] = useState<DirectDoctorReport | null>(null);
  const [requestQueued, setRequestQueued] = useState(false);
  const [connectionReplyPreview, setConnectionReplyPreview] = useState<ConnectionReplyPreview | null>(null);
  const [routeUpdatePreview, setRouteUpdatePreview] = useState<RouteUpdatePreview | null>(null);
  const generatedHostSession = useRef<string | null>(null);
  const replyHostSession = useRef<string | null>(null);
  const usableProfiles = remoteProfiles.filter((profile) => profile.state !== "expired");

  const stopUnsharedHost = async () => {
    const id = generatedHostSession.current;
    if (id && !shared) await serviceCommand("stop_participant_host", { access_id: id }).catch(() => undefined);
    generatedHostSession.current = null;
    const replyId = replyHostSession.current;
    if (replyId && !replyShared) await serviceCommand("stop_participant_host", { access_id: replyId }).catch(() => undefined);
    replyHostSession.current = null;
  };
  const closeDialog = async () => { await stopUnsharedHost(); onClose(); };
  const chooseConnection = async (value: string) => {
    await stopUnsharedHost();
    setConnectionChoice(value); setFormats(null); setManualSetup(null); setDoctor(null);
    setInviteError(""); setShared(false);
  };
  const checkDirect = async () => {
    setBusy(true); setInviteError("");
    try { setDoctor(await serviceCommand<DirectDoctorReport>("check_direct_connection")); }
    catch (reason) { setInviteError(errorMessage(reason)); }
    finally { setBusy(false); }
  };
  const prepareManual = async () => {
    setBusy(true); setInviteError("");
    try {
      await stopUnsharedHost();
      const setup = await serviceCommand<ManualParticipantSetup>("prepare_manual_participant_host", { purpose: "personal" });
      generatedHostSession.current = setup.setup_id;
      setManualSetup(setup); setManualHost(""); setManualPort(String(setup.tcp_port)); setDoctor(null); setFormats(null); setShared(false);
    } catch (reason) { setInviteError(errorMessage(reason)); }
    finally { setBusy(false); }
  };
  const createInvitation = async (manual = false) => {
    setBusy(true); setInviteError("");
    try {
      const payload = manual && manualSetup
        ? { connection_mode: "manual", manual_setup_id: manualSetup.setup_id, external_host: manualHost.trim(), external_port: Number(manualPort) }
        : connectionChoice === "participant" ? { connection_mode: "participant" }
          : connectionChoice === "webrtc" ? { connection_mode: "webrtc" }
          : connectionChoice === "email" ? { connection_mode: "email" }
          : connectionChoice === "nearby" ? { connection_mode: "nearby" }
          : connectionChoice === "i2p" ? { connection_mode: "i2p", i2p_access_point: i2pAccessPoint.trim() }
            : { connection_mode: "remote", remote_profile_id: connectionChoice.slice("remote:".length) };
      const created = await serviceCommand<InvitationFormats>("create_invitation", payload);
      const previous = generatedHostSession.current;
      if (previous && previous !== created.host_session_id) await serviceCommand("stop_participant_host", { access_id: previous }).catch(() => undefined);
      generatedHostSession.current = created.host_session_id ?? null;
      setFormats(created); setShared(false); setManualSetup(null);
    } catch (reason) {
      setFormats(null); setInviteError(errorMessage(reason));
      const details = (reason as { details?: Record<string, string> })?.details;
      if (details?.phase) setDoctor({ summary: details as unknown as DirectDoctorStep, checks: [details as unknown as DirectDoctorStep] });
    } finally { setBusy(false); }
  };

  useEffect(() => {
    if (!initialInvitation) return;
    let active = true;
    setRaw(initialInvitation); setTab("join"); setPreview(null); setRemoteConsent(false); setI2PConsent(false);
    setConnectionReplyPreview(null); setRouteUpdatePreview(null); setReplyDoctor(null); setRequestQueued(false); setError("");
    void (async () => {
      const normalized = await normalizeInvitationInput(initialInvitation);
      if (!active) return;
      setRaw(normalized);
      if (isWorkspaceInvitationValue(normalized)) {
        await stopUnsharedHost();
        if (active) onWorkspaceInvitation(normalized);
        return;
      }
      const documentKind = connectionDocumentKind(normalized);
      if (documentKind === "reply") {
        const checked = await serviceCommand<ConnectionReplyPreview>("preview_connection_reply", { response: normalized });
        if (active) setConnectionReplyPreview(checked);
      } else if (documentKind === "route") {
        const checked = await serviceCommand<RouteUpdatePreview>("preview_route_update", { update: normalized });
        if (active) setRouteUpdatePreview(checked);
      } else {
        const checked = await serviceCommand<InvitationPreview>("preview_invitation", { invitation: normalized });
        if (active) setPreview(checked);
      }
    })().catch((reason) => { if (active) setError(importedDocumentErrorMessage(reason)); });
    return () => { active = false; };
  }, [initialInvitation]);
  const check = async () => {
    setError("");
    setConnectionReplyPreview(null); setRouteUpdatePreview(null); setReplyFormats(null); setReplyDoctor(null); setRequestQueued(false); setCandidateResults([]);
    try {
      const normalized = await normalizeInvitationInput(raw);
      setRaw(normalized);
      if (isWorkspaceInvitationValue(normalized)) {
        await stopUnsharedHost();
        onWorkspaceInvitation(normalized);
        return;
      }
      const documentKind = connectionDocumentKind(normalized);
      if (documentKind === "reply") {
        setConnectionReplyPreview(await serviceCommand("preview_connection_reply", { response: normalized }));
        setPreview(null);
      } else if (documentKind === "route") {
        setRouteUpdatePreview(await serviceCommand("preview_route_update", { update: normalized }));
        setPreview(null);
      } else setPreview(await serviceCommand("preview_invitation", { invitation: normalized }));
      setRemoteConsent(false); setI2PConsent(false);
    }
    catch (reason) { setError(importedDocumentErrorMessage(reason)); }
  };
  const connect = async () => {
    if (busy || requestQueued) return;
    setBusy(true); setError(""); setCandidateResults([]);
    try {
      const accepted = await serviceCommand<Contact>("accept_invitation", { invitation: raw, ...(preview?.i2p_access_point ? { i2p_consent: i2pConsent } : {}) });
      await onChanged();
      if (accepted.connection_results?.length && !accepted.connection_results.some((item) => item.result === "connected")) {
        setCandidateResults(accepted.connection_results);
        setRequestQueued(true);
      } else if (preview?.connection_reply_available && !preview.participant_access) {
        setRequestQueued(true);
      } else onClose();
    } catch (reason) { setError(errorMessage(reason)); }
    finally { setBusy(false); }
  };
  const createReply = async () => {
    setBusy(true); setError("");
    try {
      const report = await serviceCommand<DirectDoctorReport>("check_direct_connection");
      if (!canPrepareDirectHost(report)) {
        setReplyDoctor(report);
        return;
      }
      setReplyDoctor(null);
      const created = await serviceCommand<ConnectionDocumentFormats>("create_connection_reply", { invitation: raw, purpose: "personal" });
      const previous = replyHostSession.current;
      replyHostSession.current = created.host_session_id ?? null;
      setReplyShared(false); setReplyFormats(created);
      if (previous && previous !== created.host_session_id) await serviceCommand("stop_participant_host", { access_id: previous }).catch(() => undefined);
    }
    catch (reason) {
      const report = directFailureReport(reason);
      if (report) setReplyDoctor(report);
      else setError(errorMessage(reason));
    }
    finally { setBusy(false); }
  };
  const applyConnectionDocument = async () => {
    setBusy(true); setError("");
    try {
      if (connectionReplyPreview) await serviceCommand("connect_using_reply", { response: raw });
      else await serviceCommand("apply_route_update", { update: raw });
      await onChanged(); onClose();
    } catch (reason) { setError(errorMessage(reason)); }
    finally { setBusy(false); }
  };
  return (
    <Dialog title="New chat" onClose={() => void closeDialog()} wide>
      <div className="tabs" role="tablist">
        <button role="tab" aria-selected={tab === "invite"} onClick={() => setTab("invite")}>Share an invite</button>
        <button role="tab" aria-selected={tab === "join"} onClick={() => { void stopUnsharedHost(); setTab("join"); }}>Open an invite</button>
      </div>
      {tab === "invite" && <label className="field"><span>How should they connect?</span><select value={connectionChoice} disabled={busy} onChange={(event) => void chooseConnection(event.target.value)}><option value="participant">Over the Internet — directly to this device (default)</option>{getWebRTCSession() && <option value="webrtc">WebRTC bridge — connected</option>}<option value="email">Email-assisted direct connection — reverse direction if possible</option><option value="nearby">Same network only — will not work over cellular</option><option value="i2p">I2P access point — relayed through I2P</option>{usableProfiles.map((profile) => <option key={profile.id} value={`remote:${profile.id}`}>Approved access point · {profile.label} · {profile.state === "connected" ? "connected" : "currently unavailable"}</option>)}</select></label>}
      {tab === "invite" && connectionChoice === "i2p" && !formats && <div className="stack"><p className="muted">The invitation is signed by this device and carries one I2P access point address. The recipient must consent before traffic is relayed through it. I2P is a relay, not a direct connection.</p><label className="field"><span>I2P access point address</span><input value={i2pAccessPoint} onChange={(event) => setI2PAccessPoint(event.target.value.trim())} placeholder="example.b32.i2p" spellCheck={false} /></label><Button disabled={busy || !/^[a-z2-7]{52}\.b32\.i2p$/i.test(i2pAccessPoint)} onClick={() => void createInvitation()}>{busy ? "Creating…" : "Create I2P invitation"}</Button></div>}
      {tab === "invite" && connectionChoice === "webrtc" && !formats && <div className="stack"><p className="muted">This invitation uses the connected WebRTC DataChannel. The recipient must already have the matching bridge and still reviews and approves the signed request.</p><Button disabled={busy} onClick={() => void createInvitation()}>{busy ? "Creating…" : "Create invitation over WebRTC"}</Button></div>}
      {tab === "invite" && connectionChoice === "participant" && !formats && <div className="stack"><p className="muted">Direct participant hosting stays on this device. Keep Mesh Chat open during invitation and approval. No server, rendezvous service, or transport operator is added.</p><div className="dialog-actions"><Button variant="secondary" disabled={busy} onClick={() => void checkDirect()}>{busy ? "Checking this network…" : "Check direct Internet connection"}</Button><Button disabled={busy} onClick={() => void createInvitation()}>{busy ? "Preparing a direct route…" : "Prepare direct Internet invitation"}</Button><Button variant="ghost" disabled={busy} onClick={() => void prepareManual()}>Set up manual port forwarding</Button></div>{doctor && <DirectDoctorPanel report={doctor} busy={busy} onRetry={() => void checkDirect()} onManualSetup={() => void prepareManual()} />}{manualSetup && <ManualForwardingPanel setup={manualSetup} host={manualHost} port={manualPort} busy={busy} onHostChange={setManualHost} onPortChange={setManualPort} onCreate={() => void createInvitation(true)} />}</div>}
      {tab === "invite" && connectionChoice === "nearby" && !formats && <div className="stack"><p className="direct-host-warning">Same network only — will not work over cellular.</p><Button disabled={busy} onClick={() => void createInvitation()}>{busy ? "Creating…" : "Create same-network invitation"}</Button></div>}
      {tab === "invite" && connectionChoice === "email" && !formats && <div className="stack"><p className="muted">Creates a signed invitation even when this device cannot accept inbound traffic. The recipient first tries any existing or same-network Mesh route; a return reply works only if the recipient’s network can accept inbound traffic.</p><p className="muted">Email carries bootstrap files only; Mesh Chat never logs in, sends mail, or polls an inbox. If both networks block inbound connections and no shared route exists, invitation exchange alone cannot create one.</p><Button disabled={busy} onClick={() => void createInvitation()}>{busy ? "Creating…" : "Create email-ready invitation"}</Button></div>}
      {tab === "invite" && connectionChoice.startsWith("remote:") && !formats && <div className="stack"><p className="muted">This explicitly selected, named access point can observe connection metadata, but not message content.</p><Button disabled={busy} onClick={() => void createInvitation()}>{busy ? "Creating…" : "Create invitation using selected access point"}</Button></div>}
      {tab === "invite" && formats && <InvitationShare formats={formats} onShared={() => setShared(true)} />}
      {tab === "invite" && inviteError && <p className="form-error" role="alert">{inviteError}</p>}
      {tab === "join" && !preview && !connectionReplyPreview && !routeUpdatePreview && <div className="stack"><label className="field"><span>Invitation, connection reply, or reconnect update</span><textarea aria-label="Invitation" autoCapitalize="off" autoCorrect="off" spellCheck={false} rows={5} value={raw} onChange={(event) => { setRaw(event.target.value); setReplyDoctor(null); setRequestQueued(false); setError(""); }} /></label><InvitationImportActions onValue={(value) => { setRaw(value); setReplyDoctor(null); setRequestQueued(false); setError(""); }} /><Button onClick={() => void check()} disabled={!raw.trim()}>Check invitation</Button></div>}
      {tab === "join" && connectionReplyPreview && <div className="stack"><h3>Connection reply verified</h3><p>This response is bound to the exact invitation created on this device.</p><SecurityDetails fingerprint={connectionReplyPreview.responder_fingerprint} destination={connectionReplyPreview.responder_destination} /><p>{connectionReplyPreview.endpoint_count} direct callback {connectionReplyPreview.endpoint_count === 1 ? "candidate" : "candidates"}. Importing it does not approve a contact or workspace member.</p><Button disabled={busy} onClick={() => void applyConnectionDocument()}>{busy ? "Connecting…" : "Connect using reply"}</Button></div>}
      {tab === "join" && routeUpdatePreview && <div className="stack"><h3>Reconnect update verified</h3><p><strong>{routeUpdatePreview.issuer_display_name}</strong> signed route generation {routeUpdatePreview.generation}. Existing approval or workspace membership will not be repeated.</p><SecurityDetails fingerprint={routeUpdatePreview.issuer_fingerprint} destination={routeUpdatePreview.issuer_destination} /><Button disabled={busy} onClick={() => void applyConnectionDocument()}>{busy ? "Reconnecting…" : "Apply reconnect update"}</Button></div>}
      {tab === "join" && preview && <div className="stack">
        <div className="person-preview"><Avatar name={preview.display_name} /><div><h3>{preview.display_name}</h3><p>Identity signature valid</p></div></div>
        <SecurityDetails fingerprint={preview.fingerprint} destination={preview.destination_hash} />
        {preview.i2p_access_point && <section className="direct-consent" aria-labelledby="personal-i2p-connection"><h3 id="personal-i2p-connection">Relayed via I2P</h3><p>This signed invitation asks to use an I2P access point. Traffic is relayed; it is not a direct connection. The access point can see connection metadata, not message contents.</p><p><code>{preview.i2p_access_point.b32}</code></p><label className="checkbox-line"><input type="checkbox" checked={i2pConsent} onChange={(event) => setI2PConsent(event.target.checked)} /> Use this I2P access point</label></section>}
        {preview.participant_access && <section className="direct-consent" aria-labelledby="personal-direct-connection"><h3 id="personal-direct-connection">Direct connection to {preview.display_name}</h3><p>{preview.participant_access.privacy_disclosure}</p><p>No separate operator will join this chat or workspace.</p></section>}
        {preview.connection_reply_available && <section className="direct-consent"><h3>Connection options</h3><p>{preview.participant_access ? "Mesh Chat will try the inviter’s signed route first. If every candidate fails, this device can be checked for an optional return connection." : "Mesh Chat will first save and try the signed contact request over any existing or same-network Mesh route. If no route is confirmed, it will then offer to check this device for an optional return connection."}</p></section>}
        {preview.remote_profile && <section className="remote-consent" aria-labelledby="personal-remote-consent"><h3 id="personal-remote-consent">Remote connection requested</h3><p><strong>{preview.remote_profile.label}</strong> · {preview.remote_profile.endpoint_count} access-point {preview.remote_profile.endpoint_count === 1 ? "endpoint" : "endpoints"}</p><p>{preview.remote_profile.privacy_disclosure}</p><label className="checkbox-line"><input type="checkbox" checked={remoteConsent} onChange={(event) => setRemoteConsent(event.target.checked)} /> Connect to this access point after I continue</label></section>}
        {replyFormats && <ConnectionDocumentShare formats={replyFormats} kind="reply" onShared={() => setReplyShared(true)} />}
        {!requestQueued && <Button disabled={busy || Boolean(preview.remote_profile) && !remoteConsent || Boolean(preview.i2p_access_point) && !i2pConsent} onClick={() => void connect()}>{busy ? "Saving request…" : replyFormats ? "Send contact request after sharing" : preview.remote_profile ? "Connect and send contact request" : preview.participant_access ? `Connect directly to ${preview.display_name}` : "Send contact request"}</Button>}
        {requestQueued && <section className="direct-host-warning" role="status"><h3>{candidateResults.length > 0 ? "No candidate connected yet" : "Contact request saved"}</h3>{candidateResults.length > 0 && <pre>{candidateSummary(candidateResults)}</pre>}<p>{candidateResults.length > 0 ? "The signed request remains saved and will retry." : "No route has been confirmed yet. Mesh Chat will keep the signed request queued and retry any available route."} Checking a return connection does not approve a new identity.</p>{preview.connection_reply_available && !replyFormats && !replyDoctor && <Button variant="secondary" onClick={() => void createReply()} disabled={busy}>{busy ? "Checking this network…" : "Check this device for a return connection"}</Button>}<Button variant="ghost" onClick={() => void closeDialog()}>Continue</Button></section>}
        {replyDoctor && <ReturnConnectionUnavailable report={replyDoctor} busy={busy} onRetry={() => void createReply()} />}
      </div>}
      {error && <p className="form-error" role="alert">{error}</p>}
    </Dialog>
  );
}

function CreateGroupDialog({
  contacts,
  onClose,
  onCreated,
}: {
  contacts: Contact[];
  onClose: () => void;
  onCreated: (group: Group) => Promise<void>;
}) {
  const [mode, setMode] = useState<"group" | "channel">("group");
  const [title, setTitle] = useState("");
  const [memberIds, setMemberIds] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const eligible = contacts.filter((contact) => contact.trust === "approved" || contact.trust === "verified");
  const memberLimitReached = memberIds.length >= 7;
  const postingPolicy: GroupPostingPolicy = mode === "channel" ? "owner_admins" : "members";

  const toggleMember = (contactId: string) => {
    setMemberIds((current) => current.includes(contactId)
      ? current.filter((id) => id !== contactId)
      : current.length < 7 ? [...current, contactId] : current);
  };

  const create = async () => {
    if (!title.trim() || memberIds.length === 0) return;
    setBusy(true);
    setError("");
    try {
      const group = await serviceCommand<Group>("create_group", {
        title: title.trim(),
        member_ids: memberIds,
        posting_policy: postingPolicy,
      });
      await onCreated(group);
    } catch (reason) {
      setError(errorMessage(reason));
      setBusy(false);
    }
  };

  return (
    <Dialog title={mode === "channel" ? "Create an announcement channel" : "Create a private group"} onClose={onClose}>
      <div className="group-kind" role="radiogroup" aria-label="Conversation type">
        <button type="button" role="radio" aria-checked={mode === "group"} onClick={() => setMode("group")}>
          <Users size={20} /><span><strong>Private group</strong><small>Everyone can post</small></span>
        </button>
        <button type="button" role="radio" aria-checked={mode === "channel"} onClick={() => setMode("channel")}>
          <Megaphone size={20} /><span><strong>Announcement channel</strong><small>Only the owner can post</small></span>
        </button>
      </div>
      <div className="stack">
        <label className="field">
          <span>Name</span>
          <input autoFocus value={title} onChange={(event) => setTitle(event.target.value)} maxLength={64} placeholder={mode === "channel" ? "Farm announcements" : "Farm operations"} />
        </label>
        <fieldset className="member-picker">
          <legend>Add people</legend>
          <p>You can add up to 7 contacts. With you, this conversation can have 8 people.</p>
          {eligible.length === 0 && <div className="member-picker__empty">Connect with someone first, then return here to create a group.</div>}
          {eligible.map((contact) => {
            const checked = memberIds.includes(contact.id);
            return (
              <label key={contact.id} className="member-option">
                <Avatar name={contact.display_name} small />
                <span><strong>{contact.display_name}</strong><small>{contact.trust === "verified" ? "Verified contact" : "Approved contact"}</small></span>
                <input type="checkbox" checked={checked} disabled={!checked && memberLimitReached} onChange={() => toggleMember(contact.id)} />
              </label>
            );
          })}
        </fieldset>
        <p className="group-privacy-note"><ShieldCheck size={17} /> Each member receives an individually encrypted copy. New members do not receive earlier messages.</p>
        {error && <p className="form-error" role="alert">{error}</p>}
        <div className="dialog__actions">
          <Button variant="secondary" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button onClick={() => void create()} disabled={busy || !title.trim() || memberIds.length === 0}>
            {busy ? "Creating…" : mode === "channel" ? "Create channel" : "Create group"}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

function GroupInvitationDialog({
  invitation,
  busy,
  error,
  onAccept,
  onDecline,
  onClose,
}: {
  invitation: GroupInvitation;
  busy: boolean;
  error: string;
  onAccept: () => void;
  onDecline: () => void;
  onClose: () => void;
}) {
  return (
    <Dialog title="Group invitation" onClose={onClose}>
      <div className="group-invitation">
        <div className="group-invitation__title">
          <span className="group-invitation__icon" aria-hidden="true">{invitation.posting_policy === "owner_admins" ? <Megaphone size={23} /> : <Users size={24} />}</span>
          <div><h3>{invitation.title}</h3><p>{groupPolicyLabel(invitation.posting_policy)}</p></div>
        </div>
        <p><strong>{invitation.owner_display_name}</strong> invited you to this private {invitation.posting_policy === "owner_admins" ? "channel" : "group"}.</p>
        <dl className="invitation-facts">
          <div><dt>Members</dt><dd>{invitation.member_count}</dd></div>
          <div><dt>History</dt><dd>Starts when you join</dd></div>
          <div><dt>Expires</dt><dd><time dateTime={machineTime(invitation.expires_at)}>{formatExpiry(invitation.expires_at)}</time></dd></div>
        </dl>
        {invitation.members && invitation.members.length > 0 && (
          <div className="invitation-members" aria-label="Current members">
            {invitation.members.filter((member) => member.status === "active").map((member) => <span key={member.destination_hash}>{member.display_name}{member.role === "owner" ? " · owner" : ""}</span>)}
          </div>
        )}
        <details className="security-details">
          <summary><ShieldCheck size={17} /> Owner security details</summary>
          <p>Accept only if you expected this invitation. Compare the owner fingerprint another way for stronger assurance.</p>
          <code>{invitation.owner_fingerprint}</code>
          <span>Owner address</span><code>{invitation.owner_destination}</code>
        </details>
        <p className="muted">Joining authorizes messages from the signed member list inside this group. It does not approve private chats with every member.</p>
        {error && <p className="form-error" role="alert">{error}</p>}
        <div className="dialog__actions">
          <Button variant="secondary" onClick={onDecline} disabled={busy}>Decline</Button>
          <Button onClick={onAccept} disabled={busy}>{busy ? "Responding…" : "Accept invitation"}</Button>
        </div>
      </div>
    </Dialog>
  );
}

function IncomingRequestDialog({
  contact,
  busy,
  error,
  onAccept,
  onDecline,
  onClose,
}: {
  contact: Contact;
  busy: boolean;
  error: string;
  onAccept: () => void;
  onDecline: () => void;
  onClose: () => void;
}) {
  return (
    <Dialog title="Connection request" onClose={onClose}>
      <div className="request-dialog">
        <div className="person-preview">
          <Avatar name={contact.display_name} />
          <div>
            <h3>{contact.display_name} wants to connect</h3>
            <p>They responded to your Mesh Chat invitation.</p>
          </div>
        </div>
        <p className="muted">
          Accept only if you expected this request. For stronger assurance, compare the security fingerprint with them another way.
        </p>
        <SecurityDetails fingerprint={contact.fingerprint} destination={contact.destination_hash} />
        {error && <p className="form-error" role="alert">{error}</p>}
        <div className="dialog__actions">
          <Button variant="secondary" onClick={onDecline} disabled={busy}>Decline</Button>
          <Button onClick={onAccept} disabled={busy}>{busy ? "Responding…" : "Accept and open chat"}</Button>
        </div>
      </div>
    </Dialog>
  );
}

function WorkspaceJoinRequestDialog({
  request,
  workspace,
  busy,
  error,
  onApprove,
  onDecline,
  onClose,
}: {
  request: WorkspaceJoinRequest;
  workspace: Workspace;
  busy: boolean;
  error: string;
  onApprove: () => void;
  onDecline: () => void;
  onClose: () => void;
}) {
  return (
    <Dialog title="Workspace join request" onClose={onClose}>
      <div className="request-dialog">
        <div className="person-preview">
          <Avatar name={request.display_name} />
          <div>
            <h3>{request.display_name} wants to join {workspace.name}</h3>
            <p>This signed request reached this owner device.</p>
          </div>
        </div>
        <p className="muted">Approve only if you expected this device. Compare its fingerprint another way for stronger assurance.</p>
        <SecurityDetails fingerprint={request.fingerprint} destination={request.destination_hash} />
        {error && <p className="form-error" role="alert">{error}</p>}
        <div className="dialog__actions">
          <Button variant="secondary" onClick={onDecline} disabled={busy}>Decline</Button>
          <Button onClick={onApprove} disabled={busy}>{busy ? "Responding…" : "Approve workspace access"}</Button>
        </div>
      </div>
    </Dialog>
  );
}

function ContactsDialog({
  contacts,
  onClose,
  onChanged,
  onOpenConversation,
  onDeleted,
}: {
  contacts: Contact[];
  onClose: () => void;
  onChanged: () => Promise<void>;
  onOpenConversation: (contact: Contact) => Promise<void>;
  onDeleted: (contactId: string) => Promise<void>;
}) {
  const sorted = useMemo(
    () => [...contacts].sort((left, right) => left.display_name.localeCompare(right.display_name)),
    [contacts],
  );
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(sorted[0]?.id ?? null);
  const [name, setName] = useState(sorted[0]?.display_name ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [confirm, setConfirm] = useState<"block" | "delete" | null>(null);
  const [reconnectFormats, setReconnectFormats] = useState<ConnectionDocumentFormats | null>(null);
  const selected = contacts.find((contact) => contact.id === selectedId) ?? null;
  const needle = query.trim().toLocaleLowerCase();
  const filtered = sorted.filter((contact) => [
    contact.display_name,
    contact.profile_name ?? "",
    contact.fingerprint,
    contact.destination_hash,
  ].some((value) => value.toLocaleLowerCase().includes(needle)));

  useEffect(() => {
    if (selected) return;
    const next = filtered[0] ?? sorted[0] ?? null;
    setSelectedId(next?.id ?? null);
  }, [filtered, selected, sorted]);
  useEffect(() => {
    setName(selected?.display_name ?? "");
    setError("");
    setConfirm(null);
    setReconnectFormats(null);
  }, [selected?.id, selected?.display_name]);

  const run = async (command: string) => {
    if (!selected || busy) return;
    setBusy(true);
    setError("");
    try {
      await serviceCommand(command, { contact_id: selected.id });
      setConfirm(null);
      await onChanged();
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  };
  const saveName = async () => {
    if (!selected || busy || !name.trim()) return;
    setBusy(true);
    setError("");
    try {
      await serviceCommand("update_contact", {
        contact_id: selected.id,
        display_name: name.trim(),
      });
      await onChanged();
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  };
  const createReconnect = async () => {
    if (!selected || busy) return;
    setBusy(true); setError("");
    try { setReconnectFormats(await serviceCommand<ConnectionDocumentFormats>("create_route_update", { scope_kind: "contact", scope_id: selected.id })); }
    catch (reason) { setError(errorMessage(reason)); }
    finally { setBusy(false); }
  };
  const remove = async () => {
    if (!selected || busy) return;
    const contactId = selected.id;
    setBusy(true);
    setError("");
    try {
      await serviceCommand("delete_contact", { contact_id: contactId });
      setConfirm(null);
      await onDeleted(contactId);
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  };
  const canOpenConversation = selected && selected.trust !== "pending_request";
  const canRestoreBlocked = selected?.trust === "blocked" && Boolean(selected.trust_before_block);

  return (
    <Dialog title="Contacts" onClose={onClose} wide>
      <div className="contacts-manager">
        <aside className="contacts-manager__list">
          <label className="contact-search"><Search size={16} /><span className="sr-only">Search contacts</span><input autoFocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search contacts" /></label>
          <div role="listbox" aria-label="Saved contacts">
            {filtered.map((contact) => (
              <button key={contact.id} type="button" role="option" aria-selected={selected?.id === contact.id} onClick={() => setSelectedId(contact.id)}>
                <Avatar name={contact.display_name} small />
                <span><strong>{contact.display_name}</strong><small>{contactTrustLabel(contact)}</small></span>
              </button>
            ))}
            {filtered.length === 0 && <p>{contacts.length === 0 ? "No contacts yet." : "No contacts match your search."}</p>}
          </div>
        </aside>
        <section className="contacts-manager__detail" aria-live="polite">
          {!selected ? (
            <div className="contact-detail-empty"><BookUser size={30} /><p>Add a contact by sharing or opening an invitation.</p></div>
          ) : (
            <>
              <div className="contact-detail-heading"><Avatar name={selected.display_name} /><div><h3>{selected.display_name}</h3><span className={`trust-badge trust-badge--${selected.trust}`}>{contactTrustLabel(selected)}</span></div></div>
              <form className="contact-name-form" onSubmit={(event) => { event.preventDefault(); void saveName(); }}>
                <label className="field"><span>Name on this device</span><input value={name} onChange={(event) => setName(event.target.value)} maxLength={64} /></label>
                {selected.profile_name && selected.profile_name !== selected.display_name && <p>Profile name: {selected.profile_name}</p>}
                <Button type="submit" variant="secondary" disabled={busy || !name.trim() || name.trim() === selected.display_name}>Save name</Button>
              </form>
              <div className="contact-trust-card"><div><ShieldCheck size={20} /><span><strong>{contactTrustLabel(selected)}</strong><small>{contactTrustDescription(selected)}</small></span></div>
                {(selected.trust === "approved" || selected.trust === "verified") && <Button variant="ghost" disabled={busy} onClick={() => void run(selected.trust === "verified" ? "unverify_contact" : "verify_contact")}>{selected.trust === "verified" ? "Remove verification" : "Mark verified"}</Button>}
                {canRestoreBlocked && <Button variant="secondary" disabled={busy} onClick={() => void run("unblock_contact")}>Unblock contact</Button>}
              </div>
              <SecurityDetails fingerprint={selected.fingerprint} destination={selected.destination_hash} />
              {selected.route_status === "reconnecting_automatically" && <p className="direct-host-status" role="status"><RefreshCw size={17} /> Reconnecting automatically using the stored signed route.</p>}
              {selected.route_status === "reconnect_update_required" && !reconnectFormats && <section className="direct-host-warning"><p>Every known path is gone. Create a signed route update and send it through email or another sharing app; identity approval stays unchanged.</p><Button disabled={busy} onClick={() => void createReconnect()}><Share2 size={17} /> {busy ? "Preparing…" : "Send reconnect update"}</Button></section>}
              {reconnectFormats && <ConnectionDocumentShare formats={reconnectFormats} kind="route" />}
              {error && <p className="form-error" role="alert">{error}</p>}
              <div className="contact-detail-actions">
                <Button disabled={busy || !canOpenConversation} onClick={() => void onOpenConversation(selected)}><MessageCircleMore size={17} /> Open conversation</Button>
                {selected.trust !== "blocked" && <Button variant="secondary" disabled={busy} onClick={() => setConfirm("block")}><Ban size={17} /> Block</Button>}
                <Button variant="ghost" className="contact-remove" disabled={busy} onClick={() => setConfirm("delete")}><Trash2 size={17} /> Delete contact</Button>
              </div>
              {confirm === "block" && <div className="contact-confirm" role="alertdialog" aria-label="Block contact"><ShieldOff size={20} /><p><strong>Block {selected.display_name}?</strong><span>Their direct messages and requests will be ignored. You can unblock them later.</span></p><div><Button variant="ghost" disabled={busy} onClick={() => setConfirm(null)}>Cancel</Button><Button variant="danger" disabled={busy} onClick={() => void run("block_contact")}>{busy ? "Blocking…" : "Block"}</Button></div></div>}
              {confirm === "delete" && <div className="contact-confirm" role="alertdialog" aria-label="Delete contact"><Trash2 size={20} /><p><strong>Delete {selected.display_name}?</strong><span>This permanently erases the direct conversation, saved draft, and contact from this device. Group memberships are unchanged.</span></p><div><Button variant="ghost" disabled={busy} onClick={() => setConfirm(null)}>Cancel</Button><Button variant="danger" disabled={busy} onClick={() => void remove()}>{busy ? "Deleting…" : "Delete contact"}</Button></div></div>}
            </>
          )}
        </section>
      </div>
    </Dialog>
  );
}

function remoteStateLabel(profile: RemoteProfile): string {
  if (profile.state === "connected") return `Connected · ${profile.connected_endpoint_count}/${profile.endpoint_count} endpoints`;
  if (profile.state === "connecting") return "Connecting to remote access point";
  if (profile.state === "expired") return "Profile expired";
  if (profile.state === "access_point_unavailable") return "Access point unavailable";
  return "Approved · waiting to connect";
}

function participantMethodLabel(method: ParticipantHosting["methods"][number]): string {
  if (method === "public_ipv4") return "direct public IPv4";
  if (method === "public_ipv6") return "public IPv6";
  if (method === "upnp") return "UPnP router mapping";
  if (method === "nat_pmp") return "NAT-PMP router mapping";
  if (method === "pcp") return "PCP router mapping";
  return "participant-supplied address";
}

function ParticipantHostingSettings({ initial, workspaces, onChanged }: { initial: ParticipantHosting[]; workspaces: Workspace[]; onChanged: () => Promise<void> }) {
  const [hosts, setHosts] = useState(initial);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  useEffect(() => setHosts(initial), [initial]);
  const stop = async (host: ParticipantHosting) => {
    setBusy(host.id); setError("");
    try {
      await serviceCommand("stop_participant_host", { access_id: host.id });
      setHosts((current) => current.filter((item) => item.id !== host.id));
      await onChanged();
    } catch (reason) { setError(errorMessage(reason)); }
    finally { setBusy(null); }
  };
  const configureFirewall = async (host: ParticipantHosting) => {
    setBusy(host.id); setError("");
    try {
      const outcome = await serviceCommand<DirectDoctorStep>("configure_participant_firewall", { access_id: host.id });
      if (outcome.result !== "prepared_unverified") setError(`${directReasonLabel(outcome.reason)} ${directActionLabel(outcome.recommended_action)}`);
      await onChanged();
    } catch (reason) { setError(errorMessage(reason)); }
    finally { setBusy(null); }
  };
  const label = (host: ParticipantHosting) => {
    if (host.purpose === "personal") return "Personal invitation";
    const workspace = workspaces.find((item) => item.id === host.scope_id);
    return workspace ? `Workspace invitation · ${workspace.name}` : "Workspace invitation";
  };
  const stateLabel = (host: ParticipantHosting) => host.state === "recipient_connected" ? "Recipient connected" : host.state === "prepared_unverified" ? `Prepared, not yet verified · expires ${formatExpiry(host.expires_at)}` : host.state === "manual_setup" ? `Manual setup in progress · expires ${formatExpiry(host.expires_at)}` : host.state === "unavailable" ? directReasonLabel(host.reason ?? "router_state_changed") : "Expired";
  return <section className="settings-section participant-hosting" aria-labelledby="participant-hosting-title"><div className="settings-section__heading"><h3 id="participant-hosting-title">Invitations hosted by this device</h3><p>Temporary direct Internet paths created for invitations. The invitee connects to this device; no community or third-party transport node is added.</p></div>{hosts.map((host) => <article className="remote-profile-row" key={host.id}><span><strong>{label(host)}</strong><small role="status">{stateLabel(host)}</small><small>{host.endpoint_count} public {host.endpoint_count === 1 ? "path" : "paths"}{host.methods.length > 0 ? ` · ${host.methods.map(participantMethodLabel).join(", ")}` : ""}</small></span><div>{host.state !== "expired" && host.state !== "unavailable" && !host.firewall_configured && <Button variant="ghost" disabled={busy === host.id} onClick={() => void configureFirewall(host)}>Allow in Windows Firewall</Button>}<Button variant="danger" disabled={busy === host.id} onClick={() => void stop(host)}>{busy === host.id ? "Working…" : "Stop hosting"}</Button></div></article>)}{hosts.length === 0 && <p className="muted">No Internet invitation is currently being hosted. Use the explicit prepare action when creating an invitation.</p>}<p className="muted">Stopping or closing Mesh Chat removes automatic router mappings and temporary firewall rules. A manual router rule must be removed in the router.</p>{error && <p className="form-error" role="alert">{error}</p>}</section>;
}

function RemoteConnectionsSettings({ initial, onChanged }: { initial: RemoteProfile[]; onChanged: () => Promise<void> }) {
  const [profiles, setProfiles] = useState(initial);
  const [adding, setAdding] = useState(false);
  const [label, setLabel] = useState("");
  const [host, setHost] = useState("");
  const [port, setPort] = useState("4242");
  const [propagation, setPropagation] = useState("");
  const [allowPrivate, setAllowPrivate] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const reload = async () => {
    const result = await serviceCommand<{ profiles: RemoteProfile[] }>("list_remote_profiles");
    setProfiles(result.profiles);
  };
  const run = async (command: string, profileId: string) => {
    setBusy(profileId); setError("");
    try { await serviceCommand(command, { profile_id: profileId }); await reload(); await onChanged(); }
    catch (reason) { setError(errorMessage(reason)); }
    finally { setBusy(null); }
  };
  const add = async () => {
    const numericPort = Number(port);
    if (!label.trim() || !host.trim() || !Number.isInteger(numericPort)) return;
    setBusy("new"); setError("");
    try {
      await serviceCommand("create_manual_remote_profile", {
        label: label.trim(),
        endpoints: [{ host: host.trim(), port: numericPort }],
        propagation_node: propagation.trim() || null,
        allow_private: allowPrivate,
      });
      setLabel(""); setHost(""); setPort("4242"); setPropagation(""); setAllowPrivate(false); setAdding(false);
      await reload(); await onChanged();
    } catch (reason) { setError(errorMessage(reason)); }
    finally { setBusy(null); }
  };
  return <section className="settings-section remote-connections" aria-labelledby="remote-connections-title"><div className="settings-section__heading"><h3 id="remote-connections-title">Approved access points</h3><p>Internet invitations first try a temporary path hosted by the inviter. Add an operator-supplied Reticulum access point only as an explicit fallback when the inviter's device or router cannot accept an inbound connection.</p></div><p className="muted">Operators can observe IP addresses, timing, packet sizes, connection duration, and Reticulum routing identifiers. They cannot decrypt or forge valid MeshChat content.</p>{profiles.map((profile) => <article className="remote-profile-row" key={profile.id}><span><strong>{profile.label}</strong><small role="status">{remoteStateLabel(profile)}</small><small>{profile.ratchet_ready ? "Encrypted recipient ready" : profile.path_available ? "Known peer path; awaiting ratchet" : "Path discovery occurs when an invitation is used"} · {profile.offline_delivery_available ? "Offline delivery node connected" : profile.offline_delivery_approved ? "Offline delivery approved; node unavailable" : profile.offline_delivery_recommended ? "Offline delivery available after separate approval" : "Live delivery only"}</small></span><div><Button variant="secondary" disabled={busy === profile.id || profile.state === "expired"} onClick={() => void run("test_remote_profile", profile.id)}>Test</Button><Button variant="ghost" disabled={busy === profile.id || profile.state === "expired"} onClick={() => void run("retry_remote_profile", profile.id)}>Retry</Button>{profile.offline_delivery_recommended && <Button variant="ghost" disabled={busy === profile.id} onClick={() => void run(profile.offline_delivery_approved ? "remove_remote_propagation" : "approve_remote_propagation", profile.id)}>{profile.offline_delivery_approved ? "Remove offline delivery" : "Approve offline delivery"}</Button>}<Button variant="danger" disabled={busy === profile.id || profile.offline_delivery_approved} title={profile.offline_delivery_approved ? "Remove offline delivery approval first" : undefined} onClick={() => void run("remove_remote_profile", profile.id)}>Remove</Button></div>{profile.offline_delivery_recommended && !profile.offline_delivery_approved && <p>Optional node {profile.propagation_identifier} stores recipient-encrypted objects and routing metadata. Storage is not endpoint or human receipt. Android may not retrieve messages until Mesh Chat runs again.</p>}</article>)}{profiles.length === 0 && <p className="muted">No access point is configured. Internet invitations still try a direct path to the online inviter.</p>}{adding ? <div className="remote-profile-form"><label>Profile name<input value={label} maxLength={64} onChange={(event) => setLabel(event.target.value)} /></label><label>TCP hostname or address<input value={host} autoCapitalize="off" autoCorrect="off" spellCheck={false} onChange={(event) => setHost(event.target.value)} /></label><label>TCP port<input value={port} inputMode="numeric" onChange={(event) => setPort(event.target.value)} /></label><label>Recommended LXMF propagation destination <small>Optional, 32 hexadecimal characters</small><input value={propagation} maxLength={32} autoCapitalize="off" autoCorrect="off" spellCheck={false} onChange={(event) => setPropagation(event.target.value)} /></label><label className="checkbox-line"><input type="checkbox" checked={allowPrivate} onChange={(event) => setAllowPrivate(event.target.checked)} /> Advanced: allow a private-network endpoint. This can expose local services and must only be used with an operator you trust.</label><div className="dialog-actions"><Button variant="ghost" onClick={() => setAdding(false)}>Cancel</Button><Button disabled={busy === "new" || !label.trim() || !host.trim()} onClick={() => void add()}>{busy === "new" ? "Connecting…" : "Approve and connect"}</Button></div></div> : <Button variant="secondary" disabled={profiles.length >= 4} onClick={() => setAdding(true)}>Add remote connection</Button>}{error && <p className="form-error" role="alert">{error}</p>}</section>;
}

const I2P_ROUTER_LABEL: Record<string, string> = {
  running: "managed i2pd running",
  external: "external I2P router",
  starting: "starting",
  failed: "failed",
  not_started: "not started",
};
const I2P_ROUTER_REASON: Record<string, string> = {
  router_missing: "i2pd was not found",
  router_start_failed: "i2pd could not start",
  router_exited: "i2pd exited",
  sam_timeout: "SAM did not become ready",
  unsupported_platform: "managed I2P is not supported on this platform",
};

function WebRTCCallSettings({ onSaved }: { onSaved: () => Promise<void> }) {
  const [settings, setSettings] = useState<CallSettings | null>(null);
  const [stun, setStun] = useState("");
  const [turnUrl, setTurnUrl] = useState("");
  const [turnUser, setTurnUser] = useState("");
  const [turnCredential, setTurnCredential] = useState("");
  const [relayOnly, setRelayOnly] = useState(false);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    void serviceCommand<CallSettings>("call_settings").then((value) => {
      setSettings(value);
      setStun(value.stun_urls.join(", "));
      setRelayOnly(value.relay_only);
    }).catch((reason) => setError(errorMessage(reason)));
  }, []);
  const save = async () => {
    setBusy(true); setSaved(false); setError("");
    try {
      const result = await serviceCommand<CallSettings>("update_call_settings", {
        stun_urls: stun.split(/[,\s]+/).map((value) => value.trim()).filter(Boolean),
        turn_url: turnUrl.trim() || null,
        turn_username: turnUser.trim() || null,
        turn_credential: turnCredential || null,
        relay_only: relayOnly,
      });
      setSettings(result);
      setTurnCredential("");
      setSaved(true);
      await onSaved();
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="settings-section" aria-labelledby="webrtc-call-settings-title">
      <div className="settings-section__heading"><h3 id="webrtc-call-settings-title">WebRTC calls</h3><p>Google STUN is used by default to find a direct call path. Replace or clear it to use another STUN server. TURN is optional, relays media, and can see connection metadata, not content.</p></div>
      <label className="field"><span>STUN servers <small>Comma-separated, for example stun:stun.example.org:3478</small></span><input value={stun} autoCapitalize="off" autoCorrect="off" spellCheck={false} onChange={(event) => { setStun(event.target.value); setSaved(false); }} /></label>
      <label className="field"><span>TURN server <small>Optional, for example turn:turn.example.org:443?transport=tcp</small></span><input value={turnUrl} autoCapitalize="off" autoCorrect="off" spellCheck={false} onChange={(event) => { setTurnUrl(event.target.value); setSaved(false); }} /></label>
      <div className="field-grid">
        <label className="field"><span>TURN username</span><input value={turnUser} autoCapitalize="off" autoCorrect="off" spellCheck={false} onChange={(event) => { setTurnUser(event.target.value); setSaved(false); }} /></label>
        <label className="field"><span>TURN credential</span><input type="password" value={turnCredential} autoComplete="off" onChange={(event) => { setTurnCredential(event.target.value); setSaved(false); }} /></label>
      </div>
      <label className="checkbox-line"><input type="checkbox" checked={relayOnly} onChange={(event) => { setRelayOnly(event.target.checked); setSaved(false); }} /> Relay-only: never try a direct path. This requires a TURN server and shows every call as relayed.</label>
      <p className="muted">{settings?.turn_configured ? "TURN is configured. Credentials stay in the encrypted service record and are released only to an active call." : "No TURN server configured. Calls work only on a shared LAN or when direct host candidates are reachable."}</p>
      {saved && <p className="muted" role="status">Call settings saved.</p>}
      {error && <p className="form-error" role="alert">{error}</p>}
      <Button disabled={busy} onClick={() => void save()}>{busy ? "Saving…" : "Save call settings"}</Button>
    </section>
  );
}

function SettingsDialog({ snapshot, theme, onThemeChange, onClose, onSaved }: { snapshot: Snapshot; theme: Theme; onThemeChange: (theme: Theme) => void; onClose: () => void; onSaved: () => Promise<void> }) {
  const [settings, setSettings] = useState<NetworkSettings>(snapshot.settings);
  const [saved, setSaved] = useState(false);
  const [notification, setNotification] = useState(snapshot.workspace_notification_state ?? null);
  const [capability, setCapability] = useState<NotificationCapability | null>(null);
  const [notificationBusy, setNotificationBusy] = useState(false);
  const [notificationError, setNotificationError] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [i2pStatus, setI2PStatus] = useState<I2PStatus | null>(null);
  const [isAndroid, setIsAndroid] = useState(false);
  useEffect(() => {
    void Promise.resolve(runtimePlatform()).then((value) => setIsAndroid(value === "android")).catch(() => undefined);
    if (settings.i2p_enabled) {
      void Promise.resolve(serviceCommand<I2PStatus>("i2p_status")).then(setI2PStatus).catch(() => undefined);
    }
  }, []);
  const darkThemeRef = useRef<HTMLButtonElement>(null);
  const lightThemeRef = useRef<HTMLButtonElement>(null);
  const selectTheme = (nextTheme: Theme) => {
    onThemeChange(nextTheme);
    (nextTheme === "dark" ? darkThemeRef : lightThemeRef).current?.focus();
  };
  const handleThemeKeyDown = (event: ReactKeyboardEvent<HTMLButtonElement>) => {
    const nextTheme = event.key === "Home"
      ? "dark"
      : event.key === "End"
        ? "light"
        : ["ArrowRight", "ArrowDown", "ArrowLeft", "ArrowUp"].includes(event.key)
          ? theme === "dark" ? "light" : "dark"
          : null;
    if (!nextTheme) return;
    event.preventDefault();
    selectTheme(nextTheme);
  };
  const toggle = (key: "nearby_discovery" | "lan_fallback" | "help_route" | "store_for_offline" | "i2p_enabled" | "i2p_connectable" | "i2p_managed") => {
    setSaved(false);
    setSaveError("");
    setSettings((current) => ({ ...current, [key]: !current[key] }));
  };
  const refreshNotification = useCallback(async () => {
    const native = await notificationCapability();
    setCapability(native);
    setNotification(await serviceCommand<WorkspaceNotificationState>("get_notification_state"));
  }, []);
  useEffect(() => { void refreshNotification().catch(() => undefined); }, [refreshNotification]);
  const requestPermission = async () => {
    setNotificationBusy(true); setNotificationError("");
    try { setCapability(await requestNotificationPermission()); await refreshNotification(); }
    catch (reason) { setNotificationError(errorMessage(reason)); }
    finally { setNotificationBusy(false); }
  };
  const openSettings = async () => {
    setNotificationBusy(true); setNotificationError("");
    try { setCapability(await openNotificationSettings()); }
    catch (reason) { setNotificationError(errorMessage(reason)); }
    finally { setNotificationBusy(false); }
  };
  const setPrivatePreviews = async () => {
    if (!notification) return;
    setNotificationBusy(true); setNotificationError("");
    try {
      setNotification(await serviceCommand<WorkspaceNotificationState>("set_hide_notification_previews", {
        operation_id: newOperationId(), hidden: !notification.hide_previews,
      }));
      await onSaved();
    } catch (reason) { setNotificationError(errorMessage(reason)); }
    finally { setNotificationBusy(false); }
  };
  const save = async () => {
    setSaving(true); setSaveError("");
    try {
      await serviceCommand("update_settings", { settings });
      setSaved(true);
      await onSaved();
    } catch (reason) { setSaveError(errorMessage(reason)); }
    finally { setSaving(false); }
  };
  return (
    <Dialog title="Settings" onClose={onClose}>
      <p>Mesh Chat version {packageInfo.version}</p>
      <details><summary>Help and diagnostics</summary><ConnectionDiagnostics full /></details>
      <section className="settings-section appearance-settings" aria-labelledby="appearance-settings-title">
        <div className="settings-section__heading"><h3 id="appearance-settings-title">Appearance</h3><p>Choose the look that is most comfortable. Changes apply immediately and are remembered on this device.</p></div>
        <div className="theme-picker" role="radiogroup" aria-label="Theme">
          <button ref={darkThemeRef} type="button" role="radio" aria-checked={theme === "dark"} tabIndex={theme === "dark" ? 0 : -1} onKeyDown={handleThemeKeyDown} onClick={() => selectTheme("dark")}><Moon size={18} /><span><strong>Dark</strong><small>Calm and low glare</small></span></button>
          <button ref={lightThemeRef} type="button" role="radio" aria-checked={theme === "light"} tabIndex={theme === "light" ? 0 : -1} onKeyDown={handleThemeKeyDown} onClick={() => selectTheme("light")}><Sun size={18} /><span><strong>Light</strong><small>Bright and crisp</small></span></button>
        </div>
      </section>
      <section className="settings-section" aria-labelledby="connection-settings-title">
        <div className="settings-section__heading"><h3 id="connection-settings-title">Connections</h3><p>Control how this device discovers people and helps the mesh.</p></div>
        <div className="settings-list">
          <Toggle title="Find nearby people" description="Use link-local Reticulum discovery on suitable network interfaces." checked={settings.nearby_discovery} onChange={() => toggle("nearby_discovery")} />
          <Toggle title="Use a direct local connection" description="Add a private local-network connection option to new invitations when nearby discovery is blocked." checked={settings.lan_fallback} onChange={() => toggle("lan_fallback")} />
        </div>
        <details className="advanced-settings"><summary>Advanced connection roles</summary><p>These options make this device part of the wider Reticulum mesh and may use additional power, storage, and bandwidth.</p><div className="settings-list settings-list--advanced"><Toggle title="Help route messages" description="Allow this device to forward encrypted Reticulum traffic for others." checked={settings.help_route} onChange={() => toggle("help_route")} /><Toggle title="Store encrypted messages" description="Act as an LXMF propagation node with a 100 MiB cache. This is separate from routing." checked={settings.store_for_offline} onChange={() => toggle("store_for_offline")} /></div></details>
      </section>
      <section className="settings-section i2p-settings" aria-labelledby="i2p-settings-title">
        <div className="settings-section__heading"><h3 id="i2p-settings-title">I2P relay</h3><p>Use an I2P access point when this network cannot accept a direct connection. I2P relays encrypted Reticulum traffic; it does not create a direct link.</p></div>
        <div className="settings-list">
          <Toggle title="Use I2P" description="Connect through an I2P access point. Requires an I2P router with SAM enabled." checked={settings.i2p_enabled} onChange={() => toggle("i2p_enabled")} />
        </div>
        {settings.i2p_enabled && <div className="form-stack">
          {!isAndroid && <Toggle title="Manage i2pd for me" description="Start a local i2pd process with SAM on localhost. No administrator rights or Windows service." checked={settings.i2p_managed} onChange={() => toggle("i2p_managed")} />}
          {!isAndroid && <Toggle title="Run a connectable access point" description="Accept inbound I2P tunnels. Enable Help route messages if this device should relay for others." checked={settings.i2p_connectable} onChange={() => toggle("i2p_connectable")} />}
          {isAndroid && <p className="muted">Connectable access points are desktop-only. Android uses client-only I2P.</p>}
          <label className="field"><span>I2P access point addresses</span><textarea rows={3} value={settings.i2p_peers.join("\n")} onChange={(event) => setSettings((current) => ({ ...current, i2p_peers: event.target.value.split(/\r?\n/).map((value) => value.trim()).filter(Boolean) }))} placeholder="example.b32.i2p" spellCheck={false} /></label>
          <p className="muted">One <code>*.b32.i2p</code> address per line. The access point can see connection metadata, not message contents. Save, then restart Mesh Chat to apply.</p>
          {i2pStatus && <p className="muted" role="status">I2P: {i2pStatus.state === "online" ? `online · ${i2pStatus.online_count} interface${i2pStatus.online_count === 1 ? "" : "s"}` : i2pStatus.state === "not_started" ? "saved; restart Mesh Chat to start I2P" : i2pStatus.state} · {i2pStatus.peer_count} access point{i2pStatus.peer_count === 1 ? "" : "s"}</p>}
          {i2pStatus?.router && <p className="muted" role="status">Router: {I2P_ROUTER_LABEL[i2pStatus.router.state] ?? i2pStatus.router.state}{i2pStatus.router.reason ? ` — ${I2P_ROUTER_REASON[i2pStatus.router.reason] ?? i2pStatus.router.reason}` : ""} · SAM {i2pStatus.router.sam_ready ? "ready" : "not ready"}</p>}
          {i2pStatus?.router?.reason === "router_missing" && <p className="muted">Place <code>i2pd.exe</code> next to Mesh Chat, or turn off “Manage i2pd for me” and run i2pd yourself with SAM enabled.</p>}
          {i2pStatus?.b32 && <p className="muted">This device’s I2P address: <code>{i2pStatus.b32}.b32.i2p</code></p>}
        </div>}
      </section>
      <ParticipantHostingSettings initial={snapshot.participant_hosting ?? []} workspaces={snapshot.workspaces ?? []} onChanged={onSaved} />
      <RemoteConnectionsSettings initial={snapshot.remote_profiles ?? []} onChanged={onSaved} />
      <WebRTCCallSettings onSaved={onSaved} />
      <section className="notification-settings" aria-labelledby="notification-settings-title">
        <h3 id="notification-settings-title"><Bell size={18} /> Local notifications</h3>
        <p role="status" aria-live="polite"><strong>{!capability?.supported ? "Not supported on this platform" : capability.permission_state === "allowed" ? "Allowed" : capability.permission_state === "not_requested" ? "Permission not requested" : "Permission denied or settings required"}</strong></p>
        {capability?.supported && capability.permission_state === "not_requested" && <Button disabled={notificationBusy} onClick={() => void requestPermission()}>Enable notifications</Button>}
        {capability?.supported && ["denied", "settings_required"].includes(capability.permission_state) && <Button variant="secondary" disabled={notificationBusy} onClick={() => void openSettings()}>Open system settings</Button>}
        {notification && <Toggle title="Hide notification previews" description="Use generic text without workspace, channel, person, thread, participant, or message details." checked={notification.hide_previews} onChange={() => void setPrivatePreviews()} />}
        <p className="muted">Notifications are local and best effort only while Mesh Chat can execute. They may be delayed after operating-system suspension or process termination; open Mesh Chat to reconcile. There is no cloud push.</p>
        {notification && <p className="muted" role="status">Runtime: {notification.reconciling ? "reconciling" : notification.lifecycle_state === "caught_up" || notification.caught_up ? "caught up" : notification.lifecycle_state === "foreground" ? "active" : "suspended or limited"}{notification.pending_native_count ? ` · ${notification.pending_native_count} pending local ${notification.pending_native_count === 1 ? "notification" : "notifications"}` : ""}</p>}
        {notificationError && <p className="form-error" role="alert">{notificationError}</p>}
      </section>
      <p className="app-version">Mesh Chat {packageInfo.version}<span>Emoji artwork: Twemoji (CC BY 4.0)</span></p>
      {saved && <p className="restart-note" role="status">Saved. Restart Mesh Chat to apply networking-role changes.</p>}
      {saveError && <p className="form-error" role="alert">{saveError}</p>}
      <div className="dialog__actions"><Button variant="secondary" aria-label="Close settings" disabled={saving} onClick={onClose}>Close</Button><Button disabled={saving} onClick={() => void save()}>{saving ? "Saving…" : "Save settings"}</Button></div>
    </Dialog>
  );
}

function Toggle({ title, description, checked, onChange }: { title: string; description: string; checked: boolean; onChange: () => void }) {
  return <label className="toggle-row"><span><strong>{title}</strong><small>{description}</small></span><input type="checkbox" checked={checked} onChange={onChange} /><i aria-hidden="true" /></label>;
}

function DeleteConversationDialog({ kind, name, busy, error, onCancel, onConfirm }: { kind: "direct" | "group"; name: string; busy: boolean; error: string; onCancel: () => void; onConfirm: () => void }) {
  return (
    <Dialog title="Delete conversation?" onClose={onCancel}>
      <div className="delete-conversation-dialog">
        <p>Messages, the saved draft, and chat payloads still waiting on this device will be permanently deleted locally. Messages already handed off to another device may still arrive there.</p>
        <p>{kind === "direct" ? `${name} remains an approved contact.` : `You remain a member of ${name}; this does not leave or close the group.`} A fresh incoming message will make the conversation reappear, or you can search for its name to restore an empty conversation.</p>
        {error && <p className="form-error" role="alert">{error}</p>}
        <div className="dialog__actions"><Button variant="secondary" onClick={onCancel} disabled={busy}>Cancel</Button><Button variant="danger" onClick={onConfirm} disabled={busy}>{busy ? "Deleting…" : "Delete locally"}</Button></div>
      </div>
    </Dialog>
  );
}

function MessageReactions({
  messageText,
  reactions = [],
  pickerOpen,
  catalogOpen,
  busyEmoji,
  error,
  onTogglePicker,
  onClosePicker,
  onCatalogOpenChange,
  onSetReaction,
  multiple = false,
}: {
  messageText: string;
  reactions?: MessageReaction[];
  pickerOpen: boolean;
  catalogOpen: boolean;
  busyEmoji: string | null;
  error: string;
  onTogglePicker: () => void;
  onClosePicker: () => void;
  onCatalogOpenChange: (open: boolean) => void;
  onSetReaction: (emoji: string, active: boolean) => void;
  multiple?: boolean;
}) {
  const rootRef = useRef<HTMLDivElement>(null);
  const pickerRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const moreButtonRef = useRef<HTMLButtonElement>(null);
  const catalogBackRef = useRef<HTMLButtonElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const previousCatalogOpen = useRef(catalogOpen);
  const pickerWasOpen = useRef(pickerOpen);
  const [pickerPosition, setPickerPosition] = useState<{ left: number; top: number; maxHeight: number; maxWidth: number } | null>(null);
  const [category, setCategory] = useState(REACTION_CATEGORIES[0].id);
  const [searchQuery, setSearchQuery] = useState("");
  const [customEmoji, setCustomEmoji] = useState("");
  const [localError, setLocalError] = useState("");
  const pickerId = useId();
  const messageLabel = messageText.length > 80 ? `${messageText.slice(0, 77)}…` : messageText;
  const visibleReactions = reactions
    .filter((reaction) => reaction.count > 0)
    .map((reaction) => ({
      ...reaction,
      label: REACTION_OPTION_BY_EMOJI.get(reaction.emoji)?.label
        ?? getEmojiFallbackName(reaction.emoji)
        ?? `custom emoji ${reaction.emoji}`,
    }));
  const selfReaction = reactions.find((reaction) => reaction.reacted_by_self);
  const normalizedSearch = searchQuery.trim().toLocaleLowerCase();
  const catalogOptions = normalizedSearch
    ? REACTION_CATEGORIES.flatMap((item) => item.options).filter((option, index, all) => (
      all.findIndex((candidate) => candidate.emoji === option.emoji) === index
      && `${option.label} ${option.keywords ?? ""}`.toLocaleLowerCase().includes(normalizedSearch)
    ))
    : REACTION_CATEGORIES.find((item) => item.id === category)?.options ?? [];

  const choiceLabel = (emoji: string, label: string, selected: boolean) => {
    if (selected) return `Remove your ${label} reaction`;
    if (!multiple && selfReaction) return `React with ${label}, replacing your ${selfReaction.emoji} reaction`;
    return `React with ${label}`;
  };

  useLayoutEffect(() => {
    if (!pickerOpen) return;
    const positionPicker = () => {
      const trigger = triggerRef.current;
      const picker = pickerRef.current;
      if (!trigger || !picker) return;
      const visualViewport = window.visualViewport;
      const viewportLeft = visualViewport?.offsetLeft ?? 0;
      const viewportTop = visualViewport?.offsetTop ?? 0;
      const viewportWidth = visualViewport?.width ?? window.innerWidth;
      const viewportHeight = visualViewport?.height ?? window.innerHeight;
      const gutter = 8;
      const triggerRect = trigger.getBoundingClientRect();
      const pickerRect = picker.getBoundingClientRect();
      // The measured dimensions are zero in some WebViews during the first
      // layout pass. The fallback is the exact one-row CSS footprint.
      const maxWidth = Math.max(1, viewportWidth - gutter * 2);
      const maxHeight = Math.max(1, viewportHeight - gutter * 2);
      const fallbackWidth = catalogOpen ? Math.min(360, maxWidth) : Math.min(293, maxWidth);
      const fallbackHeight = catalogOpen ? Math.min(430, maxHeight) : Math.min(108, maxHeight);
      const pickerWidth = Math.min(pickerRect.width || picker.offsetWidth || fallbackWidth, maxWidth);
      const pickerHeight = Math.min(pickerRect.height || picker.offsetHeight || fallbackHeight, maxHeight);
      const minimumLeft = viewportLeft + gutter;
      const maximumLeft = Math.max(minimumLeft, viewportLeft + viewportWidth - pickerWidth - gutter);
      const centeredLeft = triggerRect.left + triggerRect.width / 2 - pickerWidth / 2;
      const left = Math.min(maximumLeft, Math.max(minimumLeft, centeredLeft));
      const minimumTop = viewportTop + gutter;
      const maximumTop = Math.max(minimumTop, viewportTop + viewportHeight - pickerHeight - gutter);
      const spaceAbove = triggerRect.top - minimumTop;
      const spaceBelow = viewportTop + viewportHeight - gutter - triggerRect.bottom;
      const top = spaceAbove >= pickerHeight || spaceAbove >= spaceBelow
        ? Math.min(maximumTop, Math.max(minimumTop, triggerRect.top - pickerHeight - gutter))
        : Math.min(maximumTop, triggerRect.bottom + gutter);
      setPickerPosition((current) => current?.left === left && current.top === top && current.maxHeight === maxHeight && current.maxWidth === maxWidth
        ? current
        : { left, top, maxHeight, maxWidth });
    };
    positionPicker();
    window.addEventListener("resize", positionPicker);
    window.addEventListener("scroll", positionPicker, true);
    window.visualViewport?.addEventListener("resize", positionPicker);
    window.visualViewport?.addEventListener("scroll", positionPicker);
    return () => {
      window.removeEventListener("resize", positionPicker);
      window.removeEventListener("scroll", positionPicker, true);
      window.visualViewport?.removeEventListener("resize", positionPicker);
      window.visualViewport?.removeEventListener("scroll", positionPicker);
    };
  }, [catalogOpen, error, localError, pickerOpen, searchQuery]);

  useEffect(() => {
    if (!pickerOpen) return;
    if (catalogOpen) {
      // Do not raise the Android keyboard just because the catalog opened.
      // Search receives focus only when the person intentionally taps it.
      catalogBackRef.current?.focus();
    } else if (previousCatalogOpen.current) {
      moreButtonRef.current?.focus();
    } else {
      const focusTarget = pickerRef.current?.querySelector<HTMLButtonElement>('[aria-pressed="true"]')
        ?? pickerRef.current?.querySelector<HTMLButtonElement>(".reaction-picker__choice");
      focusTarget?.focus();
    }
    previousCatalogOpen.current = catalogOpen;
    const onPointerDown = (event: PointerEvent) => {
      if (event.target instanceof Node && !rootRef.current?.contains(event.target)) onClosePicker();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      const visibleModal = [...document.querySelectorAll<HTMLElement>('[role="dialog"][aria-modal="true"]')]
        .some((dialog) => !dialog.closest('[aria-hidden="true"]'));
      if (visibleModal) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      if (catalogOpen) {
        onCatalogOpenChange(false);
      } else {
        onClosePicker();
        window.setTimeout(() => triggerRef.current?.focus(), 0);
      }
    };
    document.addEventListener("pointerdown", onPointerDown, true);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown, true);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [catalogOpen, onCatalogOpenChange, onClosePicker, pickerOpen]);

  useEffect(() => {
    if (!pickerOpen) {
      setSearchQuery("");
      setCustomEmoji("");
      setLocalError("");
      previousCatalogOpen.current = false;
      if (pickerWasOpen.current) window.setTimeout(() => triggerRef.current?.focus(), 0);
    }
    pickerWasOpen.current = pickerOpen;
  }, [pickerOpen]);

  const chooseReaction = (emoji: string) => {
    const validation = validateSingleEmoji(emoji);
    if (validation.error) {
      setLocalError(validation.error);
      return;
    }
    setLocalError("");
    const selected = reactions.some((reaction) => reaction.emoji === validation.emoji && reaction.reacted_by_self);
    onSetReaction(validation.emoji, !selected);
  };

  const submitCustomEmoji = (event: React.FormEvent) => {
    event.preventDefault();
    chooseReaction(customEmoji);
  };

  const movePickerFocus = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Tab") {
      const focusable = [...event.currentTarget.querySelectorAll<HTMLElement>(
        'button:not(:disabled), input:not(:disabled), [href], [tabindex]:not([tabindex="-1"])',
      )];
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
      return;
    }
    if (!(event.target instanceof Element) || !event.target.matches(".reaction-picker__choice")) return;
    if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) return;
    const choices = [...event.currentTarget.querySelectorAll<HTMLButtonElement>(".reaction-picker__choice:not(:disabled)")];
    if (choices.length === 0) return;
    event.preventDefault();
    const currentIndex = choices.indexOf(document.activeElement as HTMLButtonElement);
    const nextIndex = event.key === "Home"
      ? 0
      : event.key === "End"
        ? choices.length - 1
        : event.key === "ArrowLeft"
          ? (currentIndex <= 0 ? choices.length - 1 : currentIndex - 1)
          : event.key === "ArrowRight"
            ? (currentIndex + 1) % choices.length
            : event.key === "ArrowUp"
              ? (currentIndex < 6 ? choices.length - (6 - currentIndex) : currentIndex - 6)
              : (currentIndex + 6) % choices.length;
    choices[nextIndex]?.focus();
  };

  const moveCategoryFocus = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    const categories = [...event.currentTarget.querySelectorAll<HTMLButtonElement>("button")];
    if (categories.length === 0) return;
    event.preventDefault();
    const currentIndex = categories.indexOf(document.activeElement as HTMLButtonElement);
    const nextIndex = event.key === "Home" ? 0
      : event.key === "End" ? categories.length - 1
        : event.key === "ArrowLeft" ? (currentIndex <= 0 ? categories.length - 1 : currentIndex - 1)
          : (currentIndex + 1) % categories.length;
    categories[nextIndex]?.focus();
  };

  return (
    <div className="message-reactions" ref={rootRef} role="group" aria-label={`Reactions to message: ${messageLabel}`} aria-busy={busyEmoji ? true : undefined}>
      {visibleReactions.map((reaction) => {
        const label = choiceLabel(reaction.emoji, reaction.label, reaction.reacted_by_self);
        return (
          <button
            key={reaction.emoji}
            type="button"
            className={`reaction-summary ${reaction.reacted_by_self ? "reaction-summary--self" : ""}`}
            aria-label={`${label}; ${reaction.count} ${reaction.count === 1 ? "reaction" : "reactions"} total`}
            aria-pressed={reaction.reacted_by_self}
            title={label}
            disabled={Boolean(busyEmoji)}
            onClick={() => onSetReaction(reaction.emoji, !reaction.reacted_by_self)}
          >
            <EmojiGlyph emoji={reaction.emoji} /><span>{reaction.count}</span>
          </button>
        );
      })}
      <button
        ref={triggerRef}
        type="button"
        className="reaction-picker-trigger"
        aria-label={pickerOpen ? "Close reaction picker" : selfReaction ? "Change or remove your reaction" : "Add a reaction"}
        aria-expanded={pickerOpen}
        aria-haspopup="dialog"
        aria-controls={pickerId}
        title={selfReaction ? "Change or remove your reaction" : "Add a reaction"}
        disabled={Boolean(busyEmoji)}
        onClick={onTogglePicker}
      ><SmilePlus size={15} /></button>
      {pickerOpen && (
        <div
          id={pickerId}
          ref={pickerRef}
          role="dialog"
          aria-label="Choose a reaction"
          className={`reaction-picker ${catalogOpen ? "reaction-picker--catalog" : "reaction-picker--quick"}`}
          style={pickerPosition ? {
            left: pickerPosition.left,
            top: pickerPosition.top,
            maxHeight: pickerPosition.maxHeight,
            maxWidth: pickerPosition.maxWidth,
          } : { visibility: "hidden" }}
          onKeyDown={movePickerFocus}
        >
          <span className="sr-only">{multiple ? "Choose reactions. Choosing yours again removes it." : "Choose one reaction. Choosing a different reaction replaces yours; choosing yours again removes it."}</span>
          {!catalogOpen && <div className="reaction-picker__quick" aria-label="Quick reactions">{QUICK_REACTION_OPTIONS.map((option) => {
            const selected = reactions.some((reaction) => reaction.emoji === option.emoji && reaction.reacted_by_self);
            const label = choiceLabel(option.emoji, option.label, selected);
            return (
              <button
                key={option.emoji}
                type="button"
                className="reaction-picker__choice"
                aria-label={label}
                aria-pressed={selected}
                title={label}
                disabled={Boolean(busyEmoji)}
                onClick={() => chooseReaction(option.emoji)}
              ><EmojiGlyph emoji={option.emoji} /></button>
            );
          })}</div>}
          {!catalogOpen && <button
            ref={moreButtonRef}
            type="button"
            className="reaction-picker__more"
            onClick={() => onCatalogOpenChange(true)}
          ><span aria-hidden="true">＋</span> More emojis</button>}
          {catalogOpen && <>
            <header className="reaction-picker__header">
              <button ref={catalogBackRef} type="button" className="reaction-picker__back" onClick={() => onCatalogOpenChange(false)} aria-label="Back to quick reactions"><ArrowLeft size={18} /> Quick</button>
              <strong>More emojis</strong>
              <button type="button" className="reaction-picker__close" onClick={onClosePicker} aria-label="Close reaction picker"><X size={18} /></button>
            </header>
            <label className="reaction-picker__search">
              <Search size={17} aria-hidden="true" />
              <input ref={searchRef} type="search" value={searchQuery} onChange={(event) => setSearchQuery(event.target.value)} placeholder="Search emojis" aria-label="Search emojis" />
            </label>
            <div className="reaction-picker__categories" role="toolbar" aria-label="Emoji categories" onKeyDown={moveCategoryFocus}>
              {REACTION_CATEGORIES.map((item) => <button
                key={item.id}
                type="button"
                aria-label={item.label}
                aria-pressed={!normalizedSearch && category === item.id}
                title={item.label}
                onClick={() => { setCategory(item.id); setSearchQuery(""); }}
              ><EmojiGlyph emoji={item.icon} /></button>)}
            </div>
            <div className="reaction-picker__catalog" role="group" aria-label={normalizedSearch ? `Search results for ${searchQuery}` : REACTION_CATEGORIES.find((item) => item.id === category)?.label}>
              {catalogOptions.map((option) => {
                const selected = reactions.some((reaction) => reaction.emoji === option.emoji && reaction.reacted_by_self);
                return <button
                  key={option.emoji}
                  type="button"
                  className="reaction-picker__choice"
                  aria-label={choiceLabel(option.emoji, option.label, selected)}
                  aria-pressed={selected}
                  title={option.label}
                  disabled={Boolean(busyEmoji)}
                  onClick={() => chooseReaction(option.emoji)}
                ><EmojiGlyph emoji={option.emoji} /></button>;
              })}
              {catalogOptions.length === 0 && <p className="reaction-picker__empty">No matching emojis. You can use your keyboard below.</p>}
            </div>
            <form className="reaction-picker__custom" onSubmit={submitCustomEmoji}>
              <label htmlFor={`${pickerId}-custom`}>Use emoji keyboard</label>
              <div><input
                id={`${pickerId}-custom`}
                value={customEmoji}
                onChange={(event) => { setCustomEmoji(event.target.value); setLocalError(""); }}
                placeholder="Enter one emoji"
                aria-describedby={`${pickerId}-custom-help`}
                autoComplete="off"
                maxLength={64}
              /><button type="submit" disabled={Boolean(busyEmoji)}>Use emoji</button></div>
              <small id={`${pickerId}-custom-help`}>Enter any single emoji from your device keyboard.</small>
            </form>
          </>}
          {(localError || error) && <span className="reaction-picker__error" role="alert">{localError || error}</span>}
        </div>
      )}
    </div>
  );
}

function Conversation({ contact, messages, draft, sendError, sending, detailsOpen, reactionTargetId, reactionCatalogOpen, reactionBusyEmoji, reactionError, onDetailsOpenChange, onToggleReactionPicker, onReactionCatalogOpenChange, onCloseReactionPicker, onSetReaction, onDraft, onSend, onHelp, onBack, onDelete, onCall }: { contact: Contact; messages: ChatMessage[]; draft: string; sendError: string; sending: boolean; detailsOpen: boolean; reactionTargetId: string | null; reactionCatalogOpen: boolean; reactionBusyEmoji: string | null; reactionError: string; onDetailsOpenChange: (open: boolean) => void; onToggleReactionPicker: (messageId: string) => void; onReactionCatalogOpenChange: (messageId: string, open: boolean) => void; onCloseReactionPicker: () => void; onSetReaction: (messageId: string, emoji: string, active: boolean) => void; onDraft: (value: string) => void; onSend: () => void; onHelp: () => void; onBack: () => void; onDelete: () => void; onCall: () => void }) {
  const messageListRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const messageList = messageListRef.current;
    if (!messageList) return;
    try {
      messageList.scrollTop = messageList.scrollHeight;
    } catch {
      // Scrolling is a convenience; a platform WebView failure must not hide the chat.
    }
  }, [messages.length]);
  const approved = contact.trust === "approved" || contact.trust === "verified";
  const routeLabel = contact.route_kind === "participant_direct" ? "Connected directly over the Internet" : contact.route_kind === "remote" ? "Reachable through remote transport" : contact.route_kind === "signed_direct" ? "Reachable through signed direct local route" : contact.route_kind === "nearby" ? "Reachable nearby" : "Secure route not currently known";
  return (
    <section className="conversation" aria-label={`Conversation with ${contact.display_name}`}>
      <header className="conversation__header"><button className="icon-button mobile-only mobile-back" type="button" onClick={onBack} aria-label="Back to conversations"><ArrowLeft size={21} /></button><div className="conversation__person"><Avatar name={contact.display_name} small /><div><h2>{contact.display_name}</h2><span>{routeLabel}</span></div></div><div className="conversation__actions">{approved && <button className="icon-button" type="button" onClick={onCall} disabled={sending} aria-label={`Call ${contact.display_name}`} title="Audio call"><Phone size={18} /></button>}<button className="icon-button conversation-delete" type="button" onClick={onDelete} disabled={sending} aria-label={`Delete conversation with ${contact.display_name}`} title="Delete conversation"><Trash2 size={18} /></button><SecurityDetails fingerprint={contact.fingerprint} destination={contact.destination_hash} open={detailsOpen} onOpenChange={onDetailsOpenChange} /></div></header>
      {!approved && <div className={`connection-banner connection-banner--${contact.trust}`} role="status"><span>{contactConnectionLabel(contact)}</span>{contact.trust === "awaiting_consent" && <Button variant="ghost" onClick={onHelp}><CircleHelp size={17} /> Connection help</Button>}</div>}
      <div className="message-list" aria-live="polite" ref={messageListRef}>
        <div className="day-divider"><span>Messages are end-to-end encrypted</span></div>
        {messages.length === 0 && <div className="empty-thread"><LockKeyhole size={30} /><p>No messages yet.</p><span>You can write now. If there is no route, your message stays saved.</span></div>}
        {messages.map((message) => (
          <article key={message.id} className={`message message--${message.direction}`}>
            <p>{message.text}</p>
            <footer>
              <time dateTime={machineTime(message.created_at)}>{formatTime(message.created_at)}</time>
              {message.direction === "outbound" && <span className={`delivery delivery--${message.state}`}>{message.state === "delivered" && <Check size={13} />}{deliveryLabel[message.state]}</span>}
              <MessageReactions
                messageText={message.text}
                reactions={message.reactions}
                pickerOpen={reactionTargetId === message.id}
                catalogOpen={reactionTargetId === message.id && reactionCatalogOpen}
                busyEmoji={reactionBusyEmoji}
                error={reactionTargetId === message.id ? reactionError : ""}
                onTogglePicker={() => onToggleReactionPicker(message.id)}
                onCatalogOpenChange={(open) => onReactionCatalogOpenChange(message.id, open)}
                onClosePicker={onCloseReactionPicker}
                onSetReaction={(emoji, active) => onSetReaction(message.id, emoji, active)}
              />
            </footer>
          </article>
        ))}
      </div>
      <form className="composer" aria-busy={sending} onSubmit={(event) => { event.preventDefault(); onSend(); }}>{sendError && <p className="composer__error" role="alert">{sendError}</p>}<label className="sr-only" htmlFor="message-composer">Message {contact.display_name}</label><textarea id="message-composer" rows={1} value={draft} readOnly={sending} enterKeyHint="send" onChange={(event) => onDraft(event.target.value)} placeholder={`Message ${contact.display_name}`} maxLength={16384} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); onSend(); } }} /><button type="submit" disabled={sending || !draft.trim()} aria-label="Send message"><Send size={19} /></button></form>
    </section>
  );
}

function GroupDetails({
  group,
  selfDestination,
  open,
  busy,
  error,
  onOpenChange,
  onRemove,
  onRetryInvite,
  onLeave,
  onCloseGroup,
}: {
  group: Group;
  selfDestination: string;
  open: boolean;
  busy: boolean;
  error: string;
  onOpenChange: (open: boolean) => void;
  onRemove: (destinationHash: string) => void;
  onRetryInvite: (destinationHash: string) => void;
  onLeave: () => void;
  onCloseGroup: () => void;
}) {
  const [confirm, setConfirm] = useState<{ action: "remove" | "leave" | "close"; destinationHash?: string } | null>(null);
  const activeMembers = group.members.filter((member) => member.status === "active");
  const visibleMembers = [...group.members].sort((left, right) => Number(right.status === "active") - Number(left.status === "active"));
  const self = group.members.find((member) => member.destination_hash === selfDestination && member.status === "active");
  const owner = self?.role === "owner";
  const confirmMember = confirm?.destinationHash ? activeMembers.find((member) => member.destination_hash === confirm.destinationHash) : null;
  useEffect(() => { if (!open) setConfirm(null); }, [open]);
  const runConfirmed = () => {
    if (confirm?.action === "remove" && confirm.destinationHash) onRemove(confirm.destinationHash);
    if (confirm?.action === "leave") onLeave();
    if (confirm?.action === "close") onCloseGroup();
    setConfirm(null);
  };
  return (
    <details className="group-details" open={open}>
      <summary onClick={(event) => { event.preventDefault(); onOpenChange(!open); }}><Users size={17} /> Members &amp; security</summary>
      <div className="group-details__panel">
        <p className="group-details__policy">{groupPolicyLabel(group.posting_policy)}</p>
        <div className="group-member-list">
          {visibleMembers.map((member) => (
            <div className="group-member" key={member.destination_hash}>
              <Avatar name={member.display_name} small />
              <span><strong>{member.display_name}{member.destination_hash === selfDestination ? " (you)" : ""}</strong><small>{member.status === "invited" ? groupInviteDeliveryLabel(member) : `${member.role} · ${member.status.replace("_", " ")}`}</small></span>
              {owner && member.status === "invited" && member.invite_delivery_state !== "delivered" && (
                <button type="button" className="group-member__retry" onClick={() => onRetryInvite(member.destination_hash)} disabled={busy} aria-label={`Retry invitation to ${member.display_name}`} title="Retry invitation now"><RefreshCw size={16} /></button>
              )}
              {owner && member.status === "active" && member.destination_hash !== selfDestination && (
                <button type="button" className="group-member__remove" onClick={() => setConfirm({ action: "remove", destinationHash: member.destination_hash })} disabled={busy} aria-label={`Remove ${member.display_name}`}><UserMinus size={16} /></button>
              )}
            </div>
          ))}
        </div>
        <details className="group-technical">
          <summary>Manifest details</summary>
          <span>Membership epoch {group.epoch}</span>
          <code>{group.manifest_hash}</code>
        </details>
        {group.status === "active" && self && (
          <button type="button" className="group-exit" onClick={() => setConfirm({ action: owner ? "close" : "leave" })} disabled={busy}>
            <LogOut size={16} /> {owner ? "Close group" : "Leave group"}
          </button>
        )}
        {confirm && (
          <div className="group-confirm" role="alertdialog" aria-label="Confirm group change">
            <p>{confirm.action === "remove" ? `Remove ${confirmMember?.display_name ?? "this member"}? They will stop receiving new messages after the membership update reaches everyone.` : confirm.action === "close" ? "Close this group for everyone? Members keep messages already received." : "Leave this group? You will stop receiving new messages after the membership update is published."}</p>
            <div><Button variant="ghost" onClick={() => setConfirm(null)} disabled={busy}>Cancel</Button><Button variant="danger" onClick={runConfirmed} disabled={busy}>{busy ? "Updating…" : "Confirm"}</Button></div>
          </div>
        )}
        {error && <p className="form-error" role="alert">{error}</p>}
      </div>
    </details>
  );
}

function GroupConversation({
  group,
  selfDestination,
  messages,
  draft,
  sendError,
  sending,
  actionBusy,
  actionError,
  detailsOpen,
  reactionTargetId,
  reactionCatalogOpen,
  reactionBusyEmoji,
  reactionError,
  onDraft,
  onSend,
  onDetailsOpenChange,
  onToggleReactionPicker,
  onReactionCatalogOpenChange,
  onCloseReactionPicker,
  onSetReaction,
  onBack,
  onDelete,
  onRemove,
  onRetryInvite,
  onLeave,
  onCloseGroup,
}: {
  group: Group;
  selfDestination: string;
  messages: GroupMessage[];
  draft: string;
  sendError: string;
  sending: boolean;
  actionBusy: boolean;
  actionError: string;
  detailsOpen: boolean;
  reactionTargetId: string | null;
  reactionCatalogOpen: boolean;
  reactionBusyEmoji: string | null;
  reactionError: string;
  onDraft: (value: string) => void;
  onSend: () => void;
  onDetailsOpenChange: (open: boolean) => void;
  onToggleReactionPicker: (messageId: string) => void;
  onReactionCatalogOpenChange: (messageId: string, open: boolean) => void;
  onCloseReactionPicker: () => void;
  onSetReaction: (messageId: string, emoji: string, active: boolean) => void;
  onBack: () => void;
  onDelete: () => void;
  onRemove: (destinationHash: string) => void;
  onRetryInvite: (destinationHash: string) => void;
  onLeave: () => void;
  onCloseGroup: () => void;
}) {
  const messageListRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const messageList = messageListRef.current;
    if (!messageList) return;
    try { messageList.scrollTop = messageList.scrollHeight; } catch { /* Scrolling must never hide the thread. */ }
  }, [messages.length]);
  const activeMembers = group.members.filter((member) => member.status === "active");
  const invitedMembers = group.members.filter((member) => member.status === "invited");
  const { canPost, reason: composerReason } = groupComposerState(group, selfDestination);
  return (
    <section className="conversation group-conversation" aria-label={`${group.posting_policy === "owner_admins" ? "Announcement channel" : "Group conversation"} ${group.title}`}>
      <header className="conversation__header">
        <button className="icon-button mobile-only mobile-back" type="button" onClick={onBack} aria-label="Back to conversations"><ArrowLeft size={21} /></button>
        <div className="conversation__person"><GroupAvatar group={group} small /><div><h2>{group.title}</h2><span>{pluralize(activeMembers.length, "member")}{invitedMembers.length > 0 ? ` · ${invitedMembers.length} invited` : ""} · {groupPolicyLabel(group.posting_policy)}</span></div></div>
        <div className="conversation__actions"><button className="icon-button conversation-delete" type="button" onClick={onDelete} disabled={sending || actionBusy} aria-label={`Delete conversation ${group.title}`} title="Delete conversation"><Trash2 size={18} /></button><GroupDetails group={group} selfDestination={selfDestination} open={detailsOpen} busy={actionBusy} error={actionError} onOpenChange={onDetailsOpenChange} onRemove={onRemove} onRetryInvite={onRetryInvite} onLeave={onLeave} onCloseGroup={onCloseGroup} /></div>
      </header>
      {(group.membership_update_pending || group.status !== "active" || group.members.some((member) => member.status === "invited")) && (
        <div className={`connection-banner ${group.status === "forked" ? "connection-banner--identity_changed" : ""}`} role="status">
          {group.status === "forked" ? "Membership conflict detected. Messaging is paused to protect the group." : group.status === "closed" ? "This group has been closed." : group.status === "joining" ? "Waiting for the owner to accept you into this group." : group.status === "removed" || group.status === "left" ? "You are no longer an active member of this group." : group.membership_update_pending ? "A membership update is still reaching the group. Messaging is paused until it arrives." : invitedMembers.length > 0 ? groupInvitationBanner(invitedMembers) : "A membership update is still reaching the group."}
        </div>
      )}
      <div className="message-list" aria-live="polite" ref={messageListRef}>
        <div className="day-divider"><span>Each member receives an individually encrypted copy</span></div>
        {messages.length === 0 && <div className="empty-thread"><LockKeyhole size={30} /><p>No messages yet.</p><span>{canPost ? "Write the first message. Delivery is tracked separately for every member." : composerReason}</span></div>}
        {messages.map((message) => message.kind === "group_event" ? (
          <div className="group-event" key={message.id}>{message.text}</div>
        ) : (
          <article key={message.id} className={`message message--${message.direction} group-message`}>
            {message.direction === "inbound" && <strong className="group-message__sender">{message.sender_display_name}</strong>}
            <p>{message.text}</p>
            <footer>
              <time dateTime={machineTime(message.created_at)}>{formatTime(message.created_at)}</time>
              {message.direction === "outbound" && (
                message.deliveries && message.deliveries.length > 0 ? (
                  <details className="group-delivery">
                    <summary>{message.delivery_summary && message.delivery_summary.total > 0 && message.delivery_summary.delivered === message.delivery_summary.total && <Check size={13} />}{groupDeliveryLabel(message)}</summary>
                    <div>{message.deliveries.map((delivery) => <span key={delivery.recipient_destination}><strong>{delivery.recipient_display_name}</strong><small>{deliveryLabel[delivery.state]}</small></span>)}</div>
                  </details>
                ) : <span className={`delivery delivery--${message.state ?? "queued"}`}>{message.delivery_summary && message.delivery_summary.total > 0 && message.delivery_summary.delivered === message.delivery_summary.total && <Check size={13} />}{groupDeliveryLabel(message)}</span>
              )}
              <MessageReactions
                messageText={message.text}
                reactions={message.reactions}
                pickerOpen={reactionTargetId === message.id}
                catalogOpen={reactionTargetId === message.id && reactionCatalogOpen}
                busyEmoji={reactionBusyEmoji}
                error={reactionTargetId === message.id ? reactionError : ""}
                onTogglePicker={() => onToggleReactionPicker(message.id)}
                onCatalogOpenChange={(open) => onReactionCatalogOpenChange(message.id, open)}
                onClosePicker={onCloseReactionPicker}
                onSetReaction={(emoji, active) => onSetReaction(message.id, emoji, active)}
              />
            </footer>
          </article>
        ))}
      </div>
      {canPost ? (
        <form className="composer" aria-busy={sending} onSubmit={(event) => { event.preventDefault(); onSend(); }}>
          {sendError && <p className="composer__error" role="alert">{sendError}</p>}
          <label className="sr-only" htmlFor="group-message-composer">Message {group.title}</label>
          <textarea id="group-message-composer" rows={1} value={draft} readOnly={sending} enterKeyHint="send" onChange={(event) => onDraft(event.target.value)} placeholder={`Message ${group.title}`} maxLength={16384} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); onSend(); } }} />
          <button type="submit" disabled={sending || !draft.trim()} aria-label="Send group message"><Send size={19} /></button>
        </form>
      ) : <div className="composer composer--restricted"><LockKeyhole size={17} /><span>{composerReason}</span></div>}
    </section>
  );
}

function newOperationId(): string {
  if (typeof globalThis.crypto?.randomUUID === "function") {
    return globalThis.crypto.randomUUID();
  }
  const bytes = new Uint8Array(16);
  globalThis.crypto.getRandomValues(bytes);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function workspaceStateLabel(workspace: Workspace): string {
  const joinStatus = workspaceJoinStatus(workspace);
  if (joinStatus) return joinStatus.headline;
  switch (workspace.state) {
    case "linking": return "Waiting for device approval";
    case "leaving": return "Leave request pending";
    case "left": return "Left workspace";
    case "removed": return "Membership removed";
    case "device_removed": return "This device was removed";
    case "closed": return "Closed · read-only";
    case "forked": return "Paused for a security conflict";
    case "incomplete_sync": return "Incomplete sync";
    default: return "Active";
  }
}

function workspaceSyncIssueLabel(workspace: Workspace): string {
  if (!workspace.sync_issue) return "";
  if (workspace.sync_issue === "queue_pressure") {
    return "Sync paused because the protected pending queue is full. Keep Mesh Chat open and review workspace diagnostics.";
  }
  return "Waiting for signed controls or an earlier event. Keep Mesh Chat open so an authorized peer can complete synchronization.";
}

function WorkspaceSwitcher({ workspaces, activeId, onSelect, onCreate, onJoin }: { workspaces: Workspace[]; activeId: "personal" | string; onSelect: (id: "personal" | string) => void; onCreate: () => void; onJoin: () => void }) {
  return (
    <nav className="workspace-switcher" aria-label="Spaces">
      <button className={`workspace-switcher__item ${activeId === "personal" ? "workspace-switcher__item--active" : ""}`} onClick={() => onSelect("personal")} aria-current={activeId === "personal" ? "page" : undefined} aria-label="Personal space" title="Personal"><MessageCircleMore size={17} /></button>
      {workspaces.map((workspace) => { const reviews = workspace.pending_owner_review_count ?? 0; const status = workspaceStateLabel(workspace); const attention = reviews > 0 ? `${reviews} owner ${reviews === 1 ? "review" : "reviews"} pending` : workspace.state !== "active" ? status : ""; return <button key={workspace.id} className={`workspace-switcher__item ${activeId === workspace.id ? "workspace-switcher__item--active" : ""}`} onClick={() => onSelect(workspace.id)} aria-current={activeId === workspace.id ? "page" : undefined} aria-label={`Workspace ${workspace.name}${attention ? `, ${attention}` : ""}`} title={`${workspace.name} · ${reviews > 0 ? attention : status}`}><span>{initials(workspace.name)}</span>{(workspace.state !== "active" || reviews > 0) && <i className={reviews > 0 ? "workspace-switcher__review-count" : undefined} aria-hidden="true">{reviews > 0 ? Math.min(reviews, 99) : ""}</i>}</button>; })}
      <button className="workspace-switcher__item workspace-switcher__item--add" onClick={onCreate} aria-label="Create workspace" title="Create workspace"><Plus size={16} /></button>
      <button className="workspace-switcher__item workspace-switcher__item--join" onClick={onJoin} aria-label="Join or connect" title="Join or connect"><LogIn size={16} /></button>
    </nav>
  );
}

function CreateWorkspaceDialog({ onClose, onCreated }: { onClose: () => void; onCreated: (workspace: Workspace) => Promise<void> }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const create = async () => {
    if (!name.trim() || busy) return;
    setBusy(true); setError("");
    try {
      const workspace = await serviceCommand<Workspace>("create_workspace", { operation_id: newOperationId(), name: name.trim(), description: description.trim() });
      await onCreated(workspace);
    } catch (reason) { setError(errorMessage(reason)); }
    finally { setBusy(false); }
  };
  return <Dialog title="Create a workspace" onClose={onClose}><div className="form-stack workspace-create"><p className="dialog-lead">A private collaboration space for a trusted team.</p><label>Name<input autoFocus value={name} maxLength={64} onChange={(event) => setName(event.target.value)} aria-label="Workspace name" /></label><label>Description <small>Optional</small><textarea value={description} maxLength={250} onChange={(event) => setDescription(event.target.value)} aria-label="Workspace description" /></label><div className="workspace-facts"><p><ShieldCheck size={17} /><span><strong>This device becomes the owner authority.</strong> Link another device and rotate authority before retiring this one.</span></p><p><Users size={17} /><span>Every public message is encrypted separately for each member device.</span></p><p><WifiOff size={17} /><span>Delivery and history depend on reachable peers; there is no hosted workspace server.</span></p></div>{error && <p className="form-error" role="alert">{error}</p>}<div className="dialog-actions"><Button variant="ghost" onClick={onClose}>Cancel</Button><Button disabled={busy || !name.trim()} onClick={() => void create()}>{busy ? "Creating…" : "Create workspace"}</Button></div></div></Dialog>;
}

function JoinWorkspaceDialog({ initialValue = "", resumeWorkspaceId, workspaces, onClose, onJoined }: { initialValue?: string; resumeWorkspaceId?: string; workspaces: Workspace[]; onClose: () => void; onJoined: (workspace: Workspace) => Promise<void> }) {
  const [value, setValue] = useState(initialValue);
  const [preview, setPreview] = useState<WorkspaceInvitationPreview | null>(null);
  const [devicePreview, setDevicePreview] = useState<WorkspaceDeviceLinkPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [remoteConsent, setRemoteConsent] = useState(false);
  const [i2pConsent, setI2PConsent] = useState(false);
  const [connectionResults, setConnectionResults] = useState<ParticipantCandidateResult[]>([]);
  const [joinedWorkspace, setJoinedWorkspace] = useState<Workspace | null>(null);
  const existingWorkspace = preview && !joinedWorkspace
    ? workspaces.find((item) => item.id === preview.workspace_id) ?? preview.existing_workspace
    : undefined;
  const existingJoinStatus = existingWorkspace ? workspaceJoinStatus(existingWorkspace) : null;
  const canResumeExisting = preview?.can_resume_join === true
    && existingWorkspace?.state === "joining" && existingJoinStatus?.terminal === false;
  const resumeExplanation = preview?.join_resume_reason ? ({
    invitation_mismatch: "This invitation does not match the invitation saved for this request. To continue it, reopen the exact original invitation.",
    request_stopped: "This saved request has stopped. Open Workspace settings to review the failed join before starting again.",
    request_expired: "The saved request’s delivery window has expired. Open the saved workspace to review its status.",
    identity_mismatch: "The saved request belongs to a different local device identity. Mesh Chat cannot reuse it for this identity.",
    saved_request_invalid: "The saved request could not be verified for recovery. Open the saved workspace to review its status.",
  })[preview.join_resume_reason] : "This invitation cannot currently resume the saved request. Open the saved workspace to review its status.";
  const currentJoin = workspaces.find((item) => item.id === joinedWorkspace?.id) ?? joinedWorkspace;
  const currentJoinStatus = currentJoin ? workspaceJoinStatus(currentJoin) : null;
  const joinReceived = currentJoin?.join_acknowledged === true || currentJoin?.state === "active";
  const [replyFormats, setReplyFormats] = useState<ConnectionDocumentFormats | null>(null);
  const [replyShared, setReplyShared] = useState(false);
  const [replyDoctor, setReplyDoctor] = useState<DirectDoctorReport | null>(null);
  const replyHostSession = useRef<string | null>(null);
  const reviewGeneration = useRef(0);
  const lastInitialValue = useRef<string | null>(null);
  const joinAttempt = useRef<{ command: string; document: string; operationId: string } | null>(null);
  const stopUnsharedReply = async () => {
    const hostId = replyHostSession.current;
    if (hostId && !replyShared) await serviceCommand("stop_participant_host", { access_id: hostId }).catch(() => undefined);
    replyHostSession.current = null;
  };
  const closeDialog = async () => { await stopUnsharedReply(); onClose(); };
  const reviewCandidate = useCallback(async (candidate: string) => {
    if (!candidate.trim()) return;
    const generation = ++reviewGeneration.current;
    setBusy(true); setError("");
    setConnectionResults([]); setJoinedWorkspace(null); setReplyDoctor(null);
    let normalized = candidate;
    try {
      normalized = await normalizeInvitationInput(candidate);
      if (generation !== reviewGeneration.current) return;
      setValue(normalized);
      if (classifyInvitationInput(normalized) === "direct_connection") {
        setPreview(null); setDevicePreview(null);
        return;
      }
      if (isWorkspacePrefixOnly(normalized)) {
        setPreview(null);
        setDevicePreview(null);
        setError(incompleteWorkspacePrefixMessage(normalized));
        return;
      }
      const isDeviceLink = classifyInvitationInput(normalized) === "workspace_device";
      if (isDeviceLink) {
        const checked = await serviceCommand<WorkspaceDeviceLinkPreview>("preview_workspace_device_link", { device_link: normalized });
        if (generation !== reviewGeneration.current) return;
        setDevicePreview(checked);
        setPreview(null);
        setRemoteConsent(false); setI2PConsent(false);
      } else {
        const checked = await serviceCommand<WorkspaceInvitationPreview>("preview_workspace_invitation", { invitation: normalized });
        if (generation !== reviewGeneration.current) return;
        setPreview(checked);
        setRemoteConsent(false); setI2PConsent(false);
        setDevicePreview(null);
      }
    }
    catch (reason) {
      if (generation !== reviewGeneration.current) return;
      setPreview(null); setDevicePreview(null);
      setError(workspaceInvitationErrorMessage(reason, normalized));
    }
    finally { if (generation === reviewGeneration.current) setBusy(false); }
  }, []);
  const review = async () => { await reviewCandidate(value); };
  useEffect(() => {
    if (lastInitialValue.current === initialValue) return;
    lastInitialValue.current = initialValue;
    reviewGeneration.current += 1;
    setBusy(false); setValue(initialValue); setError("");
    setPreview(null); setDevicePreview(null); setRemoteConsent(false); setI2PConsent(false);
    setConnectionResults([]); setJoinedWorkspace(null); setReplyFormats(null); setReplyDoctor(null);
    void stopUnsharedReply();
    if (initialValue.trim()) void reviewCandidate(initialValue);
  }, [initialValue, reviewCandidate]);
  const join = async () => {
    if ((!preview && !devicePreview) || (existingWorkspace && !canResumeExisting) || busy) return;
    setBusy(true); setError("");
    try {
      const document = value.trim();
      const command = devicePreview ? "submit_workspace_device_link" : "submit_workspace_join";
      // A lost response can follow a successful durable save. Retrying the same
      // document must recover that operation instead of creating another one.
      if (joinAttempt.current?.command !== command || joinAttempt.current.document !== document) {
        joinAttempt.current = { command, document, operationId: newOperationId() };
      }
      const workspace = await serviceCommand<Workspace>(command, {
        operation_id: joinAttempt.current.operationId,
        ...(devicePreview ? { device_link: document } : { invitation: document, ...(preview?.i2p_access_point ? { i2p_consent: i2pConsent } : {}) }),
      });
      if (workspace.connection_results?.length && !workspace.connection_results.some((item) => item.result === "connected")) {
        setConnectionResults(workspace.connection_results);
        setJoinedWorkspace(workspace);
      } else if (workspace.connection_setup_failed || preview?.connection_reply_available && !preview.participant_access) {
        setJoinedWorkspace(workspace);
      } else await onJoined(workspace);
    } catch (reason) { setError(workspaceInvitationErrorMessage(reason, value)); }
    finally { setBusy(false); }
  };
  const createReply = async () => {
    setBusy(true); setError("");
    try {
      const report = await serviceCommand<DirectDoctorReport>("check_direct_connection");
      if (!canPrepareDirectHost(report)) {
        setReplyDoctor(report);
        return;
      }
      setReplyDoctor(null);
      const created = await serviceCommand<ConnectionDocumentFormats>("create_connection_reply", { invitation: value.trim(), purpose: "workspace" });
      const previous = replyHostSession.current;
      replyHostSession.current = created.host_session_id ?? null;
      setReplyShared(false); setReplyFormats(created);
      if (previous && previous !== created.host_session_id) await serviceCommand("stop_participant_host", { access_id: previous }).catch(() => undefined);
    }
    catch (reason) {
      const report = directFailureReport(reason);
      if (report) setReplyDoctor(report);
      else setError(errorMessage(reason));
    }
    finally { setBusy(false); }
  };
  const reviewed = preview !== null || devicePreview !== null;
  const openExisting = async () => {
    if (!existingWorkspace || busy) return;
    setBusy(true); setError("");
    try { await stopUnsharedReply(); await onJoined(existingWorkspace); }
    catch (reason) { setError(errorMessage(reason)); }
    finally { setBusy(false); }
  };
  if (resumeWorkspaceId || classifyInvitationInput(value) === "direct_connection") {
    return <Dialog title="Join or connect" onClose={() => void closeDialog()}><DirectConnectionSetup workspaceId={resumeWorkspaceId} initialDocument={value} onOpenWorkspace={onJoined} /></Dialog>;
  }
  return <Dialog title={devicePreview ? "Link this device" : "Join or connect"} onClose={() => void closeDialog()}>
    <div className="form-stack">
      {preview ? <>
        <div className="workspace-preview"><span className="workspace-preview__avatar">{initials(preview.name)}</span><div><h3>{preview.name}</h3><p>{preview.description || "No description"}</p></div></div>
        <dl className="security-list"><div><dt>Owner fingerprint</dt><dd>{preview.owner_fingerprint}</dd></div><div><dt>Current members</dt><dd>{preview.member_count}</dd></div><div><dt>History preference</dt><dd>{preview.retention_days === null ? "Indefinite" : `${preview.retention_days} days`}</dd></div></dl>
        {preview.i2p_access_point && <section className="direct-consent" aria-labelledby="workspace-i2p-connection"><h3 id="workspace-i2p-connection">Relayed via I2P</h3><p>This signed workspace invitation asks to use an I2P access point. Traffic is relayed; it is not a direct connection. The access point can see connection metadata, not message contents.</p><p><code>{preview.i2p_access_point.b32}</code></p><label className="checkbox-line"><input type="checkbox" checked={i2pConsent} onChange={(event) => setI2PConsent(event.target.checked)} /> Use this I2P access point for this join</label></section>}
        {existingWorkspace ? <section className="direct-host-warning" role="status">
          <h3>Workspace already saved</h3>
          <p><strong>{workspaceStateLabel(existingWorkspace)}</strong></p>
          <p>{existingJoinStatus?.detail ?? "Open the saved workspace to view its current status and available actions."}</p>
          <p>This invitation will not replace the workspace or its saved join request.</p>
          {existingWorkspace.state === "joining" && !canResumeExisting && <p>{resumeExplanation}</p>}
          {canResumeExisting && <Button variant="secondary" disabled={busy} onClick={() => void join()}>Continue saved request</Button>}
          <Button disabled={busy} onClick={() => void openExisting()}>{busy ? "Opening…" : "Open saved workspace"}</Button>
        </section> : <>
        <p className="muted">Joining does not approve a global contact. The owner must verify this device and approve your request.</p>
        {preview.participant_access && <section className="direct-consent" aria-labelledby="workspace-direct-connection"><h3 id="workspace-direct-connection">Direct connection to the workspace owner</h3><p>{preview.participant_access.privacy_disclosure}</p><p>The owner must keep Mesh Chat open until your request arrives.</p></section>}
        {preview.connection_reply_available && <section className="direct-consent"><h3>How this request will be sent</h3><p>{preview.participant_access ? "Mesh Chat will connect outbound to the owner’s signed route first. If every candidate fails, this device can be checked for an optional return connection." : "Mesh Chat will first save and try the signed join request over any existing or same-network Mesh route. If no route is confirmed, it will then offer to check this device for an optional return connection."}</p></section>}
        {preview.remote_profile && <section className="remote-consent" aria-labelledby="workspace-remote-consent"><h3 id="workspace-remote-consent">Remote connection requested</h3><p><strong>{preview.remote_profile.label}</strong> · {preview.remote_profile.endpoint_count} access-point {preview.remote_profile.endpoint_count === 1 ? "endpoint" : "endpoints"}</p><p>{preview.remote_profile.privacy_disclosure}</p><label className="checkbox-line"><input type="checkbox" checked={remoteConsent} onChange={(event) => setRemoteConsent(event.target.checked)} /> Connect outbound after I send the join request</label></section>}
        {replyFormats && <ConnectionDocumentShare formats={replyFormats} kind="reply" onShared={() => setReplyShared(true)} />}
        </>}
      </> : devicePreview ? <>
        <div className="workspace-preview"><span className="workspace-preview__avatar">{initials(devicePreview.name)}</span><div><h3>{devicePreview.name}</h3><p>Link as {devicePreview.member_display_name}</p></div></div>
        <dl className="security-list"><div><dt>Sponsor fingerprint</dt><dd>{devicePreview.sponsor_fingerprint}</dd></div><div><dt>Existing devices</dt><dd>{devicePreview.device_count}</dd></div><div><dt>Expires</dt><dd>{formatExpiry(devicePreview.expires_at)}</dd></div></dl>
        <p className="muted">This device creates a fresh private identity. No key material is copied. The workspace owner must admit the new device before it can read or send workspace messages.</p>
      </> : <>
        <p>Paste a signed one-use invitation to join as a new person, or a device link created from one of your admitted devices.</p>
        <textarea autoFocus autoCapitalize="off" autoCorrect="off" spellCheck={false} value={value} onChange={(event) => { reviewGeneration.current += 1; setBusy(false); setValue(event.target.value); setReplyDoctor(null); setError(""); }} aria-label="Workspace invitation or device link" rows={7} />
        <InvitationImportActions onValue={(imported) => { reviewGeneration.current += 1; setBusy(false); setValue(imported); setReplyDoctor(null); setError(""); setPreview(null); setDevicePreview(null); }} />
      </>}
      {currentJoin && <section className="direct-host-warning" role="status"><h3>{joinReceived ? currentJoinStatus?.headline ?? "Workspace joined" : connectionResults.length > 0 ? "No candidate connected yet" : "Join request saved"}</h3>{!joinReceived && connectionResults.length > 0 && <pre>{candidateSummary(connectionResults)}</pre>}<p>{currentJoinStatus?.detail ?? "The owner approved this device. Open the workspace to continue."}</p>{!joinReceived && preview?.connection_reply_available && !replyFormats && !replyDoctor && <Button variant="secondary" onClick={() => void createReply()} disabled={busy}>{busy ? "Checking this network…" : "Check this device for a return connection"}</Button>}<Button onClick={() => void onJoined(currentJoin)}>{currentJoin.state === "active" ? "Open workspace" : "View pending workspace"}</Button></section>}
      {replyDoctor && <ReturnConnectionUnavailable report={replyDoctor} busy={busy} onRetry={() => void createReply()} />}
      {error && <p className="form-error" role="alert">{error}</p>}
      <div className="dialog-actions">{!joinedWorkspace && <>
        <Button variant="ghost" onClick={reviewed ? () => { void stopUnsharedReply(); setPreview(null); setDevicePreview(null); setRemoteConsent(false); setI2PConsent(false); setReplyFormats(null); setReplyDoctor(null); } : () => void closeDialog()}>{reviewed ? "Back" : "Cancel"}</Button>
        {!existingWorkspace && <Button disabled={busy || (!reviewed && !value.trim()) || Boolean(preview?.remote_profile) && !remoteConsent || Boolean(preview?.i2p_access_point) && !i2pConsent} onClick={() => void (reviewed ? join() : review())}>{busy ? "Working…" : devicePreview ? "Request device approval" : preview ? replyFormats ? "Send join request after sharing" : preview.remote_profile ? "Connect and send join request" : preview.participant_access ? "Connect directly and send join request" : "Send join request" : "Review"}</Button>}
      </>}</div>
    </div>
  </Dialog>;
}

function WorkspaceInviteDialog({ workspace, existingInvitations, remoteProfiles, onClose }: { workspace: Workspace; existingInvitations: WorkspaceInvitation[]; remoteProfiles: RemoteProfile[]; onClose: () => void }) {
  const [invitation, setInvitation] = useState<WorkspaceInvitationFormats | null>(null);
  const [savedSetupId, setSavedSetupId] = useState<string | null>(null);
  const [existing, setExisting] = useState(existingInvitations);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");
  const [connectionChoice, setConnectionChoice] = useState(() => getWebRTCSession() ? "webrtc" : "guided");
  const [doctor, setDoctor] = useState<DirectDoctorReport | null>(null);
  const [manualSetup, setManualSetup] = useState<ManualParticipantSetup | null>(null);
  const [manualHost, setManualHost] = useState("");
  const [manualPort, setManualPort] = useState("");
  const [i2pAccessPoint, setI2PAccessPoint] = useState("");
  const [shared, setShared] = useState(false);
  const [shareFeedback, setShareFeedback] = useState("");
  const [firewallFeedback, setFirewallFeedback] = useState("");
  const create = async (manual = false) => {
    if (busy) return;
    setBusy(true); setError("");
    const connection = manual && manualSetup
      ? { connection_mode: "manual", manual_setup_id: manualSetup.setup_id, external_host: manualHost.trim(), external_port: Number(manualPort) }
      : connectionChoice === "participant"
      ? { connection_mode: "participant" }
      : connectionChoice === "webrtc"
      ? { connection_mode: "webrtc" }
      : (connectionChoice === "email" || connectionChoice === "guided")
        ? { connection_mode: "email" }
      : connectionChoice === "nearby"
        ? { connection_mode: "nearby" }
      : connectionChoice === "i2p"
        ? { connection_mode: "i2p", i2p_access_point: i2pAccessPoint.trim() }
        : { connection_mode: "remote", remote_profile_id: connectionChoice.slice("remote:".length) };
    try {
      const created = await serviceCommand<WorkspaceInvitationFormats>("create_workspace_invitation", { operation_id: newOperationId(), workspace_id: workspace.id, lifetime_days: 7, ...connection });
      setInvitation(created); setManualSetup(null); setShared(false); setCopied(false); setShareFeedback("");
    } catch (reason) {
      setError(errorMessage(reason));
      const details = (reason as { details?: Record<string, string> })?.details;
      if (details?.phase) setDoctor({ summary: details as unknown as DirectDoctorStep, checks: [details as unknown as DirectDoctorStep] });
    }
    finally { setBusy(false); }
  };
  const revoke = async (invitationId: string) => {
    if (!invitationId || busy) return;
    setBusy(true); setError("");
    try {
      await serviceCommand("revoke_workspace_invitation", { operation_id: newOperationId(), workspace_id: workspace.id, invitation_id: invitationId });
      if (invitation?.id === invitationId) { setInvitation(null); setShared(false); }
      setExisting((current) => current.filter((item) => item.id !== invitationId)); setCopied(false);
    } catch (reason) { setError(errorMessage(reason)); }
    finally { setBusy(false); }
  };
  const usableProfiles = remoteProfiles.filter((profile) => profile.state !== "expired");
  const checkDirect = async () => {
    setBusy(true); setError("");
    try { setDoctor(await serviceCommand<DirectDoctorReport>("check_direct_connection")); }
    catch (reason) { setError(errorMessage(reason)); }
    finally { setBusy(false); }
  };
  const prepareManual = async () => {
    setBusy(true); setError("");
    try {
      if (manualSetup) await serviceCommand("stop_participant_host", { access_id: manualSetup.setup_id }).catch(() => undefined);
      const setup = await serviceCommand<ManualParticipantSetup>("prepare_manual_participant_host", { purpose: "workspace" });
      setManualSetup(setup); setManualHost(""); setManualPort(String(setup.tcp_port)); setDoctor(null);
    } catch (reason) { setError(errorMessage(reason)); }
    finally { setBusy(false); }
  };
  const closeDialog = async () => {
    if (invitation?.host_session_id && !shared) {
      await serviceCommand("revoke_workspace_invitation", { operation_id: newOperationId(), workspace_id: workspace.id, invitation_id: invitation.id }).catch(() => undefined);
    } else if (manualSetup) {
      await serviceCommand("stop_participant_host", { access_id: manualSetup.setup_id }).catch(() => undefined);
    }
    onClose();
  };
  const share = async () => {
    if (!invitation) return;
    if (typeof navigator.share === "function") {
      try {
        await navigator.share({ title: `Join ${workspace.name} in Mesh Chat`, text: invitation.text });
        setShared(true); setShareFeedback("Complete invitation shared.");
        return;
      }
      catch (reason) { if (reason instanceof DOMException && reason.name === "AbortError") return; }
    }
    await copyInvitation();
  };
  const copyInvitation = async () => {
    if (!invitation) return;
    try {
      await navigator.clipboard.writeText(invitation.text);
      setCopied(true); setShared(true);
      setShareFeedback(`Complete invitation copied (${invitation.text.length.toLocaleString()} characters).`);
    } catch {
      setCopied(false);
      setShareFeedback("Copy was unavailable. Select the invitation box once to select all of it, then copy.");
    }
  };
  const save = () => {
    if (!invitation) return;
    const blob = new Blob([invitation.value], { type: "application/json" });
    const anchor = document.createElement("a");
    anchor.href = URL.createObjectURL(blob);
    anchor.download = "mesh-chat-workspace-invite.meshchat-invite";
    anchor.click(); URL.revokeObjectURL(anchor.href); setShared(true);
  };
  const configureFirewall = async () => {
    if (!invitation?.host_session_id || busy) return;
    setBusy(true); setFirewallFeedback("");
    try {
      const result = await serviceCommand<DirectDoctorStep>("configure_participant_firewall", { access_id: invitation.host_session_id });
      setFirewallFeedback(result.result === "prepared_unverified"
        ? "Temporary Windows Firewall rule added for this invitation only."
        : `${directReasonLabel(result.reason)} ${directActionLabel(result.recommended_action)}`);
    } catch (reason) { setFirewallFeedback(errorMessage(reason)); }
    finally { setBusy(false); }
  };
  return <Dialog title={`Invite to ${workspace.name}`} onClose={() => void closeDialog()} wide><div className="form-stack">
    {savedSetupId && <DirectConnectionSetup key={savedSetupId} invitationId={savedSetupId} resumeExisting />}
    {invitation && connectionChoice === "guided" && <><DirectConnectionSetup invitationId={invitation.id} autoStart onShared={() => setShared(true)} /><Button variant="danger" disabled={busy} onClick={() => void revoke(invitation.id)}>Revoke invitation</Button></>}
    {invitation && connectionChoice !== "guided" && <><p>This bearer invitation works once and expires {formatExpiry(invitation.expires_at)}. This is the effective direct-host expiry.</p>{invitation.connection_mode === "participant" && <p className="direct-host-status" role="status"><ShieldCheck size={17} /> Prepared — waiting for recipient verification. Keep this owner device online.</p>}{invitation.connection_mode === "email" && <p className="direct-host-status" role="status"><ShieldCheck size={17} /> Email-ready. {invitation.host_session_id ? "The joiner tries this owner device first, then may check their device for a return connection." : "This owner device could not host an inbound path. The joiner can first try an existing or same-network Mesh route, and may create a return reply only if their network accepts inbound traffic."}</p>}{invitation.methods?.includes("manual") && <p className="muted">Mesh Chat cannot remove your manual router rule. Remove it in the router when it is no longer needed.</p>}<InvitationQrCode document={invitation.value} destination="workspace" /><label className="field"><span>Complete workspace invitation</span><textarea readOnly value={invitation.text} aria-label="Workspace invitation text" rows={5} onFocus={(event) => event.currentTarget.select()} /></label><p className="muted invite-safety">Send the entire value in this box. The <strong>MESHWORKSPACE…</strong> prefix by itself is only the format label, not an invitation.</p><div className="dialog-actions"><Button variant="danger" disabled={busy} onClick={() => void revoke(invitation.id)}>Revoke invitation</Button><Button variant="secondary" onClick={() => void copyInvitation()}>{copied ? <Check size={17} /> : <Copy size={17} />}{copied ? "Complete invitation copied" : "Copy complete invitation"}</Button><Button variant="secondary" onClick={() => void share()}><Share2 size={17} /> Share complete invitation</Button><Button variant="ghost" onClick={save}><FileUp size={17} /> Save invitation file</Button>{invitation.connection_mode === "participant" && invitation.host_session_id && !invitation.methods?.includes("manual") && <Button variant="ghost" disabled={busy} onClick={() => void configureFirewall()}><ShieldCheck size={17} /> Allow in Windows Firewall</Button>}</div>{shareFeedback && <p className="invite-feedback" aria-live="polite">{shareFeedback}</p>}{firewallFeedback && <p className="muted" role="status">{firewallFeedback}</p>}</>}
    {!invitation && !savedSetupId && <>{connectionChoice === "guided" && <><p>Send an invitation, then follow the steps on both devices. No account or connection server is needed. Some networks cannot connect directly.</p><Button disabled={busy} onClick={() => void create()}>{busy ? "Preparing…" : "Prepare invitation"}</Button></>}<details><summary>Other connection options</summary><label className="field"><span>How should they connect?</span><select value={connectionChoice} disabled={busy} onChange={(event) => { setConnectionChoice(event.target.value); setDoctor(null); setError(""); }}><option value="guided">Guided connection (recommended)</option>{getWebRTCSession() && <option value="webrtc">WebRTC bridge — connected</option>}<option value="participant">Advanced: direct TCP hosting</option><option value="email">Email-assisted direct connection — reverse direction if possible</option><option value="nearby">Same network only — will not work over cellular</option><option value="i2p">I2P access point — relayed through I2P</option>{usableProfiles.map((profile) => <option key={profile.id} value={`remote:${profile.id}`}>Approved access point · {profile.label} · {profile.state === "connected" ? "connected" : "currently unavailable"}</option>)}</select></label>{connectionChoice === "webrtc" && <><p className="muted">This workspace invitation uses the connected WebRTC DataChannel. The joiner must have the matching bridge; owner approval is still required.</p><Button disabled={busy} onClick={() => void create()}>{busy ? "Creating…" : "Create WebRTC workspace invitation"}</Button></>}{connectionChoice === "participant" && <><p className="muted">Direct participant hosting stays on this owner device. Keep Mesh Chat open through approval.</p><div className="dialog-actions"><Button variant="secondary" disabled={busy} onClick={() => void checkDirect()}>{busy ? "Checking this network…" : "Check direct Internet connection"}</Button><Button disabled={busy} onClick={() => void create()}>{busy ? "Preparing a direct route…" : "Prepare direct Internet invitation"}</Button><Button variant="ghost" disabled={busy} onClick={() => void prepareManual()}>Set up manual port forwarding</Button></div>{doctor && <DirectDoctorPanel report={doctor} busy={busy} onRetry={() => void checkDirect()} onManualSetup={() => void prepareManual()} />}{manualSetup && <ManualForwardingPanel setup={manualSetup} host={manualHost} port={manualPort} busy={busy} onHostChange={setManualHost} onPortChange={setManualPort} onCreate={() => void create(true)} />}</>}{connectionChoice === "email" && <><p className="muted">Creates the signed one-use invitation even when this owner device cannot accept inbound traffic. The joiner first tries any existing or same-network Mesh route; a return reply works only if the joiner’s network can accept inbound traffic.</p><p className="muted">Mesh Chat never accesses an email account. If both networks block inbound connections and no shared route exists, invitation exchange alone cannot create one.</p><Button disabled={busy} onClick={() => void create()}>{busy ? "Creating…" : "Create email-ready invitation"}</Button></>}{connectionChoice === "nearby" && <><p className="direct-host-warning">Same network only — will not work over cellular.</p><Button disabled={busy} onClick={() => void create()}>{busy ? "Creating…" : "Create same-network invitation"}</Button></>}{connectionChoice === "i2p" && <><p className="muted">The signed workspace invitation carries one I2P access point. The joiner must consent before traffic is relayed. I2P is a relay, not a direct connection.</p><label className="field"><span>I2P access point address</span><input value={i2pAccessPoint} onChange={(event) => setI2PAccessPoint(event.target.value.trim())} placeholder="example.b32.i2p" spellCheck={false} /></label><Button disabled={busy || !/^[a-z2-7]{52}\.b32\.i2p$/i.test(i2pAccessPoint)} onClick={() => void create()}>{busy ? "Creating…" : "Create I2P workspace invitation"}</Button></>}{connectionChoice.startsWith("remote:") && <><p className="muted">This invitation explicitly uses the named approved access point selected above. Its operator can observe connection metadata.</p><Button disabled={busy} onClick={() => void create()}>{busy ? "Creating…" : "Create using selected access point"}</Button></>}<p>Create a separate signed invitation for each person. Each request is reviewed independently.</p></details></>}
    {existing.length > 0 && <div className="workspace-invitation-list"><h3>Active invitations</h3>{existing.filter((item) => item.id !== invitation?.id).map((item) => <div className="workspace-invitation-row" key={item.id}><span>One-use invitation · expires {formatExpiry(item.expires_at)}</span>{!invitation && <Button variant="secondary" disabled={busy} onClick={() => setSavedSetupId(item.id)}>Continue setup</Button>}<Button variant="ghost" disabled={busy} onClick={() => void revoke(item.id)}>Revoke</Button></div>)}</div>}
    {error && <p className="form-error" role="alert">{error}</p>}
  </div></Dialog>;
}

function WorkspaceDevicesDialog({ workspace, transitions, busy, error, onClose, onCreate, onDecide, onRemove, onReadSync }: { workspace: Workspace; transitions: WorkspaceDeviceTransition[]; busy: boolean; error: string; onClose: () => void; onCreate: () => Promise<WorkspaceDeviceLinkFormats | null>; onDecide: (transition: WorkspaceDeviceTransition, approve: boolean) => void; onRemove: (deviceId: string) => void; onReadSync: (enabled: boolean) => void }) {
  const [link, setLink] = useState<WorkspaceDeviceLinkFormats | null>(null);
  const [copied, setCopied] = useState(false);
  const localMember = workspace.members.find((member) => member.id === workspace.local_member_id);
  const devices = localMember?.devices ?? (localMember ? [localMember.device] : []);
  const pending = transitions.filter((item) => item.state === "pending");
  const create = async () => {
    const created = await onCreate();
    if (created) { setLink(created); setCopied(false); }
  };
  return <Dialog title={`Linked devices · ${workspace.name}`} onClose={onClose}><div className="form-stack">
    <p className="muted">Each device has its own private identity. Workspace events fan out to every admitted device; delivery details remain visible per person and device.</p>
    <section className="workspace-name-requests"><h3>Your admitted devices · {devices.length}/3</h3>{devices.map((device, index) => <div className="workspace-invitation-row" key={device.id}><span><strong>{device.id === workspace.local_device_id ? "This device" : `Device ${index + 1}`}</strong><small>{device.fingerprint}{device.id === workspace.authority_device_id ? " · workspace authority" : ""}</small></span>{device.id !== workspace.local_device_id && <Button variant="danger" disabled={busy || device.id === workspace.authority_device_id} title={device.id === workspace.authority_device_id ? "Rotate workspace authority before removing this device" : undefined} onClick={() => onRemove(device.id)}>Remove</Button>}</div>)}</section>
    {link ? <section className="workspace-name-requests"><h3>One-time device link</h3><p>Open Mesh Chat on the new device, choose Join workspace, and paste this link before {formatExpiry(link.expires_at)}.</p><textarea readOnly value={link.text} aria-label="Workspace device link" rows={5} /><Button variant="secondary" onClick={async () => { await navigator.clipboard.writeText(link.text); setCopied(true); }}>{copied ? <Check size={17} /> : <Copy size={17} />}{copied ? "Copied" : "Copy device link"}</Button></section> : <Button disabled={busy || workspace.state !== "active" || devices.length >= 3} onClick={() => void create()}>{devices.length >= 3 ? "Three-device limit reached" : "Link another device"}</Button>}
    <label className="checkbox-line"><input type="checkbox" checked={Boolean(workspace.read_hint_sync)} disabled={busy || workspace.state !== "active"} onChange={(event) => onReadSync(event.target.checked)} /> Privately sync local read position between my linked devices</label><p className="muted">Read hints go only to your other admitted devices. They never become social read receipts and are ignored until both devices have the same canonical conversation head.</p>
    {workspace.local_role === "owner" && pending.length > 0 && <section className="workspace-name-requests" aria-live="polite"><h3>Owner review</h3>{pending.map((transition) => <div className="workspace-invitation-row" key={transition.id}><span><strong>{transition.transition_kind === "link" ? "Admit a new device" : "Remove a linked device"}</strong><small>{transition.fingerprint || "Signed device request"} · effective access is unchanged until approval</small></span><span><Button disabled={busy} onClick={() => onDecide(transition, true)}>Approve</Button><Button variant="ghost" disabled={busy} onClick={() => onDecide(transition, false)}>Decline</Button></span></div>)}</section>}
    {transitions.some((item) => item.state === "waiting_for_approval") && <p className="workspace-directory-status" role="status">A signed device change is waiting for the workspace owner. Existing effective access is unchanged.</p>}
    {error && <p className="form-error" role="alert">{error}</p>}
  </div></Dialog>;
}

function workspaceAdminRequestLabel(request: WorkspaceAdminRequest): string {
  if (request.request_kind === "invitation") return "Create a one-use invitation";
  if (request.request_kind === "member_removal") return `Remove ${request.target_display_name ?? "member"}`;
  return `Change ${request.target_display_name ?? "member"} from ${request.effective_role ?? "current role"} to ${request.requested_role}`;
}

function workspaceAdminRequestStateLabel(request: WorkspaceAdminRequest): string {
  if (request.state === "pending") {
    if (request.delivery_state === "waiting_for_route") return "Waiting for route to owner";
    if (request.delivery_state === "delivered_to_owner") return "Delivered to owner · waiting for approval";
    return "Waiting for owner approval";
  }
  const labels: Record<WorkspaceAdminRequest["state"], string> = {
    pending: "Waiting for owner approval",
    approved: request.request_kind === "invitation" ? "Approved · invitation ready" : "Approved and applied",
    declined: "Declined by owner",
    stale: "Stale because workspace state changed",
    superseded: "Superseded by another authority action",
    expired: "Expired before an owner decision",
    cancelled: "Cancelled locally before delivery",
    failed: "Failed · review the security warning and retry if safe",
  };
  return labels[request.state];
}

function WorkspacePeopleDialog({ workspace, requests, adminRequests, busy, error, onClose, onRequestName, onDecideName, onRemove, onChangeRole, onInvitationPolicy, onSubmitAdminRequest, onDecideAdminRequest, onCancelAdminRequest, onDismissAdminRequest, onMessage }: { workspace: Workspace; requests: WorkspaceDisplayNameRequest[]; adminRequests: WorkspaceAdminRequest[]; busy: boolean; error: string; onClose: () => void; onRequestName: (displayName: string) => void; onDecideName: (requestId: string, approve: boolean) => void; onRemove: (memberId: string) => void; onChangeRole: (memberId: string, role: "admin" | "member") => void; onInvitationPolicy: (policy: "owner_only" | "owner_and_admins" | "all_members_request") => void; onSubmitAdminRequest: (kind: "invitation" | "member_removal" | "role_change", targetMemberId?: string, requestedRole?: "admin" | "member") => void; onDecideAdminRequest: (requestId: string, approve: boolean) => void; onCancelAdminRequest: (requestId: string) => void; onDismissAdminRequest: (requestId: string) => void; onMessage: (memberId: string) => void }) {
  const local = workspace.members.find((member) => member.id === workspace.local_member_id);
  const [displayName, setDisplayName] = useState(local?.display_name ?? "");
  const [invitationPolicy, setInvitationPolicy] = useState(workspace.policies.invitation_requests);
  const [confirmRemoval, setConfirmRemoval] = useState<{ id: string; name: string; request: boolean } | null>(null);
  const invitationAllowed = workspace.local_role === "owner"
    || workspace.policies.invitation_requests === "all_members_request"
    || (workspace.local_role === "admin" && workspace.policies.invitation_requests === "owner_and_admins");
  const incoming = adminRequests.filter((request) => request.direction === "incoming" && request.state === "pending");
  const visibleRequests = adminRequests.filter((request) => request.direction === "outgoing" || request.state !== "pending");
  return <Dialog title={`People and administration · ${workspace.name}`} onClose={onClose}><div className="form-stack">
    <p className="workspace-directory-status" role="status"><ShieldCheck size={16} /><span>Your effective role is <strong>{workspace.local_role === "admin" ? "administrator" : workspace.local_role}</strong>. Requested changes below do not alter effective access until the owner authority publishes a manifest.</span></p>
    <div className="workspace-people">{workspace.members.map((member) => {
      const activeTarget = workspace.state === "active" && member.id !== workspace.local_member_id && member.status === "active";
      return <div className="workspace-person" key={member.id}><Avatar name={member.display_name} small /><span><strong>{member.display_name}{member.id === workspace.local_member_id ? " (you)" : ""}</strong><small>{member.role === "admin" ? "administrator" : member.role} · {member.status} · {member.short_id}</small></span><span className="workspace-person__actions">
        {activeTarget && <Button variant="ghost" disabled={busy} onClick={() => onMessage(member.id)}><MessageCircleMore size={15} /> Message</Button>}
        {activeTarget && member.role !== "owner" && workspace.local_role === "owner" && <Button variant="secondary" disabled={busy} onClick={() => onChangeRole(member.id, member.role === "admin" ? "member" : "admin")}>{member.role === "admin" ? "Demote" : "Promote"}</Button>}
        {activeTarget && member.role !== "owner" && workspace.local_role === "admin" && <Button variant="secondary" disabled={busy} onClick={() => onSubmitAdminRequest("role_change", member.id, member.role === "admin" ? "member" : "admin")}>Request {member.role === "admin" ? "demotion" : "promotion"}</Button>}
        {activeTarget && member.role !== "owner" && ["owner", "admin"].includes(workspace.local_role) && <Button variant="ghost" disabled={busy} onClick={() => setConfirmRemoval({ id: member.id, name: member.display_name, request: workspace.local_role === "admin" })}><UserMinus size={15} /> {workspace.local_role === "owner" ? "Remove" : "Request removal"}</Button>}
        {member.id === workspace.local_member_id && <ShieldCheck size={16} aria-label="Signed member" />}
      </span></div>;
    })}</div>
    {confirmRemoval && <div className="group-confirm" role="alertdialog" aria-label={confirmRemoval.request ? "Confirm removal request" : "Confirm member removal"}><p><strong>{confirmRemoval.request ? "Request removal" : "Remove"} {confirmRemoval.name}?</strong><span>{confirmRemoval.request ? "This stays pending until the owner reviews it." : "Their future workspace deliveries stop after the signed manifest arrives. Existing retained copies cannot be erased."}</span></p><div><Button variant="ghost" disabled={busy} onClick={() => setConfirmRemoval(null)}>Cancel</Button><Button variant="danger" disabled={busy} onClick={() => { if (confirmRemoval.request) onSubmitAdminRequest("member_removal", confirmRemoval.id); else onRemove(confirmRemoval.id); setConfirmRemoval(null); }}>{confirmRemoval.request ? "Submit request" : "Confirm removal"}</Button></div></div>}
    {workspace.state === "active" && invitationAllowed && workspace.members.filter((member) => member.status === "active").length < 8 && workspace.local_role !== "owner" && <div className="workspace-name-request"><h3>Invitation request</h3><p className="muted">The owner must approve before a signed one-use invitation exists.</p><Button disabled={busy} onClick={() => onSubmitAdminRequest("invitation")}>Request invitation</Button></div>}
    {workspace.state === "active" && workspace.local_role === "owner" && <form className="workspace-name-request" onSubmit={(event) => { event.preventDefault(); onInvitationPolicy(invitationPolicy); }}><h3>Invitation-request policy</h3><label>Who may request an invitation<select value={invitationPolicy} onChange={(event) => setInvitationPolicy(event.target.value as typeof invitationPolicy)}><option value="owner_only">Owner only</option><option value="owner_and_admins">Owner and administrators</option><option value="all_members_request">All active members may request</option></select></label><Button disabled={busy || invitationPolicy === workspace.policies.invitation_requests}>Publish signed policy update</Button></form>}
    {workspace.state === "active" && <form className="workspace-name-request" onSubmit={(event) => { event.preventDefault(); if (displayName.trim() && displayName.trim() !== local?.display_name) onRequestName(displayName); }}><label>Your workspace display name<input value={displayName} maxLength={64} onChange={(event) => setDisplayName(event.target.value)} /></label><p className="muted">{workspace.local_role === "owner" ? "The owner signs this into the next membership epoch." : "This request waits for the owner to publish the next signed membership epoch."}</p><Button disabled={busy || !displayName.trim() || displayName.trim() === local?.display_name}>Request name change</Button></form>}
    {workspace.local_role === "owner" && incoming.length > 0 && <section className="workspace-name-requests" aria-live="polite"><h3>Owner review · {incoming.length}</h3>{incoming.map((request) => <div className="workspace-invitation-row" key={request.id}><span><strong>{request.requester_display_name}</strong> requests: {workspaceAdminRequestLabel(request)}<small>Effective state is unchanged. Confirm against the current member role before approving.</small></span><span><Button disabled={busy} onClick={() => onDecideAdminRequest(request.id, true)}>Approve</Button><Button variant="ghost" disabled={busy} onClick={() => onDecideAdminRequest(request.id, false)}>Decline</Button></span></div>)}</section>}
    {visibleRequests.length > 0 && <section className="workspace-name-requests" aria-live="polite"><h3>Administrative request history</h3>{visibleRequests.map((request) => <div className="workspace-invitation-row" key={request.id}><span><strong>{workspaceAdminRequestLabel(request)}</strong><small>{workspaceAdminRequestStateLabel(request)}</small>{request.invitation && <textarea readOnly aria-label="Approved invitation" rows={3} value={request.invitation.text} />}</span><span>{request.state === "pending" && request.direction === "outgoing" && <Button variant="ghost" disabled={busy} onClick={() => onCancelAdminRequest(request.id)}>Cancel if not sent</Button>}{request.state !== "pending" && <Button variant="ghost" disabled={busy} onClick={() => onDismissAdminRequest(request.id)}>Dismiss</Button>}</span></div>)}</section>}
    {workspace.local_role === "owner" && requests.length > 0 && <div className="workspace-name-requests"><h3>Display-name requests</h3>{requests.map((request) => <div className="workspace-invitation-row" key={request.id}><span>{workspace.members.find((member) => member.id === request.member_id)?.display_name ?? "Member"} → <strong>{request.display_name}</strong></span><span><Button disabled={busy} onClick={() => onDecideName(request.id, true)}>Approve</Button><Button variant="ghost" disabled={busy} onClick={() => onDecideName(request.id, false)}>Decline</Button></span></div>)}</div>}
    {error && <p className="form-error" role="alert">{error}</p>}
  </div></Dialog>;
}

function WorkspaceAuthorityPanel({ workspace, transitions, busy, onOffer, onAccept, onFinalize, onReportLoss }: { workspace: Workspace; transitions: WorkspaceAuthorityTransition[]; busy: boolean; onOffer: (kind: "same_owner_rotation" | "ownership_transfer", memberId: string, deviceId: string, outgoingRole: "admin" | "member" | null) => void; onAccept: (transitionId: string) => void; onFinalize: (transitionId: string) => void; onReportLoss: () => void }) {
  const [kind, setKind] = useState<"same_owner_rotation" | "ownership_transfer">("ownership_transfer");
  const [successorKey, setSuccessorKey] = useState("");
  const [outgoingRole, setOutgoingRole] = useState<"admin" | "member">("admin");
  const [confirmed, setConfirmed] = useState(false);
  const [lossConfirm, setLossConfirm] = useState(false);
  const [reviewingTransition, setReviewingTransition] = useState<WorkspaceAuthorityTransition | null>(null);
  const owner = workspace.members.find((member) => member.id === workspace.owner_member_id);
  const candidates = workspace.members.flatMap((member) => (member.devices ?? [member.device]).filter((device) => device.id !== workspace.authority_device_id && member.status === "active" && (kind === "same_owner_rotation" ? member.id === workspace.owner_member_id : member.id !== workspace.owner_member_id)).map((device) => ({ member, device, key: `${member.id}:${device.id}` })));
  const selected = candidates.find((candidate) => candidate.key === successorKey);
  const stateLabel = (transition: WorkspaceAuthorityTransition) => ({
    waiting_for_delivery: "Offer saved · waiting for successor delivery",
    waiting_for_acceptance: transition.delivery_state === "received_by_endpoint" ? "Delivered · not yet accepted" : "Waiting for the named successor's acceptance",
    accepted_waiting_finalization: "Accepted · current authority must finalize",
    finalizing: "Final manifest and #general control are committing",
    applied: "Applied",
    expired: "Expired without changing authority",
    stale: "Stale because the base manifest changed",
    superseded: "Superseded",
    cancelled: "Cancelled before handoff",
    incomplete_control_state: "Incomplete control state · no authority change applied",
    forked: "Security conflict · workspace suspended",
  })[transition.state];
  return <section className="workspace-name-requests" aria-labelledby="workspace-authority-heading"><h3 id="workspace-authority-heading">Authority continuity</h3><p className="muted">Workspace owner: <strong>{owner?.display_name ?? "Owner"}</strong>. Current authority device: <strong>{owner?.devices?.find((device) => device.id === workspace.authority_device_id)?.fingerprint ?? owner?.device.fingerprint ?? "Unavailable"}</strong>. Offers and acceptances do not change effective authority; only the final manifest does.</p>
    {workspace.authority_loss && <p className="form-error" role="alert">Authority-dependent administration is permanently frozen on this workspace. Authorized chat remains usable. Create a replacement workspace and re-invite members; Mesh Chat cannot recover or clone the lost key.</p>}
    {workspace.state === "active" && workspace.local_role === "owner" && workspace.local_device_id === workspace.authority_device_id && !workspace.authority_loss && <form className="form-stack" onSubmit={(event) => { event.preventDefault(); if (selected && (kind === "same_owner_rotation" || confirmed)) onOffer(kind, selected.member.id, selected.device.id, kind === "ownership_transfer" ? outgoingRole : null); }}><label>Transition type<select value={kind} onChange={(event) => { setKind(event.target.value as typeof kind); setSuccessorKey(""); setConfirmed(false); }}><option value="ownership_transfer">Transfer workspace ownership</option><option value="same_owner_rotation">Rotate to another admitted owner device</option></select></label><label>Exact successor member and device<select aria-label="Authority successor device" value={successorKey} onChange={(event) => setSuccessorKey(event.target.value)}><option value="">Choose an active admitted device</option>{candidates.map((candidate) => <option key={candidate.key} value={candidate.key}>{candidate.member.display_name} · {candidate.device.fingerprint}</option>)}</select></label>{kind === "ownership_transfer" && <><label>Outgoing owner's resulting role<select value={outgoingRole} onChange={(event) => setOutgoingRole(event.target.value as typeof outgoingRole)}><option value="admin">Administrator</option><option value="member">Member</option></select></label><label className="checkbox-line"><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} /> I understand this changes the sole workspace owner and manifest authority, explicitly recovers #general management to the successor, and requires this authority device to remain available through finalization.</label></>}<Button variant={kind === "ownership_transfer" ? "danger" : "secondary"} disabled={busy || !selected || (kind === "ownership_transfer" && !confirmed)}>{kind === "ownership_transfer" ? "Offer ownership transfer" : "Offer authority rotation"}</Button>{candidates.length === 0 && <p className="muted">No eligible admitted successor exists yet. Link another device first, then return here to rotate authority.</p>}</form>}
    {transitions.length > 0 && <div aria-live="polite">{transitions.map((transition) => <div className="workspace-invitation-row" key={transition.id}><span><strong>{transition.transition_kind === "ownership_transfer" ? "Ownership transfer" : "Authority rotation"} · {transition.successor_display_name}</strong><small>{stateLabel(transition)}</small>{transition.transition_kind === "ownership_transfer" && <small>Outgoing owner becomes {transition.outgoing_owner_role}. #general: explicit authority recovery.</small>}</span><span>{transition.direction === "incoming" && transition.state === "waiting_for_acceptance" && workspace.local_device_id === workspace.members.find((member) => member.id === transition.successor_member_id)?.devices?.find((device) => device.fingerprint === transition.successor_fingerprint)?.id && <Button disabled={busy} onClick={() => setReviewingTransition(transition)}>Review and accept</Button>}{transition.direction === "outgoing" && transition.state === "accepted_waiting_finalization" && workspace.local_device_id === workspace.authority_device_id && <Button variant="danger" disabled={busy} onClick={() => onFinalize(transition.id)}>Finalize authority change</Button>}</span></div>)}</div>}
    {reviewingTransition && <div className="group-confirm" role="alertdialog" aria-label="Accept authority transition"><p><strong>Accept {reviewingTransition.transition_kind === "ownership_transfer" ? "workspace ownership" : "authority rotation"}?</strong><span>Workspace: {workspace.name}. Current owner: {owner?.display_name ?? "Owner"}. Named successor: {reviewingTransition.successor_display_name} · {reviewingTransition.successor_fingerprint}. Acceptance records consent but changes no effective owner or authority until the current authority publishes the final manifest.</span>{reviewingTransition.transition_kind === "ownership_transfer" && <span>You will become the sole owner and authority only after finalization; the outgoing owner becomes {reviewingTransition.outgoing_owner_role}, and #general management is recovered to this device.</span>}<span>Confirm the current workspace state and fingerprint before accepting.</span></p><div><Button variant="ghost" disabled={busy} onClick={() => setReviewingTransition(null)}>Cancel</Button><Button variant="danger" disabled={busy} onClick={() => { onAccept(reviewingTransition.id); setReviewingTransition(null); }}>Accept exact offer</Button></div></div>}
    {!workspace.authority_loss && workspace.local_role === "owner" && workspace.local_device_id === workspace.authority_device_id && <div className="danger-zone"><h3>Current authority key unavailable</h3><p>Reporting permanent loss does not recover authority. It freezes authority-dependent administration while ordinary authorized chat can continue.</p>{lossConfirm ? <div className="dialog-actions"><Button variant="ghost" onClick={() => setLossConfirm(false)}>Cancel</Button><Button variant="danger" disabled={busy} onClick={onReportLoss}>Confirm permanent authority loss</Button></div> : <Button variant="ghost" onClick={() => setLossConfirm(true)}>Report authority loss…</Button>}</div>}
  </section>;
}

function WorkspaceAuthorityDialog({ workspace, transitions, busy, error, onClose, onOffer, onAccept, onFinalize, onReportLoss }: { workspace: Workspace; transitions: WorkspaceAuthorityTransition[]; busy: boolean; error: string; onClose: () => void; onOffer: (kind: "same_owner_rotation" | "ownership_transfer", memberId: string, deviceId: string, outgoingRole: "admin" | "member" | null) => void; onAccept: (transitionId: string) => void; onFinalize: (transitionId: string) => void; onReportLoss: () => void }) {
  return <Dialog title={`Authority continuity · ${workspace.name}`} onClose={onClose}><div className="form-stack"><WorkspaceAuthorityPanel workspace={workspace} transitions={transitions} busy={busy} onOffer={onOffer} onAccept={onAccept} onFinalize={onFinalize} onReportLoss={onReportLoss} />{error && <p className="form-error" role="alert">{error}</p>}</div></Dialog>;
}

function WorkspaceSettingsDialog({ workspace, conversation, networkSettings, busy, error, onClose, onUpdateMetadata, onUpdatePolicies, onSetNotificationPreference, onApprovePropagationNode, onCloseWorkspace, onLeave, onRemove }: { workspace: Workspace; conversation: WorkspaceChannel | WorkspaceDirect | null; networkSettings: NetworkSettings; busy: boolean; error: string; onClose: () => void; onUpdateMetadata: (name: string, description: string) => void; onUpdatePolicies: (channelCreation: "all_members" | "owner_and_admins", posting: "all_members" | "owner_and_admins") => void; onSetNotificationPreference: (conversationId: string | null, mode: WorkspaceNotificationPreference) => void; onApprovePropagationNode: (node: string) => void; onCloseWorkspace: () => void; onLeave: () => void; onRemove: (confirmation: string) => void }) {
  const [confirmingClose, setConfirmingClose] = useState(false);
  const [confirmingRemove, setConfirmingRemove] = useState(false);
  const [confirmation, setConfirmation] = useState("");
  const [name, setName] = useState(workspace.name);
  const [description, setDescription] = useState(workspace.description);
  const [channelCreation, setChannelCreation] = useState(workspace.policies.channel_creation);
  const [posting, setPosting] = useState(workspace.policies.posting);
  const [propagationNode, setPropagationNode] = useState("");
  const [propagationConsent, setPropagationConsent] = useState(false);
  const failedJoin = workspaceJoinStatus(workspace)?.terminal === true;
  const terminal = failedJoin || ["left", "removed", "device_removed", "closed"].includes(workspace.state);
  const active = workspace.state === "active";
  return <Dialog title="Workspace settings" onClose={onClose}><div className="form-stack workspace-settings">{active && <DirectRecovery key={workspace.id} workspaceId={workspace.id} />}<div><h3>{workspace.name}</h3><p>{workspace.description || "No description"}</p><span className={`workspace-state workspace-state--${workspace.state}`}>{workspaceStateLabel(workspace)}</span></div>{active && workspace.local_role === "owner" && <form className="form-stack" onSubmit={(event) => { event.preventDefault(); onUpdateMetadata(name, description); }}><label>Workspace name<input value={name} maxLength={64} onChange={(event) => setName(event.target.value)} /></label><label>Description<textarea value={description} maxLength={280} rows={3} onChange={(event) => setDescription(event.target.value)} /></label><Button disabled={busy || (name.trim() === workspace.name && description.trim() === workspace.description)}>Publish metadata update</Button></form>}{active && workspace.local_role === "owner" && <form className="form-stack" onSubmit={(event) => { event.preventDefault(); onUpdatePolicies(channelCreation, posting); }}><h3>Public-channel policies</h3><label>Who can create channels<select value={channelCreation} onChange={(event) => setChannelCreation(event.target.value as typeof channelCreation)}><option value="all_members">All members</option><option value="owner_and_admins">Owner and administrators</option></select></label><label>Who can post<select value={posting} onChange={(event) => setPosting(event.target.value as typeof posting)}><option value="all_members">All members</option><option value="owner_and_admins">Owner and administrators</option></select></label><Button disabled={busy || (channelCreation === workspace.policies.channel_creation && posting === workspace.policies.posting)}>Publish policy update</Button></form>}<section className="notification-settings" aria-labelledby="workspace-notification-heading"><h3 id="workspace-notification-heading"><Bell size={18} /> Notification preference</h3><label>For this workspace<select value={workspace.notification_preference ?? "all"} disabled={!active || busy} onChange={(event) => onSetNotificationPreference(null, event.target.value as WorkspaceNotificationPreference)}><option value="all">All messages</option><option value="mentions_only">Mentions only</option><option value="muted">Muted</option></select></label>{conversation && <label>For {"name" in conversation ? `#${conversation.display_name || conversation.name}` : conversation.peer_display_name}<select value={conversation.notification_preference ?? workspace.notification_preference ?? "all"} disabled={!active || busy} onChange={(event) => onSetNotificationPreference(conversation.id, event.target.value as WorkspaceNotificationPreference)}><option value="all">All messages</option><option value="mentions_only">Mentions only</option><option value="muted">Muted</option></select></label>}<p className="muted">Structured mentions can notify in an unsubscribed public channel unless mentions are muted. Replies follow the selected conversation preference. Notifications never mark a message read.</p></section><dl className="security-list"><div><dt>Retention preference</dt><dd>{workspace.retention_days === null ? "Indefinite" : `${workspace.retention_days} days`}</dd></div></dl><p className="muted">This cooperative preference does not guarantee remote deletion. A member device may retain plaintext it already received.</p>{active && <div className="propagation-consent"><h3>Offline delivery node</h3><p className="muted">A workspace may recommend a Reticulum propagation node, but joining never enables it. Approve its 32-character address explicitly on this device.</p><label>Propagation-node address<input value={propagationNode} spellCheck={false} maxLength={32} onChange={(event) => setPropagationNode(event.target.value.toLowerCase())} /></label><label className="checkbox-line"><input type="checkbox" checked={propagationConsent} onChange={(event) => setPropagationConsent(event.target.checked)} /> I approve this node for encrypted store-and-forward delivery.</label><Button variant="secondary" disabled={busy || !propagationConsent || !/^[0-9a-f]{32}$/.test(propagationNode) || networkSettings.approved_propagation_nodes.includes(propagationNode)} onClick={() => onApprovePropagationNode(propagationNode)}>Approve node</Button></div>}{workspace.state === "forked" && <p className="form-error" role="alert">Workspace activity is paused. Mesh Chat will not choose between conflicting signed histories.</p>}{workspace.state === "incomplete_sync" && <p className="form-error" role="alert">Some signed controls or events are missing. Messaging stays paused while Mesh Chat retains the history it can validate.</p>}{error && <p className="form-error" role="alert">{error}</p>}{active && workspace.local_role === "owner" && <div className="danger-zone"><h3>Close workspace</h3><p>This signs a terminal manifest. No later joins or messages are accepted.</p>{confirmingClose ? <><p role="alert"><strong>Close {workspace.name} permanently?</strong> Cached history remains until each member removes it locally.</p><div className="dialog-actions"><Button variant="ghost" disabled={busy} onClick={() => setConfirmingClose(false)}>Cancel</Button><Button variant="danger" disabled={busy} onClick={onCloseWorkspace}>Confirm close workspace</Button></div></> : <Button variant="danger" disabled={busy} onClick={() => setConfirmingClose(true)}>Close workspace…</Button>}</div>}{active && workspace.local_role !== "owner" && <div className="danger-zone"><h3>Leave workspace</h3><p>Your signed request waits for the owner to publish the membership change.</p><Button variant="danger" disabled={busy} onClick={onLeave}>Leave workspace</Button></div>}{terminal && <div className="danger-zone"><h3>Remove local workspace data</h3><p>This permanently erases this device’s encrypted workspace records. Re-entry needs a new invitation.</p>{confirmingRemove ? <><label>Type the workspace name to confirm<input value={confirmation} onChange={(event) => setConfirmation(event.target.value)} aria-label="Workspace removal confirmation" /></label><Button variant="danger" disabled={busy || confirmation !== workspace.name} onClick={() => onRemove(workspace.id)}>Remove local data</Button></> : <Button variant="danger" onClick={() => setConfirmingRemove(true)}>Remove local data…</Button>}</div>}</div></Dialog>;
}

function workspaceHistoryStateLabel(status: WorkspaceHistoryStatus["status"]): string {
  return ({
    available: "Catch-up available",
    requesting: "Requesting history",
    waiting_peer: "Waiting for an eligible peer or route",
    verifying: "Receiving and verifying bounded pages",
    paused_offline: "Paused while offline",
    missing_prerequisites: "Missing prerequisite controls",
    peer_limited: "Peer-limited or peer-pruned coverage",
    complete_known: "Complete within known signed heads",
    cancelled: "Catch-up cancelled locally",
    dismissed: "Catch-up dismissed locally",
    authorization_changed: "Authorization changed",
    fork_suspended: "Fork-suspended",
    expired: "The signed request expired",
    failed: "Catch-up failed",
  })[status];
}

function WorkspaceRetentionDialog({ workspace, conversationId, conversationName, busy, error, onClose, onUpdate, onPrune }: { workspace: Workspace; conversationId?: string; conversationName?: string; busy: boolean; error: string; onClose: () => void; onUpdate: (retentionDays: 30 | 90 | 365 | null) => void; onPrune: () => Promise<WorkspaceRetentionPruneResult | null> }) {
  const [retention, setRetention] = useState<"30" | "90" | "365" | "indefinite">(workspace.retention_days === null ? "indefinite" : String(workspace.retention_days) as "30" | "90" | "365");
  const [result, setResult] = useState<WorkspaceRetentionPruneResult | null>(null);
  const [history, setHistory] = useState<WorkspaceHistoryStatus | null>(null);
  const [historyBusy, setHistoryBusy] = useState(false);
  const [historyError, setHistoryError] = useState("");
  const selected = retention === "indefinite" ? null : Number(retention) as 30 | 90 | 365;
  const owner = workspace.local_role === "owner" && workspace.state === "active";
  const loadHistory = useCallback(async () => {
    if (!conversationId) return;
    try {
      setHistoryError("");
      setHistory(await serviceCommand<WorkspaceHistoryStatus>("get_workspace_history_status", { workspace_id: workspace.id, conversation_id: conversationId }));
    } catch (reason) { setHistoryError(errorMessage(reason)); }
  }, [conversationId, workspace.id]);
  useEffect(() => { void loadHistory(); }, [loadHistory]);
  const changeHistory = async (command: "start_workspace_history" | "cancel_workspace_history") => {
    if (!conversationId) return;
    setHistoryBusy(true); setHistoryError("");
    try {
      await serviceCommand(command, { operation_id: newOperationId(), workspace_id: workspace.id, conversation_id: conversationId });
      await loadHistory();
    } catch (reason) { setHistoryError(errorMessage(reason)); }
    finally { setHistoryBusy(false); }
  };
  return <Dialog title="History & retention" onClose={onClose}><div className="form-stack workspace-history-view"><div><h3>Retained local history</h3><p>{workspace.retention_days === null ? "Indefinite retention" : `${workspace.retention_days}-day retention`}</p></div>{conversationId && <section className="workspace-history-sync" aria-labelledby="workspace-history-sync-title"><h3 id="workspace-history-sync-title">Synchronize {conversationName ?? "this conversation"}</h3>{history ? <><div className="workspace-directory-status" role="status" aria-live="polite"><RefreshCw size={16} /><span><strong>{workspaceHistoryStateLabel(history.status)}</strong>{history.job ? ` · ${history.job.recovered_events} events in ${history.job.verified_pages} verified pages` : ""}</span></div><p className="muted">{history.notice}</p><div className="dialog-actions">{!["requesting", "verifying", "waiting_peer", "paused_offline"].includes(history.status) && <Button disabled={historyBusy || !history.eligible} onClick={() => void changeHistory("start_workspace_history")}>Request available history</Button>}{["requesting", "verifying", "waiting_peer", "paused_offline"].includes(history.status) && <Button variant="ghost" disabled={historyBusy} onClick={() => void changeHistory("cancel_workspace_history")}>Cancel local job</Button>}<Button variant="secondary" disabled={historyBusy} onClick={() => void loadHistory()}>Refresh status</Button></div></> : <div className="workspace-directory-status" role="status"><span className="spinner" /> Checking known coverage…</div>}{historyError && <p className="form-error" role="alert">{historyError}</p>}</section>}{owner && <form className="form-stack" onSubmit={(event) => { event.preventDefault(); onUpdate(selected); }}><label>Cooperative retention<select value={retention} onChange={(event) => setRetention(event.target.value as typeof retention)}><option value="30">30 days</option><option value="90">90 days (default)</option><option value="365">365 days</option><option value="indefinite">Indefinite</option></select></label><Button disabled={busy || selected === workspace.retention_days}>Publish signed retention update</Button></form>}<p className="muted">This is a cooperative preference for encrypted history on each member device. It cannot remotely delete plaintext, exports, or backups another device already holds.</p><div className="workspace-directory-status" role="status">Pruning is bounded and restart-safe. It preserves signed high-water marks, retained floors, permanent gaps, controls still referenced by retained events, and the independent seven-day live-delivery window.</div><Button variant="secondary" disabled={busy || workspace.retention_days === null} onClick={() => void onPrune().then(setResult)}>{workspace.retention_days === null ? "Pruning disabled for indefinite retention" : workspace.retention_pruning_state === "running" ? "Continue local pruning" : "Prune local history now"}</Button>{result && <p role="status">{result.status === "complete" ? `Pruning complete · ${result.pruned} canonical events removed.` : `${result.pruned} events removed · ${result.scanned} checked. Continue to process the next bounded batch.`}</p>}{workspace.retention_pruning_state === "restart_required" && <p className="form-error" role="alert">The interrupted pruning cursor was invalidated. Start a fresh bounded pruning pass.</p>}{workspace.state !== "active" && <p className="muted">This retained archive is read-only. It remains only until local retention pruning or confirmed local erasure.</p>}{error && <p className="form-error" role="alert">{error}</p>}</div></Dialog>;
}

function CreateWorkspaceChannelDialog({ workspace, busy, error, onClose, onCreate }: { workspace: Workspace; busy: boolean; error: string; onClose: () => void; onCreate: (name: string, topic: string, visibility: "public" | "private", memberIds: string[]) => void }) {
  const [name, setName] = useState("");
  const [topic, setTopic] = useState("");
  const [visibility, setVisibility] = useState<"public" | "private">("public");
  const [memberIds, setMemberIds] = useState<string[]>([workspace.local_member_id]);
  const allowed = workspace.state === "active" && (workspace.policies.channel_creation === "all_members" || ["owner", "admin"].includes(workspace.local_role));
  const activeMembers = workspace.members.filter((member) => member.status === "active");
  return <Dialog title="Create a channel" onClose={onClose}><form className="form-stack" onSubmit={(event) => { event.preventDefault(); if (allowed && name.trim()) onCreate(name.trim(), topic.trim(), visibility, memberIds); }}><label>Visibility<select value={visibility} onChange={(event) => setVisibility(event.target.value as "public" | "private")}><option value="public">Public to workspace</option><option value="private">Private to selected members</option></select></label><p>{visibility === "public" ? "Every active workspace member receives messages. Subscriptions only control presentation." : "Only the signed roster receives the channel identifier, controls, roster, or messages. New members do not receive earlier messages."}</p><label>Channel name<input autoFocus value={name} maxLength={80} onChange={(event) => setName(event.target.value)} /></label><label>Topic <small>Optional</small><textarea value={topic} maxLength={250} onChange={(event) => setTopic(event.target.value)} /></label>{visibility === "private" && <fieldset className="form-stack"><legend>Private roster · up to eight people</legend>{activeMembers.map((member) => <label className="checkbox-line" key={member.id}><input type="checkbox" checked={memberIds.includes(member.id)} disabled={member.id === workspace.local_member_id || (!memberIds.includes(member.id) && memberIds.length >= 8)} onChange={(event) => setMemberIds((current) => event.target.checked ? [...new Set([...current, member.id])] : current.filter((id) => id !== member.id))} /> {member.display_name}{member.id === workspace.local_member_id ? " (you · manager)" : ` · ${member.short_id}`}</label>)}</fieldset>}{!allowed && <p className="form-error" role="alert">Channel creation is not permitted under the current signed policy.</p>}{error && <p className="form-error" role="alert">{error}</p>}<div className="dialog-actions"><Button variant="ghost" onClick={onClose}>Cancel</Button><Button disabled={busy || !allowed || !name.trim()}>{busy ? "Creating…" : `Create ${visibility} channel`}</Button></div></form></Dialog>;
}

function BrowseWorkspaceChannelsDialog({ workspace, channels, busy, error, onClose, onOpen, onSubscribe, onSync, onCreate }: { workspace: Workspace; channels: WorkspaceChannel[]; busy: boolean; error: string; onClose: () => void; onOpen: (channelId: string) => void; onSubscribe: (channelId: string, subscribed: boolean) => void; onSync: () => void; onCreate: () => void }) {
  const canCreate = workspace.state === "active" && (workspace.policies.channel_creation === "all_members" || ["owner", "admin"].includes(workspace.local_role));
  return <Dialog title={`Browse channels in ${workspace.name}`} onClose={onClose}><div className="form-stack workspace-channel-directory"><div className="workspace-directory-status" role="status"><RefreshCw size={16} /><span>{workspace.channel_discovery === "converged" ? "Directory synchronized with every active member device." : "Directory may be incomplete. Reachable authorized peers are still converging."}</span></div><div className="workspace-channel-directory__actions"><Button variant="secondary" disabled={busy || workspace.state !== "active"} onClick={onSync}><RefreshCw size={16} /> Sync directory</Button>{canCreate && <Button disabled={busy} onClick={onCreate}><Plus size={16} /> Create channel</Button>}</div>{channels.map((channel) => <div className="workspace-channel-directory__row" key={channel.id}><span className="workspace-channel-icon"><Hash size={17} /></span><span><strong>{channel.display_name || channel.name}</strong><small>{channel.topic || (channel.state === "archived" ? "Archived · read-only" : "No topic")}</small></span><span><Button variant="ghost" onClick={() => onOpen(channel.id)}>Open</Button>{!channel.is_general && channel.state === "active" && <Button variant="secondary" disabled={busy} onClick={() => onSubscribe(channel.id, !channel.subscribed)}>{channel.subscribed ? "Unsubscribe" : "Subscribe"}</Button>}</span></div>)}{channels.length === 0 && <p className="muted">No public channels have been discovered yet.</p>}{error && <p className="form-error" role="alert">{error}</p>}</div></Dialog>;
}

function ManageWorkspaceChannelDialog({ workspace, channel, transfers, busy, error, onClose, onUpdate, onMembers, onLeave, onOfferTransfer, onAcceptTransfer, onRecover }: { workspace: Workspace; channel: WorkspaceChannel; transfers: WorkspaceChannelTransfer[]; busy: boolean; error: string; onClose: () => void; onUpdate: (name: string, topic: string, archived: boolean) => void; onMembers: (memberIds: string[]) => void; onLeave: () => void; onOfferTransfer: (memberId: string) => void; onAcceptTransfer: (transferId: string) => void; onRecover: () => void }) {
  const [name, setName] = useState(channel.name);
  const [topic, setTopic] = useState(channel.topic);
  const [successor, setSuccessor] = useState("");
  const [memberIds, setMemberIds] = useState(channel.member_ids);
  const [confirmArchive, setConfirmArchive] = useState(false);
  const manager = channel.manager_member_id === workspace.local_member_id && channel.manager_device_id === workspace.local_device_id;
  const pending = transfers.find((item) => item.channel_id === channel.id && item.successor_member_id === workspace.local_member_id);
  const successors = workspace.members.filter((member) => member.status === "active" && member.id !== workspace.local_member_id && (channel.visibility === "public" || channel.member_ids.includes(member.id)));
  const roster = workspace.members.filter((member) => channel.member_ids.includes(member.id));
  const canRecover = workspace.local_role === "owner" && (channel.visibility === "public" || channel.member_ids.includes(workspace.local_member_id));
  return <Dialog title={`Manage #${channel.display_name || channel.name}`} onClose={onClose}><div className="form-stack"><p className="muted">{channel.visibility === "private" ? "Private signed roster" : "Public channel"} · head v{channel.version} · manager {workspace.members.find((member) => member.id === channel.manager_member_id)?.display_name ?? channel.manager_member_id.slice(0, 6)}</p>{channel.visibility === "private" && <section className="form-stack"><h3>Private roster</h3>{roster.map((member) => <div className="workspace-person" key={member.id}><Avatar name={member.display_name} small /><span><strong>{member.display_name}{member.id === workspace.local_member_id ? " (you)" : ""}</strong><small>{member.id === channel.manager_member_id ? "manager" : "member"} · {member.short_id}</small></span><ShieldCheck size={16} aria-label="Signed member" /></div>)}{manager && channel.state === "active" && <><h3>Change roster</h3>{workspace.members.filter((member) => member.status === "active").map((member) => <label className="checkbox-line" key={member.id}><input type="checkbox" checked={memberIds.includes(member.id)} disabled={member.id === channel.manager_member_id || (!memberIds.includes(member.id) && memberIds.length >= 8)} onChange={(event) => setMemberIds((current) => event.target.checked ? [...new Set([...current, member.id])] : current.filter((id) => id !== member.id))} /> {member.display_name}{member.id === channel.manager_member_id ? " (manager)" : ""}</label>)}<Button variant="secondary" disabled={busy || JSON.stringify([...memberIds].sort()) === JSON.stringify([...channel.member_ids].sort())} onClick={() => onMembers(memberIds)}>Publish roster change</Button></>}</section>}{pending && <div className="workspace-directory-status"><span>You are the named successor for this exact channel head.</span><Button disabled={busy} onClick={() => onAcceptTransfer(pending.id)}>Accept management</Button></div>}{manager && channel.state === "active" && <form className="form-stack" onSubmit={(event) => { event.preventDefault(); onUpdate(name.trim(), topic.trim(), false); }}><label>Channel name<input value={name} disabled={channel.is_general} maxLength={80} onChange={(event) => setName(event.target.value)} /></label><label>Topic<textarea value={topic} maxLength={250} onChange={(event) => setTopic(event.target.value)} /></label><Button disabled={busy || !name.trim() || (name.trim() === channel.name && topic.trim() === channel.topic)}>Publish channel update</Button></form>}{manager && !channel.is_general && channel.state === "active" && successors.length > 0 && <div className="form-stack"><h3>Transfer management</h3><p className="muted">The named successor must accept the offer bound to this exact head.</p><select value={successor} onChange={(event) => setSuccessor(event.target.value)} aria-label="Successor manager"><option value="">Choose a member</option>{successors.map((member) => <option value={member.id} key={member.id}>{member.display_name} · {member.short_id}</option>)}</select><Button variant="secondary" disabled={busy || !successor} onClick={() => onOfferTransfer(successor)}>Offer transfer</Button></div>}{canRecover && !manager && channel.state === "active" && <div className="form-stack"><h3>Recover management</h3><p className="muted">Private recovery is available only because this owner is already on the signed roster.</p><Button variant="secondary" disabled={busy} onClick={onRecover}>Recover to owner</Button></div>}{channel.visibility === "private" && !manager && channel.state === "active" && <div className="danger-zone"><h3>Leave private channel</h3><p>Sending stops immediately. The manager removes you from the next signed roster.</p><Button variant="danger" disabled={busy} onClick={onLeave}>Leave channel</Button></div>}{manager && !channel.is_general && channel.state === "active" && <div className="danger-zone"><h3>Archive channel</h3><p>Archival is terminal. Messages remain read-only on devices that retained them.</p>{confirmArchive ? <div className="dialog-actions"><Button variant="ghost" onClick={() => setConfirmArchive(false)}>Cancel</Button><Button variant="danger" disabled={busy} onClick={() => onUpdate(channel.name, channel.topic, true)}>Confirm archive</Button></div> : <Button variant="danger" disabled={busy} onClick={() => setConfirmArchive(true)}>Archive channel…</Button>}</div>}{channel.state === "forked" && <p className="form-error" role="alert">This channel alone is paused because two valid controls conflict at one version.</p>}{channel.state === "leaving" && <p className="form-error" role="status">Leaving is pending with the channel manager. This channel is read-only.</p>}{error && <p className="form-error" role="alert">{error}</p>}</div></Dialog>;
}

function workspaceDeliveryLabel(message: WorkspaceMessage): string {
  const summary = message.delivery_summary;
  if (!summary) return "Received";
  if (summary.devices_total === 0) return "Saved locally · invite a teammate to share it";
  if (summary.devices_reached > 0) return `Reached ${summary.people_reached} of ${pluralize(summary.people_total, "person", "people")} · ${summary.people_partial ?? 0} partial · ${summary.devices_reached} of ${pluralize(summary.devices_total, "device")}`;
  if ((summary.devices_cancelled ?? 0) > 0 && summary.devices_pending === 0) return "Delivery cancelled after membership changed";
  if ((summary.devices_expired ?? 0) > 0 && summary.devices_pending === 0) return "Delivery expired before reaching a device";
  if (summary.devices_failed > 0 && summary.devices_pending === 0) return "Could not reach the other device";
  return `Sending to ${pluralize(summary.devices_total, "device")}…`;
}

function workspaceDeliveryStateLabel(state: NonNullable<WorkspaceMessage["deliveries"]>[number]["state"]): string {
  if (state === "received_by_endpoint" || state === "delivered") return "Reached";
  if (state === "stored_for_delivery") return "Stored securely for delivery";
  if (state === "waiting_for_keys") return "Trying to find device";
  if (state === "queued" || state === "sending") return "Pending";
  if (state === "expired") return "Expired";
  if (state === "cancelled") return "Cancelled";
  return "Failed";
}

function WorkspaceMessageCard({
  workspace,
  message,
  reactionOpen,
  reactionCatalogOpen,
  reactionBusyEmoji,
  reactionError,
  onToggleReaction,
  onReactionCatalogOpenChange,
  onCloseReaction,
  onSetReaction,
  onEdit,
  onDelete,
  onHide,
  onOpenThread,
  allowedMentionMemberIds,
}: {
  workspace: Workspace;
  message: WorkspaceMessage;
  reactionOpen: boolean;
  reactionCatalogOpen: boolean;
  reactionBusyEmoji: string | null;
  reactionError: string;
  onToggleReaction: () => void;
  onReactionCatalogOpenChange: (open: boolean) => void;
  onCloseReaction: () => void;
  onSetReaction: (emoji: string, active: boolean) => void;
  onEdit: (text: string, mentionMemberIds: string[]) => void;
  onDelete: () => void;
  onHide: () => void;
  onOpenThread?: () => void;
  allowedMentionMemberIds: string[];
}) {
  const [editing, setEditing] = useState(false);
  const [editText, setEditText] = useState(message.text);
  const [editMentionMemberIds, setEditMentionMemberIds] = useState(
    eligibleWorkspaceMentionMemberIds(workspace, allowedMentionMemberIds, message.mention_member_ids ?? []),
  );
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [revisionPage, setRevisionPage] = useState<WorkspaceRevisionPage | null>(null);
  const [revisionLoading, setRevisionLoading] = useState(false);
  const [revisionError, setRevisionError] = useState("");
  const mutable = workspace.state === "active" && !message.deleted && !message.mutation_frozen;
  const authorMutable = mutable && message.author_member_id === workspace.local_member_id;
  useEffect(() => {
    if (!editing) {
      setEditText(message.text);
      setEditMentionMemberIds(eligibleWorkspaceMentionMemberIds(workspace, allowedMentionMemberIds, message.mention_member_ids ?? []));
    }
  }, [allowedMentionMemberIds, editing, message.mention_member_ids, message.text, workspace]);
  const loadRevisions = async (append = false) => {
    if (revisionLoading) return;
    setRevisionLoading(true);
    setRevisionError("");
    try {
      const next = await serviceCommand<WorkspaceRevisionPage>("list_workspace_message_revisions", {
        workspace_id: workspace.id,
        event_id: message.id,
        cursor: append ? revisionPage?.next_cursor ?? null : null,
        limit: 50,
      });
      setRevisionPage((current) => append && current
        ? { ...next, revisions: [...current.revisions, ...next.revisions] }
        : next);
    } catch (reason) {
      setRevisionError(errorMessage(reason));
      if (!append) setRevisionPage({ message, revisions: [], next_cursor: null, high_water: 0, history_status: "complete" });
    } finally {
      setRevisionLoading(false);
    }
  };
  return (
    <><article className={`workspace-message ${message.direction === "outbound" ? "workspace-message--self" : ""} ${message.deleted ? "workspace-message--deleted" : ""} ${message.mention_member_ids?.includes(workspace.local_member_id) ? "workspace-message--mentioned" : ""}`}>
      <Avatar name={message.author_display_name} small />
      <div>
        <header>
          <strong>{message.author_display_name}</strong>
          <time dateTime={machineTime(message.created_at)}>{formatTime(message.created_at)}</time>
          {(message.revision ?? 0) > 0 && !message.deleted && <small>Edited</small>}
          {message.mention_member_ids?.includes(workspace.local_member_id) && <small className="workspace-message__mention"><AtSign size={12} /> Mentioned you</small>}
          <button type="button" className="message-history" onClick={() => void loadRevisions(false)} aria-label={`Inspect revisions for message from ${message.author_display_name}`} title="Revision history">History</button>
          <button className="message-hide" onClick={onHide} aria-label={`Hide message from ${message.author_display_name}`} title="Hide locally"><X size={13} /></button>
        </header>
        {message.deleted ? <p className="workspace-message__tombstone">Message deleted by its author.</p> : editing ? (
          <div className="workspace-message__edit">
            <WorkspaceMentionChips workspace={workspace} memberIds={editMentionMemberIds} onRemove={(memberId) => setEditMentionMemberIds((current) => current.filter((id) => id !== memberId))} />
            <WorkspaceMentionPicker workspace={workspace} allowedMemberIds={allowedMentionMemberIds} selectedMemberIds={editMentionMemberIds} onSelect={(member) => { setEditText((current) => `${current}${current && !current.endsWith(" ") ? " " : ""}@${member.display_name} `); setEditMentionMemberIds((current) => [...current, member.id].sort()); }} />
            <textarea value={editText} maxLength={16 * 1024} aria-label="Edit workspace message" onChange={(event) => setEditText(event.target.value)} />
            <span><Button variant="ghost" onClick={() => { setEditing(false); setEditText(message.text); setEditMentionMemberIds(eligibleWorkspaceMentionMemberIds(workspace, allowedMentionMemberIds, message.mention_member_ids ?? [])); }}>Cancel</Button><Button disabled={!editText.trim()} onClick={() => { onEdit(editText, eligibleWorkspaceMentionMemberIds(workspace, allowedMentionMemberIds, editMentionMemberIds)); setEditing(false); }}>Save</Button></span>
          </div>
        ) : <p>{message.text}</p>}
        {(message.mutation_conflict || message.mutation_frozen) && <p className="workspace-message__security" role="status">{message.mutation_frozen ? "Security warning: this message is frozen after conflicting mutations from one device." : "Concurrent author changes were resolved deterministically. A later edit can resolve the conflict."}</p>}
        {!message.deleted && <footer className="workspace-message__actions">
          {message.thread_root == null && onOpenThread && <button type="button" onClick={onOpenThread}><MessageCircleMore size={13} /> Thread{(message.reply_count ?? 0) > 0 ? ` · ${message.reply_count}` : ""}{(message.thread_unread_count ?? 0) > 0 ? ` · ${message.thread_unread_count} new` : ""}</button>}
          {authorMutable && !confirmDelete && <><button type="button" onClick={() => setEditing(true)}>Edit</button><button type="button" onClick={() => setConfirmDelete(true)}>Delete</button></>}
          {authorMutable && confirmDelete && <><span>Delete for workspace participants?</span><button type="button" onClick={() => setConfirmDelete(false)}>Cancel</button><button type="button" onClick={() => { setConfirmDelete(false); onDelete(); }}>Delete</button></>}
          {mutable && <MessageReactions
            messageText={message.text}
            reactions={message.reactions}
            pickerOpen={reactionOpen}
            catalogOpen={reactionCatalogOpen}
            busyEmoji={reactionBusyEmoji}
            error={reactionError}
            multiple
            onTogglePicker={onToggleReaction}
            onClosePicker={onCloseReaction}
            onCatalogOpenChange={onReactionCatalogOpenChange}
            onSetReaction={onSetReaction}
          />}
        </footer>}
        {message.direction === "outbound" && <details className="workspace-delivery"><summary>{workspaceDeliveryLabel(message)}</summary>{message.deliveries && <ul>{message.deliveries.map((delivery) => <li key={delivery.device_id}><span>{delivery.member_display_name} · device {delivery.device_short_id}</span><strong>{workspaceDeliveryStateLabel(delivery.state)}</strong></li>)}</ul>}</details>}
      </div>
    </article>{revisionPage && <Dialog title="Message history" onClose={() => { setRevisionPage(null); setRevisionError(""); }}><div className="form-stack workspace-history-view"><p className="muted">Signed edits, reactions, and deletion tombstones retained on this device. Access is rechecked each time this view opens.</p>{revisionPage.history_status === "pruned" && <div className="workspace-directory-status" role="status">Earlier revisions were pruned under the active retention preference.</div>}{revisionLoading && revisionPage.revisions.length === 0 && <div className="workspace-loading"><span className="spinner" /> Loading revisions…</div>}{!revisionLoading && revisionPage.revisions.length === 0 && <p className="muted">No retained revisions or reactions.</p>}{revisionPage.revisions.map((revision) => <article className="workspace-history-row" key={revision.event_id}><strong>{revision.event_type === "delete" ? "Deletion tombstone" : revision.event_type === "reaction" ? `${revision.active ? "Added" : "Removed"} reaction ${revision.emoji ?? ""}` : `Edit ${revision.revision}`}</strong><time dateTime={machineTime(revision.created_at)}>{formatTime(revision.created_at)}</time>{revision.text != null && <p>{revision.text}</p>}</article>)}{revisionPage.next_cursor && <Button variant="secondary" disabled={revisionLoading} onClick={() => void loadRevisions(true)}>{revisionLoading ? "Loading…" : "Load older revisions"}</Button>}{revisionError && <p className="form-error" role="alert">{revisionError}</p>}</div></Dialog>}</>
  );
}

function WorkspaceMentionChips({ workspace, memberIds, onRemove }: { workspace: Workspace; memberIds: string[]; onRemove: (memberId: string) => void }) {
  if (memberIds.length === 0) return null;
  return <div className="workspace-mention-chips" aria-label="Selected mentions">{memberIds.map((memberId) => {
    const member = workspace.members.find((candidate) => candidate.id === memberId);
    return <span key={memberId}><AtSign size={12} />{member?.display_name ?? memberId.replaceAll("-", "").slice(0, 6)}<button type="button" onClick={() => onRemove(memberId)} aria-label={`Remove mention ${member?.display_name ?? memberId}`}><X size={12} /></button></span>;
  })}</div>;
}

function WorkspaceTombstoneDialog({ workspace, conversationId, onClose }: { workspace: Workspace; conversationId: string; onClose: () => void }) {
  const [page, setPage] = useState<WorkspaceTombstonePage | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const load = useCallback(async (append = false) => {
    if (loading) return;
    setLoading(true);
    setError("");
    try {
      const next = await serviceCommand<WorkspaceTombstonePage>("list_workspace_tombstones", {
        workspace_id: workspace.id,
        conversation_id: conversationId,
        cursor: append ? page?.next_cursor ?? null : null,
        limit: 50,
      });
      setPage((current) => append && current
        ? { ...next, tombstones: [...current.tombstones, ...next.tombstones] }
        : next);
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setLoading(false);
    }
  }, [conversationId, loading, page?.next_cursor, workspace.id]);
  useEffect(() => { void load(false); }, [conversationId, workspace.id]);
  return <Dialog title="Deleted-message history" onClose={onClose}><div className="form-stack workspace-history-view"><p className="muted">Author-signed deletion tombstones retained locally. Remote devices may keep plaintext they received before deletion.</p>{page?.history_status === "pruned" && <div className="workspace-directory-status" role="status">Older tombstones were safely pruned after the retention and live-delivery windows.</div>}{loading && !page && <div className="workspace-loading"><span className="spinner" /> Loading tombstones…</div>}{!loading && page?.tombstones.length === 0 && <p className="muted">No retained deletion tombstones in this conversation.</p>}{page?.tombstones.map((item) => <article className="workspace-history-row" key={`${item.position}:${item.message.id}`}><strong>{item.message.author_display_name}</strong><time dateTime={machineTime(item.deleted_at)}>{formatTime(item.deleted_at)}</time><p>Message deleted by its author.</p></article>)}{page?.next_cursor && <Button variant="secondary" disabled={loading} onClick={() => void load(true)}>{loading ? "Loading…" : "Load older tombstones"}</Button>}{error && <p className="form-error" role="alert">{error}</p>}</div></Dialog>;
}

function eligibleWorkspaceMentionMemberIds(workspace: Workspace, allowedMemberIds: string[], memberIds: string[]) {
  const allowed = new Set(allowedMemberIds);
  const active = new Set(workspace.members.filter((member) => member.status === "active").map((member) => member.id));
  return [...new Set(memberIds)].filter((memberId) => memberId !== workspace.local_member_id && allowed.has(memberId) && active.has(memberId)).sort();
}

function WorkspaceMentionPicker({ workspace, allowedMemberIds, selectedMemberIds, onSelect }: { workspace: Workspace; allowedMemberIds: string[]; selectedMemberIds: string[]; onSelect: (member: Workspace["members"][number]) => void }) {
  const [open, setOpen] = useState(false);
  const members = workspace.members.filter((member) => member.status === "active" && member.id !== workspace.local_member_id && allowedMemberIds.includes(member.id) && !selectedMemberIds.includes(member.id));
  useEffect(() => {
    if (!open) return;
    const close = (event: KeyboardEvent) => { if (event.key === "Escape") setOpen(false); };
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, [open]);
  return <span className="workspace-mention-picker"><button type="button" className="icon-button" onClick={() => setOpen((current) => !current)} aria-label="Mention a workspace member" aria-expanded={open}><AtSign size={19} /></button>{open && <div className="workspace-mention-picker__menu" role="dialog" aria-label="Choose a member to mention"><strong>Mention someone</strong>{members.map((member) => <button type="button" key={member.id} onClick={() => { onSelect(member); setOpen(false); }}><Avatar name={member.display_name} small /><span>{member.display_name}<small>{member.short_id}</small></span></button>)}{members.length === 0 && <p>No other eligible members.</p>}</div>}</span>;
}

function WorkspaceHeaderMoreMenu({ label, open, onOpenChange, children }: { label: string; open: boolean; onOpenChange: (open: boolean) => void; children: ReactNode }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target as Node | null;
      if (target && !containerRef.current?.contains(target)) onOpenChange(false);
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      onOpenChange(false);
      triggerRef.current?.focus();
    };
    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [onOpenChange, open]);
  return <div ref={containerRef} className="workspace-header-more compact-only">
    <button ref={triggerRef} type="button" className="icon-button" aria-label={label} title="More actions" aria-haspopup="menu" aria-expanded={open} onClick={() => onOpenChange(!open)}><EllipsisVertical size={20} /></button>
    {open && <div className="workspace-header-menu" role="menu">{children}</div>}
  </div>;
}

function WorkspaceConversation({ workspace, channel, page, draft, mentionMemberIds, loading, sending, error, reactionTargetId, reactionCatalogOpen, reactionBusyEmoji, reactionError, headerMenuOpen, onHeaderMenuOpenChange, onDraft, onSend, onLoadOlder, onHide, onOpenThread, onEdit, onDelete, onToggleReactionPicker, onReactionCatalogOpenChange, onCloseReactionPicker, onSetReaction, onBack, onPeople, onSettings, onInvite, onManage, onToggleMentionMute }: { workspace: Workspace; channel: WorkspaceChannel; page: WorkspaceMessagePage | null; draft: string; mentionMemberIds: string[]; loading: boolean; sending: boolean; error: string; reactionTargetId: string | null; reactionCatalogOpen: boolean; reactionBusyEmoji: string | null; reactionError: string; headerMenuOpen: boolean; onHeaderMenuOpenChange: (open: boolean) => void; onDraft: (value: string, mentionMemberIds: string[]) => void; onSend: () => void; onLoadOlder: () => void; onHide: (eventId: string) => void; onOpenThread: (eventId: string) => void; onEdit: (eventId: string, text: string, mentionMemberIds: string[]) => void; onDelete: (eventId: string) => void; onToggleReactionPicker: (eventId: string) => void; onReactionCatalogOpenChange: (eventId: string, open: boolean) => void; onCloseReactionPicker: () => void; onSetReaction: (eventId: string, emoji: string, active: boolean) => void; onBack: () => void; onPeople: () => void; onSettings: () => void; onInvite: () => void; onManage: () => void; onToggleMentionMute: () => void }) {
  const postingRestricted = workspace.policies.posting === "owner_and_admins" && !["owner", "admin"].includes(workspace.local_role);
  const readOnly = workspace.state !== "active" || channel.state !== "active" || postingRestricted;
  const [attachmentWarning, setAttachmentWarning] = useState("");
  const [tombstonesOpen, setTombstonesOpen] = useState(false);
  const syncWarning = workspaceSyncIssueLabel(workspace);
  return <section className="conversation workspace-conversation" aria-label={`Workspace channel ${channel.name}`} onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); if (event.dataTransfer.files.length) setAttachmentWarning("Attachments are not supported yet. No file was sent."); }}>
    <header className="conversation__header">
      <button className="icon-button mobile-only mobile-back" type="button" onClick={onBack} aria-label={`Back to ${workspace.name}`}><ArrowLeft size={21} /></button>
      <div className="conversation__identity"><span className="workspace-channel-icon">{channel.visibility === "private" ? <LockKeyhole size={19} /> : <Hash size={19} />}</span><span><h1>{channel.display_name || channel.name}</h1><small>{channel.topic || `${workspace.name} · ${channel.visibility === "private" ? "private signed roster" : workspaceStateLabel(workspace)}`}</small></span></div>
      <div className="workspace-header-actions">
        <button className="icon-button" onClick={onPeople} aria-label={`People in ${workspace.name}`} title="People"><Users size={18} /></button>
        <button className="icon-button compact-hidden" onClick={onManage} aria-label={`Manage ${channel.name} channel`} title="Channel details"><Settings size={18} /></button>
        <button className="icon-button compact-hidden" onClick={onToggleMentionMute} aria-label={`${channel.mentions_muted ? "Unmute" : "Mute"} mentions in ${channel.name}`} title={channel.mentions_muted ? "Show mentions in Mentions" : "Mute mentions from this channel"}>{channel.mentions_muted ? <BellOff size={18} /> : <Bell size={18} />}</button>
        {workspace.local_role === "owner" && workspace.state === "active" && workspace.members.filter((member) => member.status === "active").length < 8 && <button className="icon-button compact-hidden" onClick={onInvite} aria-label={`Invite people to ${workspace.name}`} title="Invite people"><UserRoundPlus size={18} /></button>}
        <button className="icon-button compact-hidden" onClick={() => setTombstonesOpen(true)} aria-label={`Deleted messages in ${channel.name}`} title="Deleted-message history"><Trash2 size={18} /></button>
        <button className="icon-button compact-hidden" onClick={onSettings} aria-label={`${workspace.name} settings`} title="Workspace settings"><Building2 size={18} /></button>
        <WorkspaceHeaderMoreMenu label={`More actions for ${channel.name}`} open={headerMenuOpen} onOpenChange={onHeaderMenuOpenChange}>
          <button type="button" role="menuitem" aria-label="Channel details from More actions" onClick={() => { onHeaderMenuOpenChange(false); onManage(); }}><Settings size={17} />Channel details</button>
          <button type="button" role="menuitem" aria-label={`${channel.mentions_muted ? "Show in Mentions" : "Mute mentions"} from More actions`} onClick={() => { onHeaderMenuOpenChange(false); onToggleMentionMute(); }}>{channel.mentions_muted ? <BellOff size={17} /> : <Bell size={17} />}{channel.mentions_muted ? "Show in Mentions" : "Mute mentions"}</button>
          {workspace.local_role === "owner" && workspace.state === "active" && workspace.members.filter((member) => member.status === "active").length < 8 && <button type="button" role="menuitem" aria-label="Invite people from More actions" onClick={() => { onHeaderMenuOpenChange(false); onInvite(); }}><UserRoundPlus size={17} />Invite people</button>}
          <button type="button" role="menuitem" aria-label="Deleted messages from More actions" onClick={() => { onHeaderMenuOpenChange(false); setTombstonesOpen(true); }}><Trash2 size={17} />Deleted messages</button>
          <button type="button" role="menuitem" aria-label="Workspace settings from More actions" onClick={() => { onHeaderMenuOpenChange(false); onSettings(); }}><Building2 size={17} />Workspace settings</button>
        </WorkspaceHeaderMoreMenu>
      </div>
    </header>
    {workspace.local_role === "owner" && Boolean(workspace.pending_owner_review_count) && <div className="workspace-directory-status" role="status"><ShieldCheck size={15} />{workspace.pending_owner_review_count} pending owner {workspace.pending_owner_review_count === 1 ? "review" : "reviews"}</div>}
    <div className="message-scroll workspace-message-scroll">
      {page?.next_cursor && <button className="load-older" disabled={loading} onClick={onLoadOlder}>{loading ? "Loading…" : "Load older messages"}</button>}
      {page?.history_status === "pruned" && !page.next_cursor && <div className="workspace-directory-status" role="status">Earlier local history was pruned under the active retention preference.</div>}
      {page?.history_status === "permanent_gap" && <div className="workspace-directory-status" role="status">Some signed ranges are permanently unavailable; this device does not claim the history is complete.</div>}
      {loading && !page && <div className="workspace-loading"><span className="spinner" /> Loading messages…</div>}
      {!loading && page?.messages.length === 0 && <div className="workspace-channel-empty">{channel.visibility === "private" ? <LockKeyhole size={26} /> : <Hash size={26} />}<h2>Welcome to #{channel.display_name || channel.name}</h2><p>{channel.visibility === "private" ? "Only the signed roster receives this channel or its future messages. Newly admitted members receive no earlier messages." : "Everyone in this workspace receives public-channel messages. History depends on copies retained by reachable members."}</p></div>}
      {page?.messages.map((message) => <WorkspaceMessageCard key={message.id} workspace={workspace} message={message} allowedMentionMemberIds={channel.visibility === "private" ? channel.member_ids : workspace.members.filter((member) => member.status === "active").map((member) => member.id)} reactionOpen={reactionTargetId === message.id} reactionCatalogOpen={reactionTargetId === message.id && reactionCatalogOpen} reactionBusyEmoji={reactionTargetId === message.id ? reactionBusyEmoji : null} reactionError={reactionTargetId === message.id ? reactionError : ""} onToggleReaction={() => onToggleReactionPicker(message.id)} onReactionCatalogOpenChange={(open) => onReactionCatalogOpenChange(message.id, open)} onCloseReaction={onCloseReactionPicker} onSetReaction={(emoji, active) => onSetReaction(message.id, emoji, active)} onEdit={(text, editedMentionMemberIds) => onEdit(message.id, text, editedMentionMemberIds)} onDelete={() => onDelete(message.id)} onHide={() => onHide(message.id)} onOpenThread={() => onOpenThread(message.id)} />)}
    </div>
    {(error || attachmentWarning || syncWarning) && <p className="form-error workspace-composer-error" role="alert">{error || attachmentWarning || syncWarning}</p>}
    {readOnly ? <div className="composer-disabled"><LockKeyhole size={16} />{postingRestricted ? "Only workspace owners and administrators can post under the current signed policy." : channel.state === "archived" ? "This channel is archived and read-only." : channel.state === "leaving" ? "Leaving is pending with the channel manager." : workspaceStateLabel(workspace)}</div> : <div className="workspace-composer-shell"><WorkspaceMentionChips workspace={workspace} memberIds={mentionMemberIds} onRemove={(memberId) => onDraft(draft, mentionMemberIds.filter((id) => id !== memberId))} /><div className="composer workspace-composer"><button type="button" className="icon-button" onClick={() => setAttachmentWarning("Attachments are not supported yet. No file was sent.")} aria-label="Add attachment"><Plus size={20} /></button><WorkspaceMentionPicker workspace={workspace} allowedMemberIds={channel.visibility === "private" ? channel.member_ids : workspace.members.filter((member) => member.status === "active").map((member) => member.id)} selectedMemberIds={mentionMemberIds} onSelect={(member) => onDraft(`${draft}${draft && !draft.endsWith(" ") ? " " : ""}@${member.display_name} `, [...mentionMemberIds, member.id].sort())} /><textarea value={draft} onChange={(event) => { setAttachmentWarning(""); onDraft(event.target.value, mentionMemberIds); }} onPaste={(event) => { if (event.clipboardData.files.length || Array.from(event.clipboardData.items).some((item) => item.kind === "file")) { event.preventDefault(); setAttachmentWarning("Attachments are not supported yet. No file was sent."); } }} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); onSend(); } }} placeholder={`Message #${channel.name}`} aria-label={`Message ${channel.name}`} maxLength={16 * 1024} /><Button disabled={sending || !draft.trim()} onClick={onSend} aria-label="Send workspace message"><Send size={18} /></Button></div></div>}
    {tombstonesOpen && <WorkspaceTombstoneDialog workspace={workspace} conversationId={channel.id} onClose={() => setTombstonesOpen(false)} />}
  </section>;
}

function WorkspaceDirectConversation({ workspace, direct, page, draft, mentionMemberIds, loading, sending, error, reactionTargetId, reactionCatalogOpen, reactionBusyEmoji, reactionError, headerMenuOpen, onHeaderMenuOpenChange, onDraft, onSend, onLoadOlder, onHideMessage, onOpenThread, onEdit, onDelete, onToggleReactionPicker, onReactionCatalogOpenChange, onCloseReactionPicker, onSetReaction, onBack, onHideConversation, onPeople }: { workspace: Workspace; direct: WorkspaceDirect; page: WorkspaceMessagePage | null; draft: string; mentionMemberIds: string[]; loading: boolean; sending: boolean; error: string; reactionTargetId: string | null; reactionCatalogOpen: boolean; reactionBusyEmoji: string | null; reactionError: string; headerMenuOpen: boolean; onHeaderMenuOpenChange: (open: boolean) => void; onDraft: (value: string, mentionMemberIds: string[]) => void; onSend: () => void; onLoadOlder: () => void; onHideMessage: (eventId: string) => void; onOpenThread: (eventId: string) => void; onEdit: (eventId: string, text: string, mentionMemberIds: string[]) => void; onDelete: (eventId: string) => void; onToggleReactionPicker: (eventId: string) => void; onReactionCatalogOpenChange: (eventId: string, open: boolean) => void; onCloseReactionPicker: () => void; onSetReaction: (eventId: string, emoji: string, active: boolean) => void; onBack: () => void; onHideConversation: () => void; onPeople: () => void }) {
  const [attachmentWarning, setAttachmentWarning] = useState("");
  const [tombstonesOpen, setTombstonesOpen] = useState(false);
  const readOnly = workspace.state !== "active" || direct.state !== "open";
  const readOnlyLabel = direct.state !== "open"
    ? "This workspace DM is read-only because one participant is no longer active."
    : workspaceStateLabel(workspace);
  return <section className="conversation workspace-conversation" aria-label={`Workspace direct message with ${direct.peer_display_name}`} onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); if (event.dataTransfer.files.length) setAttachmentWarning("Attachments are not supported yet. No file was sent."); }}>
    <header className="conversation__header">
      <button className="icon-button mobile-only mobile-back" type="button" onClick={onBack} aria-label={`Back to ${workspace.name}`}><ArrowLeft size={21} /></button>
      <div className="conversation__identity"><Avatar name={direct.peer_display_name} small /><span><h1>{direct.peer_display_name}</h1><small>{workspace.name} · workspace DM · {direct.peer_short_id}</small></span></div>
      <div className="workspace-header-actions">
        <button className="icon-button" onClick={onPeople} aria-label={`People in ${workspace.name}`} title="People"><Users size={18} /></button>
        <button className="icon-button compact-hidden" onClick={() => setTombstonesOpen(true)} aria-label={`Deleted messages with ${direct.peer_display_name}`} title="Deleted-message history"><Trash2 size={18} /></button>
        <button className="icon-button compact-hidden" onClick={onHideConversation} aria-label={`Hide workspace conversation with ${direct.peer_display_name}`} title="Hide locally"><EyeOff size={18} /></button>
        <WorkspaceHeaderMoreMenu label={`More actions for ${direct.peer_display_name}`} open={headerMenuOpen} onOpenChange={onHeaderMenuOpenChange}>
          <button type="button" role="menuitem" aria-label="Deleted messages from More actions" onClick={() => { onHeaderMenuOpenChange(false); setTombstonesOpen(true); }}><Trash2 size={17} />Deleted messages</button>
          <button type="button" role="menuitem" aria-label="Hide conversation from More actions" onClick={() => { onHeaderMenuOpenChange(false); onHideConversation(); }}><EyeOff size={17} />Hide conversation</button>
        </WorkspaceHeaderMoreMenu>
      </div>
    </header>
    <div className="message-scroll workspace-message-scroll">{page?.next_cursor && <button className="load-older" disabled={loading} onClick={onLoadOlder}>{loading ? "Loading…" : "Load older messages"}</button>}{page?.history_status === "pruned" && !page.next_cursor && <div className="workspace-directory-status" role="status">Earlier local DM history was pruned under the active retention preference.</div>}{page?.history_status === "permanent_gap" && <div className="workspace-directory-status" role="status">Some signed DM ranges are permanently unavailable; no workspace owner or admin can recover them.</div>}{loading && !page && <div className="workspace-loading"><span className="spinner" /> Loading messages…</div>}{!loading && page?.messages.length === 0 && <div className="workspace-channel-empty"><MessageCircleMore size={28} /><h2>Message {direct.peer_display_name}</h2><p>This private workspace conversation is authorized by signed membership and does not create a global Contact.</p></div>}{page?.messages.map((message) => <WorkspaceMessageCard key={message.id} workspace={workspace} message={message} allowedMentionMemberIds={direct.participant_member_ids} reactionOpen={reactionTargetId === message.id} reactionCatalogOpen={reactionTargetId === message.id && reactionCatalogOpen} reactionBusyEmoji={reactionTargetId === message.id ? reactionBusyEmoji : null} reactionError={reactionTargetId === message.id ? reactionError : ""} onToggleReaction={() => onToggleReactionPicker(message.id)} onReactionCatalogOpenChange={(open) => onReactionCatalogOpenChange(message.id, open)} onCloseReaction={onCloseReactionPicker} onSetReaction={(emoji, active) => onSetReaction(message.id, emoji, active)} onEdit={(text, editedMentionMemberIds) => onEdit(message.id, text, editedMentionMemberIds)} onDelete={() => onDelete(message.id)} onHide={() => onHideMessage(message.id)} onOpenThread={() => onOpenThread(message.id)} />)}</div>
    {(error || attachmentWarning) && <p className="form-error workspace-composer-error" role="alert">{error || attachmentWarning}</p>}
    {readOnly ? <div className="composer-disabled"><LockKeyhole size={16} />{readOnlyLabel}</div> : <div className="workspace-composer-shell"><WorkspaceMentionChips workspace={workspace} memberIds={mentionMemberIds} onRemove={(memberId) => onDraft(draft, mentionMemberIds.filter((id) => id !== memberId))} /><div className="composer workspace-composer"><button type="button" className="icon-button" onClick={() => setAttachmentWarning("Attachments are not supported yet. No file was sent.")} aria-label="Add attachment"><Plus size={20} /></button><WorkspaceMentionPicker workspace={workspace} allowedMemberIds={direct.participant_member_ids} selectedMemberIds={mentionMemberIds} onSelect={(member) => onDraft(`${draft}${draft && !draft.endsWith(" ") ? " " : ""}@${member.display_name} `, [...mentionMemberIds, member.id].sort())} /><textarea value={draft} onChange={(event) => { setAttachmentWarning(""); onDraft(event.target.value, mentionMemberIds); }} onPaste={(event) => { if (event.clipboardData.files.length || Array.from(event.clipboardData.items).some((item) => item.kind === "file")) { event.preventDefault(); setAttachmentWarning("Attachments are not supported yet. No file was sent."); } }} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); onSend(); } }} placeholder={`Message ${direct.peer_display_name}`} aria-label={`Message ${direct.peer_display_name}`} maxLength={16 * 1024} /><Button disabled={sending || !draft.trim()} onClick={onSend} aria-label="Send workspace direct message"><Send size={18} /></Button></div></div>}
    {tombstonesOpen && <WorkspaceTombstoneDialog workspace={workspace} conversationId={direct.id} onClose={() => setTombstonesOpen(false)} />}
  </section>;
}

function WorkspaceMentions({ workspace, page, loading, error, onBack, onLoadOlder, onMarkRead, onOpenConversation }: { workspace: Workspace; page: WorkspaceMentionPage | null; loading: boolean; error: string; onBack: () => void; onLoadOlder: () => void; onMarkRead: () => void; onOpenConversation: (kind: "channel" | "direct", conversationId: string, threadRootId?: string) => void }) {
  return <section className="conversation workspace-mentions" aria-label={`Mentions in ${workspace.name}`}>
    <header className="conversation__header"><button className="icon-button mobile-only mobile-back" type="button" onClick={onBack} aria-label={`Back to ${workspace.name}`}><ArrowLeft size={21} /></button><div className="conversation__identity"><span className="workspace-channel-icon"><AtSign size={19} /></span><span><h1>Mentions</h1><small>Structured mentions addressed to you in {workspace.name}</small></span></div>{(page?.unread_count ?? workspace.mention_unread_count) > 0 && <Button variant="secondary" onClick={onMarkRead}>Mark all read</Button>}</header>
    <div className="message-scroll workspace-mention-list">
      {loading && !page && <div className="workspace-loading"><span className="spinner" /> Loading mentions…</div>}
      {!loading && page?.mentions.length === 0 && <div className="workspace-channel-empty"><AtSign size={28} /><h2>No mentions</h2><p>Only member IDs inserted with the mention picker appear here. Raw @name text remains ordinary message text.</p></div>}
      {page?.mentions.map((mention) => <button type="button" className={`workspace-mention-row ${mention.read ? "" : "workspace-mention-row--unread"}`} key={`${mention.position}:${mention.message.id}`} onClick={() => onOpenConversation(mention.conversation.kind, mention.conversation.id, mention.thread_root_id)}><Avatar name={mention.message.author_display_name} small /><span><span className="workspace-mention-row__meta"><strong>{mention.message.author_display_name}</strong><small>{mention.conversation.kind === "channel" ? `#${mention.conversation.name}` : mention.conversation.name}{mention.thread_root_id ? " · thread" : ""} · {formatTime(mention.message.created_at)}</small>{!mention.read && <i>New</i>}</span><span>{mention.message.text}</span></span></button>)}
      {page?.next_cursor && <button className="load-older" disabled={loading} onClick={onLoadOlder}>{loading ? "Loading…" : "Load older mentions"}</button>}
    </div>
    {error && <p className="form-error workspace-composer-error" role="alert">{error}</p>}
  </section>;
}

function WorkspaceSearchView({ workspace, query, scope, page, loading, error, onBack, onQuery, onScope, onLoadMore, onOpen }: { workspace: Workspace; query: string; scope: WorkspaceSearchScope; page: WorkspaceSearchPage | null; loading: boolean; error: string; onBack: () => void; onQuery: (value: string) => void; onScope: (value: WorkspaceSearchScope) => void; onLoadMore: () => void; onOpen: (result: WorkspaceSearchResult) => void }) {
  const scopes: Array<{ id: WorkspaceSearchScope; label: string }> = [
    { id: "all", label: "All" },
    { id: "messages", label: "Messages" },
    { id: "threads", label: "Threads" },
    { id: "people", label: "People" },
    { id: "channels", label: "Channels" },
  ];
  const readyQuery = query.trim().length >= 2;
  return <section className="conversation workspace-search" aria-label={`Search ${workspace.name}`}>
    <header className="conversation__header"><button className="icon-button mobile-only mobile-back" type="button" onClick={onBack} aria-label={`Back to ${workspace.name}`}><ArrowLeft size={21} /></button><div className="conversation__identity"><span className="workspace-channel-icon"><Search size={19} /></span><span><h1>Search</h1><small>Encrypted local results retained on this device</small></span></div></header>
    <div className="workspace-search__controls">
      <label className="workspace-search__input"><Search size={18} aria-hidden="true" /><span className="sr-only">Search {workspace.name}</span><input autoFocus type="search" value={query} maxLength={256} onChange={(event) => onQuery(event.target.value)} placeholder={`Search ${workspace.name}`} aria-label={`Search ${workspace.name}`} /></label>
      <div className="workspace-search__filters" role="group" aria-label="Search category">{scopes.map((item) => <button type="button" key={item.id} aria-pressed={scope === item.id} className={scope === item.id ? "workspace-search__filter--active" : ""} onClick={() => onScope(item.id)}>{item.label}</button>)}</div>
    </div>
    <div className="message-scroll workspace-search__results" role="region" aria-live="polite" aria-busy={loading}>
      {!readyQuery && <div className="workspace-channel-empty"><Search size={28} /><h2>Search retained workspace data</h2><p>Enter at least two characters. Queries stay on this device and are never sent to peers.</p></div>}
      {loading && !page && <div className="workspace-loading"><span className="spinner" /> Searching encrypted local history…</div>}
      {readyQuery && !loading && page?.results.length === 0 && <div className="workspace-channel-empty"><Search size={28} /><h2>No retained results</h2><p>{page.indexing ? "Indexing is still in progress, so results may be incomplete." : "No currently authorized retained item matches this exact-token search."}</p></div>}
      {page?.coverage === "indexing" && <div className="workspace-directory-status" role="status">Indexing retained history · {page.indexed_events} of {page.target_events}. Results are incomplete until indexing finishes.</div>}
      {page?.coverage === "pruned" && <div className="workspace-directory-status" role="status">Results cover retained local data only. Earlier content was pruned under the active history preference.</div>}
      {page?.coverage === "incomplete" && <div className="workspace-directory-status" role="status">Local search coverage is incomplete because a documented index or candidate bound was reached.</div>}
      {page?.results.map((result) => <button type="button" className="workspace-search-result" key={`${result.kind}:${result.id}`} onClick={() => onOpen(result)}><span className="workspace-search-result__icon">{result.kind === "channel" ? <Hash size={18} /> : result.kind === "person" ? <Users size={18} /> : result.kind === "thread" ? <MessageCircleMore size={18} /> : <Search size={18} />}</span><span><span className="workspace-search-result__meta"><strong>{result.title}</strong><small>{result.kind === "message" ? "Message" : result.kind === "thread" ? "Thread reply" : result.kind === "person" ? "Person" : "Channel"}{result.conversation ? ` · ${result.conversation.kind === "channel" ? "#" : ""}${result.conversation.name}` : ""}{result.created_at ? ` · ${formatTime(result.created_at)}` : ""}</small></span><span>{result.snippet}</span></span><ChevronRight size={17} aria-hidden="true" /></button>)}
      {page?.next_cursor && <button className="load-older" disabled={loading} onClick={onLoadMore}>{loading ? "Loading…" : "More results"}</button>}
    </div>
    {error && <p className="form-error workspace-composer-error" role="alert">{error.includes("stale") ? "Search access or retained history changed. Run the search again." : error}</p>}
  </section>;
}

function WorkspaceThreads({ workspace, page, loading, error, onBack, onLoadOlder, onOpenThread }: { workspace: Workspace; page: WorkspaceThreadActivityPage | null; loading: boolean; error: string; onBack: () => void; onLoadOlder: () => void; onOpenThread: (kind: "channel" | "direct", conversationId: string, rootId: string) => void }) {
  return <section className="conversation workspace-threads" aria-label={`Threads in ${workspace.name}`}>
    <header className="conversation__header"><button className="icon-button mobile-only mobile-back" type="button" onClick={onBack} aria-label={`Back to ${workspace.name}`}><ArrowLeft size={21} /></button><div className="conversation__identity"><span className="workspace-channel-icon"><MessageCircleMore size={19} /></span><span><h1>Threads</h1><small>Recent one-level discussions in {workspace.name}</small></span></div></header>
    <div className="message-scroll workspace-thread-list">
      {loading && !page && <div className="workspace-loading"><span className="spinner" /> Loading threads…</div>}
      {!loading && page?.threads.length === 0 && <div className="workspace-channel-empty"><MessageCircleMore size={28} /><h2>No threads yet</h2><p>Open any workspace message and start a focused discussion.</p></div>}
      {page?.threads.map((thread) => <button type="button" className={`workspace-thread-row ${thread.unread_count ? "workspace-thread-row--unread" : ""}`} key={thread.root.id} onClick={() => onOpenThread(thread.conversation.kind, thread.conversation.id, thread.root.id)}><Avatar name={thread.root.author_display_name} small /><span><span className="workspace-mention-row__meta"><strong>{thread.root.author_display_name}</strong><small>{thread.conversation.kind === "channel" ? `#${thread.conversation.name}` : thread.conversation.name} · {formatTime(thread.updated_at)}</small>{thread.unread_count > 0 && <i>{thread.unread_count} new</i>}</span><span>{thread.root.deleted ? "Message deleted by its author." : thread.root.text}</span><small>{thread.reply_count} {thread.reply_count === 1 ? "reply" : "replies"}</small></span></button>)}
      {page?.next_cursor && <button className="load-older" disabled={loading} onClick={onLoadOlder}>{loading ? "Loading…" : "Load older threads"}</button>}
    </div>
    {error && <p className="form-error workspace-composer-error" role="alert">{error}</p>}
  </section>;
}

type WorkspaceThreadViewProps = {
  workspace: Workspace;
  page: WorkspaceThreadPage | null;
  draft: string;
  mentionMemberIds: string[];
  allowedMentionMemberIds: string[];
  loading: boolean;
  sending: boolean;
  error: string;
  reactionTargetId: string | null;
  reactionCatalogOpen: boolean;
  reactionBusyEmoji: string | null;
  reactionError: string;
  onBack: () => void;
  onDraft: (value: string, mentionMemberIds: string[]) => void;
  onSend: () => void;
  onLoadOlder: () => void;
  onHide: (eventId: string) => void;
  onEdit: (eventId: string, text: string, mentionMemberIds: string[]) => void;
  onDelete: (eventId: string) => void;
  onToggleReactionPicker: (eventId: string) => void;
  onReactionCatalogOpenChange: (eventId: string, open: boolean) => void;
  onCloseReactionPicker: () => void;
  onSetReaction: (eventId: string, emoji: string, active: boolean) => void;
};

function WorkspaceThreadView({ workspace, page, draft, mentionMemberIds, allowedMentionMemberIds, loading, sending, error, reactionTargetId, reactionCatalogOpen, reactionBusyEmoji, reactionError, onBack, onDraft, onSend, onLoadOlder, onHide, onEdit, onDelete, onToggleReactionPicker, onReactionCatalogOpenChange, onCloseReactionPicker, onSetReaction }: WorkspaceThreadViewProps) {
  const [attachmentWarning, setAttachmentWarning] = useState("");
  const readOnly = workspace.state !== "active" || (page != null && page.conversation.state !== "active" && page.conversation.state !== "open");
  const card = (message: WorkspaceMessage) => <WorkspaceMessageCard key={message.id} workspace={workspace} message={message} allowedMentionMemberIds={allowedMentionMemberIds} reactionOpen={reactionTargetId === message.id} reactionCatalogOpen={reactionTargetId === message.id && reactionCatalogOpen} reactionBusyEmoji={reactionTargetId === message.id ? reactionBusyEmoji : null} reactionError={reactionTargetId === message.id ? reactionError : ""} onToggleReaction={() => onToggleReactionPicker(message.id)} onReactionCatalogOpenChange={(open) => onReactionCatalogOpenChange(message.id, open)} onCloseReaction={onCloseReactionPicker} onSetReaction={(emoji, active) => onSetReaction(message.id, emoji, active)} onEdit={(text, editedMentionMemberIds) => onEdit(message.id, text, editedMentionMemberIds)} onDelete={() => onDelete(message.id)} onHide={() => onHide(message.id)} />;
  return <section className="conversation workspace-thread" aria-label={`Thread in ${workspace.name}`}>
    <header className="conversation__header"><div className="conversation__identity"><button type="button" className="icon-button" onClick={onBack} aria-label="Back to workspace conversation"><ArrowLeft size={19} /></button><span className="workspace-channel-icon"><MessageCircleMore size={19} /></span><span><h1>Thread</h1><small>{page ? `${page.conversation.kind === "channel" ? "#" : ""}${page.conversation.name} · ${page.replies.length} loaded replies` : workspace.name}</small></span></div></header>
    <div className="message-scroll workspace-thread-messages">
      {loading && !page && <div className="workspace-loading"><span className="spinner" /> Loading thread…</div>}
      {page && <><div className="workspace-thread-root"><small>Original message</small>{card(page.root)}</div><div className="workspace-thread-divider"><span>{page.high_water} {page.high_water === 1 ? "reply" : "replies"}</span></div>{page.next_cursor && <button className="load-older" disabled={loading} onClick={onLoadOlder}>{loading ? "Loading…" : "Load older replies"}</button>}{page.replies.map(card)}{page.replies.length === 0 && <p className="workspace-thread-empty">No replies yet. Start the discussion below.</p>}</>}
    </div>
    {(error || attachmentWarning) && <p className="form-error workspace-composer-error" role="alert">{error || attachmentWarning}</p>}
    {readOnly ? <div className="composer-disabled"><LockKeyhole size={16} />This thread is read-only under current workspace access.</div> : <div className="workspace-composer-shell"><WorkspaceMentionChips workspace={workspace} memberIds={mentionMemberIds} onRemove={(memberId) => onDraft(draft, mentionMemberIds.filter((id) => id !== memberId))} /><div className="composer workspace-composer"><button type="button" className="icon-button" onClick={() => setAttachmentWarning("Attachments are not supported yet. No file was sent.")} aria-label="Add attachment"><Plus size={20} /></button><WorkspaceMentionPicker workspace={workspace} allowedMemberIds={allowedMentionMemberIds} selectedMemberIds={mentionMemberIds} onSelect={(member) => onDraft(`${draft}${draft && !draft.endsWith(" ") ? " " : ""}@${member.display_name} `, [...mentionMemberIds, member.id].sort())} /><textarea value={draft} onChange={(event) => { setAttachmentWarning(""); onDraft(event.target.value, mentionMemberIds); }} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); onSend(); } }} placeholder="Reply in thread" aria-label="Reply in thread" maxLength={16 * 1024} /><Button disabled={sending || !draft.trim()} onClick={onSend} aria-label="Send thread reply"><Send size={18} /></Button></div></div>}
  </section>;
}

type ConversationSelection = { kind: "contact" | "group"; id: string } | null;
type ReactionTarget = { kind: "direct" | "group" | "workspace"; messageId: string; layer: "quick" | "catalog" } | null;

type DraftWrite = {
  command: "save_draft" | "save_group_draft" | "save_workspace_draft" | "save_workspace_direct_draft" | "save_workspace_thread_draft";
  payload: Record<string, unknown>;
};

type DraftWriteSlot = {
  timer: number | null;
  pending: DraftWrite | null;
  // Always-normalized tail used only as an ordering barrier.
  tail: Promise<void>;
};

type WorkspaceDraftValue = {
  text: string;
  mentionMemberIds: string[];
};

const DRAFT_SAVE_DELAY_MS = 200;

function Messenger({ snapshot, theme, onThemeChange, refresh, workspaceChannelInvalidation, notificationTarget, onNotificationHandled, onLock, initialInvitation, onInvitationHandled }: { snapshot: Snapshot; theme: Theme; onThemeChange: (theme: Theme) => void; refresh: (afterCurrent?: boolean) => Promise<Snapshot>; workspaceChannelInvalidation: ServiceEvent | null; notificationTarget: NotificationOpenTarget | null; onNotificationHandled: () => void; onLock: () => Promise<void>; initialInvitation: string; onInvitationHandled: () => void }) {
  const groups = snapshot.groups ?? [];
  const groupMessages = snapshot.group_messages ?? [];
  const groupInvitations = snapshot.group_invitations ?? [];
  const workspaces = snapshot.workspaces ?? [];
  const workspaceChannels = snapshot.workspace_channels ?? [];
  const workspaceDirects = snapshot.workspace_directs ?? [];
  const workspaceChannelTransfers = snapshot.workspace_channel_transfers ?? [];
  const workspaceJoinRequests = snapshot.workspace_join_requests ?? [];
  const workspaceDisplayNameRequests = snapshot.workspace_display_name_requests ?? [];
  const workspaceAdminRequests = snapshot.workspace_admin_requests ?? [];
  const workspaceAuthorityTransitions = snapshot.workspace_authority_transitions ?? [];
  const workspaceDeviceTransitions = snapshot.workspace_device_transitions ?? [];
  const workspaceInvitations = snapshot.workspace_invitations ?? [];
  const hiddenConversationKeys = new Set((snapshot.hidden_conversations ?? []).map((item) => `${item.kind}:${item.id}`));
  const [selection, setSelection] = useState<ConversationSelection>(() => {
    const initiallyHidden = new Set((snapshot.hidden_conversations ?? []).map((item) => `${item.kind}:${item.id}`));
    const contact = snapshot.contacts.find((candidate) => candidate.trust !== "pending_request" && !initiallyHidden.has(`direct:${candidate.id}`));
    if (contact) return { kind: "contact", id: contact.id };
    const group = groups.find((candidate) => !initiallyHidden.has(`group:${candidate.id}`));
    return group ? { kind: "group", id: group.id } : null;
  });
  const [query, setQuery] = useState("");
  const [showDeletedConversations, setShowDeletedConversations] = useState(false);
  const [conversationDetailsOpen, setConversationDetailsOpen] = useState(false);
  const [drafts, setDrafts] = useState<Record<string, string>>(() => Object.fromEntries(snapshot.drafts.map((draft) => [draft.contact_id, draft.text])));
  const [groupDrafts, setGroupDrafts] = useState<Record<string, string>>(() => Object.fromEntries((snapshot.group_drafts ?? []).map((draft) => [draft.group_id, draft.text])));
  const [newChat, setNewChat] = useState(false);
  const [newGroup, setNewGroup] = useState(false);
  const [webrtcOnboardingOpen, setWebRtcOnboardingOpen] = useState(false);
  const [webrtcSessionActive, setWebRtcSessionActive] = useState(() => getWebRTCSession() !== null);
  const [callContactId, setCallContactId] = useState<string | null>(null);
  const [callSummary, setCallSummary] = useState<CallSummary | undefined>(undefined);
  const incomingCall = (snapshot.calls ?? []).find((call) => call.direction === "inbound" && call.state === "ringing");
  const callContact = snapshot.contacts.find((contact) => contact.id === callContactId);
  const [workspacesEnabled, setWorkspacesEnabled] = useState(false);
  const [activeSpaceId, setActiveSpaceId] = useState<"personal" | string>("personal");
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(true);
  const [workspaceHeaderMenuOpen, setWorkspaceHeaderMenuOpen] = useState(false);
  const [createWorkspaceOpen, setCreateWorkspaceOpen] = useState(false);
  const [joinWorkspaceOpen, setJoinWorkspaceOpen] = useState(false);
  const [joinWorkspaceValue, setJoinWorkspaceValue] = useState("");
  const [inviteWorkspaceOpen, setInviteWorkspaceOpen] = useState(false);
  const [workspacePeopleOpen, setWorkspacePeopleOpen] = useState(false);
  const [workspaceAuthorityOpen, setWorkspaceAuthorityOpen] = useState(false);
  const [workspaceDevicesOpen, setWorkspaceDevicesOpen] = useState(false);
  const [workspaceSettingsOpen, setWorkspaceSettingsOpen] = useState(false);
  const [resumeWorkspaceId, setResumeWorkspaceId] = useState<string | undefined>();
  const [workspaceRetentionOpen, setWorkspaceRetentionOpen] = useState(false);
  const [workspaceBrowseOpen, setWorkspaceBrowseOpen] = useState(false);
  const [workspaceCreateChannelOpen, setWorkspaceCreateChannelOpen] = useState(false);
  const [workspaceManageChannelOpen, setWorkspaceManageChannelOpen] = useState(false);
  const [workspaceSelectedChannelId, setWorkspaceSelectedChannelId] = useState<string | null>(null);
  const [workspaceSelectedDirectId, setWorkspaceSelectedDirectId] = useState<string | null>(null);
  const [workspaceMentionsOpen, setWorkspaceMentionsOpen] = useState(false);
  const [workspaceMentionPage, setWorkspaceMentionPage] = useState<WorkspaceMentionPage | null>(null);
  const [workspaceMentionLoading, setWorkspaceMentionLoading] = useState(false);
  const [workspaceSearchOpen, setWorkspaceSearchOpen] = useState(false);
  const [workspaceSearchQuery, setWorkspaceSearchQuery] = useState("");
  const [workspaceSearchScope, setWorkspaceSearchScope] = useState<WorkspaceSearchScope>("all");
  const [workspaceSearchPage, setWorkspaceSearchPage] = useState<WorkspaceSearchPage | null>(null);
  const [workspaceSearchLoading, setWorkspaceSearchLoading] = useState(false);
  const [workspaceSearchError, setWorkspaceSearchError] = useState("");
  const [workspaceThreadsOpen, setWorkspaceThreadsOpen] = useState(false);
  const [workspaceThreadActivityPage, setWorkspaceThreadActivityPage] = useState<WorkspaceThreadActivityPage | null>(null);
  const [workspaceThreadActivityLoading, setWorkspaceThreadActivityLoading] = useState(false);
  const [workspaceThreadRootId, setWorkspaceThreadRootId] = useState<string | null>(null);
  const [workspaceThreadPage, setWorkspaceThreadPage] = useState<WorkspaceThreadPage | null>(null);
  const [workspaceThreadLoading, setWorkspaceThreadLoading] = useState(false);
  const [workspacePage, setWorkspacePage] = useState<WorkspaceMessagePage | null>(null);
  const [workspacePageLoading, setWorkspacePageLoading] = useState(false);
  const [workspaceDrafts, setWorkspaceDrafts] = useState<Record<string, WorkspaceDraftValue>>(() => Object.fromEntries((snapshot.workspace_drafts ?? []).map((draft) => [draft.thread_root_id ? `thread:${draft.thread_root_id}` : draft.conversation_id, { text: draft.text, mentionMemberIds: draft.mention_member_ids ?? [] }])));
  const [workspaceSending, setWorkspaceSending] = useState(false);
  const [workspaceError, setWorkspaceError] = useState("");
  const [workspaceActionBusy, setWorkspaceActionBusy] = useState(false);
  const [workspaceActionError, setWorkspaceActionError] = useState("");
  useEffect(() => {
    setWorkspaceHeaderMenuOpen(false);
  }, [activeSpaceId, mobileSidebarOpen, workspaceMentionsOpen, workspaceSearchOpen, workspaceSelectedChannelId, workspaceSelectedDirectId, workspaceThreadsOpen]);
  const workspacePageInFlight = useRef(false);
  const workspaceMentionsInFlight = useRef(false);
  const workspaceSearchRequest = useRef(0);
  const workspaceThreadsInFlight = useRef(false);
  const workspaceThreadInFlight = useRef(false);
  const loadedWorkspaceChannel = useRef<string | null>(null);
  const workspaceSendInFlight = useRef(false);
  const pendingWorkspaceSend = useRef<{
    workspaceId: string;
    conversationId: string;
    kind: "channel" | "direct";
    text: string;
    operationId: string;
    eventId: string;
    mentionMemberIds: string[];
  } | null>(null);
  const pendingWorkspaceThreadSend = useRef<{
    workspaceId: string;
    conversationId: string;
    threadRootId: string;
    text: string;
    operationId: string;
    eventId: string;
    mentionMemberIds: string[];
  } | null>(null);
  const [contactsOpen, setContactsOpen] = useState(false);
  const [settings, setSettings] = useState(false);
  const [help, setHelp] = useState<{ code: string; action: string | null } | null>(null);
  const [dismissedRequests, setDismissedRequests] = useState<string[]>([]);
  const [dismissedGroupInvitations, setDismissedGroupInvitations] = useState<string[]>([]);
  const [dismissedWorkspaceJoinRequests, setDismissedWorkspaceJoinRequests] = useState<string[]>([]);
  const [requestBusy, setRequestBusy] = useState<string | null>(null);
  const [requestError, setRequestError] = useState("");
  const [groupInvitationBusy, setGroupInvitationBusy] = useState<string | null>(null);
  const [groupInvitationError, setGroupInvitationError] = useState("");
  const [workspaceJoinRequestError, setWorkspaceJoinRequestError] = useState("");
  const [sendError, setSendError] = useState("");
  // A successful send command returns the message only after its encrypted
  // record is durable. Keep that authoritative result visible until a later
  // snapshot contains it. This is particularly important on mobile, where a
  // separate draft-cleanup or snapshot bridge call can be delayed behind the
  // single native worker even though the send itself has already succeeded.
  const [locallySavedMessages, setLocallySavedMessages] = useState<Record<string, ChatMessage>>({});
  const [directSendBusy, setDirectSendBusy] = useState(false);
  const [groupSendBusy, setGroupSendBusy] = useState(false);
  const directSendInFlight = useRef(false);
  const groupSendInFlight = useRef(false);
  const reactionInFlight = useRef(false);
  const reactionInteractionGeneration = useRef(0);
  const draftWriteSlots = useRef(new Map<string, DraftWriteSlot>());
  const [groupActionBusy, setGroupActionBusy] = useState(false);
  const [groupActionError, setGroupActionError] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<ConversationSelection>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const [conversationActionError, setConversationActionError] = useState("");
  const [reactionTarget, setReactionTarget] = useState<ReactionTarget>(null);
  const [reactionBusy, setReactionBusy] = useState<{ kind: "direct" | "group" | "workspace"; messageId: string; emoji: string } | null>(null);
  const [reactionError, setReactionError] = useState("");
  useEffect(() => { void runtimePlatform().then(() => setWorkspacesEnabled(true)); }, []);
  useEffect(() => {
    if (!initialInvitation) return;
    const workspaceInvitation = isWorkspaceInvitationValue(initialInvitation);
    if (workspaceInvitation) {
      // A mounted New Chat dialog owns any participant-host cleanup before it
      // hands the value to Join Workspace. Let its guarded invitation effect do
      // that work instead of stacking two dialogs or parsing this as personal.
      if (newChat) return;
      if (workspacesEnabled) {
        setNewChat(false);
        setJoinWorkspaceValue(initialInvitation);
        setJoinWorkspaceOpen(true);
      }
      return;
    }
    setNewChat(true);
  }, [initialInvitation, newChat, workspacesEnabled]);

  useEffect(() => () => {
    for (const slot of draftWriteSlots.current.values()) {
      if (slot.timer !== null) window.clearTimeout(slot.timer);
    }
  }, []);

  useEffect(() => {
    const persistedIds = new Set(snapshot.messages.map((message) => message.id));
    setLocallySavedMessages((current) => {
      const entries = Object.entries(current).filter(([id]) => !persistedIds.has(id));
      return entries.length === Object.keys(current).length ? current : Object.fromEntries(entries);
    });
  }, [snapshot.messages]);

  const directMessages = useMemo(() => {
    const persistedIds = new Set(snapshot.messages.map((message) => message.id));
    return [
      ...snapshot.messages,
      ...Object.values(locallySavedMessages).filter((message) => !persistedIds.has(message.id)),
    ].sort((left, right) => left.created_at - right.created_at);
  }, [locallySavedMessages, snapshot.messages]);

  const normalizedQuery = query.trim().toLowerCase();
  const revealDeletedConversations = showDeletedConversations || Boolean(normalizedQuery);
  const hiddenConversationCount = snapshot.contacts.filter((contact) => contact.trust !== "pending_request" && hiddenConversationKeys.has(`direct:${contact.id}`)).length
    + groups.filter((group) => hiddenConversationKeys.has(`group:${group.id}`)).length;
  const contacts = snapshot.contacts.filter((contact) => contact.trust !== "pending_request" && contact.display_name.toLowerCase().includes(normalizedQuery) && (!hiddenConversationKeys.has(`direct:${contact.id}`) || revealDeletedConversations));
  const visibleGroups = groups.filter((group) => (group.title.toLowerCase().includes(normalizedQuery) || group.members.some((member) => member.display_name.toLowerCase().includes(normalizedQuery))) && (!hiddenConversationKeys.has(`group:${group.id}`) || revealDeletedConversations));
  const pending = snapshot.contacts.filter((contact) => contact.trust === "pending_request");
  const incomingRequest = pending.find((contact) => !dismissedRequests.includes(contact.id)) ?? null;
  const incomingGroupInvitation = groupInvitations.find((invitation) => !dismissedGroupInvitations.includes(invitation.id)) ?? null;
  const foregroundGroupInvitation = incomingRequest ? null : incomingGroupInvitation;
  const incomingWorkspaceJoinRequest = workspaceJoinRequests.find((request) => !dismissedWorkspaceJoinRequests.includes(request.id) && workspaces.some((workspace) => workspace.id === request.workspace_id)) ?? null;
  const foregroundWorkspaceJoinRequest = incomingRequest || foregroundGroupInvitation ? null : incomingWorkspaceJoinRequest;
  const foregroundWorkspaceJoinWorkspace = foregroundWorkspaceJoinRequest
    ? workspaces.find((workspace) => workspace.id === foregroundWorkspaceJoinRequest.workspace_id) ?? null
    : null;
  const hasForegroundRequest = Boolean(incomingRequest || foregroundGroupInvitation || foregroundWorkspaceJoinWorkspace);
  const networkAvailable = Boolean(snapshot.network?.interface_available) && !snapshot.service_error;
  const selectedContact = selection?.kind === "contact" ? snapshot.contacts.find((contact) => contact.id === selection.id) ?? null : null;
  const selectedGroup = selection?.kind === "group" ? groups.find((group) => group.id === selection.id) ?? null : null;
  const selectedWorkspace = activeSpaceId === "personal" ? null : workspaces.find((workspace) => workspace.id === activeSpaceId) ?? null;
  const selectedWorkspaceJoinStatus = selectedWorkspace ? workspaceJoinStatus(selectedWorkspace) : null;
  const selectedWorkspaceChannels = selectedWorkspace ? workspaceChannels.filter((channel) => channel.workspace_id === selectedWorkspace.id) : [];
  const selectedWorkspaceDirects = selectedWorkspace ? workspaceDirects.filter((direct) => direct.workspace_id === selectedWorkspace.id) : [];
  const selectedWorkspaceDirect = selectedWorkspace
    ? selectedWorkspaceDirects.find((direct) => direct.id === workspaceSelectedDirectId) ?? null
    : null;
  const selectedWorkspaceChannel = selectedWorkspace
    ? workspaceSelectedDirectId === null
      ? selectedWorkspaceChannels.find((channel) => channel.id === workspaceSelectedChannelId)
      ?? selectedWorkspaceChannels.find((channel) => channel.id === selectedWorkspace.general_channel_id)
      ?? null
      : null
    : null;
  const selectedWorkspaceConversation = selectedWorkspaceDirect ?? selectedWorkspaceChannel;
  const selectedWorkspaceThreadAllowedMemberIds = selectedWorkspace && workspaceThreadPage
    ? selectedWorkspaceDirects.find((direct) => direct.id === workspaceThreadPage.conversation.id)?.participant_member_ids
      ?? (selectedWorkspaceChannels.find((channel) => channel.id === workspaceThreadPage.conversation.id)?.visibility === "private"
        ? selectedWorkspaceChannels.find((channel) => channel.id === workspaceThreadPage.conversation.id)!.member_ids
        : selectedWorkspace.members.filter((member) => member.status === "active").map((member) => member.id))
    : [];
  const deleteTargetName = deleteTarget?.kind === "contact"
    ? snapshot.contacts.find((contact) => contact.id === deleteTarget.id)?.display_name ?? "this contact"
    : deleteTarget?.kind === "group"
      ? groups.find((group) => group.id === deleteTarget.id)?.title ?? "this group"
      : "this conversation";
  const messages = selectedContact ? directMessages.filter((message) => message.contact_id === selectedContact.id) : [];
  const selectedGroupMessages = selectedGroup ? groupMessages.filter((message) => message.group_id === selectedGroup.id) : [];

  useEffect(() => {
    if (activeSpaceId !== "personal" && !workspaces.some((workspace) => workspace.id === activeSpaceId)) setActiveSpaceId("personal");
  }, [activeSpaceId, workspaces]);

  useEffect(() => {
    setWorkspaceSelectedChannelId(null);
    setWorkspaceSelectedDirectId(null);
    setWorkspaceMentionsOpen(false);
    setWorkspaceMentionPage(null);
    setWorkspaceSearchOpen(false);
    setWorkspaceSearchQuery("");
    setWorkspaceSearchPage(null);
    setWorkspaceSearchError("");
    setWorkspaceThreadsOpen(false);
    setWorkspaceThreadActivityPage(null);
    setWorkspaceThreadRootId(null);
    setWorkspaceThreadPage(null);
    setWorkspaceManageChannelOpen(false);
    setWorkspaceRetentionOpen(false);
  }, [activeSpaceId]);

  useEffect(() => {
    if (!notificationTarget) return;
    if (!notificationTarget.available) {
      setWorkspaceError(notificationTarget.message ?? "This notification is no longer available on this device.");
      return;
    }
    if (notificationTarget.scope === "personal_direct" || notificationTarget.scope === "personal_group") {
      const kind = notificationTarget.scope === "personal_direct" ? "contact" : "group";
      const exists = kind === "contact"
        ? snapshot.contacts.some((contact) => contact.id === notificationTarget.target_id)
        : groups.some((group) => group.id === notificationTarget.target_id);
      if (!notificationTarget.target_id || !exists) {
        setWorkspaceError("This notification is no longer available on this device.");
        return;
      }
      setActiveSpaceId("personal");
      setSelection({ kind, id: notificationTarget.target_id });
      setMobileSidebarOpen(false);
      onNotificationHandled();
      return;
    }
    if (!notificationTarget.workspace_id || !notificationTarget.conversation_id) {
      setWorkspaceError("This notification is no longer available on this device.");
      return;
    }
    if (!workspaces.some((workspace) => workspace.id === notificationTarget.workspace_id)) {
      setWorkspaceError("This notification is no longer available on this device.");
      return;
    }
    if (activeSpaceId !== notificationTarget.workspace_id) {
      setActiveSpaceId(notificationTarget.workspace_id);
      return;
    }
    setWorkspaceSearchOpen(false);
    setWorkspaceMentionsOpen(false);
    setWorkspaceThreadsOpen(false);
    setWorkspaceError("");
    setMobileSidebarOpen(false);
    if (notificationTarget.conversation_kind === "direct") {
      setWorkspaceSelectedDirectId(notificationTarget.conversation_id);
      setWorkspaceSelectedChannelId(null);
    } else {
      setWorkspaceSelectedChannelId(notificationTarget.conversation_id);
      setWorkspaceSelectedDirectId(null);
    }
    setWorkspaceThreadRootId(notificationTarget.thread_root_id ?? null);
    onNotificationHandled();
  }, [activeSpaceId, groups, notificationTarget, onNotificationHandled, snapshot.contacts, workspaces]);

  const loadWorkspaceMessages = useCallback(async (append = false) => {
    if (!selectedWorkspace || !selectedWorkspaceConversation || workspacePageInFlight.current) return;
    workspacePageInFlight.current = true;
    setWorkspacePageLoading(true);
    try {
      const page = await serviceCommand<WorkspaceMessagePage>(selectedWorkspaceDirect ? "list_workspace_direct_messages" : "list_workspace_messages", {
        workspace_id: selectedWorkspace.id,
        ...(selectedWorkspaceDirect ? { conversation_id: selectedWorkspaceDirect.id } : { channel_id: selectedWorkspaceChannel!.id }),
        cursor: append ? workspacePage?.next_cursor ?? null : null,
        limit: 50,
      });
      setWorkspacePage((current) => append && current ? { ...page, messages: [...page.messages, ...current.messages] } : page);
      if (!append && selectedWorkspaceConversation.unread_count > 0) {
        await serviceCommand(selectedWorkspaceDirect ? "mark_workspace_direct_read" : "mark_workspace_read", { operation_id: newOperationId(), workspace_id: selectedWorkspace.id, ...(selectedWorkspaceDirect ? { conversation_id: selectedWorkspaceDirect.id } : { channel_id: selectedWorkspaceChannel!.id }), high_water: page.high_water });
      }
    } catch (reason) { setWorkspaceError(errorMessage(reason)); }
    finally { workspacePageInFlight.current = false; setWorkspacePageLoading(false); }
  }, [selectedWorkspace?.id, selectedWorkspaceConversation?.id, selectedWorkspaceConversation?.unread_count, selectedWorkspaceDirect?.id, selectedWorkspaceChannel?.id, workspacePage?.next_cursor]);

  useEffect(() => {
    if (!selectedWorkspace || !selectedWorkspaceConversation) {
      loadedWorkspaceChannel.current = null;
      setWorkspacePage(null);
      return;
    }
    const channelKey = `${selectedWorkspace.id}:${selectedWorkspaceDirect ? "direct" : "channel"}:${selectedWorkspaceConversation.id}`;
    const selectionChanged = loadedWorkspaceChannel.current !== channelKey;
    const channelChanged = workspaceChannelInvalidation?.workspace_id === selectedWorkspace.id
      && (workspaceChannelInvalidation.conversation_id == null || workspaceChannelInvalidation.conversation_id === selectedWorkspaceConversation.id);
    if (!selectionChanged && !channelChanged) return;
    loadedWorkspaceChannel.current = channelKey;
    if (selectionChanged) setWorkspacePage(null);
    void loadWorkspaceMessages(false);
  }, [selectedWorkspace?.id, selectedWorkspaceConversation?.id, selectedWorkspaceDirect?.id, workspaceChannelInvalidation]);

  const loadWorkspaceMentions = useCallback(async (append = false) => {
    if (!selectedWorkspace || workspaceMentionsInFlight.current) return;
    workspaceMentionsInFlight.current = true;
    setWorkspaceMentionLoading(true);
    try {
      const page = await serviceCommand<WorkspaceMentionPage>("list_workspace_mentions", {
        workspace_id: selectedWorkspace.id,
        cursor: append ? workspaceMentionPage?.next_cursor ?? null : null,
        limit: 50,
      });
      setWorkspaceMentionPage((current) => append && current ? { ...page, mentions: [...current.mentions, ...page.mentions] } : page);
    } catch (reason) { setWorkspaceError(errorMessage(reason)); }
    finally { workspaceMentionsInFlight.current = false; setWorkspaceMentionLoading(false); }
  }, [selectedWorkspace?.id, workspaceMentionPage?.next_cursor]);

  useEffect(() => {
    if (!workspaceMentionsOpen || !selectedWorkspace) {
      if (!workspaceMentionsOpen) setWorkspaceMentionPage(null);
      return;
    }
    void loadWorkspaceMentions(false);
  }, [workspaceMentionsOpen, selectedWorkspace?.id, workspaceChannelInvalidation]);

  const loadWorkspaceSearch = useCallback(async (append = false) => {
    if (!selectedWorkspace || workspaceSearchQuery.trim().length < 2) return;
    const request = ++workspaceSearchRequest.current;
    setWorkspaceSearchLoading(true);
    if (!append) setWorkspaceSearchError("");
    try {
      const page = await serviceCommand<WorkspaceSearchPage>("search_workspace", {
        workspace_id: selectedWorkspace.id,
        query: workspaceSearchQuery,
        scope: workspaceSearchScope,
        cursor: append ? workspaceSearchPage?.next_cursor ?? null : null,
        limit: 25,
      });
      if (request !== workspaceSearchRequest.current) return;
      setWorkspaceSearchPage((current) => append && current
        ? { ...page, results: [...current.results, ...page.results] }
        : page);
    } catch (reason) {
      if (request === workspaceSearchRequest.current) setWorkspaceSearchError(errorMessage(reason));
    } finally {
      if (request === workspaceSearchRequest.current) setWorkspaceSearchLoading(false);
    }
  }, [selectedWorkspace?.id, workspaceSearchQuery, workspaceSearchScope, workspaceSearchPage?.next_cursor]);

  useEffect(() => {
    if (!workspaceSearchOpen || !selectedWorkspace || workspaceSearchQuery.trim().length < 2) {
      workspaceSearchRequest.current += 1;
      setWorkspaceSearchPage(null);
      setWorkspaceSearchLoading(false);
      if (workspaceSearchQuery.trim().length < 2) setWorkspaceSearchError("");
      return;
    }
    const timer = window.setTimeout(() => void loadWorkspaceSearch(false), 250);
    return () => window.clearTimeout(timer);
  }, [workspaceSearchOpen, selectedWorkspace?.id, workspaceSearchQuery, workspaceSearchScope, workspaceChannelInvalidation]);

  const loadWorkspaceThreads = useCallback(async (append = false) => {
    if (!selectedWorkspace || workspaceThreadsInFlight.current) return;
    workspaceThreadsInFlight.current = true;
    setWorkspaceThreadActivityLoading(true);
    try {
      const page = await serviceCommand<WorkspaceThreadActivityPage>("list_workspace_threads", {
        workspace_id: selectedWorkspace.id,
        cursor: append ? workspaceThreadActivityPage?.next_cursor ?? null : null,
        limit: 50,
      });
      setWorkspaceThreadActivityPage((current) => append && current ? { ...page, threads: [...current.threads, ...page.threads] } : page);
    } catch (reason) { setWorkspaceError(errorMessage(reason)); }
    finally { workspaceThreadsInFlight.current = false; setWorkspaceThreadActivityLoading(false); }
  }, [selectedWorkspace?.id, workspaceThreadActivityPage?.next_cursor]);

  useEffect(() => {
    if (!workspaceThreadsOpen || !selectedWorkspace) {
      if (!workspaceThreadsOpen) setWorkspaceThreadActivityPage(null);
      return;
    }
    void loadWorkspaceThreads(false);
  }, [workspaceThreadsOpen, selectedWorkspace?.id, workspaceChannelInvalidation]);

  const loadWorkspaceThread = useCallback(async (append = false) => {
    if (!selectedWorkspace || !workspaceThreadRootId || workspaceThreadInFlight.current) return;
    workspaceThreadInFlight.current = true;
    setWorkspaceThreadLoading(true);
    try {
      const page = await serviceCommand<WorkspaceThreadPage>("list_workspace_thread_messages", {
        workspace_id: selectedWorkspace.id,
        thread_root_id: workspaceThreadRootId,
        cursor: append ? workspaceThreadPage?.next_cursor ?? null : null,
        limit: 50,
      });
      setWorkspaceThreadPage((current) => append && current ? { ...page, unread_count: current.unread_count, replies: [...page.replies, ...current.replies] } : page);
      if (!append && page.unread_count > 0) {
        await serviceCommand("mark_workspace_thread_read", {
          operation_id: newOperationId(),
          workspace_id: selectedWorkspace.id,
          thread_root_id: workspaceThreadRootId,
          high_water: page.high_water,
        });
        setWorkspaceThreadPage((current) => current ? { ...current, unread_count: 0 } : current);
        void refresh(true);
      }
    } catch (reason) { setWorkspaceError(errorMessage(reason)); }
    finally { workspaceThreadInFlight.current = false; setWorkspaceThreadLoading(false); }
  }, [selectedWorkspace?.id, workspaceThreadRootId, workspaceThreadPage?.next_cursor, refresh]);

  useEffect(() => {
    if (!workspaceThreadRootId || !selectedWorkspace) {
      setWorkspaceThreadPage(null);
      return;
    }
    void loadWorkspaceThread(false);
  }, [workspaceThreadRootId, selectedWorkspace?.id, workspaceChannelInvalidation]);

  const conversationItems = [
    ...contacts.map((contact) => {
      const latest = [...directMessages].reverse().find((message) => message.contact_id === contact.id);
      return { kind: "contact" as const, id: contact.id, updatedAt: latest?.created_at ?? contact.updated_at, contact, latest, hidden: hiddenConversationKeys.has(`direct:${contact.id}`) };
    }),
    ...visibleGroups.map((group) => {
      const latest = [...groupMessages].reverse().find((message) => message.group_id === group.id);
      return { kind: "group" as const, id: group.id, updatedAt: latest?.created_at ?? group.updated_at, group, latest, hidden: hiddenConversationKeys.has(`group:${group.id}`) };
    }),
  ].sort((left, right) => right.updatedAt - left.updatedAt);

  const selectConversation = (next: ConversationSelection) => {
    reactionInteractionGeneration.current += 1;
    setSendError("");
    setGroupActionError("");
    setConversationActionError("");
    setConversationDetailsOpen(false);
    setReactionTarget(null);
    setReactionError("");
    setSelection(next);
    setMobileSidebarOpen(next === null);
  };

  const closeReactionPicker = useCallback(() => {
    reactionInteractionGeneration.current += 1;
    setReactionTarget(null);
    setReactionError("");
  }, []);

  const toggleReactionPicker = (kind: "direct" | "group" | "workspace", messageId: string) => {
    if (reactionInFlight.current) return;
    setReactionError("");
    setReactionTarget((current) => current?.kind === kind && current.messageId === messageId ? null : { kind, messageId, layer: "quick" });
  };

  const setReactionCatalogOpen = (kind: "direct" | "group" | "workspace", messageId: string, open: boolean) => {
    setReactionTarget((current) => current?.kind === kind && current.messageId === messageId
      ? { ...current, layer: open ? "catalog" : "quick" }
      : current);
  };

  const setMessageReaction = async (kind: "direct" | "group", messageId: string, emoji: string, active: boolean) => {
    if (reactionInFlight.current) return;
    const validation = validateSingleEmoji(emoji);
    if (validation.error) {
      setReactionError(validation.error);
      return;
    }
    reactionInFlight.current = true;
    const interactionGeneration = ++reactionInteractionGeneration.current;
    setReactionTarget((current) => current?.kind === kind && current.messageId === messageId ? current : { kind, messageId, layer: "quick" });
    setReactionBusy({ kind, messageId, emoji: validation.emoji });
    setReactionError("");
    try {
      await serviceCommand("set_message_reaction", { kind, message_id: messageId, emoji: validation.emoji, active });
      await refresh(true);
      if (reactionInteractionGeneration.current === interactionGeneration) {
        setReactionTarget((current) => current?.kind === kind && current.messageId === messageId ? null : current);
      }
    } catch (reason) {
      if (reactionInteractionGeneration.current === interactionGeneration) {
        setReactionTarget((current) => current?.kind === kind && current.messageId === messageId ? current : { kind, messageId, layer: "quick" });
        setReactionError(errorMessage(reason));
      }
    } finally {
      reactionInFlight.current = false;
      setReactionBusy(null);
    }
  };

  const restoreAndSelect = async (next: Exclude<ConversationSelection, null>, hidden: boolean) => {
    if (!hidden) {
      selectConversation(next);
      return;
    }
    setConversationActionError("");
    try {
      await serviceCommand("restore_conversation", {
        kind: next.kind === "contact" ? "direct" : "group",
        id: next.id,
      });
      setQuery("");
      selectConversation(next);
      await refresh(true);
    } catch (reason) {
      setConversationActionError(errorMessage(reason));
    }
  };

  const draftSlot = (key: string): DraftWriteSlot => {
    const existing = draftWriteSlots.current.get(key);
    if (existing) return existing;
    const created: DraftWriteSlot = { timer: null, pending: null, tail: Promise.resolve() };
    draftWriteSlots.current.set(key, created);
    return created;
  };
  const enqueueDraftWrite = (slot: DraftWriteSlot, write: DraftWrite): Promise<void> => {
    const result = slot.tail.then(async () => {
      await serviceCommand(write.command, write.payload);
    });
    // Keep the ordering barrier usable after an individual persistence error;
    // an immediate clear after a successful send must still be able to run.
    slot.tail = result.catch(() => undefined);
    return result;
  };
  const scheduleDraftWrite = (key: string, write: DraftWrite) => {
    const slot = draftSlot(key);
    slot.pending = write;
    if (slot.timer !== null) window.clearTimeout(slot.timer);
    slot.timer = window.setTimeout(() => {
      slot.timer = null;
      const pending = slot.pending;
      slot.pending = null;
      if (pending) void enqueueDraftWrite(slot, pending).catch(() => undefined);
    }, DRAFT_SAVE_DELAY_MS);
  };
  const cancelPendingDraftWrite = async (key: string) => {
    const slot = draftSlot(key);
    if (slot.timer !== null) {
      window.clearTimeout(slot.timer);
      slot.timer = null;
    }
    slot.pending = null;
    await slot.tail;
  };
  const writeDraftNow = async (key: string, write: DraftWrite) => {
    await cancelPendingDraftWrite(key);
    await enqueueDraftWrite(draftSlot(key), write);
  };
  const deleteConversation = async () => {
    if (!deleteTarget || deleteBusy) return;
    const target = deleteTarget;
    const kind = target.kind === "contact" ? "direct" : "group";
    const draftKey = `${target.kind}:${target.id}`;
    setDeleteBusy(true);
    setDeleteError("");
    try {
      // Prevent a delayed draft write from recreating content after the vault
      // has committed the deletion.
      await cancelPendingDraftWrite(draftKey);
      await serviceCommand("delete_conversation", { kind, id: target.id });
      if (target.kind === "contact") {
        setDrafts((current) => {
          const next = { ...current };
          delete next[target.id];
          return next;
        });
        setLocallySavedMessages((current) => Object.fromEntries(Object.entries(current).filter(([, message]) => message.contact_id !== target.id)));
      } else {
        setGroupDrafts((current) => {
          const next = { ...current };
          delete next[target.id];
          return next;
        });
      }
      setSelection(null);
      setDeleteTarget(null);
      setQuery("");
      await refresh(true);
    } catch (reason) {
      setDeleteError(errorMessage(reason));
    } finally {
      setDeleteBusy(false);
    }
  };
  const saveDraft = (contactId: string, text: string) => {
    setDrafts((current) => ({ ...current, [contactId]: text }));
    scheduleDraftWrite(`contact:${contactId}`, {
      command: "save_draft",
      payload: { contact_id: contactId, text },
    });
  };
  const saveGroupDraft = (groupId: string, text: string) => {
    setGroupDrafts((current) => ({ ...current, [groupId]: text }));
    scheduleDraftWrite(`group:${groupId}`, {
      command: "save_group_draft",
      payload: { group_id: groupId, text },
    });
  };
  const saveWorkspaceDraft = (workspaceId: string, channelId: string, text: string, mentionMemberIds: string[]) => {
    setWorkspaceDrafts((current) => ({ ...current, [channelId]: { text, mentionMemberIds } }));
    scheduleDraftWrite(`workspace:${channelId}`, {
      command: "save_workspace_draft",
      payload: { operation_id: newOperationId(), workspace_id: workspaceId, channel_id: channelId, text, mention_member_ids: mentionMemberIds },
    });
  };
  const saveWorkspaceDirectDraft = (workspaceId: string, conversationId: string, text: string, mentionMemberIds: string[]) => {
    setWorkspaceDrafts((current) => ({ ...current, [conversationId]: { text, mentionMemberIds } }));
    scheduleDraftWrite(`workspace-direct:${conversationId}`, {
      command: "save_workspace_direct_draft",
      payload: { operation_id: newOperationId(), workspace_id: workspaceId, conversation_id: conversationId, text, mention_member_ids: mentionMemberIds },
    });
  };
  const saveWorkspaceThreadDraft = (workspaceId: string, conversationId: string, threadRootId: string, text: string, mentionMemberIds: string[]) => {
    const key = `thread:${threadRootId}`;
    setWorkspaceDrafts((current) => ({ ...current, [key]: { text, mentionMemberIds } }));
    scheduleDraftWrite(`workspace-thread:${threadRootId}`, {
      command: "save_workspace_thread_draft",
      payload: { operation_id: newOperationId(), workspace_id: workspaceId, conversation_id: conversationId, thread_root_id: threadRootId, text, mention_member_ids: mentionMemberIds },
    });
  };
  const send = async () => {
    if (!selectedContact || directSendInFlight.current) return;
    const text = drafts[selectedContact.id] ?? "";
    if (!text.trim()) return;
    const contactId = selectedContact.id;
    const draftKey = `contact:${contactId}`;
    directSendInFlight.current = true;
    setDirectSendBusy(true);
    setSendError("");
    setDrafts((current) => ({ ...current, [contactId]: "" }));
    // Drop every not-yet-started keystroke save and wait for the sole active
    // save, if any. The send and final empty-draft write then have a strict
    // order even on Android's single native Python worker.
    await cancelPendingDraftWrite(draftKey);
    try {
      const saved = await serviceCommand<ChatMessage>("send_message", { contact_id: contactId, text });
      setLocallySavedMessages((current) => ({ ...current, [saved.id]: saved }));
    } catch (reason) {
      setDrafts((current) => current[contactId] ? current : { ...current, [contactId]: text });
      scheduleDraftWrite(draftKey, {
        command: "save_draft",
        payload: { contact_id: contactId, text },
      });
      setSendError(`${errorMessage(reason)} Your text is still in the composer. Check the conversation before sending it again.`);
      directSendInFlight.current = false;
      setDirectSendBusy(false);
      return;
    }
    try {
      await writeDraftNow(draftKey, {
        command: "save_draft",
        payload: { contact_id: contactId, text: "" },
      });
    } catch {
      // The durable send already succeeded. Do not restore the text and imply
      // that it is safe to submit again merely because draft cleanup failed.
      setSendError("Your message was saved, but its saved draft could not be cleared. It may reappear after reopening Mesh Chat.");
    }
    try {
      // A state-change event may already have started a snapshot before the
      // send committed. Queue a new snapshot behind it instead of reusing it.
      await refresh(true);
    } catch {
      setSendError((current) => current || "Your message was saved. The conversation could not refresh yet, but it will appear when Mesh Chat updates.");
    } finally {
      directSendInFlight.current = false;
      setDirectSendBusy(false);
    }
  };
  const sendGroupMessage = async () => {
    if (!selectedGroup || groupSendInFlight.current) return;
    const posting = groupComposerState(selectedGroup, snapshot.profile?.destination_hash ?? "");
    if (!posting.canPost) {
      setSendError(posting.reason || "Messaging is not available for this group right now.");
      return;
    }
    const groupId = selectedGroup.id;
    const text = groupDrafts[groupId] ?? "";
    if (!text.trim()) return;
    const draftKey = `group:${groupId}`;
    groupSendInFlight.current = true;
    setGroupSendBusy(true);
    setSendError("");
    setGroupDrafts((current) => ({ ...current, [groupId]: "" }));
    await cancelPendingDraftWrite(draftKey);
    try {
      await serviceCommand("send_group_message", { group_id: groupId, text });
    } catch (reason) {
      setGroupDrafts((current) => current[groupId] ? current : { ...current, [groupId]: text });
      scheduleDraftWrite(draftKey, {
        command: "save_group_draft",
        payload: { group_id: groupId, text },
      });
      setSendError(`${errorMessage(reason)} Your text is still in the composer. Check the conversation before sending it again.`);
      groupSendInFlight.current = false;
      setGroupSendBusy(false);
      return;
    }
    try {
      await writeDraftNow(draftKey, {
        command: "save_group_draft",
        payload: { group_id: groupId, text: "" },
      });
    } catch {
      setSendError("Your message was saved, but its saved draft could not be cleared. It may reappear after reopening Mesh Chat.");
    }
    try {
      await refresh(true);
    } catch {
      setSendError((current) => current || "Your message was saved. The conversation could not refresh yet, but it will appear when Mesh Chat updates.");
    } finally {
      groupSendInFlight.current = false;
      setGroupSendBusy(false);
    }
  };
  const connectionHelp = async () => {
    if (selectedContact) setHelp(await serviceCommand("connection_help", { contact_id: selectedContact.id }));
  };
  const respondToRequest = async (contact: Contact, accept: boolean) => {
    setRequestBusy(contact.id);
    setRequestError("");
    setDismissedRequests((current) => current.filter((id) => id !== contact.id));
    try {
      await serviceCommand(accept ? "approve_request" : "decline_request", { contact_id: contact.id });
      if (accept) {
        selectConversation({ kind: "contact", id: contact.id });
        setNewChat(false);
        onInvitationHandled();
      }
      await refresh(true);
    } catch (reason) {
      if (accept) {
        try {
          const latest = await refresh(true);
          const reconciled = latest.contacts.find((candidate) => candidate.id === contact.id);
          if (reconciled?.trust === "approved" || reconciled?.trust === "verified") {
            selectConversation({ kind: "contact", id: contact.id });
            setNewChat(false);
            onInvitationHandled();
            return;
          }
        } catch {
          // Preserve the original approval error when reconciliation is unavailable.
        }
      }
      setRequestError(
        accept && String(reason).includes("service_timeout")
          ? "Mesh Chat is still processing this approval. Keep both apps open, wait a moment, then try again if the request is still shown."
          : errorMessage(reason),
      );
    } finally {
      setRequestBusy(null);
    }
  };
  const respondToGroupInvitation = async (invitation: GroupInvitation, accept: boolean) => {
    setGroupInvitationBusy(invitation.id);
    setGroupInvitationError("");
    setDismissedGroupInvitations((current) => current.filter((id) => id !== invitation.id));
    try {
      const result = await serviceCommand<Group | null>(accept ? "accept_group_invitation" : "decline_group_invitation", { invitation_id: invitation.id });
      if (accept) selectConversation({ kind: "group", id: result?.id ?? invitation.group_id });
      await refresh(true);
    } catch (reason) {
      setGroupInvitationError(errorMessage(reason));
    } finally {
      setGroupInvitationBusy(null);
    }
  };
  const runGroupAction = async (command: "leave_group" | "remove_group_member" | "retry_group_invitation" | "close_group", payload: Record<string, unknown>, leaveConversation = false) => {
    setGroupActionBusy(true);
    setGroupActionError("");
    try {
      await serviceCommand(command, payload);
      if (leaveConversation) setSelection(null);
      await refresh(true);
    } catch (reason) {
      setGroupActionError(errorMessage(reason));
    } finally {
      setGroupActionBusy(false);
    }
  };

  const respondToWorkspaceJoin = async (request: WorkspaceJoinRequest, accept: boolean) => {
    if (workspaceActionBusy || !workspaces.some((workspace) => workspace.id === request.workspace_id)) return;
    setWorkspaceActionBusy(true); setWorkspaceActionError(""); setWorkspaceJoinRequestError("");
    setDismissedWorkspaceJoinRequests((current) => current.filter((id) => id !== request.id));
    const applyLocalDecision = () => {
      setDismissedWorkspaceJoinRequests((current) => [...new Set([...current, request.id])]);
      if (accept) {
        setActiveSpaceId(request.workspace_id);
        setMobileSidebarOpen(true);
      }
    };
    try {
      await serviceCommand(accept ? "approve_workspace_join" : "decline_workspace_join", { operation_id: newOperationId(), workspace_id: request.workspace_id, request_id: request.id });
    } catch (reason) {
      try {
        const latest = await refresh(true);
        const stillPending = (latest.workspace_join_requests ?? []).some((candidate) => candidate.id === request.id);
        const latestWorkspace = (latest.workspaces ?? []).find((candidate) => candidate.id === request.workspace_id);
        const admitted = latestWorkspace?.members.some((member) => member.id === request.member_id && member.status === "active") === true;
        if ((accept && admitted) || (!accept && !stillPending && !admitted)) {
          applyLocalDecision();
          setWorkspaceActionBusy(false);
          return;
        }
      } catch {
        // Preserve the original decision error when reconciliation is unavailable.
      }
      const message = errorMessage(reason);
      const decisionMessage = String(reason).includes("service_timeout")
        ? "Mesh Chat is still processing this decision. Wait a moment, then try again only if the request is still shown."
        : message;
      setWorkspaceActionError(decisionMessage);
      setWorkspaceJoinRequestError(decisionMessage);
      setWorkspaceActionBusy(false);
      return;
    }
    applyLocalDecision();
    try {
      await refresh(true);
    } catch {
      setWorkspaceActionError("The workspace decision was saved. This view will update automatically when Mesh Chat refreshes.");
    }
    finally { setWorkspaceActionBusy(false); }
  };
  const runWorkspaceAdministration = async (
    command:
      | "update_workspace_metadata"
      | "update_workspace_policies"
      | "update_workspace_retention"
      | "remove_workspace_member"
      | "change_workspace_role"
      | "submit_workspace_admin_request"
      | "approve_workspace_admin_request"
      | "decline_workspace_admin_request"
      | "cancel_workspace_admin_request"
      | "dismiss_workspace_admin_request"
      | "offer_workspace_authority_transition"
      | "accept_workspace_authority_transition"
      | "finalize_workspace_authority_transition"
      | "report_workspace_authority_loss"
      | "approve_workspace_device_link"
      | "decline_workspace_device_link"
      | "request_workspace_device_removal"
      | "approve_workspace_device_removal"
      | "decline_workspace_device_removal"
      | "set_workspace_read_hint_sync"
      | "request_workspace_display_name"
      | "decide_workspace_display_name",
    payload: Record<string, unknown>,
  ) => {
    if (!selectedWorkspace || workspaceActionBusy) return;
    setWorkspaceActionBusy(true); setWorkspaceActionError("");
    try {
      await serviceCommand(command, {
        operation_id: newOperationId(),
        workspace_id: selectedWorkspace.id,
        ...payload,
      });
      await refresh(true);
    } catch (reason) { setWorkspaceActionError(errorMessage(reason)); }
    finally { setWorkspaceActionBusy(false); }
  };
  const createWorkspaceDeviceLink = async (): Promise<WorkspaceDeviceLinkFormats | null> => {
    if (!selectedWorkspace || workspaceActionBusy) return null;
    setWorkspaceActionBusy(true); setWorkspaceActionError("");
    try {
      const result = await serviceCommand<WorkspaceDeviceLinkFormats>("create_workspace_device_link", {
        operation_id: newOperationId(),
        workspace_id: selectedWorkspace.id,
      });
      await refresh(true);
      return result;
    } catch (reason) {
      setWorkspaceActionError(errorMessage(reason));
      return null;
    } finally { setWorkspaceActionBusy(false); }
  };
  const pruneWorkspaceHistory = async (): Promise<WorkspaceRetentionPruneResult | null> => {
    if (!selectedWorkspace || workspaceActionBusy) return null;
    setWorkspaceActionBusy(true); setWorkspaceActionError("");
    try {
      const result = await serviceCommand<WorkspaceRetentionPruneResult>("prune_workspace_history", {
        operation_id: newOperationId(),
        workspace_id: selectedWorkspace.id,
        max_events: 500,
      });
      await refresh(true);
      if (result.pruned_this_batch) {
        setWorkspacePage(null);
        setWorkspaceMentionPage(null);
        setWorkspaceThreadActivityPage(null);
        setWorkspaceThreadPage(null);
      }
      return result;
    } catch (reason) {
      setWorkspaceActionError(errorMessage(reason));
      return null;
    } finally {
      setWorkspaceActionBusy(false);
    }
  };
  const runWorkspaceChannelAction = async (
    command:
      | "create_workspace_channel"
      | "update_workspace_channel"
      | "update_workspace_private_channel_members"
      | "leave_workspace_private_channel"
      | "set_workspace_channel_subscription"
      | "set_workspace_channel_mentions_muted"
      | "offer_workspace_channel_transfer"
      | "accept_workspace_channel_transfer"
      | "recover_workspace_channel"
      | "sync_workspace_channels",
    payload: Record<string, unknown> = {},
  ) => {
    if (!selectedWorkspace || workspaceActionBusy) return;
    setWorkspaceActionBusy(true); setWorkspaceActionError("");
    try {
      const result = await serviceCommand<WorkspaceChannel | { channel_id?: string }>(command, {
        operation_id: newOperationId(),
        workspace_id: selectedWorkspace.id,
        ...payload,
      });
      if (command === "create_workspace_channel" && "id" in result) {
        setWorkspaceSelectedChannelId(result.id);
        setWorkspaceSelectedDirectId(null);
        setWorkspaceMentionsOpen(false);
        setWorkspaceThreadsOpen(false);
        setWorkspaceThreadRootId(null);
        setWorkspaceCreateChannelOpen(false);
        setWorkspaceBrowseOpen(false);
        setMobileSidebarOpen(false);
      }
      if (command === "update_workspace_channel" && "id" in result && result.state === "archived") {
        setWorkspaceManageChannelOpen(false);
      }
      await refresh(true);
    } catch (reason) { setWorkspaceActionError(errorMessage(reason)); }
    finally { setWorkspaceActionBusy(false); }
  };
  const runWorkspaceNotificationPreference = async (
    conversationId: string | null,
    mode: WorkspaceNotificationPreference,
  ) => {
    if (!selectedWorkspace || workspaceActionBusy) return;
    setWorkspaceActionBusy(true); setWorkspaceActionError("");
    try {
      await serviceCommand("set_workspace_notification_preference", {
        operation_id: newOperationId(),
        workspace_id: selectedWorkspace.id,
        conversation_id: conversationId,
        mode,
      });
      await refresh(true);
    } catch (reason) { setWorkspaceActionError(errorMessage(reason)); }
    finally { setWorkspaceActionBusy(false); }
  };
  const approveWorkspacePropagationNode = async (node: string) => {
    if (workspaceActionBusy) return;
    setWorkspaceActionBusy(true); setWorkspaceActionError("");
    try {
      await serviceCommand("update_settings", {
        settings: {
          ...snapshot.settings,
          approved_propagation_nodes: [
            ...new Set([...snapshot.settings.approved_propagation_nodes, node]),
          ],
        },
      });
      await refresh(true);
    } catch (reason) { setWorkspaceActionError(errorMessage(reason)); }
    finally { setWorkspaceActionBusy(false); }
  };
  const sendWorkspaceMessage = async () => {
    if (!selectedWorkspace || !selectedWorkspaceConversation || workspaceSendInFlight.current) return;
    const draft = workspaceDrafts[selectedWorkspaceConversation.id] ?? { text: "", mentionMemberIds: [] };
    const text = draft.text;
    const allowedMentionMemberIds = selectedWorkspaceDirect
      ? selectedWorkspaceDirect.participant_member_ids
      : selectedWorkspaceChannel?.visibility === "private"
        ? selectedWorkspaceChannel.member_ids
        : selectedWorkspace.members.filter((member) => member.status === "active").map((member) => member.id);
    const mentionMemberIds = eligibleWorkspaceMentionMemberIds(selectedWorkspace, allowedMentionMemberIds, draft.mentionMemberIds);
    if (!text.trim()) return;
    const workspaceId = selectedWorkspace.id;
    const conversationId = selectedWorkspaceConversation.id;
    const kind = selectedWorkspaceDirect ? "direct" as const : "channel" as const;
    const draftKey = kind === "direct" ? `workspace-direct:${conversationId}` : `workspace:${conversationId}`;
    const prior = pendingWorkspaceSend.current;
    const durable = prior
      && prior.workspaceId === workspaceId
      && prior.conversationId === conversationId
      && prior.kind === kind
      && prior.text === text
      && prior.mentionMemberIds.join(",") === mentionMemberIds.join(",")
      ? prior
      : {
        workspaceId,
        conversationId,
        kind,
        text,
        mentionMemberIds,
        operationId: newOperationId(),
        eventId: newOperationId(),
      };
    pendingWorkspaceSend.current = durable;
    workspaceSendInFlight.current = true;
    setWorkspaceSending(true); setWorkspaceError("");
    await cancelPendingDraftWrite(draftKey);
    let saved: WorkspaceMessage;
    try {
      saved = await serviceCommand<WorkspaceMessage>(kind === "direct" ? "send_workspace_direct_message" : "send_workspace_message", {
        operation_id: durable.operationId,
        event_id: durable.eventId,
        workspace_id: workspaceId,
        ...(kind === "direct" ? { conversation_id: conversationId } : { channel_id: conversationId }),
        text,
        mention_member_ids: durable.mentionMemberIds,
      });
    } catch (reason) {
      setWorkspaceError(`${errorMessage(reason)} Your text is still in the composer; retrying will reuse the same durable message ID.`);
      workspaceSendInFlight.current = false;
      setWorkspaceSending(false);
      return;
    }
    pendingWorkspaceSend.current = null;
    setWorkspaceDrafts((current) => ({ ...current, [conversationId]: { text: "", mentionMemberIds: [] } }));
    setWorkspacePage((current) => {
      if (!current || current.messages.some((message) => message.id === saved.id)) return current;
      return {
        ...current,
        messages: [...current.messages, saved],
        high_water: current.high_water + 1,
      };
    });
    try {
      await writeDraftNow(draftKey, kind === "direct"
        ? { command: "save_workspace_direct_draft", payload: { operation_id: newOperationId(), workspace_id: workspaceId, conversation_id: conversationId, text: "", mention_member_ids: [] } }
        : { command: "save_workspace_draft", payload: { operation_id: newOperationId(), workspace_id: workspaceId, channel_id: conversationId, text: "", mention_member_ids: [] } });
    } catch {
      setWorkspaceError("Your message was saved, but its saved draft could not be cleared. It may reappear after reopening Mesh Chat.");
    }
    try {
      await refresh(true);
    } catch {
      setWorkspaceError((current) => current || "Your message was saved. Workspace summaries could not refresh yet, but the message remains durable.");
    } finally {
      workspaceSendInFlight.current = false;
      setWorkspaceSending(false);
    }
  };
  const sendWorkspaceThreadReply = async () => {
    if (!selectedWorkspace || !workspaceThreadRootId || !workspaceThreadPage || workspaceSendInFlight.current) return;
    const conversationId = workspaceThreadPage.conversation.id;
    const draftStorageKey = `thread:${workspaceThreadRootId}`;
    const draft = workspaceDrafts[draftStorageKey] ?? { text: "", mentionMemberIds: [] };
    if (!draft.text.trim()) return;
    const direct = selectedWorkspaceDirects.find((item) => item.id === conversationId);
    const channel = selectedWorkspaceChannels.find((item) => item.id === conversationId);
    const allowedMentionMemberIds = direct?.participant_member_ids
      ?? (channel?.visibility === "private" ? channel.member_ids : selectedWorkspace.members.filter((member) => member.status === "active").map((member) => member.id));
    const mentionMemberIds = eligibleWorkspaceMentionMemberIds(selectedWorkspace, allowedMentionMemberIds, draft.mentionMemberIds);
    const prior = pendingWorkspaceThreadSend.current;
    const durable = prior
      && prior.workspaceId === selectedWorkspace.id
      && prior.threadRootId === workspaceThreadRootId
      && prior.text === draft.text
      && prior.mentionMemberIds.join(",") === mentionMemberIds.join(",")
      ? prior
      : { workspaceId: selectedWorkspace.id, conversationId, threadRootId: workspaceThreadRootId, text: draft.text, mentionMemberIds, operationId: newOperationId(), eventId: newOperationId() };
    pendingWorkspaceThreadSend.current = durable;
    workspaceSendInFlight.current = true;
    setWorkspaceSending(true);
    setWorkspaceError("");
    const draftWriteKey = `workspace-thread:${workspaceThreadRootId}`;
    await cancelPendingDraftWrite(draftWriteKey);
    let saved: WorkspaceMessage;
    try {
      saved = await serviceCommand<WorkspaceMessage>("send_workspace_thread_reply", {
        operation_id: durable.operationId,
        event_id: durable.eventId,
        workspace_id: durable.workspaceId,
        conversation_id: durable.conversationId,
        thread_root_id: durable.threadRootId,
        text: durable.text,
        mention_member_ids: durable.mentionMemberIds,
      });
    } catch (reason) {
      setWorkspaceError(`${errorMessage(reason)} Your reply is still in the composer; retrying will reuse the same durable message ID.`);
      workspaceSendInFlight.current = false;
      setWorkspaceSending(false);
      return;
    }
    pendingWorkspaceThreadSend.current = null;
    setWorkspaceDrafts((current) => ({ ...current, [draftStorageKey]: { text: "", mentionMemberIds: [] } }));
    setWorkspaceThreadPage((current) => !current || current.replies.some((reply) => reply.id === saved.id) ? current : { ...current, replies: [...current.replies, saved], high_water: current.high_water + 1 });
    try {
      await writeDraftNow(draftWriteKey, { command: "save_workspace_thread_draft", payload: { operation_id: newOperationId(), workspace_id: durable.workspaceId, conversation_id: durable.conversationId, thread_root_id: durable.threadRootId, text: "", mention_member_ids: [] } });
    } catch {
      setWorkspaceError("Your reply was saved, but its saved draft could not be cleared. It may reappear after reopening Mesh Chat.");
    }
    try { await refresh(true); }
    catch { setWorkspaceError((current) => current || "Your reply was saved. Thread summaries could not refresh yet, but the reply remains durable."); }
    finally { workspaceSendInFlight.current = false; setWorkspaceSending(false); }
  };
  const openWorkspaceDirect = async (memberId: string) => {
    if (!selectedWorkspace || workspaceActionBusy) return;
    setWorkspaceActionBusy(true); setWorkspaceActionError("");
    try {
      const direct = await serviceCommand<WorkspaceDirect>("open_workspace_direct", { operation_id: newOperationId(), workspace_id: selectedWorkspace.id, member_id: memberId });
      setWorkspaceSelectedDirectId(direct.id);
      setWorkspaceSelectedChannelId(null);
      setWorkspaceMentionsOpen(false);
      setWorkspaceThreadsOpen(false);
      setWorkspaceSearchOpen(false);
      setWorkspaceThreadRootId(null);
      setWorkspacePeopleOpen(false);
      setMobileSidebarOpen(false);
      await refresh(true);
    } catch (reason) { setWorkspaceActionError(errorMessage(reason)); }
    finally { setWorkspaceActionBusy(false); }
  };
  const hideWorkspaceDirect = async () => {
    if (!selectedWorkspace || !selectedWorkspaceDirect || workspaceActionBusy) return;
    setWorkspaceActionBusy(true); setWorkspaceError("");
    try {
      await serviceCommand("hide_workspace_direct", { operation_id: newOperationId(), workspace_id: selectedWorkspace.id, conversation_id: selectedWorkspaceDirect.id });
      setWorkspaceSelectedDirectId(null);
      await refresh(true);
    } catch (reason) { setWorkspaceError(errorMessage(reason)); }
    finally { setWorkspaceActionBusy(false); }
  };
  const markWorkspaceMentionsRead = async () => {
    if (!selectedWorkspace || !workspaceMentionPage || workspaceMentionPage.unread_count === 0) return;
    setWorkspaceError("");
    try {
      await serviceCommand("mark_workspace_mentions_read", {
        operation_id: newOperationId(),
        workspace_id: selectedWorkspace.id,
        high_water: workspaceMentionPage.high_water,
      });
      setWorkspaceMentionPage((current) => current ? {
        ...current,
        unread_count: 0,
        mentions: current.mentions.map((mention) => ({ ...mention, read: true })),
      } : current);
      await refresh(true);
    } catch (reason) { setWorkspaceError(errorMessage(reason)); }
  };
  const openWorkspaceThread = (kind: "channel" | "direct", conversationId: string, threadRootId: string) => {
    setWorkspaceMentionsOpen(false);
    setWorkspaceThreadsOpen(false);
    setWorkspaceSearchOpen(false);
    if (kind === "direct") {
      setWorkspaceSelectedDirectId(conversationId);
      setWorkspaceSelectedChannelId(null);
    } else {
      setWorkspaceSelectedChannelId(conversationId);
      setWorkspaceSelectedDirectId(null);
    }
    setWorkspaceThreadRootId(threadRootId);
    setWorkspaceThreadPage(null);
    setWorkspaceError("");
    setMobileSidebarOpen(false);
  };
  const openWorkspaceMentionConversation = (kind: "channel" | "direct", conversationId: string, threadRootId?: string) => {
    if (threadRootId) {
      openWorkspaceThread(kind, conversationId, threadRootId);
      return;
    }
    setWorkspaceMentionsOpen(false);
    setWorkspaceThreadsOpen(false);
    setWorkspaceThreadRootId(null);
    if (kind === "direct") {
      setWorkspaceSelectedDirectId(conversationId);
      setWorkspaceSelectedChannelId(null);
    } else {
      setWorkspaceSelectedChannelId(conversationId);
      setWorkspaceSelectedDirectId(null);
    }
    setMobileSidebarOpen(false);
  };
  const openWorkspaceSearchResult = (result: WorkspaceSearchResult) => {
    setWorkspaceSearchOpen(false);
    setWorkspaceSearchError("");
    if (result.kind === "person" && result.member_id) {
      if (result.member_id === selectedWorkspace?.local_member_id) setWorkspacePeopleOpen(true);
      else void openWorkspaceDirect(result.member_id);
      return;
    }
    if (result.kind === "channel" && result.conversation) {
      setWorkspaceMentionsOpen(false);
      setWorkspaceThreadsOpen(false);
      setWorkspaceThreadRootId(null);
      setWorkspaceSelectedChannelId(result.conversation.id);
      setWorkspaceSelectedDirectId(null);
      return;
    }
    if (result.conversation && result.event_id) {
      openWorkspaceThread(
        result.conversation.kind,
        result.conversation.id,
        result.thread_root_id ?? result.event_id,
      );
    }
  };
  const hideWorkspaceMessage = async (eventId: string) => {
    if (!selectedWorkspace) return;
    setWorkspaceError("");
    try {
      await serviceCommand("hide_workspace_message", { operation_id: newOperationId(), workspace_id: selectedWorkspace.id, event_id: eventId });
      if (workspaceThreadRootId === eventId) {
        setWorkspaceThreadRootId(null);
        setWorkspaceThreadPage(null);
        await loadWorkspaceMessages(false);
      } else if (workspaceThreadRootId) await loadWorkspaceThread(false);
      else await loadWorkspaceMessages(false);
    } catch (reason) { setWorkspaceError(errorMessage(reason)); }
  };
  const mutateWorkspaceMessage = async (
    command: "edit_workspace_message" | "delete_workspace_message",
    eventId: string,
    text?: string,
    mentionMemberIds: string[] = [],
  ) => {
    if (!selectedWorkspace) return;
    setWorkspaceError("");
    try {
      const updated = await serviceCommand<WorkspaceMessage>(command, {
        operation_id: newOperationId(),
        mutation_event_id: newOperationId(),
        workspace_id: selectedWorkspace.id,
        event_id: eventId,
        ...(command === "edit_workspace_message" ? { text, mention_member_ids: mentionMemberIds } : {}),
      });
      setWorkspacePage((current) => current ? {
        ...current,
        messages: current.messages.map((message) => message.id === eventId ? updated : message),
      } : current);
      setWorkspaceThreadPage((current) => current ? {
        ...current,
        root: current.root.id === eventId ? updated : current.root,
        replies: current.replies.map((message) => message.id === eventId ? updated : message),
      } : current);
    } catch (reason) { setWorkspaceError(errorMessage(reason)); }
  };
  const setWorkspaceReaction = async (messageId: string, emoji: string, active: boolean) => {
    if (!selectedWorkspace || reactionInFlight.current) return;
    const validation = validateSingleEmoji(emoji);
    if (validation.error) { setReactionError(validation.error); return; }
    reactionInFlight.current = true;
    const interactionGeneration = ++reactionInteractionGeneration.current;
    setReactionTarget((current) => current?.kind === "workspace" && current.messageId === messageId ? current : { kind: "workspace", messageId, layer: "quick" });
    setReactionBusy({ kind: "workspace", messageId, emoji: validation.emoji });
    setReactionError("");
    try {
      const updated = await serviceCommand<WorkspaceMessage>("set_workspace_reaction", {
        operation_id: newOperationId(),
        mutation_event_id: newOperationId(),
        workspace_id: selectedWorkspace.id,
        event_id: messageId,
        emoji: validation.emoji,
        active,
      });
      setWorkspacePage((current) => current ? {
        ...current,
        messages: current.messages.map((message) => message.id === messageId ? updated : message),
      } : current);
      setWorkspaceThreadPage((current) => current ? {
        ...current,
        root: current.root.id === messageId ? updated : current.root,
        replies: current.replies.map((message) => message.id === messageId ? updated : message),
      } : current);
      if (reactionInteractionGeneration.current === interactionGeneration) setReactionTarget(null);
    } catch (reason) {
      if (reactionInteractionGeneration.current === interactionGeneration) setReactionError(errorMessage(reason));
    } finally {
      reactionInFlight.current = false;
      setReactionBusy(null);
    }
  };
  const runWorkspaceLifecycle = async (command: "leave_workspace" | "close_workspace" | "remove_workspace_data", confirmation?: string) => {
    if (!selectedWorkspace || workspaceActionBusy) return;
    setWorkspaceActionBusy(true); setWorkspaceActionError("");
    try {
      await serviceCommand(command, { operation_id: newOperationId(), workspace_id: selectedWorkspace.id, ...(confirmation ? { confirmation } : {}) });
      const removed = command === "remove_workspace_data";
      if (removed) { setActiveSpaceId("personal"); setWorkspaceSettingsOpen(false); }
      await refresh(true);
    } catch (reason) { setWorkspaceActionError(errorMessage(reason)); }
    finally { setWorkspaceActionBusy(false); }
  };

  const handleMobileBack = useCallback(() => {
    const visibleDialogs = [...document.querySelectorAll<HTMLElement>('[role="dialog"]')]
      .filter((dialog) => !dialog.closest('[aria-hidden="true"]'));
    if (visibleDialogs.length > 0) {
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
      return;
    }
    if (workspaceHeaderMenuOpen) {
      setWorkspaceHeaderMenuOpen(false);
      return;
    }
    // Foreground requests cover dialogs which were already open, so they must
    // be dismissed before the underlying layer or conversation.
    if (incomingRequest) {
      setRequestError("");
      setDismissedRequests((current) => [...new Set([...current, incomingRequest.id])]);
      return;
    }
    if (foregroundGroupInvitation) {
      setGroupInvitationError("");
      setDismissedGroupInvitations((current) => [...new Set([...current, foregroundGroupInvitation.id])]);
      return;
    }
    if (foregroundWorkspaceJoinRequest) {
      setWorkspaceJoinRequestError("");
      setDismissedWorkspaceJoinRequests((current) => [...new Set([...current, foregroundWorkspaceJoinRequest.id])]);
      return;
    }
    if (deleteTarget) {
      if (!deleteBusy) {
        setDeleteError("");
        setDeleteTarget(null);
      }
      return;
    }
    if (help) {
      setHelp(null);
      return;
    }
    if (workspaceManageChannelOpen) {
      setWorkspaceManageChannelOpen(false);
      return;
    }
    if (workspaceCreateChannelOpen) {
      setWorkspaceCreateChannelOpen(false);
      return;
    }
    if (workspaceBrowseOpen) {
      setWorkspaceBrowseOpen(false);
      return;
    }
    if (workspaceRetentionOpen) {
      setWorkspaceRetentionOpen(false);
      return;
    }
    if (workspaceSettingsOpen) {
      setWorkspaceSettingsOpen(false);
      return;
    }
    if (workspaceDevicesOpen) {
      setWorkspaceDevicesOpen(false);
      return;
    }
    if (workspaceAuthorityOpen) {
      setWorkspaceAuthorityOpen(false);
      return;
    }
    if (workspacePeopleOpen) {
      setWorkspacePeopleOpen(false);
      return;
    }
    if (inviteWorkspaceOpen) {
      setInviteWorkspaceOpen(false);
      return;
    }
    if (joinWorkspaceOpen) {
      setJoinWorkspaceOpen(false);
      setJoinWorkspaceValue("");
      onInvitationHandled();
      return;
    }
    if (createWorkspaceOpen) {
      setCreateWorkspaceOpen(false);
      return;
    }
    if (contactsOpen) {
      setContactsOpen(false);
      return;
    }
    if (settings) {
      setSettings(false);
      return;
    }
    if (newGroup) {
      setNewGroup(false);
      return;
    }
    if (newChat) {
      setNewChat(false);
      onInvitationHandled();
      return;
    }
    if (reactionTarget) {
      if (reactionTarget.layer === "catalog") {
        setReactionTarget({ ...reactionTarget, layer: "quick" });
      } else {
        closeReactionPicker();
      }
      return;
    }
    if (conversationDetailsOpen) {
      setConversationDetailsOpen(false);
      return;
    }
    if (workspaceThreadRootId) {
      setWorkspaceThreadRootId(null);
      setWorkspaceThreadPage(null);
      setWorkspaceError("");
      return;
    }
    const compactLayout = window.innerWidth <= 560;
    if (!compactLayout && workspaceSearchOpen) {
      setWorkspaceSearchOpen(false);
      setWorkspaceSearchError("");
      return;
    }
    if (!compactLayout && workspaceThreadsOpen) {
      setWorkspaceThreadsOpen(false);
      setWorkspaceError("");
      return;
    }
    if (!compactLayout && workspaceMentionsOpen) {
      setWorkspaceMentionsOpen(false);
      setWorkspaceError("");
      return;
    }
    if (compactLayout && !mobileSidebarOpen && (selectedWorkspace || selection)) {
      setMobileSidebarOpen(true);
      return;
    }
    if (compactLayout && mobileSidebarOpen && activeSpaceId !== "personal") {
      setActiveSpaceId("personal");
      return;
    }
    if (!compactLayout && activeSpaceId !== "personal") {
      setActiveSpaceId("personal");
      return;
    }
    if (selection) selectConversation(null);
  }, [activeSpaceId, closeReactionPicker, contactsOpen, conversationDetailsOpen, createWorkspaceOpen, deleteBusy, deleteTarget, foregroundGroupInvitation, foregroundWorkspaceJoinRequest, help, incomingRequest, inviteWorkspaceOpen, joinWorkspaceOpen, mobileSidebarOpen, newChat, newGroup, onInvitationHandled, reactionTarget, selectedWorkspace, selection, settings, workspaceAuthorityOpen, workspaceBrowseOpen, workspaceCreateChannelOpen, workspaceDevicesOpen, workspaceHeaderMenuOpen, workspaceManageChannelOpen, workspaceMentionsOpen, workspacePeopleOpen, workspaceRetentionOpen, workspaceSearchOpen, workspaceSettingsOpen, workspaceThreadRootId, workspaceThreadsOpen]);

  const mobileBackHandlerRef = useRef(handleMobileBack);
  // Keep the single native listener pointed at the newest committed render.
  // Updating the ref while rendering avoids a one-frame gap after a layer opens.
  mobileBackHandlerRef.current = handleMobileBack;

  const hasMobileBackTarget = Boolean(
    incomingRequest
      || foregroundGroupInvitation
      || foregroundWorkspaceJoinRequest
      || (notificationTarget && !notificationTarget.available)
      || deleteTarget
      || help
      || contactsOpen
      || settings
      || newGroup
      || newChat
      || reactionTarget
      || conversationDetailsOpen
      || workspaceManageChannelOpen
      || workspaceCreateChannelOpen
      || workspaceBrowseOpen
      || workspaceRetentionOpen
      || workspaceSettingsOpen
      || workspaceDevicesOpen
      || workspaceAuthorityOpen
      || workspacePeopleOpen
      || inviteWorkspaceOpen
      || joinWorkspaceOpen
      || createWorkspaceOpen
      || workspaceHeaderMenuOpen
      || workspaceThreadRootId
      || (!mobileSidebarOpen && Boolean(selectedWorkspace || selection))
      || (mobileSidebarOpen && activeSpaceId !== "personal"),
  );
  useEffect(() => {
    // Register only while there is an in-app destination for Back. At the
    // conversation list no listener is installed, so Android retains its
    // normal behavior and exits instead of becoming trapped in the app.
    if (!hasMobileBackTarget) return;
    let active = true;
    let stop: (() => void) | undefined;
    void (async () => {
      try {
        const registered = await onMobileBackButton(() => mobileBackHandlerRef.current());
        if (typeof registered !== "function") return;
        if (active) stop = registered;
        else registered();
      } catch {
        // Desktop builds and older webviews still have the visible Back button.
      }
    })();
    return () => {
      active = false;
      stop?.();
    };
  }, [hasMobileBackTarget]);

  return (
    <main className={`app-shell ${mobileSidebarOpen || !(selectedWorkspace || selectedContact || selectedGroup) ? "app-shell--list" : "app-shell--thread"}`}>
      <aside className="sidebar">
        <header className="sidebar__top"><Brand /><div><button className="icon-button" onClick={() => setContactsOpen(true)} aria-label="Contacts" title="Contacts"><BookUser size={19} /></button><button className="icon-button" onClick={() => void onLock()} aria-label="Lock Mesh Chat" title="Lock Mesh Chat"><LockKeyhole size={18} /></button><button className="icon-button" onClick={() => setSettings(true)} aria-label="Settings" title="Settings"><Settings size={19} /></button></div></header>
        {workspacesEnabled && <WorkspaceSwitcher workspaces={workspaces} activeId={activeSpaceId} onSelect={(id) => { setActiveSpaceId(id); setMobileSidebarOpen(true); setWorkspaceError(""); setWorkspaceActionError(""); }} onCreate={() => setCreateWorkspaceOpen(true)} onJoin={() => { setJoinWorkspaceValue(""); setJoinWorkspaceOpen(true); }} />}
        {activeSpaceId === "personal" ? <>
        <div className="search-box"><Search size={17} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Filter conversations" aria-label="Filter conversations" />{query && <button type="button" className="search-box__clear" onClick={() => setQuery("")} aria-label="Clear conversation filter"><X size={16} /></button>}</div>
        {conversationActionError && <p className="form-error sidebar-action-error" role="alert">{conversationActionError}</p>}
        <nav className="contact-list" aria-label="Conversations">
          {pending.map((contact) => <section className="request-card" key={contact.id}><div><Avatar name={contact.display_name} small /><span><strong>{contact.display_name}</strong><small>Wants to connect</small></span></div><div><Button disabled={requestBusy === contact.id} onClick={() => void respondToRequest(contact, true)}>Accept</Button><Button variant="ghost" disabled={requestBusy === contact.id} onClick={() => void respondToRequest(contact, false)}>Decline</Button></div></section>)}
          {groupInvitations.map((invitation) => <section className="request-card group-request-card" key={invitation.id}><div><span className="group-request-card__icon">{invitation.posting_policy === "owner_admins" ? <Megaphone size={18} /> : <Users size={19} />}</span><span><strong>{invitation.title}</strong><small>{invitation.owner_display_name} invited you</small></span></div><div><Button disabled={groupInvitationBusy === invitation.id} onClick={() => void respondToGroupInvitation(invitation, true)}>Accept</Button><Button variant="ghost" disabled={groupInvitationBusy === invitation.id} onClick={() => void respondToGroupInvitation(invitation, false)}>Decline</Button></div></section>)}
          {pending.length > 0 && !incomingRequest && <button className="pending-reminder" type="button" onClick={() => setDismissedRequests((current) => current.filter((id) => id !== pending[0].id))}><UserRoundPlus size={17} /> Review pending request</button>}
          {groupInvitations.length > 0 && !incomingGroupInvitation && <button className="pending-reminder" type="button" onClick={() => setDismissedGroupInvitations((current) => current.filter((id) => id !== groupInvitations[0].id))}><Users size={17} /> Review group invitation</button>}
          {hiddenConversationCount > 0 && <button className="deleted-conversations-toggle" type="button" aria-pressed={showDeletedConversations} onClick={() => setShowDeletedConversations((current) => !current)}><Trash2 size={16} /> {showDeletedConversations ? "Hide deleted conversations" : `Show deleted conversations (${hiddenConversationCount})`}</button>}
          {conversationItems.map((item) => item.kind === "contact" ? (
            <button key={`contact:${item.id}`} className={`contact-row ${selection?.kind === "contact" && selection.id === item.id ? "contact-row--selected" : ""}`} onClick={() => void restoreAndSelect({ kind: "contact", id: item.id }, item.hidden)} aria-current={selection?.kind === "contact" && selection.id === item.id ? "page" : undefined} aria-label={item.hidden ? `Restore conversation with ${item.contact.display_name}` : undefined}>
              <Avatar name={item.contact.display_name} small /><span className="contact-row__content"><span><strong>{item.contact.display_name}</strong>{item.latest && <time>{formatTime(item.latest.created_at)}</time>}</span><span className="contact-row__preview">{item.hidden ? "Deleted locally · open to restore" : item.latest?.text ?? contactConnectionLabel(item.contact)}</span></span>
            </button>
          ) : (
            <button key={`group:${item.id}`} className={`contact-row ${selection?.kind === "group" && selection.id === item.id ? "contact-row--selected" : ""}`} onClick={() => void restoreAndSelect({ kind: "group", id: item.id }, item.hidden)} aria-current={selection?.kind === "group" && selection.id === item.id ? "page" : undefined} aria-label={item.hidden ? `Restore conversation ${item.group.title}` : undefined}>
              <GroupAvatar group={item.group} small /><span className="contact-row__content"><span><strong>{item.group.title}</strong>{item.latest && <time>{formatTime(item.latest.created_at)}</time>}</span><span className="contact-row__preview">{item.hidden ? "Deleted locally · open to restore" : item.latest ? `${item.latest.direction === "inbound" ? `${item.latest.sender_display_name}: ` : "You: "}${item.latest.text}` : groupPolicyLabel(item.group.posting_policy)}</span></span>
            </button>
          ))}
          {conversationItems.length === 0 && <div className="conversation-list-empty"><MessageCircleMore size={24} /><strong>{query ? "No matching conversations" : "Your conversations will appear here"}</strong><span>{query ? "Try a different name or clear the filter." : "Start a private chat or create a group below."}</span></div>}
        </nav>
        <div className="new-conversation-actions">
          <button className="new-chat-button" aria-label="New chat" onClick={() => setNewChat(true)}><Plus size={20} /><span>New chat</span></button>
          <button className="new-group-button" aria-label="New group" onClick={() => setNewGroup(true)}><Users size={19} /><span>New group</span></button>
          <button className="new-group-button" aria-label="Connect with WebRTC" onClick={() => setWebRtcOnboardingOpen(true)}><QrCode size={19} /><span>WebRTC</span></button>
        </div>
        </> : selectedWorkspace ? <>
          <div className="workspace-sidebar-heading"><div className="workspace-sidebar-heading__avatar">{initials(selectedWorkspace.name)}</div><div><strong>{selectedWorkspace.name}</strong><small>{workspaceStateLabel(selectedWorkspace)}</small></div></div>
          {workspaceActionError && <p className="form-error sidebar-action-error" role="alert">{workspaceActionError}</p>}
          <nav className="contact-list workspace-nav" aria-label={`${selectedWorkspace.name} conversations`}>
            {workspaceJoinRequests.filter((request) => request.workspace_id === selectedWorkspace.id).map((request) => <section className="request-card workspace-join-request" key={request.id}><div><Avatar name={request.display_name} small /><span><strong>{request.display_name}</strong><small>Requests to join · {request.member_id.replaceAll("-", "").slice(0, 6)}</small></span></div><p className="request-fingerprint">{request.fingerprint}</p><div><Button disabled={workspaceActionBusy} onClick={() => void respondToWorkspaceJoin(request, true)}>Approve</Button><Button variant="ghost" disabled={workspaceActionBusy} onClick={() => void respondToWorkspaceJoin(request, false)}>Decline</Button></div></section>)}
            <button className={`workspace-nav-action ${workspaceSearchOpen ? "workspace-nav-action--active" : ""}`} aria-current={workspaceSearchOpen ? "page" : undefined} onClick={() => { setWorkspaceSearchOpen(true); setWorkspaceThreadsOpen(false); setWorkspaceMentionsOpen(false); setWorkspaceThreadRootId(null); setWorkspaceSearchError(""); setMobileSidebarOpen(false); }}><Search size={17} />Search {selectedWorkspace.search_index?.status === "rebuilding" && <span aria-label="Indexing">…</span>}</button>
            <button className={`workspace-nav-action ${workspaceThreadsOpen ? "workspace-nav-action--active" : ""}`} aria-current={workspaceThreadsOpen ? "page" : undefined} onClick={() => { setWorkspaceSearchOpen(false); setWorkspaceThreadsOpen(true); setWorkspaceMentionsOpen(false); setWorkspaceThreadRootId(null); setWorkspaceError(""); setMobileSidebarOpen(false); }}><MessageCircleMore size={17} />Threads {selectedWorkspace.thread_unread_count > 0 && <b className="unread-badge">{selectedWorkspace.thread_unread_count}</b>}</button>
            <button className={`workspace-nav-action ${workspaceMentionsOpen ? "workspace-nav-action--active" : ""}`} aria-current={workspaceMentionsOpen ? "page" : undefined} onClick={() => { setWorkspaceSearchOpen(false); setWorkspaceMentionsOpen(true); setWorkspaceThreadsOpen(false); setWorkspaceThreadRootId(null); setWorkspaceError(""); setMobileSidebarOpen(false); }}><AtSign size={17} />Mentions {selectedWorkspace.mention_unread_count > 0 && <b className="unread-badge">{selectedWorkspace.mention_unread_count}</b>}</button>
            <p className="workspace-nav__label">Channels</p>
            {selectedWorkspaceChannels.filter((channel) => channel.visibility === "private" || channel.subscribed || channel.id === selectedWorkspace.general_channel_id || channel.id === selectedWorkspaceChannel?.id).map((channel) => { const current = !workspaceSearchOpen && !workspaceMentionsOpen && !workspaceThreadsOpen && !workspaceThreadRootId && selectedWorkspaceChannel?.id === channel.id; return <button key={channel.id} className={`contact-row workspace-channel-row ${current ? "contact-row--selected" : ""}`} aria-current={current ? "page" : undefined} onClick={() => { setWorkspaceSearchOpen(false); setWorkspaceMentionsOpen(false); setWorkspaceThreadsOpen(false); setWorkspaceThreadRootId(null); setWorkspaceSelectedChannelId(channel.id); setWorkspaceSelectedDirectId(null); setMobileSidebarOpen(false); }}><span className="workspace-channel-icon">{channel.visibility === "private" ? <LockKeyhole size={18} /> : <Hash size={18} />}</span><span className="contact-row__content"><span><strong>{channel.display_name || channel.name}</strong>{channel.unread_count > 0 && <b className="unread-badge">{channel.unread_count}</b>}</span><span className="contact-row__preview">{channel.state === "archived" ? "Archived · read-only" : channel.state === "leaving" ? "Leaving · read-only" : channel.topic || (channel.visibility === "private" ? "Private signed roster" : "Everyone in the workspace")}</span></span></button>; })}
            {selectedWorkspaceChannels.length === 0 && <div className="workspace-channel-pending" role={selectedWorkspaceJoinStatus ? "status" : undefined} aria-live={selectedWorkspaceJoinStatus ? "polite" : undefined} aria-atomic={selectedWorkspaceJoinStatus ? "true" : undefined}><RefreshCw size={16} aria-hidden="true" /><span><strong>{selectedWorkspaceJoinStatus?.headline ?? "Channel controls are syncing"}</strong>{selectedWorkspaceJoinStatus && <small>{selectedWorkspaceJoinStatus.detail}</small>}</span></div>}
            {selectedWorkspace.state === "joining" && <><Button variant="secondary" onClick={() => { setResumeWorkspaceId(selectedWorkspace.id); setJoinWorkspaceOpen(true); }}>Continue setup</Button><ConnectionDiagnostics /></>}
            <button className="workspace-nav-action" onClick={() => setWorkspaceBrowseOpen(true)}><Search size={17} />Browse channels <span>{selectedWorkspace.channel_discovery === "converged" ? selectedWorkspaceChannels.length : "…"}</span></button>
            {selectedWorkspace.state === "active" && (selectedWorkspace.policies.channel_creation === "all_members" || ["owner", "admin"].includes(selectedWorkspace.local_role)) && <button className="workspace-nav-action" onClick={() => setWorkspaceCreateChannelOpen(true)}><Plus size={17} />Create channel</button>}
            <p className="workspace-nav__label">Direct messages</p>
            {selectedWorkspaceDirects.map((direct) => { const current = !workspaceSearchOpen && !workspaceMentionsOpen && !workspaceThreadsOpen && !workspaceThreadRootId && selectedWorkspaceDirect?.id === direct.id; return <button key={direct.id} className={`contact-row workspace-channel-row ${current ? "contact-row--selected" : ""}`} aria-current={current ? "page" : undefined} onClick={() => { setWorkspaceSearchOpen(false); setWorkspaceMentionsOpen(false); setWorkspaceThreadsOpen(false); setWorkspaceThreadRootId(null); setWorkspaceSelectedDirectId(direct.id); setWorkspaceSelectedChannelId(null); setMobileSidebarOpen(false); }}><Avatar name={direct.peer_display_name} small /><span className="contact-row__content"><span><strong>{direct.peer_display_name}</strong>{direct.unread_count > 0 && <b className="unread-badge">{direct.unread_count}</b>}</span><span className="contact-row__preview">{direct.state === "read_only" ? "Former member · read-only" : `Workspace DM · ${direct.peer_short_id}`}</span></span></button>; })}
            {selectedWorkspaceDirects.length === 0 && <p className="workspace-direct-empty">Start a private workspace chat from People.</p>}
            <p className="workspace-nav__label">Workspace</p>
            <button className="workspace-nav-action" onClick={() => setWorkspacePeopleOpen(true)} aria-label={`People and administration${selectedWorkspace.pending_owner_review_count ? `, ${selectedWorkspace.pending_owner_review_count} requests waiting` : ""}`}><Users size={17} />People <span>{selectedWorkspace.pending_owner_review_count || selectedWorkspace.members.filter((member) => member.status === "active").length}</span></button>
            <button className="workspace-nav-action" onClick={() => setWorkspaceAuthorityOpen(true)} aria-label="Authority continuity"><ShieldCheck size={17} />Authority <span>{workspaceAuthorityTransitions.filter((item) => item.workspace_id === selectedWorkspace.id && !["applied", "expired", "stale", "superseded", "cancelled"].includes(item.state)).length || ""}</span></button>
            <button className="workspace-nav-action" onClick={() => setWorkspaceDevicesOpen(true)} aria-label="Linked devices"><Building2 size={17} />Devices <span>{workspaceDeviceTransitions.filter((item) => item.workspace_id === selectedWorkspace.id && item.state === "pending").length || (selectedWorkspace.members.find((item) => item.id === selectedWorkspace.local_member_id)?.devices?.length ?? 1)}</span></button>
            {selectedWorkspace.local_role === "owner" && selectedWorkspace.state === "active" && selectedWorkspace.members.filter((member) => member.status === "active").length < 8 && <button className="workspace-nav-action" onClick={() => setInviteWorkspaceOpen(true)}><UserRoundPlus size={17} />Invite people</button>}
            <button className="workspace-nav-action" onClick={() => setWorkspaceRetentionOpen(true)}><Clock3 size={17} />History &amp; retention</button>
            <button className="workspace-nav-action" onClick={() => setWorkspaceSettingsOpen(true)}><Settings size={17} />Workspace settings</button>
          </nav>
        </> : null}
        <footer className="sidebar__footer" title={networkAvailable ? "The local network service is running. This does not confirm that another device is reachable." : undefined}><span className={`network-dot ${networkAvailable ? "network-dot--on" : ""}`} />{networkAvailable ? "Network service active" : "Networking unavailable"}</footer>
      </aside>
      <div className="main-pane">
        {snapshot.service_error && (
          <div className="service-warning" role="alert">
            <WifiOff size={18} />
            <span><strong>Networking is unavailable.</strong> Put both devices on the same local network and reopen Mesh Chat. Your profile and queued messages are safe.</span>
          </div>
        )}
        {webrtcSessionActive && (
          <div className="incoming-call-banner" role="status">
            <QrCode size={18} />
            <span><strong>WebRTC path connected</strong><small>Reticulum packets are using the DataChannel. Approval is still required.</small></span>
            <Button variant="secondary" onClick={() => { void closeWebRTCSession().finally(() => { setWebRtcSessionActive(false); void refresh(true); }); }}>Disconnect</Button>
          </div>
        )}
        {incomingCall && !callContactId && (
          <div className="incoming-call-banner" role="status">
            <Phone size={18} />
            <span><strong>Incoming {incomingCall.media === "video" ? "video" : "audio"} call</strong><small>{snapshot.contacts.find((contact) => contact.id === incomingCall.contact_id)?.display_name ?? "An approved contact"} is calling.</small></span>
            <Button onClick={() => { setCallSummary(incomingCall); setCallContactId(incomingCall.contact_id); }}>Review</Button>
          </div>
        )}
        {callContactId && callContact && (
          <CallDialog
            contact={callContact}
            initialCall={callSummary}
            onClose={() => { setCallContactId(null); setCallSummary(undefined); }}
            onChanged={async () => { await refresh(true); }}
          />
        )}
        {selectedWorkspace ? (workspaceSearchOpen ? (
          <WorkspaceSearchView
            workspace={selectedWorkspace}
            query={workspaceSearchQuery}
            scope={workspaceSearchScope}
            page={workspaceSearchPage}
            loading={workspaceSearchLoading}
            error={workspaceSearchError}
            onBack={() => setMobileSidebarOpen(true)}
            onQuery={setWorkspaceSearchQuery}
            onScope={(value) => { setWorkspaceSearchScope(value); setWorkspaceSearchPage(null); setWorkspaceSearchError(""); }}
            onLoadMore={() => void loadWorkspaceSearch(true)}
            onOpen={openWorkspaceSearchResult}
          />
        ) : workspaceThreadRootId ? (
          <WorkspaceThreadView
            workspace={selectedWorkspace}
            page={workspaceThreadPage}
            draft={workspaceDrafts[`thread:${workspaceThreadRootId}`]?.text ?? ""}
            mentionMemberIds={eligibleWorkspaceMentionMemberIds(selectedWorkspace, selectedWorkspaceThreadAllowedMemberIds, workspaceDrafts[`thread:${workspaceThreadRootId}`]?.mentionMemberIds ?? [])}
            allowedMentionMemberIds={selectedWorkspaceThreadAllowedMemberIds}
            loading={workspaceThreadLoading}
            sending={workspaceSending}
            error={workspaceError}
            reactionTargetId={reactionTarget?.kind === "workspace" ? reactionTarget.messageId : null}
            reactionCatalogOpen={reactionTarget?.kind === "workspace" && reactionTarget.layer === "catalog"}
            reactionBusyEmoji={reactionBusy?.kind === "workspace" ? reactionBusy.emoji : null}
            reactionError={reactionTarget?.kind === "workspace" ? reactionError : ""}
            onBack={() => { setWorkspaceThreadRootId(null); setWorkspaceThreadPage(null); setWorkspaceError(""); }}
            onDraft={(value, mentionMemberIds) => workspaceThreadPage && saveWorkspaceThreadDraft(selectedWorkspace.id, workspaceThreadPage.conversation.id, workspaceThreadRootId, value, mentionMemberIds)}
            onSend={() => void sendWorkspaceThreadReply()}
            onLoadOlder={() => void loadWorkspaceThread(true)}
            onHide={(eventId) => void hideWorkspaceMessage(eventId)}
            onEdit={(eventId, text, mentionMemberIds) => void mutateWorkspaceMessage("edit_workspace_message", eventId, text, mentionMemberIds)}
            onDelete={(eventId) => void mutateWorkspaceMessage("delete_workspace_message", eventId)}
            onToggleReactionPicker={(eventId) => toggleReactionPicker("workspace", eventId)}
            onReactionCatalogOpenChange={(eventId, open) => setReactionCatalogOpen("workspace", eventId, open)}
            onCloseReactionPicker={closeReactionPicker}
            onSetReaction={(eventId, emoji, active) => void setWorkspaceReaction(eventId, emoji, active)}
          />
        ) : workspaceThreadsOpen ? (
          <WorkspaceThreads workspace={selectedWorkspace} page={workspaceThreadActivityPage} loading={workspaceThreadActivityLoading} error={workspaceError} onBack={() => setMobileSidebarOpen(true)} onLoadOlder={() => void loadWorkspaceThreads(true)} onOpenThread={openWorkspaceThread} />
        ) : workspaceMentionsOpen ? (
          <WorkspaceMentions workspace={selectedWorkspace} page={workspaceMentionPage} loading={workspaceMentionLoading} error={workspaceError} onBack={() => setMobileSidebarOpen(true)} onLoadOlder={() => void loadWorkspaceMentions(true)} onMarkRead={() => void markWorkspaceMentionsRead()} onOpenConversation={openWorkspaceMentionConversation} />
        ) : selectedWorkspaceDirect ? (
          <WorkspaceDirectConversation
            workspace={selectedWorkspace}
            direct={selectedWorkspaceDirect}
            page={workspacePage}
            draft={workspaceDrafts[selectedWorkspaceDirect.id]?.text ?? ""}
            mentionMemberIds={eligibleWorkspaceMentionMemberIds(selectedWorkspace, selectedWorkspaceDirect.participant_member_ids, workspaceDrafts[selectedWorkspaceDirect.id]?.mentionMemberIds ?? [])}
            loading={workspacePageLoading}
            sending={workspaceSending}
            error={workspaceError}
            reactionTargetId={reactionTarget?.kind === "workspace" ? reactionTarget.messageId : null}
            reactionCatalogOpen={reactionTarget?.kind === "workspace" && reactionTarget.layer === "catalog"}
            reactionBusyEmoji={reactionBusy?.kind === "workspace" ? reactionBusy.emoji : null}
            reactionError={reactionTarget?.kind === "workspace" ? reactionError : ""}
            headerMenuOpen={workspaceHeaderMenuOpen}
            onHeaderMenuOpenChange={setWorkspaceHeaderMenuOpen}
            onDraft={(value, mentionMemberIds) => { setWorkspaceError(""); saveWorkspaceDirectDraft(selectedWorkspace.id, selectedWorkspaceDirect.id, value, mentionMemberIds); }}
            onSend={() => void sendWorkspaceMessage()}
            onLoadOlder={() => void loadWorkspaceMessages(true)}
            onHideMessage={(eventId) => void hideWorkspaceMessage(eventId)}
            onOpenThread={(eventId) => openWorkspaceThread("direct", selectedWorkspaceDirect.id, eventId)}
            onEdit={(eventId, text, mentionMemberIds) => void mutateWorkspaceMessage("edit_workspace_message", eventId, text, mentionMemberIds)}
            onDelete={(eventId) => void mutateWorkspaceMessage("delete_workspace_message", eventId)}
            onToggleReactionPicker={(eventId) => toggleReactionPicker("workspace", eventId)}
            onReactionCatalogOpenChange={(eventId, open) => setReactionCatalogOpen("workspace", eventId, open)}
            onCloseReactionPicker={closeReactionPicker}
            onSetReaction={(eventId, emoji, active) => void setWorkspaceReaction(eventId, emoji, active)}
            onBack={() => setMobileSidebarOpen(true)}
            onHideConversation={() => void hideWorkspaceDirect()}
            onPeople={() => setWorkspacePeopleOpen(true)}
          />
        ) : selectedWorkspaceChannel ? (
          <WorkspaceConversation
            workspace={selectedWorkspace}
            channel={selectedWorkspaceChannel}
            page={workspacePage}
            draft={workspaceDrafts[selectedWorkspaceChannel.id]?.text ?? ""}
            mentionMemberIds={eligibleWorkspaceMentionMemberIds(selectedWorkspace, selectedWorkspaceChannel.visibility === "private" ? selectedWorkspaceChannel.member_ids : selectedWorkspace.members.filter((member) => member.status === "active").map((member) => member.id), workspaceDrafts[selectedWorkspaceChannel.id]?.mentionMemberIds ?? [])}
            loading={workspacePageLoading}
            sending={workspaceSending}
            error={workspaceError}
            reactionTargetId={reactionTarget?.kind === "workspace" ? reactionTarget.messageId : null}
            reactionCatalogOpen={reactionTarget?.kind === "workspace" && reactionTarget.layer === "catalog"}
            reactionBusyEmoji={reactionBusy?.kind === "workspace" ? reactionBusy.emoji : null}
            reactionError={reactionTarget?.kind === "workspace" ? reactionError : ""}
            headerMenuOpen={workspaceHeaderMenuOpen}
            onHeaderMenuOpenChange={setWorkspaceHeaderMenuOpen}
            onDraft={(value, mentionMemberIds) => { setWorkspaceError(""); saveWorkspaceDraft(selectedWorkspace.id, selectedWorkspaceChannel.id, value, mentionMemberIds); }}
            onSend={() => void sendWorkspaceMessage()}
            onLoadOlder={() => void loadWorkspaceMessages(true)}
            onHide={(eventId) => void hideWorkspaceMessage(eventId)}
            onOpenThread={(eventId) => openWorkspaceThread("channel", selectedWorkspaceChannel.id, eventId)}
            onEdit={(eventId, text, mentionMemberIds) => void mutateWorkspaceMessage("edit_workspace_message", eventId, text, mentionMemberIds)}
            onDelete={(eventId) => void mutateWorkspaceMessage("delete_workspace_message", eventId)}
            onToggleReactionPicker={(eventId) => toggleReactionPicker("workspace", eventId)}
            onReactionCatalogOpenChange={(eventId, open) => setReactionCatalogOpen("workspace", eventId, open)}
            onCloseReactionPicker={closeReactionPicker}
            onSetReaction={(eventId, emoji, active) => void setWorkspaceReaction(eventId, emoji, active)}
            onBack={() => setMobileSidebarOpen(true)}
            onPeople={() => setWorkspacePeopleOpen(true)}
            onSettings={() => setWorkspaceSettingsOpen(true)}
            onInvite={() => setInviteWorkspaceOpen(true)}
            onManage={() => setWorkspaceManageChannelOpen(true)}
            onToggleMentionMute={() => void runWorkspaceChannelAction("set_workspace_channel_mentions_muted", { channel_id: selectedWorkspaceChannel.id, muted: !selectedWorkspaceChannel.mentions_muted })}
          />
        ) : (
          <section className="empty-state workspace-waiting">
            <button className="icon-button mobile-only workspace-empty-back" type="button" onClick={() => setMobileSidebarOpen(true)} aria-label={`Back to ${selectedWorkspace.name}`}><ArrowLeft size={21} /></button>
            <div className="empty-state__icon"><Building2 size={31} /></div>
            <h1>{selectedWorkspace.name}</h1>
            {selectedWorkspaceJoinStatus ? (
              <div className="workspace-join-status">
                <strong>{selectedWorkspaceJoinStatus.headline}</strong>
                <p>{selectedWorkspaceJoinStatus.detail}</p>
                {!selectedWorkspaceJoinStatus.terminal && <small>#general appears only after the owner receives, validates, and approves the request.</small>}
              </div>
            ) : <p>{workspaceStateLabel(selectedWorkspace)}. Keep Mesh Chat open so signed membership and channel controls can arrive.</p>}
            {selectedWorkspaceJoinStatus?.terminal
              ? <Button variant="secondary" onClick={() => setWorkspaceSettingsOpen(true)}><Settings size={18} /> Open Workspace settings</Button>
              : <Button variant="secondary" onClick={() => setWorkspacePeopleOpen(true)}><Users size={18} /> People</Button>}
          </section>
        )) : selectedContact ? (
          <Conversation
            contact={selectedContact}
            messages={messages}
            draft={drafts[selectedContact.id] ?? ""}
            sendError={sendError}
            sending={directSendBusy}
            detailsOpen={conversationDetailsOpen}
            reactionTargetId={reactionTarget?.kind === "direct" ? reactionTarget.messageId : null}
            reactionCatalogOpen={reactionTarget?.kind === "direct" && reactionTarget.layer === "catalog"}
            reactionBusyEmoji={reactionBusy?.kind === "direct" ? reactionBusy.emoji : null}
            reactionError={reactionTarget?.kind === "direct" ? reactionError : ""}
            onDetailsOpenChange={setConversationDetailsOpen}
            onToggleReactionPicker={(messageId) => toggleReactionPicker("direct", messageId)}
            onReactionCatalogOpenChange={(messageId, open) => setReactionCatalogOpen("direct", messageId, open)}
            onCloseReactionPicker={closeReactionPicker}
            onSetReaction={(messageId, emoji, active) => void setMessageReaction("direct", messageId, emoji, active)}
            onDraft={(value) => { setSendError(""); saveDraft(selectedContact.id, value); }}
            onSend={() => void send()}
            onHelp={() => void connectionHelp()}
            onBack={() => selectConversation(null)}
            onDelete={() => { setDeleteError(""); setDeleteTarget({ kind: "contact", id: selectedContact.id }); }}
            onCall={() => { setCallSummary(undefined); setCallContactId(selectedContact.id); }}
          />
        ) : selectedGroup && snapshot.profile ? (
          <GroupConversation
            group={selectedGroup}
            selfDestination={snapshot.profile.destination_hash}
            messages={selectedGroupMessages}
            draft={groupDrafts[selectedGroup.id] ?? ""}
            sendError={sendError}
            sending={groupSendBusy}
            actionBusy={groupActionBusy}
            actionError={groupActionError}
            detailsOpen={conversationDetailsOpen}
            reactionTargetId={reactionTarget?.kind === "group" ? reactionTarget.messageId : null}
            reactionCatalogOpen={reactionTarget?.kind === "group" && reactionTarget.layer === "catalog"}
            reactionBusyEmoji={reactionBusy?.kind === "group" ? reactionBusy.emoji : null}
            reactionError={reactionTarget?.kind === "group" ? reactionError : ""}
            onDetailsOpenChange={setConversationDetailsOpen}
            onToggleReactionPicker={(messageId) => toggleReactionPicker("group", messageId)}
            onReactionCatalogOpenChange={(messageId, open) => setReactionCatalogOpen("group", messageId, open)}
            onCloseReactionPicker={closeReactionPicker}
            onSetReaction={(messageId, emoji, active) => void setMessageReaction("group", messageId, emoji, active)}
            onDraft={(value) => { setSendError(""); saveGroupDraft(selectedGroup.id, value); }}
            onSend={() => void sendGroupMessage()}
            onBack={() => selectConversation(null)}
            onDelete={() => { setDeleteError(""); setDeleteTarget({ kind: "group", id: selectedGroup.id }); }}
            onRemove={(destinationHash) => void runGroupAction("remove_group_member", { group_id: selectedGroup.id, destination_hash: destinationHash })}
            onRetryInvite={(destinationHash) => void runGroupAction("retry_group_invitation", { group_id: selectedGroup.id, destination_hash: destinationHash })}
            onLeave={() => void runGroupAction("leave_group", { group_id: selectedGroup.id }, true)}
            onCloseGroup={() => void runGroupAction("close_group", { group_id: selectedGroup.id }, true)}
          />
        ) : (
          <section className="empty-state"><div className="empty-state__icon"><MessageCircleMore size={32} /></div><h1>Your private conversations</h1><p>Start a private chat or a small group. There’s no account or central chat server.</p><div className="empty-state__actions"><Button onClick={() => setNewChat(true)}><Plus size={18} /> New chat</Button><Button variant="secondary" onClick={() => setNewGroup(true)}><Users size={18} /> New group</Button></div></section>
        )}
      </div>
      {createWorkspaceOpen && <CreateWorkspaceDialog onClose={() => setCreateWorkspaceOpen(false)} onCreated={async (workspace) => { await refresh(true); setActiveSpaceId(workspace.id); setCreateWorkspaceOpen(false); }} />}
      {joinWorkspaceOpen && <JoinWorkspaceDialog resumeWorkspaceId={resumeWorkspaceId} workspaces={workspaces} initialValue={joinWorkspaceValue || (isWorkspaceInvitationValue(initialInvitation) ? initialInvitation : "")} onClose={() => { setJoinWorkspaceOpen(false); setResumeWorkspaceId(undefined); setJoinWorkspaceValue(""); onInvitationHandled(); }} onJoined={async (workspace) => { await refresh(true); setActiveSpaceId(workspace.id); setJoinWorkspaceOpen(false); setResumeWorkspaceId(undefined); setJoinWorkspaceValue(""); onInvitationHandled(); }} />}
      {selectedWorkspace && workspaceBrowseOpen && <BrowseWorkspaceChannelsDialog workspace={selectedWorkspace} channels={selectedWorkspaceChannels.filter((channel) => channel.visibility === "public")} busy={workspaceActionBusy} error={workspaceActionError} onClose={() => setWorkspaceBrowseOpen(false)} onOpen={(channelId) => { setWorkspaceMentionsOpen(false); setWorkspaceThreadsOpen(false); setWorkspaceThreadRootId(null); setWorkspaceSelectedChannelId(channelId); setWorkspaceSelectedDirectId(null); setWorkspaceBrowseOpen(false); setMobileSidebarOpen(false); }} onSubscribe={(channelId, subscribed) => void runWorkspaceChannelAction("set_workspace_channel_subscription", { channel_id: channelId, subscribed })} onSync={() => void runWorkspaceChannelAction("sync_workspace_channels")} onCreate={() => { setWorkspaceBrowseOpen(false); setWorkspaceCreateChannelOpen(true); }} />}
      {selectedWorkspace && workspaceCreateChannelOpen && <CreateWorkspaceChannelDialog workspace={selectedWorkspace} busy={workspaceActionBusy} error={workspaceActionError} onClose={() => setWorkspaceCreateChannelOpen(false)} onCreate={(name, topic, visibility, memberIds) => void runWorkspaceChannelAction("create_workspace_channel", { name, topic, visibility, member_ids: memberIds })} />}
      {selectedWorkspace && selectedWorkspaceChannel && workspaceManageChannelOpen && <ManageWorkspaceChannelDialog workspace={selectedWorkspace} channel={selectedWorkspaceChannel} transfers={workspaceChannelTransfers.filter((item) => item.workspace_id === selectedWorkspace.id)} busy={workspaceActionBusy} error={workspaceActionError} onClose={() => setWorkspaceManageChannelOpen(false)} onUpdate={(name, topic, archived) => void runWorkspaceChannelAction("update_workspace_channel", { channel_id: selectedWorkspaceChannel.id, name, topic, archived })} onMembers={(memberIds) => void runWorkspaceChannelAction("update_workspace_private_channel_members", { channel_id: selectedWorkspaceChannel.id, member_ids: memberIds })} onLeave={() => void runWorkspaceChannelAction("leave_workspace_private_channel", { channel_id: selectedWorkspaceChannel.id })} onOfferTransfer={(successorMemberId) => void runWorkspaceChannelAction("offer_workspace_channel_transfer", { channel_id: selectedWorkspaceChannel.id, successor_member_id: successorMemberId })} onAcceptTransfer={(transferId) => void runWorkspaceChannelAction("accept_workspace_channel_transfer", { transfer_id: transferId })} onRecover={() => void runWorkspaceChannelAction("recover_workspace_channel", { channel_id: selectedWorkspaceChannel.id })} />}
      {selectedWorkspace && inviteWorkspaceOpen && <WorkspaceInviteDialog workspace={selectedWorkspace} existingInvitations={workspaceInvitations.filter((invitation) => invitation.workspace_id === selectedWorkspace.id)} remoteProfiles={snapshot.remote_profiles ?? []} onClose={() => setInviteWorkspaceOpen(false)} />}
      {selectedWorkspace && workspacePeopleOpen && <WorkspacePeopleDialog
        workspace={selectedWorkspace}
        requests={workspaceDisplayNameRequests.filter((request) => request.workspace_id === selectedWorkspace.id)}
        adminRequests={workspaceAdminRequests.filter((request) => request.workspace_id === selectedWorkspace.id)}
        busy={workspaceActionBusy}
        error={workspaceActionError}
        onClose={() => setWorkspacePeopleOpen(false)}
        onRequestName={(displayName) => void runWorkspaceAdministration("request_workspace_display_name", { display_name: displayName })}
        onDecideName={(requestId, approve) => void runWorkspaceAdministration("decide_workspace_display_name", { request_id: requestId, approve })}
        onRemove={(memberId) => void runWorkspaceAdministration("remove_workspace_member", { member_id: memberId })}
        onChangeRole={(memberId, role) => void runWorkspaceAdministration("change_workspace_role", { member_id: memberId, role })}
        onInvitationPolicy={(invitationRequests) => void runWorkspaceAdministration("update_workspace_policies", { channel_creation: selectedWorkspace.policies.channel_creation, posting: selectedWorkspace.policies.posting, invitation_requests: invitationRequests })}
        onSubmitAdminRequest={(requestKind, targetMemberId, requestedRole) => void runWorkspaceAdministration("submit_workspace_admin_request", { request_kind: requestKind, target_member_id: targetMemberId, requested_role: requestedRole, note: "" })}
        onDecideAdminRequest={(requestId, approve) => void runWorkspaceAdministration(approve ? "approve_workspace_admin_request" : "decline_workspace_admin_request", { request_id: requestId })}
        onCancelAdminRequest={(requestId) => void runWorkspaceAdministration("cancel_workspace_admin_request", { request_id: requestId })}
        onDismissAdminRequest={(requestId) => void runWorkspaceAdministration("dismiss_workspace_admin_request", { request_id: requestId })}
        onMessage={(memberId) => void openWorkspaceDirect(memberId)}
      />}
      {selectedWorkspace && workspaceAuthorityOpen && <WorkspaceAuthorityDialog workspace={selectedWorkspace} transitions={workspaceAuthorityTransitions.filter((item) => item.workspace_id === selectedWorkspace.id)} busy={workspaceActionBusy} error={workspaceActionError} onClose={() => setWorkspaceAuthorityOpen(false)} onOffer={(transitionKind, successorMemberId, successorDeviceId, outgoingOwnerRole) => void runWorkspaceAdministration("offer_workspace_authority_transition", { transition_kind: transitionKind, successor_member_id: successorMemberId, successor_device_id: successorDeviceId, outgoing_owner_role: outgoingOwnerRole })} onAccept={(transitionId) => void runWorkspaceAdministration("accept_workspace_authority_transition", { transition_id: transitionId })} onFinalize={(transitionId) => void runWorkspaceAdministration("finalize_workspace_authority_transition", { transition_id: transitionId })} onReportLoss={() => void runWorkspaceAdministration("report_workspace_authority_loss", {})} />}
      {selectedWorkspace && workspaceDevicesOpen && <WorkspaceDevicesDialog workspace={selectedWorkspace} transitions={workspaceDeviceTransitions.filter((item) => item.workspace_id === selectedWorkspace.id)} busy={workspaceActionBusy} error={workspaceActionError} onClose={() => setWorkspaceDevicesOpen(false)} onCreate={createWorkspaceDeviceLink} onDecide={(transition, approve) => void runWorkspaceAdministration(transition.transition_kind === "link" ? (approve ? "approve_workspace_device_link" : "decline_workspace_device_link") : (approve ? "approve_workspace_device_removal" : "decline_workspace_device_removal"), transition.transition_kind === "link" ? { link_id: transition.id } : { removal_id: transition.id })} onRemove={(deviceId) => void runWorkspaceAdministration("request_workspace_device_removal", { target_device_id: deviceId })} onReadSync={(enabled) => void runWorkspaceAdministration("set_workspace_read_hint_sync", { enabled })} />}
      {selectedWorkspace && workspaceSettingsOpen && <WorkspaceSettingsDialog workspace={selectedWorkspace} conversation={selectedWorkspaceConversation} networkSettings={snapshot.settings} busy={workspaceActionBusy} error={workspaceActionError} onClose={() => setWorkspaceSettingsOpen(false)} onUpdateMetadata={(name, description) => void runWorkspaceAdministration("update_workspace_metadata", { name, description })} onUpdatePolicies={(channelCreation, posting) => void runWorkspaceAdministration("update_workspace_policies", { channel_creation: channelCreation, posting })} onSetNotificationPreference={(conversationId, mode) => void runWorkspaceNotificationPreference(conversationId, mode)} onApprovePropagationNode={(node) => void approveWorkspacePropagationNode(node)} onCloseWorkspace={() => void runWorkspaceLifecycle("close_workspace")} onLeave={() => void runWorkspaceLifecycle("leave_workspace")} onRemove={(confirmation) => void runWorkspaceLifecycle("remove_workspace_data", confirmation)} />}
      {selectedWorkspace && workspaceRetentionOpen && <WorkspaceRetentionDialog workspace={selectedWorkspace} conversationId={selectedWorkspaceConversation?.id} conversationName={selectedWorkspaceDirect?.peer_display_name ?? selectedWorkspaceChannel?.display_name ?? selectedWorkspaceChannel?.name} busy={workspaceActionBusy} error={workspaceActionError} onClose={() => setWorkspaceRetentionOpen(false)} onUpdate={(retentionDays) => void runWorkspaceAdministration("update_workspace_retention", { retention_days: retentionDays })} onPrune={pruneWorkspaceHistory} />}
      {webrtcOnboardingOpen && <WebRTCOnboardingDialog onClose={() => setWebRtcOnboardingOpen(false)} onConnected={() => setWebRtcSessionActive(true)} onChanged={async () => { await refresh(true); }} />}
      {newChat && <div className={hasForegroundRequest ? "dialog-suspended" : ""} aria-hidden={hasForegroundRequest ? true : undefined}><NewChatDialog initialInvitation={initialInvitation} remoteProfiles={snapshot.remote_profiles ?? []} onClose={() => { setNewChat(false); onInvitationHandled(); }} onChanged={async () => { await refresh(true); }} onWorkspaceInvitation={(value) => { setNewChat(false); setJoinWorkspaceValue(value); setJoinWorkspaceOpen(true); }} /></div>}
      {newGroup && <div className={hasForegroundRequest ? "dialog-suspended" : ""} aria-hidden={hasForegroundRequest ? true : undefined}><CreateGroupDialog contacts={snapshot.contacts} onClose={() => setNewGroup(false)} onCreated={async (group) => { await refresh(true); selectConversation({ kind: "group", id: group.id }); setNewGroup(false); }} /></div>}
      {contactsOpen && <div className={hasForegroundRequest ? "dialog-suspended" : ""} aria-hidden={hasForegroundRequest ? true : undefined}><ContactsDialog contacts={snapshot.contacts.filter((contact) => contact.trust !== "pending_request")} onClose={() => setContactsOpen(false)} onChanged={async () => { await refresh(true); }} onOpenConversation={async (contact) => { const hidden = hiddenConversationKeys.has(`direct:${contact.id}`); setContactsOpen(false); await restoreAndSelect({ kind: "contact", id: contact.id }, hidden); }} onDeleted={async (contactId) => { if (selection?.kind === "contact" && selection.id === contactId) setSelection(null); setDrafts((current) => { const next = { ...current }; delete next[contactId]; return next; }); setLocallySavedMessages((current) => Object.fromEntries(Object.entries(current).filter(([, message]) => message.contact_id !== contactId))); await refresh(true); }} /></div>}
      {settings && <div className={hasForegroundRequest ? "dialog-suspended" : ""} aria-hidden={hasForegroundRequest ? true : undefined}><SettingsDialog snapshot={snapshot} theme={theme} onThemeChange={onThemeChange} onClose={() => setSettings(false)} onSaved={async () => { await refresh(true); }} /></div>}
      {notificationTarget && !notificationTarget.available && <Dialog title="Notification unavailable" onClose={onNotificationHandled}><div className="form-stack"><p>{notificationTarget.message ?? "This notification is no longer available or authorized on this device."}</p><p className="muted">Mesh Chat did not open stale content or change any read state.</p><Button onClick={onNotificationHandled}>Done</Button></div></Dialog>}
      {deleteTarget && <div className={hasForegroundRequest ? "dialog-suspended" : ""} aria-hidden={hasForegroundRequest ? true : undefined}><DeleteConversationDialog kind={deleteTarget.kind === "contact" ? "direct" : "group"} name={deleteTargetName} busy={deleteBusy} error={deleteError} onCancel={() => { if (!deleteBusy) { setDeleteError(""); setDeleteTarget(null); } }} onConfirm={() => void deleteConversation()} /></div>}
      {help && <div className={hasForegroundRequest ? "dialog-suspended" : ""} aria-hidden={hasForegroundRequest ? true : undefined}><Dialog title="Connection help" onClose={() => setHelp(null)}><div className="help-content">{help.code === "service_unavailable" ? <><WifiOff size={28} /><h3>Networking is unavailable</h3><p>Connect this device to the same local network as {selectedContact?.display_name}, make sure local-network access is allowed, then reopen Mesh Chat.</p></> : help.code === "waiting_for_keys" ? <><WifiOff size={28} /><h3>Trying to find {selectedContact?.display_name}</h3><p>Keep Mesh Chat open on both devices and connect them to the same local network. We’ll continue trying automatically.</p></> : help.code === "no_route" ? <><WifiOff size={28} /><h3>We can’t reach them yet</h3><p>Your message is saved. Try the same local network, check local-network permission, or request a fresh invitation with a usable connection hint.</p></> : <><Check size={28} /><h3>The secure path is ready</h3><p>Mesh Chat is continuing the connection automatically.</p></>}<Button onClick={() => setHelp(null)}>Done</Button></div></Dialog></div>}
      {incomingRequest && <IncomingRequestDialog contact={incomingRequest} busy={requestBusy === incomingRequest.id} error={requestError} onAccept={() => void respondToRequest(incomingRequest, true)} onDecline={() => void respondToRequest(incomingRequest, false)} onClose={() => { setRequestError(""); setDismissedRequests((current) => [...new Set([...current, incomingRequest.id])]); }} />}
      {foregroundGroupInvitation && <GroupInvitationDialog invitation={foregroundGroupInvitation} busy={groupInvitationBusy === foregroundGroupInvitation.id} error={groupInvitationError} onAccept={() => void respondToGroupInvitation(foregroundGroupInvitation, true)} onDecline={() => void respondToGroupInvitation(foregroundGroupInvitation, false)} onClose={() => { setGroupInvitationError(""); setDismissedGroupInvitations((current) => [...new Set([...current, foregroundGroupInvitation.id])]); }} />}
      {foregroundWorkspaceJoinRequest && foregroundWorkspaceJoinWorkspace && <WorkspaceJoinRequestDialog request={foregroundWorkspaceJoinRequest} workspace={foregroundWorkspaceJoinWorkspace} busy={workspaceActionBusy} error={workspaceJoinRequestError} onApprove={() => void respondToWorkspaceJoin(foregroundWorkspaceJoinRequest, true)} onDecline={() => void respondToWorkspaceJoin(foregroundWorkspaceJoinRequest, false)} onClose={() => { setWorkspaceJoinRequestError(""); setDismissedWorkspaceJoinRequests((current) => [...new Set([...current, foregroundWorkspaceJoinRequest.id])]); }} />}
    </main>
  );
}

export default function App() {
  const [theme, setTheme] = useState<Theme>(initialTheme);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [initialInvitation, setInitialInvitation] = useState("");
  const [workspaceChannelInvalidation, setWorkspaceChannelInvalidation] = useState<ServiceEvent | null>(null);
  const [notificationTarget, setNotificationTarget] = useState<NotificationOpenTarget | null>(null);
  const [fatal, setFatal] = useState("");
  const [locked, setLocked] = useState(false);
  const refreshInFlight = useRef<Promise<Snapshot> | null>(null);
  const workspaceRefreshInFlight = useRef<Promise<WorkspaceSnapshot> | null>(null);
  const mobileReconcileInFlight = useRef<Promise<void> | null>(null);
  useLayoutEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
    document.querySelector<HTMLMetaElement>('meta[name="theme-color"]')?.setAttribute("content", theme === "dark" ? "#0f1714" : "#f7f4eb");
    try { window.localStorage.setItem(THEME_STORAGE_KEY, theme); } catch { /* The theme still applies for this session. */ }
    try { void setNativeTheme(theme).catch(() => undefined); } catch { /* Browser previews do not expose the native bridge. */ }
  }, [theme]);
  const refresh = useCallback(function requestSnapshot(afterCurrent = false): Promise<Snapshot> {
    if (workspaceRefreshInFlight.current) {
      return workspaceRefreshInFlight.current.then(
        () => requestSnapshot(false),
        () => requestSnapshot(false),
      );
    }
    if (refreshInFlight.current) {
      const current = refreshInFlight.current;
      if (!afterCurrent) return current;
      // Mutations and service events must observe a snapshot which begins
      // after any older request settles. Concurrent trailing requests still
      // coalesce because the first continuation installs the next in-flight
      // request before the other continuations run.
      return current.then(
        () => requestSnapshot(false),
        () => requestSnapshot(false),
      );
    }
    const request = serviceCommand<Snapshot>("snapshot").then((latest) => {
      setSnapshot(latest);
      return latest;
    });
    refreshInFlight.current = request;
    const clear = () => { if (refreshInFlight.current === request) refreshInFlight.current = null; };
    void request.then(clear, clear);
    return request;
  }, []);
  const refreshWorkspace = useCallback(function requestWorkspaceSnapshot(afterCurrent = false): Promise<WorkspaceSnapshot> {
    if (refreshInFlight.current) {
      return refreshInFlight.current.then(
        () => requestWorkspaceSnapshot(false),
        () => requestWorkspaceSnapshot(false),
      );
    }
    if (workspaceRefreshInFlight.current) {
      const current = workspaceRefreshInFlight.current;
      if (!afterCurrent) return current;
      return current.then(
        () => requestWorkspaceSnapshot(false),
        () => requestWorkspaceSnapshot(false),
      );
    }
    const request = serviceCommand<WorkspaceSnapshot>("workspace_snapshot").then((latest) => {
      setSnapshot((current) => current ? { ...current, ...latest } : current);
      return latest;
    });
    workspaceRefreshInFlight.current = request;
    const clear = () => { if (workspaceRefreshInFlight.current === request) workspaceRefreshInFlight.current = null; };
    void request.then(clear, clear);
    return request;
  }, []);
  useEffect(() => {
    let active = true;
    const cleanups: Array<() => void> = [];
    const keepCleanup = (cleanup: () => void) => active ? cleanups.push(cleanup) : cleanup();
    void (async () => {
      try {
        keepCleanup(await onServiceEvent((event) => {
          if (event.event === "workspace_changed" && ["message", "message_visibility", "delivery"].includes(event.resource_kind ?? "")) {
            setWorkspaceChannelInvalidation(event);
          }
          const update = event.event === "workspace_changed"
            ? refreshWorkspace(true)
            : refresh(true);
          void update.catch(() => undefined);
        }));
      } catch {
        // The focus and visible-window refresh below still self-heal a missed listener.
      }
      if (!active) return;
      try {
        const result = await initializeService();
        if (active) setSnapshot(result);
      } catch (reason) {
        if (active) setFatal(errorMessage(reason));
      }
    })();
    void onInvitation((value) => setInitialInvitation(value)).then(keepCleanup).catch(() => undefined);
    void onNotificationOpen(async (notificationId) => {
      try {
        const target = await serviceCommand<NotificationOpenTarget>("open_notification_target", { notification_id: notificationId });
        if (active) {
          await refresh(true);
          if (active) setNotificationTarget({ ...target });
        }
      } catch (reason) {
        if (active) setNotificationTarget({ available: false, reason: "unavailable", message: errorMessage(reason) });
      }
    }).then(keepCleanup).catch(() => undefined);
    return () => { active = false; cleanups.forEach((cleanup) => cleanup()); };
  }, [refresh, refreshWorkspace]);
  useEffect(() => {
    let active = true;
    let timer: number | undefined;
    let mobile = false;
    const reconcileMobile = () => {
      if (mobileReconcileInFlight.current) return mobileReconcileInFlight.current;
      const request = serviceCommand("reconcile_mobile_lifecycle")
        .then(() => refresh(true))
        .catch(() => refresh())
        .then(() => undefined);
      mobileReconcileInFlight.current = request;
      const clear = () => {
        if (mobileReconcileInFlight.current === request) mobileReconcileInFlight.current = null;
      };
      void request.then(clear, clear);
      return request;
    };
    const refreshVisible = () => {
      if (!active || document.visibilityState !== "visible") return;
      if (mobile) {
        void reconcileMobile().catch(() => undefined);
      } else {
        void refresh().catch(() => undefined);
      }
    };
    const onVisibility = () => refreshVisible();
    window.addEventListener("focus", refreshVisible);
    document.addEventListener("visibilitychange", onVisibility);
    void runtimePlatform().then((platform) => {
      if (!active) return;
      mobile = platform !== "desktop";
      if (!mobile) timer = window.setInterval(refreshVisible, 3000);
    }).catch(() => undefined);
    return () => {
      active = false;
      if (timer !== undefined) window.clearInterval(timer);
      window.removeEventListener("focus", refreshVisible);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [refresh]);
  if (locked) return <main className="fatal-screen"><LockKeyhole size={36} /><h1>Mesh Chat is locked</h1><p>The messaging service is stopped and its keys have been released.</p><Button onClick={async () => { setSnapshot(await initializeService()); setLocked(false); }}>Unlock</Button></main>;
  if (fatal) return <main className="fatal-screen"><LockKeyhole size={36} /><h1>Mesh Chat stopped safely</h1><p>{fatal}</p><p className="muted">No plaintext fallback was used.</p></main>;
  if (!snapshot) return <main className="loading-screen"><Brand /><span className="spinner" /><p>Opening your private profile…</p></main>;
  if (!snapshot.profile) {
    return (
      <Onboarding
        initialInvitation={initialInvitation}
        onReady={(ready, pendingInvitation) => {
          setInitialInvitation(pendingInvitation ?? "");
          setSnapshot(ready);
        }}
      />
    );
  }
  return <Messenger snapshot={snapshot} theme={theme} onThemeChange={setTheme} refresh={refresh} workspaceChannelInvalidation={workspaceChannelInvalidation} notificationTarget={notificationTarget} onNotificationHandled={() => setNotificationTarget(null)} initialInvitation={initialInvitation} onInvitationHandled={() => setInitialInvitation("")} onLock={async () => { await lockService(); setSnapshot(null); setLocked(true); }} />;
}

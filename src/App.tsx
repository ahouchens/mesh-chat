import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  BookUser,
  Building2,
  ArrowLeft,
  Ban,
  Check,
  ChevronRight,
  CircleHelp,
  Copy,
  FileUp,
  Hash,
  EyeOff,
  LogOut,
  LockKeyhole,
  Megaphone,
  Menu,
  MessageCircleMore,
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
  Trash2,
  UserMinus,
  UserRoundPlus,
  Users,
  WifiOff,
  X,
} from "lucide-react";
import { QRCodeSVG } from "qrcode.react";
import {
  initializeService,
  lockService,
  onInvitation,
  onMobileBackButton,
  onServiceEvent,
  runtimePlatform,
  serviceCommand,
} from "./api";
import type { ServiceEvent } from "./api";
import { contactConnectionLabel, deliveryLabel } from "./status";
import { EmojiGlyph } from "./EmojiGlyph";
import { getEmojiFallbackName } from "./emoji-artwork";
import {
  QUICK_REACTION_OPTIONS,
  REACTION_CATEGORIES,
  REACTION_OPTION_BY_EMOJI,
  validateSingleEmoji,
} from "./reactions";
import packageInfo from "../package.json";
import type {
  ChatMessage,
  Contact,
  Group,
  GroupInvitation,
  GroupMember,
  GroupMessage,
  GroupPostingPolicy,
  InvitationFormats,
  InvitationPreview,
  MessageReaction,
  NetworkSettings,
  Snapshot,
  Workspace,
  WorkspaceChannel,
  WorkspaceChannelTransfer,
  WorkspaceDisplayNameRequest,
  WorkspaceDirect,
  WorkspaceInvitation,
  WorkspaceInvitationFormats,
  WorkspaceInvitationPreview,
  WorkspaceMessage,
  WorkspaceMessagePage,
  WorkspaceSnapshot,
} from "./types";
import "./styles.css";

type OnboardingMode = "home" | "start" | "join";

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
  if (raw.includes("identity_mismatch")) {
    return "This invitation’s identity check failed.";
  }
  if (raw.includes("invitation_expired")) {
    return "This invitation has expired. Ask the sender to create a new one.";
  }
  if (raw.includes("invitation_invalid")) {
    return "This does not appear to be a complete Mesh Chat invitation. Copy it again, including the MESHCHAT1: prefix, or scan its QR code.";
  }
  if (raw.includes("contact_not_approved")) {
    return "This contact is not approved for that action.";
  }
  if (raw.includes("contact_in_use")) {
    return "Remove this contact from any pending group invitations before deleting them.";
  }
  if (raw.includes("invalid_request")) {
    return "That information could not be validated.";
  }
  return "Something went wrong. Your saved messages were not discarded.";
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

function InvitationShare({ formats }: { formats: InvitationFormats }) {
  const [feedback, setFeedback] = useState("");

  const copyInvite = async () => {
    try {
      await navigator.clipboard.writeText(formats.text);
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
    anchor.download = "mesh-chat-invite.meshchat";
    anchor.click();
    URL.revokeObjectURL(anchor.href);
    setFeedback("Invitation file saved.");
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
      <p id="invite-expiry-note" className="invite-expiry">
        Expires <time dateTime={new Date(formats.expires_at * 1000).toISOString()}>{formatExpiry(formats.expires_at)}</time>
      </p>
      <div className="invite-actions">
        <Button onClick={() => void copyInvite()}><Copy size={17} /> Copy details</Button>
        <Button variant="secondary" onClick={() => void shareInvite()}><Share2 size={17} /> Share invite</Button>
        <Button variant="ghost" onClick={saveInvite}><FileUp size={17} /> Save invite file</Button>
      </div>
      <p className="invite-feedback" aria-live="polite">{feedback}</p>
      <div className="invite-qr">
        <div className="qr-frame qr-frame--small" aria-label="Invitation QR code">
          <QRCodeSVG value={formats.link} size={164} bgColor="#f7f4eb" fgColor="#10251e" />
        </div>
        <div>
          <strong>Or scan this QR code</strong>
          <span>Open Mesh Chat on the other device and choose Join a chat.</span>
        </div>
      </div>
    </section>
  );
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
      if (event.key !== "Escape" || event.defaultPrevented) return;
      const currentDialog = dialogRef.current;
      if (!currentDialog || currentDialog.closest('[aria-hidden="true"]')) return;
      const visibleDialogs = [...document.querySelectorAll<HTMLElement>('[role="dialog"][aria-modal="true"]')]
        .filter((dialog) => !dialog.closest('[aria-hidden="true"]'));
      if (visibleDialogs.at(-1) !== currentDialog) return;
      event.preventDefault();
      onCloseRef.current();
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

function Onboarding({
  initialInvitation,
  onReady,
}: {
  initialInvitation: string;
  onReady: (snapshot: Snapshot) => void;
}) {
  const [mode, setMode] = useState<OnboardingMode>(initialInvitation ? "join" : "home");
  const [name, setName] = useState("");
  const [invitation, setInvitation] = useState(initialInvitation);
  const [preview, setPreview] = useState<InvitationPreview | null>(null);
  const [formats, setFormats] = useState<InvitationFormats | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!initialInvitation) return;
    setInvitation(initialInvitation);
    setMode("join");
    setPreview(null);
    void serviceCommand<InvitationPreview>("preview_invitation", {
      invitation: initialInvitation,
    }).then(setPreview).catch((reason) => setError(errorMessage(reason)));
  }, [initialInvitation]);

  const createProfile = async () => {
    setBusy(true);
    setError("");
    try {
      await serviceCommand("create_profile", { display_name: name });
      if (mode === "join") {
        await serviceCommand("accept_invitation", { invitation });
        onReady(await serviceCommand<Snapshot>("snapshot"));
      } else {
        const created = await serviceCommand<InvitationFormats>("create_invitation");
        setFormats(created);
      }
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const previewInvite = async () => {
    setBusy(true);
    setError("");
    try {
      setPreview(
        await serviceCommand<InvitationPreview>("preview_invitation", { invitation }),
      );
    } catch (reason) {
      setPreview(null);
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
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
          <button className="back-link" onClick={() => { setMode("home"); setPreview(null); setError(""); }}>
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
            <p className="eyebrow">Start a chat</p>
            <h1>What should people call you?</h1>
            <p className="muted">This name is shared only in invitations and connection requests.</p>
            <label className="field">
              <span>Display name</span>
              <input autoFocus value={name} onChange={(event) => setName(event.target.value)} maxLength={64} autoComplete="name" />
            </label>
            {error && <p className="form-error" role="alert">{error}</p>}
            <Button type="submit" disabled={!name.trim() || busy}>{busy ? "Creating…" : "Create my invite"}</Button>
          </form>
        )}

        {mode === "join" && !preview && (
          <form onSubmit={(event) => { event.preventDefault(); void previewInvite(); }}>
            <p className="eyebrow">Join a chat</p>
            <h1>Open an invitation</h1>
            <p className="muted">Paste the invitation you received. It never looks anything up online.</p>
            <label className="field">
              <span>Invitation</span>
              <textarea autoFocus autoCapitalize="off" autoCorrect="off" spellCheck={false} rows={5} value={invitation} onChange={(event) => setInvitation(event.target.value)} placeholder="Paste a Mesh Chat invitation" />
            </label>
            <ImportButtons onValue={setInvitation} />
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
            {error && <p className="form-error" role="alert">{error}</p>}
            <Button type="submit" disabled={!name.trim() || busy}>{busy ? "Connecting…" : `Connect to ${preview.display_name}`}</Button>
          </form>
        )}
      </section>
    </main>
  );
}

function ImportButtons({ onValue, showTextFile = true }: { onValue: (value: string) => void; showTextFile?: boolean }) {
  const [scanError, setScanError] = useState("");
  const [scanning, setScanning] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);
  const readFile = (file: File) => {
    const reader = new FileReader();
    reader.onload = () => onValue(String(reader.result ?? ""));
    reader.readAsText(file);
  };
  const scanImage = async (file: File) => {
    setScanError("");
    const url = URL.createObjectURL(file);
    try {
      const { BrowserQRCodeReader } = await import("@zxing/browser");
      const result = await new BrowserQRCodeReader().decodeFromImageUrl(url);
      onValue(result.getText());
    } catch {
      setScanError("No Mesh Chat QR code was found in that image.");
    } finally {
      URL.revokeObjectURL(url);
    }
  };
  const scanCamera = async () => {
    setScanError("");
    try {
      if (await runtimePlatform() === "desktop") {
        setScanning((value) => !value);
        return;
      }
      const {
        checkPermissions,
        Format,
        requestPermissions,
        scan,
      } = await import("@tauri-apps/plugin-barcode-scanner");
      let permission = await checkPermissions();
      if (permission !== "granted") permission = await requestPermissions();
      if (permission !== "granted") {
        setScanError("Camera access was not granted. Enable Camera for Mesh Chat in system settings, or paste the invitation.");
        return;
      }
      const result = await scan({ cameraDirection: "back", formats: [Format.QRCode] });
      if (result.content) onValue(result.content);
    } catch {
      setScanError("The camera scan was closed or unavailable. You can still choose a QR image or paste the invite.");
    }
  };
  useEffect(() => {
    if (!scanning || !videoRef.current) return;
    let stopped = false;
    let stop: (() => void) | undefined;
    void import("@zxing/browser").then(async ({ BrowserQRCodeReader }) => {
      try {
        const controls = await new BrowserQRCodeReader().decodeFromVideoDevice(
          undefined,
          videoRef.current ?? undefined,
          (result) => {
            if (result && !stopped) {
              onValue(result.getText());
              controls.stop();
              setScanning(false);
            }
          },
        );
        stop = () => controls.stop();
      } catch {
        setScanError("Camera scanning is unavailable. You can still choose a QR image or paste the invite.");
        setScanning(false);
      }
    });
    return () => { stopped = true; stop?.(); };
  }, [scanning, onValue]);
  return (
    <div className="import-row">
      {showTextFile && <label className="file-action"><FileUp size={17} /> Open invite file<input type="file" accept=".meshchat,.json,text/plain,application/json" onChange={(event) => event.target.files?.[0] && readFile(event.target.files[0])} /></label>}
      <label className="file-action"><QrCode size={17} /> Read QR image<input type="file" accept="image/*" onChange={(event) => event.target.files?.[0] && void scanImage(event.target.files[0])} /></label>
      <button className="file-action file-action--button" type="button" onClick={() => void scanCamera()}><QrCode size={17} /> {scanning ? "Stop camera" : "Scan with camera"}</button>
      {scanning && <div className="camera-box"><video ref={videoRef} muted playsInline aria-label="Camera preview for QR scanning" /><span>Point the camera at a Mesh Chat QR code.</span></div>}
      {scanError && <span className="form-error" role="alert">{scanError}</span>}
    </div>
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

function NewChatDialog({ initialInvitation, onClose, onChanged }: { initialInvitation: string; onClose: () => void; onChanged: () => Promise<void> }) {
  const [tab, setTab] = useState<"invite" | "join">(initialInvitation ? "join" : "invite");
  const [formats, setFormats] = useState<InvitationFormats | null>(null);
  const [raw, setRaw] = useState(initialInvitation);
  const [preview, setPreview] = useState<InvitationPreview | null>(null);
  const [error, setError] = useState("");
  const [inviteError, setInviteError] = useState("");
  const [creatingInvitation, setCreatingInvitation] = useState(false);
  const createInvitation = useCallback(async () => {
    setCreatingInvitation(true);
    setInviteError("");
    try {
      setFormats(await serviceCommand<InvitationFormats>("create_invitation"));
    } catch (reason) {
      setFormats(null);
      setInviteError(errorMessage(reason));
    } finally {
      setCreatingInvitation(false);
    }
  }, []);
  useEffect(() => { void createInvitation(); }, [createInvitation]);
  useEffect(() => {
    if (!initialInvitation) return;
    setRaw(initialInvitation);
    setTab("join");
    setPreview(null);
    void serviceCommand<InvitationPreview>("preview_invitation", {
      invitation: initialInvitation,
    }).then(setPreview).catch((reason) => setError(errorMessage(reason)));
  }, [initialInvitation]);
  const check = async () => {
    setError("");
    try { setPreview(await serviceCommand("preview_invitation", { invitation: raw })); }
    catch (reason) { setError(errorMessage(reason)); }
  };
  const connect = async () => {
    try {
      await serviceCommand("accept_invitation", { invitation: raw });
      await onChanged();
      onClose();
    } catch (reason) { setError(errorMessage(reason)); }
  };
  return (
    <Dialog title="New chat" onClose={onClose} wide>
      <div className="tabs" role="tablist">
        <button role="tab" aria-selected={tab === "invite"} onClick={() => setTab("invite")}>Share an invite</button>
        <button role="tab" aria-selected={tab === "join"} onClick={() => setTab("join")}>Open an invite</button>
      </div>
      {tab === "invite" && formats && <InvitationShare formats={formats} />}
      {tab === "invite" && !formats && !inviteError && <p className="muted">Creating a secure invitation…</p>}
      {tab === "invite" && !formats && inviteError && <div className="stack"><p className="form-error" role="alert">{inviteError}</p><Button onClick={() => void createInvitation()} disabled={creatingInvitation}>{creatingInvitation ? "Retrying…" : "Retry invitation"}</Button></div>}
      {tab === "join" && !preview && <div className="stack"><label className="field"><span>Invitation</span><textarea autoCapitalize="off" autoCorrect="off" spellCheck={false} rows={5} value={raw} onChange={(event) => setRaw(event.target.value)} /></label><ImportButtons onValue={setRaw} /><Button onClick={() => void check()} disabled={!raw.trim()}>Check invitation</Button></div>}
      {tab === "join" && preview && <div className="stack"><div className="person-preview"><Avatar name={preview.display_name} /><div><h3>{preview.display_name}</h3><p>Identity signature valid</p></div></div><SecurityDetails fingerprint={preview.fingerprint} destination={preview.destination_hash} /><Button onClick={() => void connect()}>Connect to {preview.display_name}</Button></div>}
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

function SettingsDialog({ snapshot, onClose, onSaved }: { snapshot: Snapshot; onClose: () => void; onSaved: () => Promise<void> }) {
  const [settings, setSettings] = useState<NetworkSettings>(snapshot.settings);
  const [saved, setSaved] = useState(false);
  const toggle = (key: "nearby_discovery" | "lan_fallback" | "help_route" | "store_for_offline") => setSettings((current) => ({ ...current, [key]: !current[key] }));
  const save = async () => {
    await serviceCommand("update_settings", { settings });
    setSaved(true); await onSaved();
  };
  return (
    <Dialog title="Settings" onClose={onClose}>
      <div className="settings-list">
        <Toggle title="Find nearby people" description="Use link-local Reticulum discovery on suitable network interfaces." checked={settings.nearby_discovery} onChange={() => toggle("nearby_discovery")} />
        <Toggle title="Use a direct local connection" description="Add a private local-network connection option to new invitations when nearby discovery is blocked." checked={settings.lan_fallback} onChange={() => toggle("lan_fallback")} />
        <Toggle title="Help route messages" description="Allow this device to forward encrypted Reticulum traffic for others." checked={settings.help_route} onChange={() => toggle("help_route")} />
        <Toggle title="Store encrypted messages" description="Act as an LXMF propagation node with a 100 MiB cache. This is separate from routing." checked={settings.store_for_offline} onChange={() => toggle("store_for_offline")} />
      </div>
      <details className="advanced-settings"><summary>Advanced</summary><p>TCP listeners, approved propagation peers, interface restrictions, and diagnostics are intentionally outside the normal joining flow.</p><p className="technical">Destination: {snapshot.profile?.destination_hash}</p></details>
      <p className="app-version">Mesh Chat {packageInfo.version}<span>Emoji artwork: Twemoji (CC BY 4.0)</span></p>
      {saved && <p className="restart-note" role="status">Saved. Restart Mesh Chat to apply networking-role changes.</p>}
      <div className="dialog__actions"><Button variant="secondary" onClick={onClose}>Cancel</Button><Button onClick={() => void save()}>Save settings</Button></div>
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
    if (selfReaction) return `React with ${label}, replacing your ${selfReaction.emoji} reaction`;
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
    const selected = selfReaction?.emoji === validation.emoji;
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
          <span className="sr-only">Choose one reaction. Choosing a different reaction replaces yours; choosing yours again removes it.</span>
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
                const selected = selfReaction?.emoji === option.emoji;
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

function Conversation({ contact, messages, draft, sendError, sending, detailsOpen, reactionTargetId, reactionCatalogOpen, reactionBusyEmoji, reactionError, onDetailsOpenChange, onToggleReactionPicker, onReactionCatalogOpenChange, onCloseReactionPicker, onSetReaction, onDraft, onSend, onHelp, onBack, onDelete }: { contact: Contact; messages: ChatMessage[]; draft: string; sendError: string; sending: boolean; detailsOpen: boolean; reactionTargetId: string | null; reactionCatalogOpen: boolean; reactionBusyEmoji: string | null; reactionError: string; onDetailsOpenChange: (open: boolean) => void; onToggleReactionPicker: (messageId: string) => void; onReactionCatalogOpenChange: (messageId: string, open: boolean) => void; onCloseReactionPicker: () => void; onSetReaction: (messageId: string, emoji: string, active: boolean) => void; onDraft: (value: string) => void; onSend: () => void; onHelp: () => void; onBack: () => void; onDelete: () => void }) {
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
  return (
    <section className="conversation" aria-label={`Conversation with ${contact.display_name}`}>
      <header className="conversation__header"><button className="icon-button mobile-only mobile-back" type="button" onClick={onBack} aria-label="Back to conversations"><ArrowLeft size={21} /></button><div className="conversation__person"><Avatar name={contact.display_name} small /><div><h2>{contact.display_name}</h2><span>{contact.trust === "verified" ? "Verified contact" : "Private conversation"}</span></div></div><div className="conversation__actions"><button className="icon-button conversation-delete" type="button" onClick={onDelete} disabled={sending} aria-label={`Delete conversation with ${contact.display_name}`} title="Delete conversation"><Trash2 size={18} /></button><SecurityDetails fingerprint={contact.fingerprint} destination={contact.destination_hash} open={detailsOpen} onOpenChange={onDetailsOpenChange} /></div></header>
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
  switch (workspace.state) {
    case "joining": return "Waiting for owner approval";
    case "leaving": return "Leave request pending";
    case "left": return "Left workspace";
    case "removed": return "Membership removed";
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
    <div className="workspace-switcher" aria-label="Spaces">
      <button className={`workspace-switcher__item ${activeId === "personal" ? "workspace-switcher__item--active" : ""}`} onClick={() => onSelect("personal")} aria-label="Personal space" title="Personal"><MessageCircleMore size={17} /></button>
      {workspaces.map((workspace) => <button key={workspace.id} className={`workspace-switcher__item ${activeId === workspace.id ? "workspace-switcher__item--active" : ""}`} onClick={() => onSelect(workspace.id)} aria-label={`Workspace ${workspace.name}`} title={`${workspace.name} · ${workspaceStateLabel(workspace)}`}><span>{initials(workspace.name)}</span>{workspace.state !== "active" && <i aria-hidden="true" />}</button>)}
      <button className="workspace-switcher__item workspace-switcher__item--add" onClick={onCreate} aria-label="Create workspace" title="Create workspace"><Plus size={16} /></button>
      <button className="workspace-switcher__item workspace-switcher__item--join" onClick={onJoin} aria-label="Join workspace" title="Join workspace"><LogOut size={15} /></button>
    </div>
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
  return <Dialog title="Create a workspace" onClose={onClose}><div className="form-stack workspace-create"><p className="dialog-lead">A private collaboration space for a trusted team.</p><label>Name<input autoFocus value={name} maxLength={64} onChange={(event) => setName(event.target.value)} aria-label="Workspace name" /></label><label>Description <small>Optional</small><textarea value={description} maxLength={250} onChange={(event) => setDescription(event.target.value)} aria-label="Workspace description" /></label><div className="workspace-facts"><p><ShieldCheck size={17} /><span><strong>This device becomes the owner authority.</strong> Losing it freezes administration until authority continuity ships.</span></p><p><Users size={17} /><span>Every public message is encrypted separately for each member device.</span></p><p><WifiOff size={17} /><span>Delivery and history depend on reachable peers; there is no hosted workspace server.</span></p></div>{error && <p className="form-error" role="alert">{error}</p>}<div className="dialog-actions"><Button variant="ghost" onClick={onClose}>Cancel</Button><Button disabled={busy || !name.trim()} onClick={() => void create()}>{busy ? "Creating…" : "Create workspace"}</Button></div></div></Dialog>;
}

function JoinWorkspaceDialog({ initialValue = "", onClose, onJoined }: { initialValue?: string; onClose: () => void; onJoined: (workspace: Workspace) => Promise<void> }) {
  const [value, setValue] = useState(initialValue);
  const [preview, setPreview] = useState<WorkspaceInvitationPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const review = async () => {
    if (!value.trim() || busy) return;
    setBusy(true); setError("");
    try { setPreview(await serviceCommand("preview_workspace_invitation", { invitation: value.trim() })); }
    catch (reason) { setPreview(null); setError(errorMessage(reason)); }
    finally { setBusy(false); }
  };
  const join = async () => {
    if (!preview || busy) return;
    setBusy(true); setError("");
    try {
      const workspace = await serviceCommand<Workspace>("submit_workspace_join", { operation_id: newOperationId(), invitation: value.trim() });
      await onJoined(workspace);
    } catch (reason) { setError(errorMessage(reason)); }
    finally { setBusy(false); }
  };
  return <Dialog title="Join a workspace" onClose={onClose}><div className="form-stack">{preview ? <><div className="workspace-preview"><span className="workspace-preview__avatar">{initials(preview.name)}</span><div><h3>{preview.name}</h3><p>{preview.description || "No description"}</p></div></div><dl className="security-list"><div><dt>Owner fingerprint</dt><dd>{preview.owner_fingerprint}</dd></div><div><dt>Current members</dt><dd>{preview.member_count}</dd></div><div><dt>History preference</dt><dd>{preview.retention_days === null ? "Indefinite" : `${preview.retention_days} days`}</dd></div></dl><p className="muted">Joining does not approve a global contact. The owner must verify this device and approve your request.</p></> : <><p>Paste or scan the signed one-use invitation from the workspace owner.</p><textarea autoFocus value={value} onChange={(event) => { setValue(event.target.value); setError(""); }} aria-label="Workspace invitation" rows={7} /><ImportButtons onValue={setValue} showTextFile={false} /></>}{error && <p className="form-error" role="alert">{error}</p>}<div className="dialog-actions"><Button variant="ghost" onClick={preview ? () => setPreview(null) : onClose}>{preview ? "Back" : "Cancel"}</Button><Button disabled={busy || (!preview && !value.trim())} onClick={() => void (preview ? join() : review())}>{busy ? "Checking…" : preview ? "Send join request" : "Review invitation"}</Button></div></div></Dialog>;
}

function WorkspaceInviteDialog({ workspace, existingInvitations, onClose }: { workspace: Workspace; existingInvitations: WorkspaceInvitation[]; onClose: () => void }) {
  const [invitation, setInvitation] = useState<WorkspaceInvitationFormats | null>(null);
  const [existing, setExisting] = useState(existingInvitations);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");
  const create = async () => {
    if (busy) return;
    setBusy(true); setError("");
    try { setInvitation(await serviceCommand("create_workspace_invitation", { operation_id: newOperationId(), workspace_id: workspace.id, lifetime_days: 7 })); }
    catch (reason) { setError(errorMessage(reason)); }
    finally { setBusy(false); }
  };
  const revoke = async (invitationId: string) => {
    if (!invitationId || busy) return;
    setBusy(true); setError("");
    try {
      await serviceCommand("revoke_workspace_invitation", { operation_id: newOperationId(), workspace_id: workspace.id, invitation_id: invitationId });
      if (invitation?.id === invitationId) setInvitation(null);
      setExisting((current) => current.filter((item) => item.id !== invitationId)); setCopied(false);
    } catch (reason) { setError(errorMessage(reason)); }
    finally { setBusy(false); }
  };
  return <Dialog title={`Invite to ${workspace.name}`} onClose={onClose}><div className="form-stack">{invitation && <><p>This bearer invitation works once and expires {formatExpiry(invitation.expires_at)}. Copy it now; Mesh Chat will not place it in startup data later.</p>{invitation.link.length <= 4096 && <div className="qr-card"><QRCodeSVG value={invitation.link} size={188} level="M" /></div>}<textarea readOnly value={invitation.text} aria-label="Workspace invitation text" rows={5} /><div className="dialog-actions"><Button variant="danger" disabled={busy} onClick={() => void revoke(invitation.id)}>Revoke invitation</Button><Button variant="secondary" onClick={async () => { await navigator.clipboard.writeText(invitation.text); setCopied(true); }}>{copied ? <Check size={17} /> : <Copy size={17} />}{copied ? "Copied" : "Copy invitation"}</Button></div></>}{existing.length > 0 && <div className="workspace-invitation-list"><h3>Active invitations</h3>{existing.filter((item) => item.id !== invitation?.id).map((item) => <div className="workspace-invitation-row" key={item.id}><span>One-use invitation · expires {formatExpiry(item.expires_at)}</span><Button variant="ghost" disabled={busy} onClick={() => void revoke(item.id)}>Revoke</Button></div>)}</div>}<p>Create a separate signed invitation for each person. Each request is reviewed independently.</p><Button disabled={busy} onClick={() => void create()}>{busy ? "Creating…" : "Create another invitation"}</Button>{error && <p className="form-error" role="alert">{error}</p>}</div></Dialog>;
}

function WorkspacePeopleDialog({ workspace, requests, busy, error, onClose, onRequestName, onDecideName, onRemove, onMessage }: { workspace: Workspace; requests: WorkspaceDisplayNameRequest[]; busy: boolean; error: string; onClose: () => void; onRequestName: (displayName: string) => void; onDecideName: (requestId: string, approve: boolean) => void; onRemove: (memberId: string) => void; onMessage: (memberId: string) => void }) {
  const local = workspace.members.find((member) => member.id === workspace.local_member_id);
  const [displayName, setDisplayName] = useState(local?.display_name ?? "");
  return <Dialog title={`People in ${workspace.name}`} onClose={onClose}><div className="form-stack"><div className="workspace-people">{workspace.members.map((member) => <div className="workspace-person" key={member.id}><Avatar name={member.display_name} small /><span><strong>{member.display_name}{member.id === workspace.local_member_id ? " (you)" : ""}</strong><small>{member.role} · {member.status} · {member.short_id}</small></span><span className="workspace-person__actions">{workspace.state === "active" && member.id !== workspace.local_member_id && member.status === "active" && <Button variant="ghost" disabled={busy} onClick={() => onMessage(member.id)}><MessageCircleMore size={15} /> Message</Button>}{workspace.local_role === "owner" && workspace.state === "active" && member.role !== "owner" && member.status === "active" ? <Button variant="ghost" disabled={busy} onClick={() => onRemove(member.id)}><UserMinus size={15} /> Remove</Button> : member.id === workspace.local_member_id && <ShieldCheck size={16} aria-label="Signed member" />}</span></div>)}</div>{workspace.state === "active" && <form className="workspace-name-request" onSubmit={(event) => { event.preventDefault(); if (displayName.trim() && displayName.trim() !== local?.display_name) onRequestName(displayName); }}><label>Your workspace display name<input value={displayName} maxLength={64} onChange={(event) => setDisplayName(event.target.value)} /></label><p className="muted">{workspace.local_role === "owner" ? "The owner signs this into the next membership epoch." : "This request waits for the owner to publish the next signed membership epoch."}</p><Button disabled={busy || !displayName.trim() || displayName.trim() === local?.display_name}>Request name change</Button></form>}{workspace.local_role === "owner" && requests.length > 0 && <div className="workspace-name-requests"><h3>Display-name requests</h3>{requests.map((request) => <div className="workspace-invitation-row" key={request.id}><span>{workspace.members.find((member) => member.id === request.member_id)?.display_name ?? "Member"} → <strong>{request.display_name}</strong></span><span><Button disabled={busy} onClick={() => onDecideName(request.id, true)}>Approve</Button><Button variant="ghost" disabled={busy} onClick={() => onDecideName(request.id, false)}>Decline</Button></span></div>)}</div>}{error && <p className="form-error" role="alert">{error}</p>}</div></Dialog>;
}

function WorkspaceSettingsDialog({ workspace, networkSettings, busy, error, onClose, onUpdateMetadata, onUpdatePolicies, onApprovePropagationNode, onCloseWorkspace, onLeave, onRemove }: { workspace: Workspace; networkSettings: NetworkSettings; busy: boolean; error: string; onClose: () => void; onUpdateMetadata: (name: string, description: string) => void; onUpdatePolicies: (channelCreation: "all_members" | "owner_and_admins", posting: "all_members" | "owner_and_admins") => void; onApprovePropagationNode: (node: string) => void; onCloseWorkspace: () => void; onLeave: () => void; onRemove: (confirmation: string) => void }) {
  const [confirmingClose, setConfirmingClose] = useState(false);
  const [confirmingRemove, setConfirmingRemove] = useState(false);
  const [confirmation, setConfirmation] = useState("");
  const [name, setName] = useState(workspace.name);
  const [description, setDescription] = useState(workspace.description);
  const [channelCreation, setChannelCreation] = useState(workspace.policies.channel_creation);
  const [posting, setPosting] = useState(workspace.policies.posting);
  const [propagationNode, setPropagationNode] = useState("");
  const [propagationConsent, setPropagationConsent] = useState(false);
  const terminal = ["left", "removed", "closed"].includes(workspace.state);
  const active = workspace.state === "active";
  return <Dialog title="Workspace settings" onClose={onClose}><div className="form-stack workspace-settings"><div><h3>{workspace.name}</h3><p>{workspace.description || "No description"}</p><span className={`workspace-state workspace-state--${workspace.state}`}>{workspaceStateLabel(workspace)}</span></div>{active && workspace.local_role === "owner" && <form className="form-stack" onSubmit={(event) => { event.preventDefault(); onUpdateMetadata(name, description); }}><label>Workspace name<input value={name} maxLength={64} onChange={(event) => setName(event.target.value)} /></label><label>Description<textarea value={description} maxLength={280} rows={3} onChange={(event) => setDescription(event.target.value)} /></label><Button disabled={busy || (name.trim() === workspace.name && description.trim() === workspace.description)}>Publish metadata update</Button></form>}{active && workspace.local_role === "owner" && <form className="form-stack" onSubmit={(event) => { event.preventDefault(); onUpdatePolicies(channelCreation, posting); }}><h3>Public-channel policies</h3><label>Who can create channels<select value={channelCreation} onChange={(event) => setChannelCreation(event.target.value as typeof channelCreation)}><option value="all_members">All members</option><option value="owner_and_admins">Owner only until admins ship</option></select></label><label>Who can post<select value={posting} onChange={(event) => setPosting(event.target.value as typeof posting)}><option value="all_members">All members</option><option value="owner_and_admins">Owner only until admins ship</option></select></label><Button disabled={busy || (channelCreation === workspace.policies.channel_creation && posting === workspace.policies.posting)}>Publish policy update</Button></form>}<dl className="security-list"><div><dt>Workspace ID</dt><dd>{workspace.id}</dd></div><div><dt>Manifest epoch</dt><dd>{workspace.epoch}</dd></div><div><dt>Retention preference</dt><dd>{workspace.retention_days === null ? "Indefinite" : `${workspace.retention_days} days`}</dd></div></dl><p className="muted">This cooperative preference does not guarantee remote deletion. A member device may retain plaintext it already received.</p>{active && <div className="propagation-consent"><h3>Offline delivery node</h3><p className="muted">A workspace may recommend a Reticulum propagation node, but joining never enables it. Approve its 32-character address explicitly on this device.</p><label>Propagation-node address<input value={propagationNode} spellCheck={false} maxLength={32} onChange={(event) => setPropagationNode(event.target.value.toLowerCase())} /></label><label className="checkbox-line"><input type="checkbox" checked={propagationConsent} onChange={(event) => setPropagationConsent(event.target.checked)} /> I approve this node for encrypted store-and-forward delivery.</label><Button variant="secondary" disabled={busy || !propagationConsent || !/^[0-9a-f]{32}$/.test(propagationNode) || networkSettings.approved_propagation_nodes.includes(propagationNode)} onClick={() => onApprovePropagationNode(propagationNode)}>Approve node</Button></div>}{workspace.state === "forked" && <p className="form-error" role="alert">Workspace activity is paused. Mesh Chat will not choose between conflicting signed histories.</p>}{workspace.state === "incomplete_sync" && <p className="form-error" role="alert">Some signed controls or events are missing. Messaging stays paused while Mesh Chat retains the history it can validate.</p>}{error && <p className="form-error" role="alert">{error}</p>}{active && workspace.local_role === "owner" && <div className="danger-zone"><h3>Close workspace</h3><p>This signs a terminal manifest. No later joins or messages are accepted.</p>{confirmingClose ? <><p role="alert"><strong>Close {workspace.name} permanently?</strong> Cached history remains until each member removes it locally.</p><div className="dialog-actions"><Button variant="ghost" disabled={busy} onClick={() => setConfirmingClose(false)}>Cancel</Button><Button variant="danger" disabled={busy} onClick={onCloseWorkspace}>Confirm close workspace</Button></div></> : <Button variant="danger" disabled={busy} onClick={() => setConfirmingClose(true)}>Close workspace…</Button>}</div>}{active && workspace.local_role !== "owner" && <div className="danger-zone"><h3>Leave workspace</h3><p>Your signed request waits for the owner to publish the membership change.</p><Button variant="danger" disabled={busy} onClick={onLeave}>Leave workspace</Button></div>}{terminal && <div className="danger-zone"><h3>Remove local workspace data</h3><p>This permanently erases this device’s encrypted workspace records. Re-entry needs a new invitation.</p>{confirmingRemove ? <><label>Type the workspace ID to confirm<input value={confirmation} onChange={(event) => setConfirmation(event.target.value)} aria-label="Workspace removal confirmation" /></label><Button variant="danger" disabled={busy || confirmation !== workspace.id} onClick={() => onRemove(confirmation)}>Remove local data</Button></> : <Button variant="danger" onClick={() => setConfirmingRemove(true)}>Remove local data…</Button>}</div>}</div></Dialog>;
}

function CreateWorkspaceChannelDialog({ workspace, busy, error, onClose, onCreate }: { workspace: Workspace; busy: boolean; error: string; onClose: () => void; onCreate: (name: string, topic: string, visibility: "public" | "private", memberIds: string[]) => void }) {
  const [name, setName] = useState("");
  const [topic, setTopic] = useState("");
  const [visibility, setVisibility] = useState<"public" | "private">("public");
  const [memberIds, setMemberIds] = useState<string[]>([workspace.local_member_id]);
  const allowed = workspace.state === "active" && (workspace.policies.channel_creation === "all_members" || workspace.local_role === "owner");
  const activeMembers = workspace.members.filter((member) => member.status === "active");
  return <Dialog title="Create a channel" onClose={onClose}><form className="form-stack" onSubmit={(event) => { event.preventDefault(); if (allowed && name.trim()) onCreate(name.trim(), topic.trim(), visibility, memberIds); }}><label>Visibility<select value={visibility} onChange={(event) => setVisibility(event.target.value as "public" | "private")}><option value="public">Public to workspace</option><option value="private">Private to selected members</option></select></label><p>{visibility === "public" ? "Every active workspace member receives messages. Subscriptions only control presentation." : "Only the signed roster receives the channel identifier, controls, roster, or messages. New members do not receive earlier messages."}</p><label>Channel name<input autoFocus value={name} maxLength={80} onChange={(event) => setName(event.target.value)} /></label><label>Topic <small>Optional</small><textarea value={topic} maxLength={250} onChange={(event) => setTopic(event.target.value)} /></label>{visibility === "private" && <fieldset className="form-stack"><legend>Private roster · up to eight people</legend>{activeMembers.map((member) => <label className="checkbox-line" key={member.id}><input type="checkbox" checked={memberIds.includes(member.id)} disabled={member.id === workspace.local_member_id || (!memberIds.includes(member.id) && memberIds.length >= 8)} onChange={(event) => setMemberIds((current) => event.target.checked ? [...new Set([...current, member.id])] : current.filter((id) => id !== member.id))} /> {member.display_name}{member.id === workspace.local_member_id ? " (you · manager)" : ` · ${member.short_id}`}</label>)}</fieldset>}{!allowed && <p className="form-error" role="alert">Channel creation is not permitted under the current signed policy.</p>}{error && <p className="form-error" role="alert">{error}</p>}<div className="dialog-actions"><Button variant="ghost" onClick={onClose}>Cancel</Button><Button disabled={busy || !allowed || !name.trim()}>{busy ? "Creating…" : `Create ${visibility} channel`}</Button></div></form></Dialog>;
}

function BrowseWorkspaceChannelsDialog({ workspace, channels, busy, error, onClose, onOpen, onSubscribe, onSync, onCreate }: { workspace: Workspace; channels: WorkspaceChannel[]; busy: boolean; error: string; onClose: () => void; onOpen: (channelId: string) => void; onSubscribe: (channelId: string, subscribed: boolean) => void; onSync: () => void; onCreate: () => void }) {
  const canCreate = workspace.state === "active" && (workspace.policies.channel_creation === "all_members" || workspace.local_role === "owner");
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

function WorkspaceConversation({ workspace, channel, page, draft, loading, sending, error, onDraft, onSend, onLoadOlder, onHide, onPeople, onSettings, onInvite, onManage }: { workspace: Workspace; channel: WorkspaceChannel; page: WorkspaceMessagePage | null; draft: string; loading: boolean; sending: boolean; error: string; onDraft: (value: string) => void; onSend: () => void; onLoadOlder: () => void; onHide: (eventId: string) => void; onPeople: () => void; onSettings: () => void; onInvite: () => void; onManage: () => void }) {
  const postingRestricted = workspace.policies.posting === "owner_and_admins" && workspace.local_role !== "owner";
  const readOnly = workspace.state !== "active" || channel.state !== "active" || postingRestricted;
  const [attachmentWarning, setAttachmentWarning] = useState("");
  const syncWarning = workspaceSyncIssueLabel(workspace);
  return <section className="conversation workspace-conversation" aria-label={`Workspace channel ${channel.name}`} onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); if (event.dataTransfer.files.length) setAttachmentWarning("Attachments are not supported yet. No file was sent."); }}><header className="conversation__header"><div className="conversation__identity"><span className="workspace-channel-icon">{channel.visibility === "private" ? <LockKeyhole size={19} /> : <Hash size={19} />}</span><span><h1>{channel.display_name || channel.name}</h1><small>{channel.topic || `${workspace.name} · ${channel.visibility === "private" ? "private signed roster" : workspaceStateLabel(workspace)}`}</small></span></div><div className="workspace-header-actions">{workspace.local_role === "owner" && workspace.state === "active" && workspace.members.filter((member) => member.status === "active").length < 8 && <button className="icon-button" onClick={onInvite} aria-label={`Invite people to ${workspace.name}`} title="Invite people"><UserRoundPlus size={18} /></button>}<button className="icon-button" onClick={onManage} aria-label={`Manage ${channel.name} channel`} title="Channel details"><Settings size={18} /></button><button className="icon-button" onClick={onPeople} aria-label={`People in ${workspace.name}`} title="People"><Users size={18} /></button><button className="icon-button" onClick={onSettings} aria-label={`${workspace.name} settings`} title="Workspace settings"><Building2 size={18} /></button></div></header><div className="message-scroll workspace-message-scroll">{page?.next_cursor && <button className="load-older" disabled={loading} onClick={onLoadOlder}>{loading ? "Loading…" : "Load older messages"}</button>}{loading && !page && <div className="workspace-loading"><span className="spinner" /> Loading messages…</div>}{!loading && page?.messages.length === 0 && <div className="workspace-channel-empty">{channel.visibility === "private" ? <LockKeyhole size={26} /> : <Hash size={26} />}<h2>Welcome to #{channel.display_name || channel.name}</h2><p>{channel.visibility === "private" ? "Only the signed roster receives this channel or its future messages. Newly admitted members receive no earlier messages." : "Everyone in this workspace receives public-channel messages. History depends on copies retained by reachable members."}</p></div>}{page?.messages.map((message) => <article className={`workspace-message ${message.direction === "outbound" ? "workspace-message--self" : ""}`} key={message.id}><Avatar name={message.author_display_name} small /><div><header><strong>{message.author_display_name}</strong><time dateTime={machineTime(message.created_at)}>{formatTime(message.created_at)}</time><button className="message-hide" onClick={() => onHide(message.id)} aria-label={`Hide message from ${message.author_display_name}`} title="Hide locally"><X size={13} /></button></header><p>{message.text}</p>{message.direction === "outbound" && <details className="workspace-delivery"><summary>{workspaceDeliveryLabel(message)}</summary>{message.deliveries && <ul>{message.deliveries.map((delivery) => <li key={delivery.device_id}><span>{delivery.member_display_name} · device {delivery.device_short_id}</span><strong>{workspaceDeliveryStateLabel(delivery.state)}</strong></li>)}</ul>}</details>}</div></article>)}</div>{(error || attachmentWarning || syncWarning) && <p className="form-error workspace-composer-error" role="alert">{error || attachmentWarning || syncWarning}</p>}{readOnly ? <div className="composer-disabled"><LockKeyhole size={16} />{postingRestricted ? "Only the workspace owner can post under the current signed policy." : channel.state === "archived" ? "This channel is archived and read-only." : channel.state === "leaving" ? "Leaving is pending with the channel manager." : workspaceStateLabel(workspace)}</div> : <div className="composer workspace-composer"><button type="button" className="icon-button" onClick={() => setAttachmentWarning("Attachments are not supported yet. No file was sent.")} aria-label="Add attachment"><Plus size={20} /></button><textarea value={draft} onChange={(event) => { setAttachmentWarning(""); onDraft(event.target.value); }} onPaste={(event) => { if (event.clipboardData.files.length || Array.from(event.clipboardData.items).some((item) => item.kind === "file")) { event.preventDefault(); setAttachmentWarning("Attachments are not supported yet. No file was sent."); } }} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); onSend(); } }} placeholder={`Message #${channel.name}`} aria-label={`Message ${channel.name}`} maxLength={16 * 1024} /><Button disabled={sending || !draft.trim()} onClick={onSend} aria-label="Send workspace message"><Send size={18} /></Button></div>}</section>;
}

function WorkspaceDirectConversation({ workspace, direct, page, draft, loading, sending, error, onDraft, onSend, onLoadOlder, onHideMessage, onHideConversation, onPeople }: { workspace: Workspace; direct: WorkspaceDirect; page: WorkspaceMessagePage | null; draft: string; loading: boolean; sending: boolean; error: string; onDraft: (value: string) => void; onSend: () => void; onLoadOlder: () => void; onHideMessage: (eventId: string) => void; onHideConversation: () => void; onPeople: () => void }) {
  const [attachmentWarning, setAttachmentWarning] = useState("");
  const readOnly = workspace.state !== "active" || direct.state !== "open";
  const readOnlyLabel = direct.state !== "open"
    ? "This workspace DM is read-only because one participant is no longer active."
    : workspaceStateLabel(workspace);
  return <section className="conversation workspace-conversation" aria-label={`Workspace direct message with ${direct.peer_display_name}`} onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); if (event.dataTransfer.files.length) setAttachmentWarning("Attachments are not supported yet. No file was sent."); }}>
    <header className="conversation__header"><div className="conversation__identity"><Avatar name={direct.peer_display_name} small /><span><h1>{direct.peer_display_name}</h1><small>{workspace.name} · workspace DM · {direct.peer_short_id}</small></span></div><div className="workspace-header-actions"><button className="icon-button" onClick={onHideConversation} aria-label={`Hide workspace conversation with ${direct.peer_display_name}`} title="Hide locally"><EyeOff size={18} /></button><button className="icon-button" onClick={onPeople} aria-label={`People in ${workspace.name}`} title="People"><Users size={18} /></button></div></header>
    <div className="message-scroll workspace-message-scroll">{page?.next_cursor && <button className="load-older" disabled={loading} onClick={onLoadOlder}>{loading ? "Loading…" : "Load older messages"}</button>}{loading && !page && <div className="workspace-loading"><span className="spinner" /> Loading messages…</div>}{!loading && page?.messages.length === 0 && <div className="workspace-channel-empty"><MessageCircleMore size={28} /><h2>Message {direct.peer_display_name}</h2><p>This private workspace conversation is authorized by signed membership and does not create a global Contact.</p></div>}{page?.messages.map((message) => <article className={`workspace-message ${message.direction === "outbound" ? "workspace-message--self" : ""}`} key={message.id}><Avatar name={message.author_display_name} small /><div><header><strong>{message.author_display_name}</strong><time dateTime={machineTime(message.created_at)}>{formatTime(message.created_at)}</time><button className="message-hide" onClick={() => onHideMessage(message.id)} aria-label={`Hide message from ${message.author_display_name}`} title="Hide locally"><X size={13} /></button></header><p>{message.text}</p>{message.direction === "outbound" && <details className="workspace-delivery"><summary>{workspaceDeliveryLabel(message)}</summary>{message.deliveries && <ul>{message.deliveries.map((delivery) => <li key={delivery.device_id}><span>{delivery.member_display_name} · device {delivery.device_short_id}</span><strong>{workspaceDeliveryStateLabel(delivery.state)}</strong></li>)}</ul>}</details>}</div></article>)}</div>
    {(error || attachmentWarning) && <p className="form-error workspace-composer-error" role="alert">{error || attachmentWarning}</p>}
    {readOnly ? <div className="composer-disabled"><LockKeyhole size={16} />{readOnlyLabel}</div> : <div className="composer workspace-composer"><button type="button" className="icon-button" onClick={() => setAttachmentWarning("Attachments are not supported yet. No file was sent.")} aria-label="Add attachment"><Plus size={20} /></button><textarea value={draft} onChange={(event) => { setAttachmentWarning(""); onDraft(event.target.value); }} onPaste={(event) => { if (event.clipboardData.files.length || Array.from(event.clipboardData.items).some((item) => item.kind === "file")) { event.preventDefault(); setAttachmentWarning("Attachments are not supported yet. No file was sent."); } }} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); onSend(); } }} placeholder={`Message ${direct.peer_display_name}`} aria-label={`Message ${direct.peer_display_name}`} maxLength={16 * 1024} /><Button disabled={sending || !draft.trim()} onClick={onSend} aria-label="Send workspace direct message"><Send size={18} /></Button></div>}
  </section>;
}

type ConversationSelection = { kind: "contact" | "group"; id: string } | null;
type ReactionTarget = { kind: "direct" | "group"; messageId: string; layer: "quick" | "catalog" } | null;

type DraftWrite = {
  command: "save_draft" | "save_group_draft" | "save_workspace_draft" | "save_workspace_direct_draft";
  payload: Record<string, unknown>;
};

type DraftWriteSlot = {
  timer: number | null;
  pending: DraftWrite | null;
  // Always-normalized tail used only as an ordering barrier.
  tail: Promise<void>;
};

const DRAFT_SAVE_DELAY_MS = 200;

function Messenger({ snapshot, refresh, workspaceChannelInvalidation, onLock, initialInvitation, onInvitationHandled }: { snapshot: Snapshot; refresh: (afterCurrent?: boolean) => Promise<Snapshot>; workspaceChannelInvalidation: ServiceEvent | null; onLock: () => Promise<void>; initialInvitation: string; onInvitationHandled: () => void }) {
  const groups = snapshot.groups ?? [];
  const groupMessages = snapshot.group_messages ?? [];
  const groupInvitations = snapshot.group_invitations ?? [];
  const workspaces = snapshot.workspaces ?? [];
  const workspaceChannels = snapshot.workspace_channels ?? [];
  const workspaceDirects = snapshot.workspace_directs ?? [];
  const workspaceChannelTransfers = snapshot.workspace_channel_transfers ?? [];
  const workspaceJoinRequests = snapshot.workspace_join_requests ?? [];
  const workspaceDisplayNameRequests = snapshot.workspace_display_name_requests ?? [];
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
  const [workspacesEnabled, setWorkspacesEnabled] = useState(false);
  const [activeSpaceId, setActiveSpaceId] = useState<"personal" | string>("personal");
  const [createWorkspaceOpen, setCreateWorkspaceOpen] = useState(false);
  const [joinWorkspaceOpen, setJoinWorkspaceOpen] = useState(false);
  const [inviteWorkspaceOpen, setInviteWorkspaceOpen] = useState(false);
  const [workspacePeopleOpen, setWorkspacePeopleOpen] = useState(false);
  const [workspaceSettingsOpen, setWorkspaceSettingsOpen] = useState(false);
  const [workspaceBrowseOpen, setWorkspaceBrowseOpen] = useState(false);
  const [workspaceCreateChannelOpen, setWorkspaceCreateChannelOpen] = useState(false);
  const [workspaceManageChannelOpen, setWorkspaceManageChannelOpen] = useState(false);
  const [workspaceSelectedChannelId, setWorkspaceSelectedChannelId] = useState<string | null>(null);
  const [workspaceSelectedDirectId, setWorkspaceSelectedDirectId] = useState<string | null>(null);
  const [workspacePage, setWorkspacePage] = useState<WorkspaceMessagePage | null>(null);
  const [workspacePageLoading, setWorkspacePageLoading] = useState(false);
  const [workspaceDrafts, setWorkspaceDrafts] = useState<Record<string, string>>(() => Object.fromEntries((snapshot.workspace_drafts ?? []).map((draft) => [draft.conversation_id, draft.text])));
  const [workspaceSending, setWorkspaceSending] = useState(false);
  const [workspaceError, setWorkspaceError] = useState("");
  const [workspaceActionBusy, setWorkspaceActionBusy] = useState(false);
  const [workspaceActionError, setWorkspaceActionError] = useState("");
  const workspacePageInFlight = useRef(false);
  const loadedWorkspaceChannel = useRef<string | null>(null);
  const workspaceSendInFlight = useRef(false);
  const pendingWorkspaceSend = useRef<{
    workspaceId: string;
    conversationId: string;
    kind: "channel" | "direct";
    text: string;
    operationId: string;
    eventId: string;
  } | null>(null);
  const [contactsOpen, setContactsOpen] = useState(false);
  const [settings, setSettings] = useState(false);
  const [help, setHelp] = useState<{ code: string; action: string | null } | null>(null);
  const [dismissedRequests, setDismissedRequests] = useState<string[]>([]);
  const [dismissedGroupInvitations, setDismissedGroupInvitations] = useState<string[]>([]);
  const [requestBusy, setRequestBusy] = useState<string | null>(null);
  const [requestError, setRequestError] = useState("");
  const [groupInvitationBusy, setGroupInvitationBusy] = useState<string | null>(null);
  const [groupInvitationError, setGroupInvitationError] = useState("");
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
  const [reactionBusy, setReactionBusy] = useState<{ kind: "direct" | "group"; messageId: string; emoji: string } | null>(null);
  const [reactionError, setReactionError] = useState("");
  useEffect(() => { void runtimePlatform().then((platform) => setWorkspacesEnabled(platform === "desktop")); }, []);
  useEffect(() => {
    if (!initialInvitation) return;
    const workspaceInvitation = initialInvitation.startsWith("meshchat://workspace/") || initialInvitation.trim().startsWith("MESHWORKSPACE1:") || initialInvitation.includes('"type":"workspace_invite"');
    if (workspaceInvitation) {
      if (workspacesEnabled) setJoinWorkspaceOpen(true);
      return;
    }
    setNewChat(true);
  }, [initialInvitation, workspacesEnabled]);

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
  const hasForegroundRequest = Boolean(incomingRequest || foregroundGroupInvitation);
  const networkAvailable = Boolean(snapshot.network?.interface_available) && !snapshot.service_error;
  const selectedContact = selection?.kind === "contact" ? snapshot.contacts.find((contact) => contact.id === selection.id) ?? null : null;
  const selectedGroup = selection?.kind === "group" ? groups.find((group) => group.id === selection.id) ?? null : null;
  const selectedWorkspace = activeSpaceId === "personal" ? null : workspaces.find((workspace) => workspace.id === activeSpaceId) ?? null;
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
    setWorkspaceManageChannelOpen(false);
  }, [activeSpaceId]);

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
  };

  const closeReactionPicker = useCallback(() => {
    reactionInteractionGeneration.current += 1;
    setReactionTarget(null);
    setReactionError("");
  }, []);

  const toggleReactionPicker = (kind: "direct" | "group", messageId: string) => {
    if (reactionInFlight.current) return;
    setReactionError("");
    setReactionTarget((current) => current?.kind === kind && current.messageId === messageId ? null : { kind, messageId, layer: "quick" });
  };

  const setReactionCatalogOpen = (kind: "direct" | "group", messageId: string, open: boolean) => {
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
  const saveWorkspaceDraft = (workspaceId: string, channelId: string, text: string) => {
    setWorkspaceDrafts((current) => ({ ...current, [channelId]: text }));
    scheduleDraftWrite(`workspace:${channelId}`, {
      command: "save_workspace_draft",
      payload: { operation_id: newOperationId(), workspace_id: workspaceId, channel_id: channelId, text },
    });
  };
  const saveWorkspaceDirectDraft = (workspaceId: string, conversationId: string, text: string) => {
    setWorkspaceDrafts((current) => ({ ...current, [conversationId]: text }));
    scheduleDraftWrite(`workspace-direct:${conversationId}`, {
      command: "save_workspace_direct_draft",
      payload: { operation_id: newOperationId(), workspace_id: workspaceId, conversation_id: conversationId, text },
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

  const respondToWorkspaceJoin = async (requestId: string, accept: boolean) => {
    if (!selectedWorkspace || workspaceActionBusy) return;
    setWorkspaceActionBusy(true); setWorkspaceActionError("");
    try {
      await serviceCommand(accept ? "approve_workspace_join" : "decline_workspace_join", { operation_id: newOperationId(), workspace_id: selectedWorkspace.id, request_id: requestId });
      await refresh(true);
    } catch (reason) { setWorkspaceActionError(errorMessage(reason)); }
    finally { setWorkspaceActionBusy(false); }
  };
  const runWorkspaceAdministration = async (
    command:
      | "update_workspace_metadata"
      | "update_workspace_policies"
      | "remove_workspace_member"
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
  const runWorkspaceChannelAction = async (
    command:
      | "create_workspace_channel"
      | "update_workspace_channel"
      | "update_workspace_private_channel_members"
      | "leave_workspace_private_channel"
      | "set_workspace_channel_subscription"
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
        setWorkspaceCreateChannelOpen(false);
        setWorkspaceBrowseOpen(false);
      }
      if (command === "update_workspace_channel" && "id" in result && result.state === "archived") {
        setWorkspaceManageChannelOpen(false);
      }
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
    const text = workspaceDrafts[selectedWorkspaceConversation.id] ?? "";
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
      ? prior
      : {
        workspaceId,
        conversationId,
        kind,
        text,
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
      });
    } catch (reason) {
      setWorkspaceError(`${errorMessage(reason)} Your text is still in the composer; retrying will reuse the same durable message ID.`);
      workspaceSendInFlight.current = false;
      setWorkspaceSending(false);
      return;
    }
    pendingWorkspaceSend.current = null;
    setWorkspaceDrafts((current) => ({ ...current, [conversationId]: "" }));
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
        ? { command: "save_workspace_direct_draft", payload: { operation_id: newOperationId(), workspace_id: workspaceId, conversation_id: conversationId, text: "" } }
        : { command: "save_workspace_draft", payload: { operation_id: newOperationId(), workspace_id: workspaceId, channel_id: conversationId, text: "" } });
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
  const openWorkspaceDirect = async (memberId: string) => {
    if (!selectedWorkspace || workspaceActionBusy) return;
    setWorkspaceActionBusy(true); setWorkspaceActionError("");
    try {
      const direct = await serviceCommand<WorkspaceDirect>("open_workspace_direct", { operation_id: newOperationId(), workspace_id: selectedWorkspace.id, member_id: memberId });
      setWorkspaceSelectedDirectId(direct.id);
      setWorkspaceSelectedChannelId(null);
      setWorkspacePeopleOpen(false);
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
  const hideWorkspaceMessage = async (eventId: string) => {
    if (!selectedWorkspace) return;
    setWorkspaceError("");
    try {
      await serviceCommand("hide_workspace_message", { operation_id: newOperationId(), workspace_id: selectedWorkspace.id, event_id: eventId });
      await loadWorkspaceMessages(false);
    } catch (reason) { setWorkspaceError(errorMessage(reason)); }
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
    if (selection) selectConversation(null);
  }, [closeReactionPicker, contactsOpen, conversationDetailsOpen, deleteBusy, deleteTarget, foregroundGroupInvitation, help, incomingRequest, newChat, newGroup, onInvitationHandled, reactionTarget, selection, settings]);

  const mobileBackHandlerRef = useRef(handleMobileBack);
  // Keep the single native listener pointed at the newest committed render.
  // Updating the ref while rendering avoids a one-frame gap after a layer opens.
  mobileBackHandlerRef.current = handleMobileBack;

  const hasMobileBackTarget = Boolean(
    incomingRequest
      || foregroundGroupInvitation
      || deleteTarget
      || help
      || contactsOpen
      || settings
      || newGroup
      || newChat
      || selection,
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
    <main className={`app-shell ${selectedWorkspace || selectedContact || selectedGroup ? "app-shell--thread" : "app-shell--list"}`}>
      <aside className="sidebar">
        <header className="sidebar__top"><Brand /><div><button className="icon-button" onClick={() => setContactsOpen(true)} aria-label="Contacts" title="Contacts"><BookUser size={19} /></button><button className="icon-button" onClick={() => void onLock()} aria-label="Lock Mesh Chat"><LockKeyhole size={18} /></button><button className="icon-button" onClick={() => setSettings(true)} aria-label="Settings"><Settings size={19} /></button><button className="icon-button mobile-only" aria-label="Menu"><Menu size={20} /></button></div></header>
        {workspacesEnabled && <WorkspaceSwitcher workspaces={workspaces} activeId={activeSpaceId} onSelect={(id) => { setActiveSpaceId(id); setWorkspaceError(""); setWorkspaceActionError(""); }} onCreate={() => setCreateWorkspaceOpen(true)} onJoin={() => setJoinWorkspaceOpen(true)} />}
        {activeSpaceId === "personal" ? <>
        <div className="search-box"><Search size={17} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search conversations" aria-label="Search conversations" /></div>
        {conversationActionError && <p className="form-error sidebar-action-error" role="alert">{conversationActionError}</p>}
        <nav className="contact-list" aria-label="Conversations">
          {pending.map((contact) => <section className="request-card" key={contact.id}><div><Avatar name={contact.display_name} small /><span><strong>{contact.display_name}</strong><small>Wants to connect</small></span></div><div><Button disabled={requestBusy === contact.id} onClick={() => void respondToRequest(contact, true)}>Accept</Button><Button variant="ghost" disabled={requestBusy === contact.id} onClick={() => void respondToRequest(contact, false)}>Decline</Button></div></section>)}
          {groupInvitations.map((invitation) => <section className="request-card group-request-card" key={invitation.id}><div><span className="group-request-card__icon">{invitation.posting_policy === "owner_admins" ? <Megaphone size={18} /> : <Users size={19} />}</span><span><strong>{invitation.title}</strong><small>{invitation.owner_display_name} invited you</small></span></div><div><Button disabled={groupInvitationBusy === invitation.id} onClick={() => void respondToGroupInvitation(invitation, true)}>Accept</Button><Button variant="ghost" disabled={groupInvitationBusy === invitation.id} onClick={() => void respondToGroupInvitation(invitation, false)}>Decline</Button></div></section>)}
          {pending.length > 0 && !incomingRequest && <button className="pending-reminder" type="button" onClick={() => setDismissedRequests((current) => current.filter((id) => id !== pending[0].id))}><UserRoundPlus size={17} /> Review pending request</button>}
          {groupInvitations.length > 0 && !incomingGroupInvitation && <button className="pending-reminder" type="button" onClick={() => setDismissedGroupInvitations((current) => current.filter((id) => id !== groupInvitations[0].id))}><Users size={17} /> Review group invitation</button>}
          {hiddenConversationCount > 0 && <button className="deleted-conversations-toggle" type="button" aria-pressed={showDeletedConversations} onClick={() => setShowDeletedConversations((current) => !current)}><Trash2 size={16} /> {showDeletedConversations ? "Hide deleted conversations" : `Show deleted conversations (${hiddenConversationCount})`}</button>}
          {conversationItems.map((item) => item.kind === "contact" ? (
            <button key={`contact:${item.id}`} className={`contact-row ${selection?.kind === "contact" && selection.id === item.id ? "contact-row--selected" : ""}`} onClick={() => void restoreAndSelect({ kind: "contact", id: item.id }, item.hidden)} aria-label={item.hidden ? `Restore conversation with ${item.contact.display_name}` : undefined}>
              <Avatar name={item.contact.display_name} small /><span className="contact-row__content"><span><strong>{item.contact.display_name}</strong>{item.latest && <time>{formatTime(item.latest.created_at)}</time>}</span><span className="contact-row__preview">{item.hidden ? "Deleted locally · open to restore" : item.latest?.text ?? contactConnectionLabel(item.contact)}</span></span>
            </button>
          ) : (
            <button key={`group:${item.id}`} className={`contact-row ${selection?.kind === "group" && selection.id === item.id ? "contact-row--selected" : ""}`} onClick={() => void restoreAndSelect({ kind: "group", id: item.id }, item.hidden)} aria-label={item.hidden ? `Restore conversation ${item.group.title}` : undefined}>
              <GroupAvatar group={item.group} small /><span className="contact-row__content"><span><strong>{item.group.title}</strong>{item.latest && <time>{formatTime(item.latest.created_at)}</time>}</span><span className="contact-row__preview">{item.hidden ? "Deleted locally · open to restore" : item.latest ? `${item.latest.direction === "inbound" ? `${item.latest.sender_display_name}: ` : "You: "}${item.latest.text}` : groupPolicyLabel(item.group.posting_policy)}</span></span>
            </button>
          ))}
        </nav>
        <div className="new-conversation-actions">
          <button className="new-chat-button" aria-label="New chat" onClick={() => setNewChat(true)}><Plus size={20} /><span>New chat</span></button>
          <button className="new-group-button" aria-label="New group" onClick={() => setNewGroup(true)}><Users size={19} /><span>New group</span></button>
        </div>
        </> : selectedWorkspace ? <>
          <div className="workspace-sidebar-heading"><div className="workspace-sidebar-heading__avatar">{initials(selectedWorkspace.name)}</div><div><strong>{selectedWorkspace.name}</strong><small>{workspaceStateLabel(selectedWorkspace)}</small></div></div>
          {workspaceActionError && <p className="form-error sidebar-action-error" role="alert">{workspaceActionError}</p>}
          <nav className="contact-list workspace-nav" aria-label={`${selectedWorkspace.name} conversations`}>
            {workspaceJoinRequests.filter((request) => request.workspace_id === selectedWorkspace.id).map((request) => <section className="request-card workspace-join-request" key={request.id}><div><Avatar name={request.display_name} small /><span><strong>{request.display_name}</strong><small>Requests to join · {request.member_id.replaceAll("-", "").slice(0, 6)}</small></span></div><p className="request-fingerprint">{request.fingerprint}</p><div><Button disabled={workspaceActionBusy} onClick={() => void respondToWorkspaceJoin(request.id, true)}>Approve</Button><Button variant="ghost" disabled={workspaceActionBusy} onClick={() => void respondToWorkspaceJoin(request.id, false)}>Decline</Button></div></section>)}
            <p className="workspace-nav__label">Channels</p>
            {selectedWorkspaceChannels.filter((channel) => channel.visibility === "private" || channel.subscribed || channel.id === selectedWorkspace.general_channel_id || channel.id === selectedWorkspaceChannel?.id).map((channel) => <button key={channel.id} className={`contact-row workspace-channel-row ${selectedWorkspaceChannel?.id === channel.id ? "contact-row--selected" : ""}`} onClick={() => { setWorkspaceSelectedChannelId(channel.id); setWorkspaceSelectedDirectId(null); }}><span className="workspace-channel-icon">{channel.visibility === "private" ? <LockKeyhole size={18} /> : <Hash size={18} />}</span><span className="contact-row__content"><span><strong>{channel.display_name || channel.name}</strong>{channel.unread_count > 0 && <b className="unread-badge">{channel.unread_count}</b>}</span><span className="contact-row__preview">{channel.state === "archived" ? "Archived · read-only" : channel.state === "leaving" ? "Leaving · read-only" : channel.topic || (channel.visibility === "private" ? "Private signed roster" : "Everyone in the workspace")}</span></span></button>)}
            {selectedWorkspaceChannels.length === 0 && <div className="workspace-channel-pending"><RefreshCw size={16} /><span>{selectedWorkspace.state === "joining" ? "Waiting for #general access" : "Channel controls are syncing"}</span></div>}
            <button className="workspace-nav-action" onClick={() => setWorkspaceBrowseOpen(true)}><Search size={17} />Browse channels <span>{selectedWorkspace.channel_discovery === "converged" ? selectedWorkspaceChannels.length : "…"}</span></button>
            {selectedWorkspace.state === "active" && (selectedWorkspace.policies.channel_creation === "all_members" || selectedWorkspace.local_role === "owner") && <button className="workspace-nav-action" onClick={() => setWorkspaceCreateChannelOpen(true)}><Plus size={17} />Create channel</button>}
            <p className="workspace-nav__label">Direct messages</p>
            {selectedWorkspaceDirects.map((direct) => <button key={direct.id} className={`contact-row workspace-channel-row ${selectedWorkspaceDirect?.id === direct.id ? "contact-row--selected" : ""}`} onClick={() => { setWorkspaceSelectedDirectId(direct.id); setWorkspaceSelectedChannelId(null); }}><Avatar name={direct.peer_display_name} small /><span className="contact-row__content"><span><strong>{direct.peer_display_name}</strong>{direct.unread_count > 0 && <b className="unread-badge">{direct.unread_count}</b>}</span><span className="contact-row__preview">{direct.state === "read_only" ? "Former member · read-only" : `Workspace DM · ${direct.peer_short_id}`}</span></span></button>)}
            {selectedWorkspaceDirects.length === 0 && <p className="workspace-direct-empty">Start a private workspace chat from People.</p>}
            <p className="workspace-nav__label">Workspace</p>
            <button className="workspace-nav-action" onClick={() => setWorkspacePeopleOpen(true)}><Users size={17} />People <span>{selectedWorkspace.members.filter((member) => member.status === "active").length}</span></button>
            {selectedWorkspace.local_role === "owner" && selectedWorkspace.state === "active" && selectedWorkspace.members.filter((member) => member.status === "active").length < 8 && <button className="workspace-nav-action" onClick={() => setInviteWorkspaceOpen(true)}><UserRoundPlus size={17} />Invite people</button>}
            <button className="workspace-nav-action" onClick={() => setWorkspaceSettingsOpen(true)}><Settings size={17} />Workspace settings</button>
          </nav>
        </> : null}
        <footer className="sidebar__footer"><span className={`network-dot ${networkAvailable ? "network-dot--on" : ""}`} />{networkAvailable ? "Networking active" : "Networking unavailable"}</footer>
      </aside>
      <div className="main-pane">
        {snapshot.service_error && (
          <div className="service-warning" role="alert">
            <WifiOff size={18} />
            <span><strong>Networking is unavailable.</strong> Put both devices on the same local network and reopen Mesh Chat. Your profile and queued messages are safe.</span>
          </div>
        )}
        {selectedWorkspace ? (selectedWorkspaceDirect ? (
          <WorkspaceDirectConversation
            workspace={selectedWorkspace}
            direct={selectedWorkspaceDirect}
            page={workspacePage}
            draft={workspaceDrafts[selectedWorkspaceDirect.id] ?? ""}
            loading={workspacePageLoading}
            sending={workspaceSending}
            error={workspaceError}
            onDraft={(value) => { setWorkspaceError(""); saveWorkspaceDirectDraft(selectedWorkspace.id, selectedWorkspaceDirect.id, value); }}
            onSend={() => void sendWorkspaceMessage()}
            onLoadOlder={() => void loadWorkspaceMessages(true)}
            onHideMessage={(eventId) => void hideWorkspaceMessage(eventId)}
            onHideConversation={() => void hideWorkspaceDirect()}
            onPeople={() => setWorkspacePeopleOpen(true)}
          />
        ) : selectedWorkspaceChannel ? (
          <WorkspaceConversation
            workspace={selectedWorkspace}
            channel={selectedWorkspaceChannel}
            page={workspacePage}
            draft={workspaceDrafts[selectedWorkspaceChannel.id] ?? ""}
            loading={workspacePageLoading}
            sending={workspaceSending}
            error={workspaceError}
            onDraft={(value) => { setWorkspaceError(""); saveWorkspaceDraft(selectedWorkspace.id, selectedWorkspaceChannel.id, value); }}
            onSend={() => void sendWorkspaceMessage()}
            onLoadOlder={() => void loadWorkspaceMessages(true)}
            onHide={(eventId) => void hideWorkspaceMessage(eventId)}
            onPeople={() => setWorkspacePeopleOpen(true)}
            onSettings={() => setWorkspaceSettingsOpen(true)}
            onInvite={() => setInviteWorkspaceOpen(true)}
            onManage={() => setWorkspaceManageChannelOpen(true)}
          />
        ) : (
          <section className="empty-state workspace-waiting"><div className="empty-state__icon"><Building2 size={31} /></div><h1>{selectedWorkspace.name}</h1><p>{workspaceStateLabel(selectedWorkspace)}. Keep Mesh Chat open so signed membership and channel controls can arrive.</p><Button variant="secondary" onClick={() => setWorkspacePeopleOpen(true)}><Users size={18} /> People</Button></section>
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
      {joinWorkspaceOpen && <JoinWorkspaceDialog initialValue={initialInvitation.startsWith("meshchat://workspace/") || initialInvitation.trim().startsWith("MESHWORKSPACE1:") || initialInvitation.includes("workspace_invite") ? initialInvitation : ""} onClose={() => { setJoinWorkspaceOpen(false); onInvitationHandled(); }} onJoined={async (workspace) => { await refresh(true); setActiveSpaceId(workspace.id); setJoinWorkspaceOpen(false); onInvitationHandled(); }} />}
      {selectedWorkspace && workspaceBrowseOpen && <BrowseWorkspaceChannelsDialog workspace={selectedWorkspace} channels={selectedWorkspaceChannels.filter((channel) => channel.visibility === "public")} busy={workspaceActionBusy} error={workspaceActionError} onClose={() => setWorkspaceBrowseOpen(false)} onOpen={(channelId) => { setWorkspaceSelectedChannelId(channelId); setWorkspaceSelectedDirectId(null); setWorkspaceBrowseOpen(false); }} onSubscribe={(channelId, subscribed) => void runWorkspaceChannelAction("set_workspace_channel_subscription", { channel_id: channelId, subscribed })} onSync={() => void runWorkspaceChannelAction("sync_workspace_channels")} onCreate={() => { setWorkspaceBrowseOpen(false); setWorkspaceCreateChannelOpen(true); }} />}
      {selectedWorkspace && workspaceCreateChannelOpen && <CreateWorkspaceChannelDialog workspace={selectedWorkspace} busy={workspaceActionBusy} error={workspaceActionError} onClose={() => setWorkspaceCreateChannelOpen(false)} onCreate={(name, topic, visibility, memberIds) => void runWorkspaceChannelAction("create_workspace_channel", { name, topic, visibility, member_ids: memberIds })} />}
      {selectedWorkspace && selectedWorkspaceChannel && workspaceManageChannelOpen && <ManageWorkspaceChannelDialog workspace={selectedWorkspace} channel={selectedWorkspaceChannel} transfers={workspaceChannelTransfers.filter((item) => item.workspace_id === selectedWorkspace.id)} busy={workspaceActionBusy} error={workspaceActionError} onClose={() => setWorkspaceManageChannelOpen(false)} onUpdate={(name, topic, archived) => void runWorkspaceChannelAction("update_workspace_channel", { channel_id: selectedWorkspaceChannel.id, name, topic, archived })} onMembers={(memberIds) => void runWorkspaceChannelAction("update_workspace_private_channel_members", { channel_id: selectedWorkspaceChannel.id, member_ids: memberIds })} onLeave={() => void runWorkspaceChannelAction("leave_workspace_private_channel", { channel_id: selectedWorkspaceChannel.id })} onOfferTransfer={(successorMemberId) => void runWorkspaceChannelAction("offer_workspace_channel_transfer", { channel_id: selectedWorkspaceChannel.id, successor_member_id: successorMemberId })} onAcceptTransfer={(transferId) => void runWorkspaceChannelAction("accept_workspace_channel_transfer", { transfer_id: transferId })} onRecover={() => void runWorkspaceChannelAction("recover_workspace_channel", { channel_id: selectedWorkspaceChannel.id })} />}
      {selectedWorkspace && inviteWorkspaceOpen && <WorkspaceInviteDialog workspace={selectedWorkspace} existingInvitations={workspaceInvitations.filter((invitation) => invitation.workspace_id === selectedWorkspace.id)} onClose={() => setInviteWorkspaceOpen(false)} />}
      {selectedWorkspace && workspacePeopleOpen && <WorkspacePeopleDialog workspace={selectedWorkspace} requests={workspaceDisplayNameRequests.filter((request) => request.workspace_id === selectedWorkspace.id)} busy={workspaceActionBusy} error={workspaceActionError} onClose={() => setWorkspacePeopleOpen(false)} onRequestName={(displayName) => void runWorkspaceAdministration("request_workspace_display_name", { display_name: displayName })} onDecideName={(requestId, approve) => void runWorkspaceAdministration("decide_workspace_display_name", { request_id: requestId, approve })} onRemove={(memberId) => void runWorkspaceAdministration("remove_workspace_member", { member_id: memberId })} onMessage={(memberId) => void openWorkspaceDirect(memberId)} />}
      {selectedWorkspace && workspaceSettingsOpen && <WorkspaceSettingsDialog workspace={selectedWorkspace} networkSettings={snapshot.settings} busy={workspaceActionBusy} error={workspaceActionError} onClose={() => setWorkspaceSettingsOpen(false)} onUpdateMetadata={(name, description) => void runWorkspaceAdministration("update_workspace_metadata", { name, description })} onUpdatePolicies={(channelCreation, posting) => void runWorkspaceAdministration("update_workspace_policies", { channel_creation: channelCreation, posting })} onApprovePropagationNode={(node) => void approveWorkspacePropagationNode(node)} onCloseWorkspace={() => void runWorkspaceLifecycle("close_workspace")} onLeave={() => void runWorkspaceLifecycle("leave_workspace")} onRemove={(confirmation) => void runWorkspaceLifecycle("remove_workspace_data", confirmation)} />}
      {newChat && <div className={hasForegroundRequest ? "dialog-suspended" : ""} aria-hidden={hasForegroundRequest ? true : undefined}><NewChatDialog initialInvitation={initialInvitation} onClose={() => { setNewChat(false); onInvitationHandled(); }} onChanged={async () => { await refresh(true); }} /></div>}
      {newGroup && <div className={hasForegroundRequest ? "dialog-suspended" : ""} aria-hidden={hasForegroundRequest ? true : undefined}><CreateGroupDialog contacts={snapshot.contacts} onClose={() => setNewGroup(false)} onCreated={async (group) => { await refresh(true); selectConversation({ kind: "group", id: group.id }); setNewGroup(false); }} /></div>}
      {contactsOpen && <div className={hasForegroundRequest ? "dialog-suspended" : ""} aria-hidden={hasForegroundRequest ? true : undefined}><ContactsDialog contacts={snapshot.contacts.filter((contact) => contact.trust !== "pending_request")} onClose={() => setContactsOpen(false)} onChanged={async () => { await refresh(true); }} onOpenConversation={async (contact) => { const hidden = hiddenConversationKeys.has(`direct:${contact.id}`); setContactsOpen(false); await restoreAndSelect({ kind: "contact", id: contact.id }, hidden); }} onDeleted={async (contactId) => { if (selection?.kind === "contact" && selection.id === contactId) setSelection(null); setDrafts((current) => { const next = { ...current }; delete next[contactId]; return next; }); setLocallySavedMessages((current) => Object.fromEntries(Object.entries(current).filter(([, message]) => message.contact_id !== contactId))); await refresh(true); }} /></div>}
      {settings && <div className={hasForegroundRequest ? "dialog-suspended" : ""} aria-hidden={hasForegroundRequest ? true : undefined}><SettingsDialog snapshot={snapshot} onClose={() => setSettings(false)} onSaved={async () => { await refresh(true); }} /></div>}
      {deleteTarget && <div className={hasForegroundRequest ? "dialog-suspended" : ""} aria-hidden={hasForegroundRequest ? true : undefined}><DeleteConversationDialog kind={deleteTarget.kind === "contact" ? "direct" : "group"} name={deleteTargetName} busy={deleteBusy} error={deleteError} onCancel={() => { if (!deleteBusy) { setDeleteError(""); setDeleteTarget(null); } }} onConfirm={() => void deleteConversation()} /></div>}
      {help && <div className={hasForegroundRequest ? "dialog-suspended" : ""} aria-hidden={hasForegroundRequest ? true : undefined}><Dialog title="Connection help" onClose={() => setHelp(null)}><div className="help-content">{help.code === "service_unavailable" ? <><WifiOff size={28} /><h3>Networking is unavailable</h3><p>Connect this device to the same local network as {selectedContact?.display_name}, make sure local-network access is allowed, then reopen Mesh Chat.</p></> : help.code === "waiting_for_keys" ? <><WifiOff size={28} /><h3>Trying to find {selectedContact?.display_name}</h3><p>Keep Mesh Chat open on both devices and connect them to the same local network. We’ll continue trying automatically.</p></> : help.code === "no_route" ? <><WifiOff size={28} /><h3>We can’t reach them yet</h3><p>Your message is saved. Try the same local network, check local-network permission, or request a fresh invitation with a usable connection hint.</p></> : <><Check size={28} /><h3>The secure path is ready</h3><p>Mesh Chat is continuing the connection automatically.</p></>}<Button onClick={() => setHelp(null)}>Done</Button></div></Dialog></div>}
      {incomingRequest && <IncomingRequestDialog contact={incomingRequest} busy={requestBusy === incomingRequest.id} error={requestError} onAccept={() => void respondToRequest(incomingRequest, true)} onDecline={() => void respondToRequest(incomingRequest, false)} onClose={() => { setRequestError(""); setDismissedRequests((current) => [...new Set([...current, incomingRequest.id])]); }} />}
      {foregroundGroupInvitation && <GroupInvitationDialog invitation={foregroundGroupInvitation} busy={groupInvitationBusy === foregroundGroupInvitation.id} error={groupInvitationError} onAccept={() => void respondToGroupInvitation(foregroundGroupInvitation, true)} onDecline={() => void respondToGroupInvitation(foregroundGroupInvitation, false)} onClose={() => { setGroupInvitationError(""); setDismissedGroupInvitations((current) => [...new Set([...current, foregroundGroupInvitation.id])]); }} />}
    </main>
  );
}

export default function App() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [initialInvitation, setInitialInvitation] = useState("");
  const [workspaceChannelInvalidation, setWorkspaceChannelInvalidation] = useState<ServiceEvent | null>(null);
  const [fatal, setFatal] = useState("");
  const [locked, setLocked] = useState(false);
  const refreshInFlight = useRef<Promise<Snapshot> | null>(null);
  const workspaceRefreshInFlight = useRef<Promise<WorkspaceSnapshot> | null>(null);
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
    return () => { active = false; cleanups.forEach((cleanup) => cleanup()); };
  }, [refresh, refreshWorkspace]);
  useEffect(() => {
    let active = true;
    let timer: number | undefined;
    const refreshVisible = () => {
      if (active && document.visibilityState === "visible") void refresh().catch(() => undefined);
    };
    const onVisibility = () => refreshVisible();
    window.addEventListener("focus", refreshVisible);
    document.addEventListener("visibilitychange", onVisibility);
    void runtimePlatform().then((platform) => {
      if (active && platform === "desktop") timer = window.setInterval(refreshVisible, 3000);
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
  if (!snapshot.profile) return <Onboarding initialInvitation={initialInvitation} onReady={setSnapshot} />;
  return <Messenger snapshot={snapshot} refresh={refresh} workspaceChannelInvalidation={workspaceChannelInvalidation} initialInvitation={initialInvitation} onInvitationHandled={() => setInitialInvitation("")} onLock={async () => { await lockService(); setSnapshot(null); setLocked(true); }} />;
}

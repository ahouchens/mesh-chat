import type { CallIceConfiguration } from "./types";
import type { WebRTCSessionPath } from "./webrtc-session";

export type ReconnectState =
  | "idle"
  | "waiting_for_peer"
  | "probing"
  | "offer_pending"
  | "answer_pending"
  | "connecting"
  | "connected"
  | "retry_wait"
  | "peer_offline"
  | "manual_required"
  | "stopped";

export type ReconnectRole = "request" | "offer" | "answer";

export interface ReconnectEffective {
  ready: boolean;
  configured: boolean;
  preferred: boolean;
  session: string | null;
  mailbox_url: string | null;
  source: "local" | "remote" | null;
  reasons: string[];
}

export interface ReconnectProfile {
  native_session_id?: string;
  id: string;
  contact_id: string;
  display_name?: string;
  destination_hash?: string;
  trust?: string;
  local_device_id: string;
  remote_device_id: string | null;
  auto_reconnect: boolean;
  auto_reconnect_preference?: "default" | "explicit" | "legacy_disabled";
  allow_direct_ip_disclosure: boolean;
  relay_consent_scope: string;
  peer_auto_reconnect: boolean;
  peer_allow_direct_ip_disclosure: boolean;
  has_local_capabilities: boolean;
  has_peer_capabilities: boolean;
  capabilities_expires_at: number;
  peer_capabilities_expires_at: number;
  capabilities_persistent?: boolean;
  peer_capabilities_persistent?: boolean;
  state: ReconnectState;
  active: boolean;
  last_attempt_at: number;
  last_error: string;
  updated_at: number;
  effective: ReconnectEffective;
}

export interface ReconnectProfilesPayload {
  local_device_id: string;
  local_destination?: string;
  mailbox_configured: boolean;
  profiles: ReconnectProfile[];
}

export interface ReconnectEntry {
  profileId: string;
  contactId: string;
  displayName: string;
  state: ReconnectState;
  detail: string;
  attempts: number;
  nextAttemptAt: number | null;
  path: WebRTCSessionPath | null;
  updatedAt: number;
}

export interface ReconnectSnapshot {
  running: boolean;
  entries: Record<string, ReconnectEntry>;
}

export interface CoordinatorPeer {
  createOffer(): Promise<string>;
  createAnswer(remoteOffer: string): Promise<string>;
  applyAnswer(remoteAnswer: string): Promise<void>;
  open(): Promise<unknown>;
  path(): Promise<WebRTCSessionPath>;
  close(): void;
}

export interface ReconnectCoordinatorDeps {
  profiles(): Promise<ReconnectProfilesPayload>;
  start(contactId: string): Promise<unknown>;
  stop(contactId?: string): Promise<unknown>;
  requestCreate(
    contactId: string,
    attemptId: string,
  ): Promise<{ document: string; expires_at: number }>;
  offerCreate(
    contactId: string,
    requestDocument: string,
    sdp: string,
    fingerprint: string,
  ): Promise<{ document: string; session_id: string; expires_at: number }>;
  answerCreate(
    contactId: string,
    offerDocument: string,
    sdp: string,
    fingerprint: string,
  ): Promise<{ document: string; expires_at: number }>;
  verifyRequest(document: string, profileId?: string): Promise<{ contact_id: string; attempt_id: string }>;
  verifyOffer(document: string, profileId?: string): Promise<{ sdp: string; attempt_id: string }>;
  verifyAnswer(
    document: string,
    offerDocument: string,
    profileId?: string,
  ): Promise<{ sdp: string; attempt_id: string }>;
  publish(profileId: string, document: string, role: ReconnectRole): Promise<unknown>;
  fetch(
    profileId: string,
    role: ReconnectRole,
  ): Promise<{ document: string | null; pending: boolean }>;
  status(state: ReconnectState, detail?: string, attemptId?: string): Promise<unknown>;
  ice(profile: ReconnectProfile): Promise<CallIceConfiguration>;
  createPeer(ice: CallIceConfiguration, role: "offer" | "answer", profile?: ReconnectProfile): CoordinatorPeer;
  attach(peer: CoordinatorPeer, profile: ReconnectProfile, isCurrent?: () => boolean): Promise<void>;
  pathStatus?(
    contactId: string,
  ): Promise<{ has_path: boolean; ready?: boolean; state: string; reason: string | null }>;
  /** True when this profile or its contact already has a live WebRTC transport. */
  hasSession?(profileId: string, contactId: string): boolean;
  closeSession?(profileId: string): Promise<void>;
  now?(): number;
  random?(): number;
  sleep?(ms: number): Promise<void>;
  fingerprint?(sdp: string): string;
}

export const BACKOFF_MS = [1000, 2000, 5000, 15000, 30000, 60000] as const;
export const MAX_ATTEMPTS = 20;
export const MAX_CONCURRENT = 2;
export const REQUEST_POLL_MS = 25000;
export const ANSWER_POLL_MS = 25000;
export const OPEN_TIMEOUT_MS = 30000;
export const PATH_TIMEOUT_MS = 10000;
export const MAILBOX_POLL_MS = 5000;
export const PATH_POLL_MS = 5000;

export const RECONNECT_STATUS_LABELS: Record<ReconnectState, string> = {
  idle: "Not connected",
  waiting_for_peer: "Waiting for peer",
  probing: "Reconnecting…",
  offer_pending: "Waiting for peer",
  answer_pending: "Reconnecting…",
  connecting: "Connecting…",
  connected: "Connected",
  retry_wait: "Reconnecting shortly",
  peer_offline: "Peer offline",
  manual_required: "Manual reconnect required",
  stopped: "Auto-reconnect is off",
};

export function reconnectStatusLabel(entry: ReconnectEntry | undefined): string {
  if (!entry) return "Auto-reconnect is off";
  if (entry.state === "retry_wait" && entry.nextAttemptAt) {
    const seconds = Math.max(0, Math.ceil(entry.nextAttemptAt - Date.now() / 1000));
    return `Reconnecting in ${seconds}s`;
  }
  return RECONNECT_STATUS_LABELS[entry.state];
}

export function reconnectStatusDetail(entry: ReconnectEntry | undefined): string {
  if (!entry) return "";
  if (entry.state === "manual_required") {
    if (entry.detail === "mailbox_not_configured") {
      return "No signaling mailbox is configured on this device. Configure one or exchange a fresh link.";
    }
    return entry.detail || "A manual reconnect is required.";
  }
  if (entry.state === "peer_offline") return "The peer has not answered. Mesh Chat will keep trying while this app is open.";
  if (entry.state === "connected") {
    if (entry.detail) return entry.detail;
    return entry.path === "relayed"
      ? "Connected over the community relay."
      : entry.path === "direct"
        ? "Connected directly."
        : "Connected. Path details are still settling.";
  }
  if (entry.state === "retry_wait") return entry.detail || "Waiting before the next attempt.";
  if (entry.state === "waiting_for_peer") return entry.detail || "Waiting for the other device.";
  return entry.detail;
}

type Listener = () => void;

function makeAttemptId(): string {
  const value =
    typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
      ? crypto.randomUUID()
      : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 14)}`;
  return value.replace(/[^A-Za-z0-9_-]/g, "-");
}

function errorCode(reason: unknown): string {
  if (reason && typeof reason === "object" && "code" in reason) {
    return String((reason as { code?: unknown }).code ?? "");
  }
  return "";
}

function safeMessage(reason: unknown): string {
  const code = errorCode(reason);
  if (code) return code;
  return reason instanceof Error ? reason.message.slice(0, 120) : "Reconnect attempt failed";
}

/**
 * Renderer-owned reconnect coordinator.
 *
 * The Python service owns trust, capabilities, signatures, replay state, and
 * mailbox I/O. This class owns only the lifecycle of fresh RTCPeerConnections
 * and never opens a dialog, steals focus, or asks for contact approval.
 *
 * Protocol shape (bound by the signed documents):
 *   preferred device  -> publishes a signed request
 *   other device      -> verifies it, creates the offer, publishes the offer
 *   preferred device  -> verifies the offer, creates the answer, publishes it
 *   other device      -> verifies the answer, applies it
 * Only the preferred device publishes a request, so one attempt yields one
 * offer: simultaneous starts cannot glare.
 */
interface RetryProgress {
  attempts: number;
  nextAt: number;
  attemptId: string;
  requestDocument: string;
  requestExpiresAt: number;
  waitingForOfferUntil: number;
  rateLimitedUntil?: number;
  blockedSignature?: string;
}

interface RunningAttempt {
  profile: ReconnectProfile;
  controller: AbortController;
  peer: CoordinatorPeer | null;
}

class ReconnectCancelled extends Error {}

const SUPERVISOR_INTERVAL_MS = 1000;
const TERMINAL_ERRORS = ["mailbox_unauthorized", "contact_not_approved", "identity_mismatch"];
const POLL_TERMINAL_ERRORS = ["mailbox_unauthorized", "contact_not_approved", "mailbox_rate_limited"];

export class ReconnectCoordinator {
  private readonly deps: ReconnectCoordinatorDeps;
  private readonly listeners = new Set<Listener>();
  private entries: Record<string, ReconnectEntry> = {};
  private profiles = new Map<string, ReconnectProfile>();
  private running = false;
  private online = true;
  private supervisor: Promise<void> | null = null;
  private wakeSupervisor: (() => void) | null = null;
  private readonly attempts = new Map<string, RunningAttempt>();
  private readonly retries = new Map<string, RetryProgress>();
  private readonly stoppedContacts = new Set<string>();
  private readonly stoppedProfiles = new Set<string>();
  private readonly startedProfiles = new Set<string>();
  private readonly lastScheduled = new Map<string, number>();
  private readonly pathChecks = new Set<string>();
  private readonly nextPathCheckAt = new Map<string, number>();
  private scheduleOrder = 0;

  constructor(deps: ReconnectCoordinatorDeps) {
    this.deps = deps;
  }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  snapshot(): ReconnectSnapshot {
    return { running: this.running, entries: { ...this.entries } };
  }

  isActive(): boolean {
    return this.running;
  }

  /** Resume ordinary retries without undoing a contact's Stop or a trust block. */
  wake(): void {
    if (!this.running || !this.online) return;
    const now = this.clock();
    for (const retry of this.retries.values()) {
      if (!retry.blockedSignature) retry.nextAt = Math.max(now, retry.rateLimitedUntil ?? 0);
    }
    this.nextPathCheckAt.clear();
    this.ensureSupervisor();
    this.wakeSupervisor?.();
  }

  setOnline(online: boolean): boolean {
    if (this.online === online) return false;
    this.online = online;
    if (online) this.wake();
    else {
      this.cancelAttempts();
      this.wakeSupervisor?.();
    }
    return true;
  }

  async start(): Promise<void> {
    if (this.running) return;
    this.running = true;
    this.stoppedContacts.clear();
    this.stoppedProfiles.clear();
    this.emit();
    this.ensureSupervisor();
  }

  async refresh(): Promise<void> {
    try {
      const payload = await this.deps.profiles();
      if (Array.isArray(payload?.profiles)) this.reconcile(payload.profiles);
    } catch {
      // Service startup, locking and network changes are retried by supervision.
    }
  }

  async stop(contactId?: string): Promise<void> {
    if (contactId === undefined) this.running = false;
    else this.stoppedContacts.add(contactId);
    const selected = Object.values(this.entries).filter((entry) => !contactId || entry.contactId === contactId);
    // Cancellation is synchronous, before any native cleanup can yield.
    for (const entry of selected) {
      this.stoppedProfiles.add(entry.profileId);
      this.startedProfiles.delete(entry.profileId);
      entry.state = "stopped";
      entry.detail = "Stopped by you";
      entry.nextAttemptAt = null;
      entry.updatedAt = this.now();
    }
    this.cancelAttempts(contactId);
    this.wakeSupervisor?.();
    this.emit();
    await Promise.all(selected.map(async (entry) => {
      try { await this.deps.closeSession?.(entry.profileId); } catch { /* Already closed. */ }
    }));
    try { await this.deps.stop(contactId); } catch { /* Local cancellation is already effective. */ }
  }

  async retryNow(contactId?: string): Promise<void> {
    // Keep the one supervisor and leave other contacts and healthy sessions alone.
    this.cancelAttempts(contactId);
    if (contactId) this.stoppedContacts.delete(contactId);
    else this.stoppedContacts.clear();
    for (const entry of Object.values(this.entries)) {
      if (contactId && entry.contactId !== contactId) continue;
      this.stoppedProfiles.delete(entry.profileId);
      this.startedProfiles.delete(entry.profileId);
      this.retries.delete(entry.profileId);
      if (this.hasSession(entry.profileId, entry.contactId)) continue;
      entry.state = "waiting_for_peer";
      entry.detail = "Retrying now";
      entry.attempts = 0;
      entry.nextAttemptAt = null;
      entry.updatedAt = this.now();
    }
    this.running = true;
    this.emit();
    this.ensureSupervisor();
    this.wakeSupervisor?.();
  }

  private emit(): void {
    for (const listener of this.listeners) listener();
  }

  private now(): number { return Math.floor(this.clock() / 1000); }
  private clock(): number { return this.deps.now?.() ?? Date.now(); }
  private hasSession(profileId: string, contactId: string): boolean {
    return this.deps.hasSession?.(profileId, contactId) ?? this.entries[profileId]?.state === "connected";
  }
  private isReady(profile: ReconnectProfile): boolean {
    return Boolean(profile.auto_reconnect && profile.peer_auto_reconnect && profile.effective.ready && profile.effective.configured);
  }
  private signature(profile: ReconnectProfile): string {
    return JSON.stringify([profile.auto_reconnect, profile.peer_auto_reconnect, profile.capabilities_expires_at, profile.peer_capabilities_expires_at, profile.effective]);
  }

  private ensureSupervisor(): void {
    if (this.supervisor) return;
    const task = this.supervise();
    this.supervisor = task;
    void task.finally(() => {
      if (this.supervisor !== task) return;
      this.supervisor = null;
      if (this.running) this.ensureSupervisor();
    });
  }

  private async supervise(): Promise<void> {
    while (this.running) {
      if (!this.online) {
        await this.pauseSupervisor();
        continue;
      }
      await this.refresh();
      if (!this.running) break;
      if (!this.online) continue;
      const eligible = [...this.profiles.values()].filter((profile) => {
        if (this.stoppedContacts.has(profile.contact_id) || this.stoppedProfiles.has(profile.id)) return false;
        if (this.hasSession(profile.id, profile.contact_id)) {
          this.retries.delete(profile.id);
          this.monitorPath(profile);
          return false;
        }
        if (!profile.auto_reconnect) {
          this.setState(profile, "stopped", "Automatic reconnect is off on this device.");
          return false;
        }
        if (!profile.peer_auto_reconnect) {
          this.setState(profile, "manual_required", "The contact has not enabled automatic reconnect on their device.");
          return false;
        }
        if (!profile.effective.configured || !profile.effective.ready) {
          this.setState(profile, "manual_required", !profile.effective.configured ? "mailbox_not_configured" : profile.effective.reasons.join(", "));
          return false;
        }
        const retry = this.retries.get(profile.id);
        if (retry?.blockedSignature === this.signature(profile)) return false;
        return !this.attempts.has(profile.id) && (!retry || retry.nextAt <= this.clock());
      });
      // Each attempt yields its slot; least recently scheduled profiles go first.
      eligible.sort((a, b) => (this.lastScheduled.get(a.id) ?? 0) - (this.lastScheduled.get(b.id) ?? 0));
      for (const profile of eligible) {
        if (this.attempts.size >= MAX_CONCURRENT) break;
        const attempt: RunningAttempt = { profile, controller: new AbortController(), peer: null };
        this.attempts.set(profile.id, attempt);
        this.lastScheduled.set(profile.id, ++this.scheduleOrder);
        void this.runAttempt(attempt).finally(() => {
          if (this.attempts.get(profile.id) === attempt) this.attempts.delete(profile.id);
          this.wakeSupervisor?.();
        });
      }
      await this.pauseSupervisor();
    }
  }

  private pauseSupervisor(): Promise<void> {
    return new Promise((resolve) => {
      let finished = false;
      let timer: number | undefined;
      const finish = () => {
        if (finished) return;
        finished = true;
        if (timer !== undefined) window.clearTimeout(timer);
        if (this.wakeSupervisor === finish) this.wakeSupervisor = null;
        resolve();
      };
      this.wakeSupervisor = finish;
      if (this.deps.sleep) void this.deps.sleep(SUPERVISOR_INTERVAL_MS).then(finish, finish);
      else timer = window.setTimeout(finish, SUPERVISOR_INTERVAL_MS);
    });
  }

  private cancelAttempts(contactId?: string): void {
    for (const attempt of this.attempts.values()) {
      if (contactId && attempt.profile.contact_id !== contactId) continue;
      attempt.controller.abort();
      try { attempt.peer?.close(); } catch { /* Already closed. */ }
      // Keep the slot until its pending native operation settles. A retry must
      // not create overlapping fetches or publish a second offer for this peer.
    }
  }

  private current(attempt: RunningAttempt): boolean {
    const profile = this.profiles.get(attempt.profile.id);
    return this.running && this.online && !attempt.controller.signal.aborted &&
      this.attempts.get(attempt.profile.id) === attempt &&
      !this.stoppedContacts.has(attempt.profile.contact_id) && !this.stoppedProfiles.has(attempt.profile.id) &&
      Boolean(profile && this.isReady(profile));
  }

  private reconcile(profiles: ReconnectProfile[]): void {
    this.profiles = new Map(profiles.map((profile) => [profile.id, profile]));
    const next: Record<string, ReconnectEntry> = {};
    for (const profile of profiles) {
      next[profile.id] = this.entries[profile.id] ?? {
        profileId: profile.id, contactId: profile.contact_id,
        displayName: profile.display_name ?? "Contact", state: profile.state,
        detail: profile.last_error, attempts: 0, nextAttemptAt: null, path: null,
        updatedAt: profile.updated_at,
      };
      next[profile.id].contactId = profile.contact_id;
      next[profile.id].displayName = profile.display_name ?? next[profile.id].displayName;
      if (this.stoppedContacts.has(profile.contact_id) || this.stoppedProfiles.has(profile.id)) {
        next[profile.id].state = "stopped";
        next[profile.id].detail = "Stopped by you";
        next[profile.id].nextAttemptAt = null;
      }
    }
    this.entries = next;
    for (const attempt of this.attempts.values()) {
      if (this.current(attempt)) continue;
      attempt.controller.abort();
      try { attempt.peer?.close(); } catch { /* Already closed. */ }
    }
    this.emit();
  }

  private setState(profile: ReconnectProfile, state: ReconnectState, detail = ""): void {
    if (this.stoppedContacts.has(profile.contact_id) || this.stoppedProfiles.has(profile.id)) return;
    const entry = this.entries[profile.id];
    if (!entry || (entry.state === state && entry.detail === detail)) return;
    entry.state = state;
    entry.detail = detail;
    entry.updatedAt = this.now();
    if (state !== "retry_wait") entry.nextAttemptAt = null;
    this.emit();
    void this.deps.status(state, detail).catch(() => undefined);
  }

  private monitorPath(profile: ReconnectProfile): void {
    if (!this.deps.pathStatus || this.attempts.has(profile.id) || this.pathChecks.has(profile.id) ||
        this.pathChecks.size >= MAX_CONCURRENT || (this.nextPathCheckAt.get(profile.id) ?? 0) > this.clock()) return;
    const entry = this.entries[profile.id];
    this.pathChecks.add(profile.id);
    this.nextPathCheckAt.set(profile.id, this.clock() + PATH_POLL_MS);
    void this.deps.pathStatus(profile.contact_id).then((status) => {
      if (!this.running || !this.online || this.entries[profile.id] !== entry ||
          !this.hasSession(profile.id, profile.contact_id)) return;
      if (status.has_path && status.ready !== false) {
        this.setState(profile, "connected", "Secure messaging route ready.");
      } else {
        this.setState(profile, "connecting", "Connection open; waiting for the secure messaging route.");
      }
    }).catch(() => {
      // A temporary native query failure does not close a healthy DataChannel.
    }).finally(() => this.pathChecks.delete(profile.id));
  }

  private async attemptSleep(ms: number, signal: AbortSignal): Promise<void> {
    if (signal.aborted) throw new ReconnectCancelled();
    let cancel: (() => void) | undefined;
    let timer: number | undefined;
    try {
      await Promise.race([
        this.deps.sleep ? this.deps.sleep(ms) : new Promise<void>((resolve) => { timer = window.setTimeout(resolve, ms); }),
        new Promise<void>((_, reject) => {
          cancel = () => reject(new ReconnectCancelled());
          signal.addEventListener("abort", cancel, { once: true });
        }),
      ]);
    } finally {
      if (timer !== undefined) window.clearTimeout(timer);
      if (cancel) signal.removeEventListener("abort", cancel);
    }
  }

  private async runAttempt(attempt: RunningAttempt): Promise<void> {
    const profile = attempt.profile;
    let attached = false;
    const check = () => {
      if (!this.current(attempt) || (!attached && this.hasSession(profile.id, profile.contact_id))) throw new ReconnectCancelled();
    };
    const step = async <T,>(operation: () => Promise<T>): Promise<T> => {
      check();
      const result = await operation();
      check();
      return result;
    };
    let retry = this.retries.get(profile.id);
    if (!retry || retry.blockedSignature) {
      retry = { attempts: 0, nextAt: 0, attemptId: makeAttemptId(), requestDocument: "", requestExpiresAt: 0, waitingForOfferUntil: 0 };
      this.retries.set(profile.id, retry);
    }
    const poll = async (role: ReconnectRole, timeout: number, accept: (document: string) => Promise<boolean>): Promise<string | null> => {
      const deadline = this.clock() + timeout;
      do {
        try {
          const fetched = await step(() => this.deps.fetch(profile.id, role));
          if (!fetched.pending && fetched.document && await step(() => accept(fetched.document!))) return fetched.document;
        } catch (reason) {
          // A stable pair mailbox may still contain the previous handshake's
          // answer. Reject that document, but keep waiting for the current
          // signed response instead of permanently blocking the contact.
          if (reason instanceof ReconnectCancelled || POLL_TERMINAL_ERRORS.includes(errorCode(reason))) throw reason;
        }
        if (this.clock() >= deadline) return null;
        await this.attemptSleep(1000, attempt.controller.signal);
        check();
      } while (this.clock() < deadline);
      return null;
    };
    try {
      check();
      if (!this.startedProfiles.has(profile.id)) {
        await step(() => this.deps.start(profile.contact_id));
        this.startedProfiles.add(profile.id);
      }
      if (profile.effective.preferred) {
        this.setState(profile, "probing", "Publishing a signed reconnect request");
        if (!retry.requestDocument || retry.requestExpiresAt <= this.now()) {
          if (retry.requestDocument) retry.attemptId = makeAttemptId();
          const request = await step(() => this.deps.requestCreate(profile.contact_id, retry!.attemptId));
          retry.requestDocument = request.document;
          retry.requestExpiresAt = request.expires_at;
          retry.waitingForOfferUntil = 0;
        }
        if (!retry.waitingForOfferUntil) {
          await step(() => this.deps.publish(profile.id, retry!.requestDocument, "request"));
          retry.waitingForOfferUntil = this.clock() + REQUEST_POLL_MS;
        }
        let offer: { sdp: string; attempt_id: string } | undefined;
        const offerDocument = await poll("offer", 0, async (document) => {
          const verified = await this.deps.verifyOffer(document, profile.id);
          if (verified.attempt_id !== retry!.attemptId) return false;
          offer = verified;
          return true;
        });
        if (!offerDocument || !offer) {
          if (this.clock() >= retry.waitingForOfferUntil) {
            retry.waitingForOfferUntil = 0;
            throw new Error("offer_timeout");
          }
          // Waiting for an offline contact must not occupy one of the two
          // peer-connection workers and delay every contact behind it.
          retry.nextAt = this.clock() + MAILBOX_POLL_MS;
          this.setState(profile, "waiting_for_peer", "Waiting for the other device; reconnect continues automatically.");
          return;
        }
        retry.waitingForOfferUntil = 0;
        const ice = await step(() => this.deps.ice(profile));
        attempt.peer = this.deps.createPeer(ice, "answer", profile);
        const sdp = await step(() => attempt.peer!.createAnswer(offer!.sdp));
        const answer = await step(() => this.deps.answerCreate(profile.contact_id, offerDocument, sdp, this.deps.fingerprint?.(sdp) ?? fingerprintOf(sdp)));
        await step(() => this.deps.publish(profile.id, answer.document, "answer"));
      } else {
        this.setState(profile, "waiting_for_peer", "Waiting for a signed reconnect request");
        // A missing request must not occupy a worker for the lifetime of an offline peer.
        const requestDocument = await poll("request", 0, async (document) => {
          const request = await this.deps.verifyRequest(document, profile.id);
          return request.contact_id === profile.contact_id;
        });
        if (!requestDocument) {
          retry.nextAt = this.clock() + MAILBOX_POLL_MS;
          return;
        }
        const ice = await step(() => this.deps.ice(profile));
        attempt.peer = this.deps.createPeer(ice, "offer", profile);
        const sdp = await step(() => attempt.peer!.createOffer());
        const offer = await step(() => this.deps.offerCreate(profile.contact_id, requestDocument, sdp, this.deps.fingerprint?.(sdp) ?? fingerprintOf(sdp)));
        await step(() => this.deps.publish(profile.id, offer.document, "offer"));
        this.setState(profile, "answer_pending", "Waiting for the answer");
        let answer: { sdp: string } | undefined;
        const answerDocument = await poll("answer", ANSWER_POLL_MS, async (document) => {
          answer = await this.deps.verifyAnswer(document, offer.document, profile.id);
          return true;
        });
        if (!answerDocument || !answer) throw new Error("answer_timeout");
        await step(() => attempt.peer!.applyAnswer(answer!.sdp));
      }
      this.setState(profile, "connecting", "Opening the DataChannel");
      await step(() => attempt.peer!.open());
      check();
      await this.deps.attach(attempt.peer!, profile, () => this.current(attempt));
      attached = true;
      check();
      const path = await step(() => attempt.peer!.path().catch(() => "unknown" as WebRTCSessionPath));
      const entry = this.entries[profile.id];
      if (entry) entry.path = path;
      let detail = "Fresh WebRTC transport attached.";
      let messagingReady = !this.deps.pathStatus;
      if (this.deps.pathStatus) {
        detail = "Fresh WebRTC transport attached; waiting for a Reticulum path.";
        const deadline = this.clock() + PATH_TIMEOUT_MS;
        while (this.clock() < deadline) {
          const status = await step(() => this.deps.pathStatus!(profile.contact_id).catch(() => null));
          if (!status) { detail = "Connection open; waiting to confirm the secure messaging route."; break; }
          if (status.has_path && status.ready !== false) { messagingReady = true; detail = "Fresh WebRTC transport attached; Reticulum path ready."; break; }
          if (status.state === "network_unavailable") { detail = "Fresh WebRTC transport attached; Reticulum networking is unavailable."; break; }
          await this.attemptSleep(1000, attempt.controller.signal);
          check();
        }
      }
      check();
      this.setState(profile, messagingReady ? "connected" : "connecting", detail);
      this.retries.delete(profile.id);
      attempt.peer = null; // The session registry now owns this healthy transport.
    } catch (reason) {
      try { attempt.peer?.close(); } catch { /* Failed or cancelled peer. */ }
      if (reason instanceof ReconnectCancelled || !this.current(attempt)) return;
      const code = errorCode(reason);
      if (TERMINAL_ERRORS.includes(code)) {
        retry.blockedSignature = this.signature(profile);
        this.setState(profile, "manual_required", code);
        return;
      }
      if (code === "invalid_request" || code === "reconnect_replayed") {
        retry.requestDocument = "";
        retry.attemptId = makeAttemptId();
        retry.waitingForOfferUntil = 0;
      }
      retry.attempts += 1;
      const base = BACKOFF_MS[Math.min(retry.attempts - 1, BACKOFF_MS.length - 1)];
      const delay = code === "mailbox_rate_limited" ? 60000 : Math.round(base * (0.8 + (this.deps.random?.() ?? Math.random()) * 0.4));
      retry.nextAt = this.clock() + delay;
      retry.rateLimitedUntil = code === "mailbox_rate_limited" ? retry.nextAt : undefined;
      const entry = this.entries[profile.id];
      if (entry) entry.attempts = retry.attempts;
      this.setState(profile, retry.attempts > MAX_ATTEMPTS ? "peer_offline" : "retry_wait", safeMessage(reason));
      if (entry) entry.nextAttemptAt = Math.ceil(retry.nextAt / 1000);
      this.emit();
    }
  }
}

function fingerprintOf(sdp: string): string {
  for (const line of sdp.split(/\r?\n/)) {
    if (line.startsWith("a=fingerprint:")) {
      return line.slice("a=fingerprint:".length).trim();
    }
  }
  throw new Error("The SDP has no DTLS fingerprint.");
}

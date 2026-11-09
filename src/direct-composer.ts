import type { AcceptedComposerSend, ComposerEnqueue, ComposerPort, ComposerSendOutcome, CoreComposer } from "./core-composer";

interface PendingUpdate {
  expectedRevision: string | null;
  text: string;
  updateKey: string;
  editVersion: number;
}

interface PendingSend {
  revision: string;
  text: string;
  editVersion: number;
}

export interface DirectComposerView {
  text: string;
  loaded: boolean;
  phase: "loading" | "ready" | "saving" | "sending";
  error: string;
  saved: ComposerSendOutcome | null;
  recoveryText: string | null;
  canSave: boolean;
  canSend: boolean;
  retry: "save" | "send" | null;
}

function errorCode(error: unknown): string {
  if (error && typeof error === "object" && "code" in error && typeof error.code === "string") return error.code;
  return error instanceof Error ? error.message : String(error);
}

const TERMINAL_REPLAY_ERRORS = new Set(["conflict", "idempotency_conflict", "idempotency_expired", "forbidden", "locked"]);

/** Owns presentation ordering and exact Core tickets, never delivery retry policy. */
export class DirectComposerController {
  private composer: CoreComposer | null = null;
  private text = "";
  private editVersion = 0;
  private dirty = false;
  private phase: DirectComposerView["phase"] = "loading";
  private error = "";
  private saved: ComposerSendOutcome | null = null;
  private recoveryText: string | null = null;
  private pendingUpdate: PendingUpdate | null = null;
  private pendingSend: PendingSend | null = null;
  private sendRequested = false;
  private frozen = false;
  private tail: Promise<unknown> = Promise.resolve();
  private listeners = new Set<() => void>();
  private view: DirectComposerView = this.project();

  constructor(private readonly port: ComposerPort) {}

  getSnapshot = (): DirectComposerView => this.view;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  edit(text: string): void {
    if (this.frozen) return;
    this.text = text;
    this.editVersion += 1;
    this.dirty = true;
    if (!this.pendingUpdate && !this.pendingSend && this.recoveryText === null) this.error = "";
    this.emit();
  }

  restoreRecovery(): void {
    if (this.recoveryText === null) return;
    const text = this.recoveryText;
    this.recoveryText = null;
    this.error = "";
    this.edit(text);
  }

  load(): Promise<void> {
    return this.serialize(async () => {
      const version = this.editVersion;
      this.phase = "loading";
      this.emit();
      try {
        const current = await this.port.query(this.pendingSend?.revision);
        if (this.hasSupersedingDraft(current) || (this.dirty && this.composer && current.revision !== this.composer.revision
          && current.send_lookup?.status !== "accepted")) {
          if (current.send_lookup?.status === "accepted") this.pendingSend = null;
          this.conflict(current);
        } else {
          this.adoptQuery(current, version, this.dirty);
          this.error = "";
        }
      } catch {
        this.error = "The saved draft could not be loaded. Your local text is kept here.";
      } finally {
        this.phase = "ready";
        this.emit();
      }
    });
  }

  save(): Promise<void> {
    return this.serialize(async () => {
      if (this.frozen || !this.composer || this.pendingUpdate || this.recoveryText !== null || !this.dirty) return;
      if (this.pendingSend) {
        try {
          const current = await this.port.query(this.pendingSend.revision);
          const ownAcceptance = current.send_lookup?.status === "accepted";
          if (this.hasSupersedingDraft(current) || (current.revision !== this.composer.revision && !ownAcceptance)) {
            if (ownAcceptance) this.pendingSend = null;
            this.conflict(current);
            return;
          }
          this.adoptQuery(current, this.editVersion, true);
        } catch {
          this.error = "The previous send still needs checking. Your newer text is kept here.";
          this.emit();
          return;
        }
      }
      if (this.frozen) return;
      await this.persist(this.text, this.editVersion);
    });
  }

  send(): Promise<void> {
    if (this.frozen) return Promise.resolve();
    if (this.sendRequested) return this.tail.then(() => undefined);
    this.sendRequested = true;
    this.emit();
    const text = this.text;
    const version = this.editVersion;
    const sending = this.serialize(async () => {
      if (this.frozen || !this.composer || !text.trim() || this.pendingUpdate || this.pendingSend || this.recoveryText !== null) return;
      if (this.dirty || this.composer.revision === null || this.composer.text !== text) {
        await this.persist(text, version);
      }
      if (this.frozen || this.pendingUpdate || this.recoveryText !== null || !this.composer.revision || this.composer.text !== text) return;
      this.pendingSend = { revision: this.composer.revision, text, editVersion: version };
      await this.submitPendingSend();
    });
    return sending.finally(() => { this.sendRequested = false; this.emit(); });
  }

  /** Called only by an explicit Retry action; it never substitutes a new key. */
  retry(): Promise<void> {
    return this.serialize(async () => {
      if (this.frozen) return;
      if (this.pendingUpdate) {
        await this.submitPendingUpdate(true);
      } else if (this.pendingSend) {
        await this.submitPendingSend();
      }
    });
  }

  freezeAndFlush(): Promise<void> {
    this.frozen = true;
    this.emit();
    return this.serialize(async () => {
      if (!this.composer || !this.dirty || this.pendingUpdate || this.pendingSend || this.recoveryText !== null) return;
      this.pendingUpdate = { expectedRevision: this.composer.revision, updateKey: this.composer.update_key,
        text: this.text, editVersion: this.editVersion };
      await this.submitPendingUpdate(false, true);
    });
  }

  private async persist(text: string, editVersion: number): Promise<void> {
    if (!this.composer) return;
    this.pendingUpdate = {
      expectedRevision: this.composer.revision, updateKey: this.composer.update_key, text, editVersion,
    };
    await this.submitPendingUpdate(false);
  }

  private async submitPendingUpdate(explicitRetry: boolean, retirement = false): Promise<void> {
    const pending = this.pendingUpdate;
    if (!pending) return;
    this.phase = "saving";
    this.emit();
    try {
      const update = retirement && this.port.updateForRetirement ? this.port.updateForRetirement : this.port.update;
      const result = await update(pending.expectedRevision, pending.text, pending.updateKey);
      this.pendingUpdate = null;
      if (result.composer.revision !== result.applied_revision && this.dirty && this.editVersion !== pending.editVersion) {
        this.conflict(result.composer);
      } else {
        this.adopt(result.composer, pending.editVersion);
        this.error = "";
      }
    } catch (error) {
      const code = errorCode(error);
      this.error = "The draft save was not confirmed. Retry checks the same draft save.";
      if (explicitRetry && TERMINAL_REPLAY_ERRORS.has(code)) await this.recoverRejectedReplay("save", code);
    } finally {
      this.phase = "ready";
      this.emit();
    }
  }

  private async submitPendingSend(): Promise<void> {
    const pending = this.pendingSend;
    if (!pending) return;
    this.phase = "sending";
    this.emit();
    try {
      const result = await this.port.enqueue(pending.revision);
      this.pendingSend = null;
      const newerDraft = result.draft_disposition === "superseded" && this.dirty
        && this.editVersion !== pending.editVersion && this.text !== result.composer.text;
      if (newerDraft) this.conflict(result.composer);
      else this.adopt(result.composer, pending.editVersion);
      this.saved = this.acceptedOutcome(result, pending);
      if (!newerDraft) this.error = "";
    } catch (error) {
      const code = errorCode(error);
      this.error = "The send outcome is uncertain. Retry checks the same message; it does not create another send.";
      if (TERMINAL_REPLAY_ERRORS.has(code)) await this.recoverRejectedReplay("send", code);
    } finally {
      this.phase = "ready";
      this.emit();
    }
  }

  private async recoverRejectedReplay(kind: "save" | "send", code: string): Promise<void> {
    try {
      const current = await this.port.query();
      if (kind === "save") this.pendingUpdate = null;
      else this.pendingSend = null;
      this.conflict(current);
      this.error = `The previous ${kind} ${code === "idempotency_expired" ? "has expired" : "cannot be replayed"}. Review the saved draft and conversation before a new send.`;
    } catch {
      // Authority loss or a failed query cannot authorize replacement tokens.
    }
  }

  private adoptQuery(current: CoreComposer, version: number, preserveLocal = false): void {
    if (current.send_lookup?.status === "accepted") {
      this.saved = current.send_lookup;
      if (this.pendingSend?.revision === current.send_lookup.revision) this.pendingSend = null;
    } else {
      this.saved = current.last_send;
    }
    this.adopt(current, version, preserveLocal);
  }

  private hasSupersedingDraft(current: CoreComposer): boolean {
    return this.dirty && current.send_lookup?.status === "accepted"
      && current.send_lookup.draft_disposition === "superseded" && current.text !== this.text;
  }

  private adopt(current: CoreComposer, version: number, preserveLocal = false): void {
    this.composer = current;
    if (!preserveLocal && this.editVersion === version && !this.pendingUpdate) {
      this.text = current.text;
      this.dirty = false;
    }
    if (!this.saved || this.saved.revision === current.last_send?.revision) this.saved = current.last_send;
  }

  private conflict(current: CoreComposer): void {
    this.recoveryText = this.text !== current.text ? this.text : null;
    this.composer = current;
    this.text = current.text;
    this.dirty = false;
    this.saved = current.last_send;
    this.error = "The saved draft changed. Your local text is kept separately; review it before replacing the saved draft.";
    this.emit();
  }

  private acceptedOutcome(result: ComposerEnqueue, pending: PendingSend): AcceptedComposerSend {
    return {
      revision: pending.revision, status: "accepted", text: pending.text,
      acceptance: { profile: result.profile, message: result.message, accepted: true,
        accepted_at: result.accepted_at, idempotency_expires_at: result.idempotency_expires_at },
      draft_disposition: result.draft_disposition,
    };
  }

  private project(): DirectComposerView {
    const ready = !this.frozen && this.phase === "ready" && this.composer !== null && this.recoveryText === null;
    return {
      text: this.text, loaded: this.composer !== null, phase: this.phase, error: this.error, saved: this.saved, recoveryText: this.recoveryText,
      canSave: ready && this.dirty && !this.pendingUpdate,
      canSend: ready && !this.sendRequested && !this.pendingUpdate && !this.pendingSend && Boolean(this.text.trim()),
      retry: this.pendingUpdate ? "save" : this.pendingSend ? "send" : null,
    };
  }

  private emit(): void {
    this.view = this.project();
    for (const listener of this.listeners) listener();
  }

  private serialize(action: () => Promise<void>): Promise<void> {
    const result = this.tail.then(action);
    this.tail = result.catch(() => undefined);
    return result;
  }
}

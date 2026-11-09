import { prepareCallControl, submitCallControl, type CallControlTicket } from "./call-core";

type Result = Record<string, unknown>;
interface Pending {
  action: string;
  params: Record<string, unknown>;
  ticket?: CallControlTicket;
  invoked: boolean;
  uncertain: boolean;
  resolve: (result: Result) => void;
  reject: (reason: unknown) => void;
}

export interface CallOperationView {
  pending: boolean;
  busy: boolean;
  uncertain: boolean;
  cancelling: boolean;
  errorCode: string | null;
}

const DEFINITE_REJECTIONS = new Set(["invalid_request", "forbidden", "locked", "unsupported_operation", "resource_exhausted", "rate_limited"]);
const recoverySessions = new Set<CallOperation>();
const recoveryListeners = new Set<() => void>();
let recoveryView: readonly CallOperation[] = [];

function publishRecovery() {
  recoveryView = [...recoverySessions];
  recoveryListeners.forEach((listener) => listener());
}

export const callRecovery = {
  subscribe(listener: () => void) { recoveryListeners.add(listener); return () => { recoveryListeners.delete(listener); }; },
  getSnapshot: () => recoveryView,
};

/** Retains one exact mutation until resolved; media capture remains in the view. */
export class CallOperation {
  private pending: Pending | null = null;
  private attempt: Promise<void> | null = null;
  private scope?: string;
  private scopeBinding: Promise<string> | null = null;
  private callId?: string;
  private cancellation: "completed" | "declined" | "cancelled" | null = null;
  private cancellationDone: Promise<void> | null = null;
  private resolveCancellation: (() => void) | null = null;
  private cancellationAttempt: Promise<void> | null = null;
  private uncertain = false;
  private errorCode: string | null = null;
  private listeners = new Set<() => void>();
  private view: CallOperationView = { pending: false, busy: false, uncertain: false, cancelling: false, errorCode: null };

  constructor(readonly name: string, initialCallId?: string, private readonly verifyIncomingScope?: () => Promise<string>,
              private readonly submitTicket: (ticket: CallControlTicket, retiring: boolean) => Promise<Result> = submitCallControl) { this.callId = initialCallId; }

  getSnapshot = () => this.view;
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; };

  control(action: string, params: Record<string, unknown>): Promise<Result> {
    if (this.pending || this.attempt || this.cancellation) return Promise.reject(new Error("call_operation_pending"));
    return this.begin(action, params);
  }

  async bindIncomingScope(): Promise<string | undefined> {
    if (!this.scope && this.verifyIncomingScope) {
      this.scopeBinding ??= this.verifyIncomingScope().catch((error: unknown) => { this.scopeBinding = null; throw error; });
      this.scope = await this.scopeBinding;
    }
    return this.scope;
  }

  reset(): boolean {
    if (this.pending || this.attempt || this.callId || recoverySessions.size > 0) return false;
    this.cancellation = null;
    this.cancellationDone = null;
    this.resolveCancellation = null;
    this.uncertain = false;
    this.errorCode = null;
    this.emit();
    return true;
  }

  observeEnded(): void {
    if (!this.pending) this.callId = undefined;
  }

  retry = async (): Promise<void> => {
    if (this.attempt) return this.attempt;
    if (this.pending) await this.submit();
  };

  /** An explicit cancel/unmount resolves the in-flight ticket once before ending its call. */
  cancel(reason: "completed" | "declined" | "cancelled" = "cancelled"): Promise<void> {
    if (this.cancellationDone) return this.cancellationDone;
    this.cancellationDone = new Promise((resolve) => { this.resolveCancellation = resolve; });
    this.cancellation = reason;
    recoverySessions.add(this);
    this.emit();
    const previous = this.attempt;
    this.cancellationAttempt = (async () => {
      if (previous) await previous;
      if (this.pending) await this.retry();
      else this.finishCancellation();
      while (this.attempt) await this.attempt;
    })();
    return this.cancellationDone;
  }

  async retireForProfile(): Promise<void> {
    const wasCancelling = this.cancellation !== null;
    void this.cancel();
    await this.cancellationAttempt;
    if (wasCancelling && this.pending && !this.attempt) await this.retry();
    while (this.attempt) await this.attempt;
    if (this.pending) throw new Error("call_cleanup_pending");
  }

  private begin(action: string, params: Record<string, unknown>): Promise<Result> {
    const outcome = new Promise<Result>((resolve, reject) => {
      this.pending = { action, params: structuredClone(params), invoked: false, uncertain: false, resolve, reject };
    });
    this.uncertain = false;
    void this.submit();
    return outcome;
  }

  private submit(): Promise<void> {
    if (this.attempt) return this.attempt;
    const pending = this.pending;
    if (!pending) return Promise.resolve();
    // A microtask installs the single-flight guard before calling the host.
    this.attempt = Promise.resolve().then(async () => {
      try {
        await this.bindIncomingScope();
        pending.ticket ??= await prepareCallControl(pending.action, pending.params, this.scope);
        this.scope ??= pending.ticket.params.profile;
        if (this.cancellation && !pending.invoked && pending.action !== "end") {
          this.pending = null;
          pending.reject(new Error("Call cancelled."));
          return;
        }
        pending.invoked = true;
        const result = await this.submitTicket(pending.ticket, this.cancellation !== null);
        if (pending.action === "start" && typeof result.id !== "string") throw new Error("core_api_protocol");
        if ((pending.action === "start" || pending.action === "answer") && typeof result.id === "string") this.callId = result.id;
        if (pending.action === "end") this.callId = undefined;
        this.pending = null;
        this.uncertain = false;
        this.errorCode = null;
        pending.resolve(result);
      } catch (reason) {
        const code = reason && typeof reason === "object" && "code" in reason ? reason.code : null;
        if (pending.action !== "end" && !pending.uncertain
          && (!pending.invoked || (typeof code === "string" && DEFINITE_REJECTIONS.has(code)))) {
          this.pending = null;
          this.uncertain = false;
          pending.reject(reason);
        } else {
          // Keep the original continuation, profile, key and SDP for explicit resolution.
          pending.uncertain = true;
          this.uncertain = true;
          this.errorCode = typeof code === "string" ? code : reason instanceof Error ? reason.message : "unknown";
        }
      }
    }).finally(() => {
      this.attempt = null;
      if (this.cancellation && !this.pending) this.finishCancellation();
      this.emit();
    });
    this.emit();
    return this.attempt;
  }

  private finishCancellation(): void {
    if (this.pending || !this.cancellation) return;
    if (this.callId) {
      void this.begin("end", { call_id: this.callId, reason: this.cancellation }).catch(() => {
        // A rejected cleanup stays visible; it must not silently authorize a new call.
        recoverySessions.add(this);
        this.uncertain = true;
        this.emit();
      });
    } else {
      recoverySessions.delete(this);
      this.resolveCancellation?.();
      this.emit();
    }
  }

  private emit(): void {
    this.view = { pending: this.pending !== null, busy: this.attempt !== null, uncertain: this.uncertain, cancelling: this.cancellation !== null, errorCode: this.errorCode };
    this.listeners.forEach((listener) => listener());
    if (recoverySessions.has(this) || recoveryView.includes(this)) publishRecovery();
  }
}

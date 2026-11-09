import type { ComposerEnqueue, CoreComposer } from "../core-composer";

export const composerCapabilities = {
  api_major: 1, api_minor: 1,
  operations: ["peer.composer_query", "peer.composer_update", "message.enqueue_draft"],
  profiles: ["profile-handle"], stability: "experimental",
  limits: {
    composer_text_utf8_bytes: 16384, composers_per_caller_profile: 256, composers_per_vault: 4096,
    composer_update_idempotency_seconds: 3600, composer_update_keys_per_caller_profile: 8192,
    composer_update_keys_per_vault: 65536, composer_send_idempotency_seconds: 604800,
    composer_send_keys_per_caller_profile: 4096, composer_send_keys_per_vault: 65536,
  },
};

function failure(code: string): never { throw Object.assign(new Error(code), { code }); }

/** Native-envelope fixture only; production storage/authority is qualified independently. */
export class ComposerHostFixture {
  private counter = 0;
  private current: CoreComposer;
  private updateReceipts = new Map<string, { input: string; applied_revision: string; changed: boolean }>();
  private sendReceipts = new Map<string, ComposerEnqueue>();
  readonly calls: Array<{ operation: string; params: Record<string, unknown>; key?: string }> = [];
  onEnqueue: (text: string) => Promise<void> = async () => undefined;
  loseNextSendReply = false;
  loseNextUpdateReply = false;
  failQuery = false;

  constructor(profile = "profile-handle", peer = "peer-handle", text = "") {
    this.current = { profile, peer, text, revision: null, update_key: this.token(), last_send: null, send_lookup: null };
  }

  get messageCount(): number { return this.sendReceipts.size; }
  snapshot(): CoreComposer { return structuredClone(this.current); }

  replace(text: string): void {
    this.current = { ...this.current, text, revision: this.token(), update_key: this.token() };
  }

  async request(operation: string, params: Record<string, unknown>, key?: string): Promise<unknown> {
    this.calls.push({ operation, params: structuredClone(params), key });
    if (params.profile !== this.current.profile || (params.peer ?? params.recipient) !== this.current.peer) failure("forbidden");
    if (operation === "peer.composer_query") {
      if (this.failQuery) failure("forbidden");
      const result = this.snapshot();
      const revision = params.send_revision as string | undefined;
      if (revision && this.sendReceipts.has(revision)) {
        const receipt = this.sendReceipts.get(revision)!;
        const outcome = receipt.composer.last_send!;
        if (outcome.status === "accepted") result.send_lookup = {
          ...outcome, draft_disposition: result.revision === receipt.composer.revision ? "cleared" : "superseded",
        };
      } else if (revision === result.revision) result.send_lookup = { revision, status: "not_accepted" };
      return result;
    }
    if (operation === "peer.composer_update") {
      const input = JSON.stringify([params.expected_revision, params.text]);
      const prior = this.updateReceipts.get(key!);
      if (prior) {
        if (input !== prior.input) failure("idempotency_conflict");
        return { applied_revision: prior.applied_revision, changed: prior.changed, composer: this.snapshot() };
      }
      if (key !== this.current.update_key || params.expected_revision !== this.current.revision) failure("conflict");
      const text = String(params.text);
      const changed = this.current.revision === null || this.current.text !== text;
      this.current = { ...this.current, text, revision: changed ? this.token() : this.current.revision, update_key: this.token() };
      const receipt = { input, applied_revision: this.current.revision!, changed };
      this.updateReceipts.set(key!, receipt);
      if (this.loseNextUpdateReply) { this.loseNextUpdateReply = false; failure("unavailable"); }
      return { applied_revision: receipt.applied_revision, changed, composer: this.snapshot() };
    }
    if (operation === "message.enqueue_draft") {
      const revision = String(params.draft_revision);
      if (key !== revision) failure("invalid_request");
      const prior = this.sendReceipts.get(revision);
      if (prior) return { ...prior, composer: this.snapshot(), draft_disposition: this.current.revision === prior.composer.revision ? "cleared" : "superseded" };
      if (this.current.revision !== revision || !this.current.text.trim()) failure("conflict");
      const text = this.current.text;
      const acceptance = { profile: this.current.profile, message: this.token(), accepted: true as const, accepted_at: 1, idempotency_expires_at: 604801 };
      this.current = { ...this.current, text: "", revision: this.token(), update_key: this.token(), last_send: {
        revision, status: "accepted", text, acceptance, draft_disposition: "cleared",
      } };
      const result: ComposerEnqueue = { ...acceptance, peer: this.current.peer, draft_revision: revision, draft_disposition: "cleared", composer: this.snapshot() };
      this.sendReceipts.set(revision, result);
      await this.onEnqueue(text);
      if (this.loseNextSendReply) { this.loseNextSendReply = false; failure("unavailable"); }
      return result;
    }
    return failure("unsupported_operation");
  }

  private token(): string { return (++this.counter).toString(16).padStart(64, "0"); }
}

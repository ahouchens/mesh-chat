import type { GroupComposer, GroupComposerEnqueue } from "../core-group-composer";

export const groupComposerCapabilities = {
  api_major: 1, api_minor: 1, stability: "experimental", profiles: ["profile"],
  operations: ["group.composer_query", "group.composer_update", "group.message_enqueue_draft"],
  limits: { group_composer_text_utf8_bytes: 16384, group_composers_per_caller_profile: 256, group_composers_per_vault: 4096,
    group_composer_update_idempotency_seconds: 3600, group_composer_update_keys_per_caller_profile: 8192, group_composer_update_keys_per_vault: 65536,
    group_composer_send_idempotency_seconds: 604800, group_composer_send_keys_per_caller_profile: 4096, group_composer_send_keys_per_vault: 65536 },
};
const fail = (code: string): never => { throw Object.assign(new Error(code), { code }); };

/** UI transport double only; real encrypted/signed group durability is A/D evidence. */
export class GroupComposerHostFixture {
  private counter = 0;
  private current: GroupComposer;
  private updates = new Map<string, { input: string; applied_revision: string; changed: boolean }>();
  private sends = new Map<string, GroupComposerEnqueue>();
  loseNextUpdateReply = false;
  loseNextSendReply = false;
  forbidden = false;
  expireSends = false;
  onEnqueue: (text: string) => Promise<void> = async () => undefined;
  constructor(profile = "profile", group = "group", text = "") {
    this.current = { profile, group, text, revision: null, update_key: this.token(), last_send: null, send_lookup: null };
  }
  get messageCount(): number { return this.sends.size; }
  snapshot(): GroupComposer { return structuredClone(this.current); }
  replace(text: string): void { this.current = { ...this.current, text, revision: this.token(), update_key: this.token() }; }
  private token(): string { return (++this.counter).toString(16).padStart(64, "0"); }
  async request(operation: string, params: Record<string, unknown>, key?: string): Promise<unknown> {
    if (this.forbidden || params.profile !== this.current.profile || params.group !== this.current.group) fail("forbidden");
    if (operation === "group.composer_query") {
      const result = this.snapshot(); const revision = params.send_revision as string | undefined;
      if (revision && this.expireSends) fail("idempotency_expired");
      const receipt = this.sends.get(revision ?? "");
      if (receipt?.composer.last_send?.status === "accepted") result.send_lookup = { ...receipt.composer.last_send,
        draft_disposition: result.revision === receipt.composer.revision ? "cleared" : "superseded" };
      else if (revision === result.revision) result.send_lookup = { revision, status: "not_accepted" };
      return result;
    }
    if (operation === "group.composer_update") {
      const input = JSON.stringify([params.expected_revision, params.text]); const prior = this.updates.get(key!);
      if (prior) { if (prior.input !== input) fail("idempotency_conflict"); return { ...prior, composer: this.snapshot() }; }
      if (key !== this.current.update_key || params.expected_revision !== this.current.revision) fail("conflict");
      const text = String(params.text); const changed = this.current.revision === null || text !== this.current.text;
      this.current = { ...this.current, text, revision: changed ? this.token() : this.current.revision, update_key: this.token() };
      const receipt = { input, applied_revision: this.current.revision!, changed }; this.updates.set(key!, receipt);
      if (this.loseNextUpdateReply) { this.loseNextUpdateReply = false; fail("unavailable"); }
      return { ...receipt, composer: this.snapshot() };
    }
    if (operation === "group.message_enqueue_draft") {
      const revision = String(params.draft_revision);
      if (key !== revision) fail("invalid_request");
      if (this.expireSends) fail("idempotency_expired");
      const prior = this.sends.get(revision);
      if (prior) return { ...prior, composer: this.snapshot(), draft_disposition: this.current.revision === prior.composer.revision ? "cleared" : "superseded" };
      if (revision !== this.current.revision || !this.current.text.trim()) fail("conflict");
      const text = this.current.text;
      const acceptance = { profile: this.current.profile, message: this.token(), accepted: true as const, accepted_at: 1, idempotency_expires_at: 604801 };
      this.current = { ...this.current, text: "", revision: this.token(), update_key: this.token(), last_send: { revision, status: "accepted", text, acceptance, draft_disposition: "cleared" } };
      const result: GroupComposerEnqueue = { ...acceptance, group: this.current.group, draft_revision: revision, draft_disposition: "cleared", composer: this.snapshot() };
      this.sends.set(revision, result); await this.onEnqueue(text);
      if (this.loseNextSendReply) { this.loseNextSendReply = false; fail("unavailable"); }
      return result;
    }
    return fail("unsupported_operation");
  }
}

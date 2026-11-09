import { describe, expect, it } from "vitest";
import type { ComposerEnqueue, ComposerPort, ComposerUpdate, CoreComposer } from "./core-composer";
import { DirectComposerController } from "./direct-composer";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((finish) => { resolve = finish; });
  return { promise, resolve };
}

/** Protocol double: no legacy commands or generated client-side identities. */
function fixture() {
  let next = 0;
  const token = () => (++next).toString(16).padStart(64, "0");
  let current: CoreComposer = { profile: "profile", peer: "peer", revision: null, update_key: token(), text: "", last_send: null, send_lookup: null };
  const updates: Array<{ revision: string | null; text: string; key: string }> = [];
  const sends: string[] = [];
  const updateReceipts = new Map<string, { request: string; applied_revision: string; changed: boolean }>();
  const sendReceipts = new Map<string, ComposerEnqueue>();
  let loseUpdate = false;
  let loseSend = false;
  let expireUpdate = false;
  let expireSend = false;
  const snapshot = () => structuredClone(current);
  const port: ComposerPort = {
    async query(revision) {
      const view = snapshot();
      if (revision && sendReceipts.has(revision)) {
        const receipt = sendReceipts.get(revision)!;
        view.send_lookup = { revision, status: "accepted", text: receipt.composer.last_send!.status === "accepted" ? receipt.composer.last_send!.text : "",
          acceptance: receipt, draft_disposition: current.revision === receipt.composer.revision ? "cleared" : "superseded" };
      } else if (revision === view.revision) view.send_lookup = { revision, status: "not_accepted" };
      return view;
    },
    async update(revision, text, key) {
      updates.push({ revision, text, key });
      if (expireUpdate) throw Object.assign(new Error("expired"), { code: "idempotency_expired" });
      const request = JSON.stringify([revision, text]);
      const existing = updateReceipts.get(key);
      if (existing) {
        if (existing.request !== request) throw Object.assign(new Error("conflict"), { code: "idempotency_conflict" });
        return { applied_revision: existing.applied_revision, changed: existing.changed, composer: snapshot() };
      }
      if (key !== current.update_key || revision !== current.revision) throw Object.assign(new Error("conflict"), { code: "conflict" });
      const changed = current.revision === null || current.text !== text;
      current = { ...current, text, revision: changed ? token() : current.revision, update_key: token() };
      const receipt = { request, applied_revision: current.revision!, changed };
      updateReceipts.set(key, receipt);
      if (loseUpdate) { loseUpdate = false; throw Object.assign(new Error("lost update reply"), { code: "unavailable" }); }
      return { ...receipt, composer: snapshot() };
    },
    async enqueue(revision) {
      sends.push(revision);
      if (expireSend) throw Object.assign(new Error("expired"), { code: "idempotency_expired" });
      const previous = sendReceipts.get(revision);
      if (previous) return { ...previous, draft_disposition: current.revision === previous.composer.revision ? "cleared" : "superseded", composer: snapshot() };
      if (revision !== current.revision) throw Object.assign(new Error("conflict"), { code: "conflict" });
      const acceptance = { profile: current.profile, message: token(), accepted: true as const, accepted_at: 1, idempotency_expires_at: 604801 };
      const text = current.text;
      current = { ...current, text: "", revision: token(), update_key: token(), last_send: { revision, text, status: "accepted", acceptance, draft_disposition: "cleared" } };
      const result: ComposerEnqueue = { ...acceptance, peer: current.peer, draft_revision: revision, draft_disposition: "cleared", composer: snapshot() };
      sendReceipts.set(revision, result);
      if (loseSend) { loseSend = false; throw Object.assign(new Error("lost send reply"), { code: "unavailable" }); }
      return result;
    },
  };
  return { port, snapshot, updates, sends, sendReceipts,
    loseUpdate: () => { loseUpdate = true; }, loseSend: () => { loseSend = true; },
    expireUpdate: () => { expireUpdate = true; }, expireSend: () => { expireSend = true; },
    replace(text: string) { current = { ...current, text, revision: token(), update_key: token() }; },
  };
}

describe("direct composer presentation ordering", () => {
  it("loads purely, then uses the distinct issued update key and revision to send", async () => {
    const core = fixture();
    const controller = new DirectComposerController(core.port);
    await controller.load();
    expect(core.updates).toEqual([]);
    expect(core.sends).toEqual([]);
    const initialKey = core.snapshot().update_key;
    controller.edit("Durable text");
    await controller.send();
    expect(core.updates).toEqual([{ revision: null, text: "Durable text", key: initialKey }]);
    expect(core.sends).toHaveLength(1);
    expect(core.sends[0]).not.toBe(initialKey);
    expect(controller.getSnapshot().text).toBe("");
    expect(controller.getSnapshot().saved).toMatchObject({ status: "accepted", text: "Durable text" });
    expect(core.updates).toHaveLength(1); // no independent empty-draft clear
  });

  it("explicitly retries an uncertain update with exactly the original ticket and payload", async () => {
    const core = fixture();
    const controller = new DirectComposerController(core.port);
    await controller.load();
    core.loseUpdate();
    controller.edit("First text");
    await controller.save();
    controller.edit("Newer local text");
    await controller.save();
    expect(core.updates).toHaveLength(1);
    expect(controller.getSnapshot().retry).toBe("save");
    await controller.retry();
    expect(core.updates[1]).toEqual(core.updates[0]);
    expect(controller.getSnapshot().text).toBe("Newer local text");
    await controller.save();
    expect(core.updates[2].key).not.toBe(core.updates[0].key);
    expect(core.snapshot().text).toBe("Newer local text");
  });

  it("fences two synchronous submits before the disabled button can paint", async () => {
    const core = fixture();
    const controller = new DirectComposerController(core.port);
    await controller.load();
    controller.edit("One send");
    await Promise.all([controller.send(), controller.send()]);
    expect(core.sends).toHaveLength(1);
    expect(core.sendReceipts.size).toBe(1);
  });

  it("rotates update tickets on an unchanged-text save while retaining the send revision", async () => {
    const core = fixture();
    const controller = new DirectComposerController(core.port);
    await controller.load();
    controller.edit("Same draft");
    await controller.save();
    const first = core.snapshot();
    controller.edit("Same draft");
    await controller.save();
    expect(core.snapshot().revision).toBe(first.revision);
    expect(core.snapshot().update_key).not.toBe(first.update_key);
    expect(core.updates[1].key).toBe(first.update_key);
    expect(core.sends).toHaveLength(0);
  });

  it("keeps newer persisted text when replaying an old successful update", async () => {
    const core = fixture();
    const controller = new DirectComposerController(core.port);
    await controller.load();
    core.loseUpdate();
    controller.edit("Old text");
    await controller.save();
    core.replace("Newer saved text");
    await controller.retry();
    expect(controller.getSnapshot().text).toBe("Newer saved text");
    expect(core.snapshot().text).toBe("Newer saved text");
    expect(core.updates[1]).toEqual(core.updates[0]);
  });

  it("keeps newer local edits while a successful update reply is delayed", async () => {
    const core = fixture();
    const response = deferred<ComposerUpdate>();
    const original = core.port.update;
    core.port.update = async (...args) => { const result = await original(...args); return response.promise.then(() => result); };
    const controller = new DirectComposerController(core.port);
    await controller.load();
    controller.edit("First text");
    const save = controller.save();
    await Promise.resolve();
    controller.edit("Newer text");
    response.resolve({} as ComposerUpdate);
    await save;
    expect(controller.getSnapshot().text).toBe("Newer text");
    expect(controller.getSnapshot().canSave).toBe(true);
  });

  it("recovers accepted text on a new controller after a committed reply was lost", async () => {
    const core = fixture();
    const first = new DirectComposerController(core.port);
    await first.load();
    first.edit("Only one message");
    core.loseSend();
    await first.send();
    expect(first.getSnapshot().retry).toBe("send");
    const reopened = new DirectComposerController(core.port);
    await reopened.load();
    expect(reopened.getSnapshot().text).toBe("");
    expect(reopened.getSnapshot().saved).toMatchObject({ status: "accepted", text: "Only one message" });
    expect(core.sends).toHaveLength(1);
    await first.retry();
    expect(core.sends[1]).toBe(core.sends[0]);
    expect(core.sendReceipts.size).toBe(1);
  });

  it("resolves an uncertain send before persisting newer edits without another enqueue", async () => {
    const core = fixture();
    const controller = new DirectComposerController(core.port);
    await controller.load();
    controller.edit("Sent text");
    core.loseSend();
    await controller.send();
    controller.edit("Newer draft");
    await controller.save();
    expect(core.snapshot().text).toBe("Newer draft");
    expect(controller.getSnapshot().text).toBe("Newer draft");
    expect(controller.getSnapshot().saved).toMatchObject({ status: "accepted", text: "Sent text" });
    expect(core.sends).toHaveLength(1);
  });

  it("preserves a newer draft during a delayed accepted enqueue reply", async () => {
    const core = fixture();
    const response = deferred<ComposerEnqueue>();
    const started = deferred<void>();
    const original = core.port.enqueue;
    let committed!: ComposerEnqueue;
    core.port.enqueue = async (revision) => { committed = await original(revision); started.resolve(); return response.promise; };
    const controller = new DirectComposerController(core.port);
    await controller.load();
    controller.edit("Send first");
    const sending = controller.send();
    await started.promise;
    controller.edit("Keep newer typing");
    response.resolve(committed);
    await sending;
    expect(controller.getSnapshot().text).toBe("Keep newer typing");
    await controller.save();
    expect(core.snapshot().text).toBe("Keep newer typing");
    expect(core.sends).toHaveLength(1);
  });

  it.each(["save", "retry", "load"] as const)("keeps a superseding Core draft and local recovery separate during %s", async (action) => {
    const core = fixture();
    const controller = new DirectComposerController(core.port);
    await controller.load();
    controller.edit("Original send");
    core.loseSend();
    await controller.send();
    core.replace("Newer persisted draft");
    controller.edit("New local typing");
    await controller[action]();
    expect(controller.getSnapshot().text).toBe("Newer persisted draft");
    expect(controller.getSnapshot().recoveryText).toBe("New local typing");
    expect(controller.getSnapshot().canSave).toBe(false);
    expect(core.snapshot().text).toBe("Newer persisted draft");
    expect(core.sends).toHaveLength(action === "retry" ? 2 : 1);
  });

  it("permits an intentional later same-text send only through a new Core revision", async () => {
    const core = fixture();
    const controller = new DirectComposerController(core.port);
    await controller.load();
    controller.edit("Same text");
    await controller.send();
    controller.edit("Same text");
    await controller.send();
    expect(core.sends).toHaveLength(2);
    expect(core.sends[1]).not.toBe(core.sends[0]);
    expect(core.sendReceipts.size).toBe(2);
  });

  it("does not replace an expired update ticket with a fresh mutation key", async () => {
    const core = fixture();
    const controller = new DirectComposerController(core.port);
    await controller.load();
    core.loseUpdate();
    controller.edit("Old uncertain text");
    await controller.save();
    core.replace("Newer saved draft");
    core.expireUpdate();
    await controller.retry();
    expect(core.updates[1]).toEqual(core.updates[0]);
    expect(controller.getSnapshot().text).toBe("Newer saved draft");
    expect(controller.getSnapshot().recoveryText).toBe("Old uncertain text");
    await controller.save();
    expect(core.updates).toHaveLength(2);
    expect(core.sends).toHaveLength(0);
  });

  it("will not enqueue a purged or expired send as a new operation", async () => {
    const core = fixture();
    const controller = new DirectComposerController(core.port);
    await controller.load();
    controller.edit("Expired send");
    core.loseSend();
    await controller.send();
    core.expireSend();
    await controller.retry();
    expect(core.sends[1]).toBe(core.sends[0]);
    expect(core.sendReceipts.size).toBe(1);
    expect(controller.getSnapshot().canSend).toBe(false);
    expect(controller.getSnapshot().text).toBe("");
  });
});

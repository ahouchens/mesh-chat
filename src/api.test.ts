import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const tauri = vi.hoisted(() => ({
  invoke: vi.fn(),
  listen: vi.fn(async (_channel: string, _callback: (event: { payload: unknown }) => void) => () => undefined),
  getCurrent: vi.fn(async () => [] as string[]),
  onOpenUrl: vi.fn(async () => () => undefined),
}));

vi.mock("@tauri-apps/api/core", () => ({ invoke: tauri.invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen: tauri.listen }));
vi.mock("@tauri-apps/plugin-deep-link", () => ({
  getCurrent: tauri.getCurrent,
  onOpenUrl: tauri.onOpenUrl,
}));
vi.mock("@tauri-apps/api/app", () => ({ onBackButtonPress: vi.fn() }));

import { beginCallAudio, onInvitation, pickInvitationFile, requestMediaPermission, type ServiceEvent } from "./api";

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.clearAllMocks();
});

it("passes the chosen call media to Android permission and foreground-service commands", async () => {
  tauri.invoke.mockResolvedValue({ audio: true, camera: false, granted: true });
  await requestMediaPermission("audio");
  await beginCallAudio("audio");
  expect(tauri.invoke).toHaveBeenCalledWith("request_media_permission", { media: "audio" });
  expect(tauri.invoke).toHaveBeenCalledWith("begin_call_audio", { media: "audio" });
});

describe("Android invitation ingress", () => {
  it("returns a natively validated invitation selected from the document picker", async () => {
    const invitation = "MESHWORKSPACE4:validated";
    tauri.invoke.mockResolvedValueOnce(invitation);

    await expect(pickInvitationFile()).resolves.toBe(invitation);
    expect(tauri.invoke).toHaveBeenCalledWith("pick_invitation_file");
  });

  it("treats document-picker cancellation as a non-error", async () => {
    tauri.invoke.mockResolvedValueOnce(null);

    await expect(pickInvitationFile()).resolves.toBeNull();
  });

  it("preserves a native invitation-file error code", async () => {
    tauri.invoke.mockRejectedValueOnce("invitation_file_type_invalid");

    await expect(pickInvitationFile()).rejects.toMatchObject({
      name: "ServiceCommandError",
      code: "invitation_file_type_invalid",
    });
  });

  it("hands a cold-launch invitation to the renderer exactly once", async () => {
    const invitation = "meshchat://invite/cold_launch";
    const pending = [invitation, null, invitation];
    tauri.invoke.mockImplementation(async (command: string) => {
      if (command === "runtime_platform") return "android";
      if (command === "take_pending_invitation") return pending.shift() ?? null;
      return null;
    });
    const received = vi.fn();

    const stop = await onInvitation(received);
    window.dispatchEvent(new Event("focus"));
    await Promise.resolve();
    window.dispatchEvent(new Event("focus"));
    await Promise.resolve();

    expect(received).toHaveBeenCalledTimes(1);
    expect(received).toHaveBeenCalledWith(invitation);
    expect(tauri.onOpenUrl).not.toHaveBeenCalled();
    stop();
  });

  it("retries delayed native handoff while visible and accepts a warm singleTask launch", async () => {
    vi.useFakeTimers();
    const invitation = "meshchat://workspace-device/delayed_renderer";
    const pending = [null, null, invitation, null];
    tauri.invoke.mockImplementation(async (command: string) => {
      if (command === "runtime_platform") return "android";
      if (command === "take_pending_invitation") return pending.shift() ?? null;
      return null;
    });
    const received = vi.fn();

    const stop = await onInvitation(received);
    expect(received).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1_500);

    expect(received).toHaveBeenCalledTimes(1);
    expect(received).toHaveBeenCalledWith(invitation);
    stop();
  });
});

describe("Android connection-document ingress", () => {
  it.each([
    "meshchat://connect/signed_reply",
    "meshchat://route/signed_update",
  ])("accepts %s through the same bounded launch handoff", async (document) => {
    const pending = [document, null];
    tauri.invoke.mockImplementation(async (command: string) => {
      if (command === "runtime_platform") return "android";
      if (command === "take_pending_invitation") return pending.shift() ?? null;
      return null;
    });
    const received = vi.fn();

    const stop = await onInvitation(received);

    expect(received).toHaveBeenCalledTimes(1);
    expect(received).toHaveBeenCalledWith(document);
    stop();
  });
});

describe("shared mobile service events", () => {
  const packet: ServiceEvent = { type: "event", event: "webrtc_packet", bridge_id: "bridge-1", data: "AQID" };
  const receipt: ServiceEvent = { type: "event", event: "message_status", message_id: "message-1", state: "delivered" };
  let api: typeof import("./api");
  let queued: ServiceEvent[];
  let cleanups: Array<() => void>;
  let platform: "desktop" | "android" | "ios";
  const nativeUnlisten = vi.fn();
  const pollCalls = () => tauri.invoke.mock.calls.filter(([command]) => command === "poll_mobile_events");
  const subscribe = async (callback: (event: ServiceEvent) => void) => {
    const stop = await api.onServiceEvent(callback);
    cleanups.push(stop);
    return stop;
  };

  beforeEach(async () => {
    vi.resetModules();
    api = await import("./api");
    vi.useFakeTimers();
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
    queued = [];
    cleanups = [];
    platform = "android";
    tauri.listen.mockResolvedValue(nativeUnlisten);
    tauri.invoke.mockImplementation(async (command: string) => {
      if (command === "runtime_platform") return platform;
      if (command === "poll_mobile_events") return queued.splice(0);
      throw new Error(`Unexpected native command: ${command}`);
    });
  });

  afterEach(() => {
    cleanups.forEach((stop) => stop());
  });

  it.each(["android", "ios"] as const)("broadcasts packets and delivery receipts from one %s queue drain", async (mobilePlatform) => {
    platform = mobilePlatform;
    const ui = vi.fn();
    const bridge = vi.fn();
    await Promise.all([subscribe(ui), subscribe(bridge)]);
    queued.push(packet, receipt);

    await vi.advanceTimersByTimeAsync(750);

    expect(pollCalls()).toHaveLength(1);
    expect(queued).toEqual([]);
    expect(ui.mock.calls).toEqual([[packet], [receipt]]);
    expect(bridge.mock.calls).toEqual([[packet], [receipt]]);
  });

  it("keeps polling for remaining subscribers, stops after the last, and restarts once", async () => {
    const ui = vi.fn();
    const bridge = vi.fn();
    const stopUi = await subscribe(ui);
    const stopBridge = await subscribe(bridge);
    stopUi();
    stopUi();
    expect(nativeUnlisten).toHaveBeenCalledTimes(1);
    queued.push(packet, receipt);

    await vi.advanceTimersByTimeAsync(750);
    expect(ui).not.toHaveBeenCalled();
    expect(bridge.mock.calls).toEqual([[packet], [receipt]]);

    stopBridge();
    expect(vi.getTimerCount()).toBe(0);
    document.dispatchEvent(new Event("visibilitychange"));
    await vi.advanceTimersByTimeAsync(1_500);
    expect(pollCalls()).toHaveLength(1);

    const replacement = vi.fn();
    await subscribe(replacement);
    queued.push(receipt);
    await vi.advanceTimersByTimeAsync(750);
    expect(pollCalls()).toHaveLength(2);
    expect(replacement.mock.calls).toEqual([[receipt]]);
    expect(bridge).toHaveBeenCalledTimes(2);
  });

  it("never starts a second drain while an old subscription's poll is still in flight", async () => {
    let resolvePoll!: (events: ServiceEvent[]) => void;
    const pending = new Promise<ServiceEvent[]>((resolve) => { resolvePoll = resolve; });
    const oldSubscriber = vi.fn();
    const stop = await subscribe(oldSubscriber);
    tauri.invoke.mockReturnValueOnce(pending);
    await vi.advanceTimersByTimeAsync(750);
    stop();

    const replacement = vi.fn();
    await subscribe(replacement);
    document.dispatchEvent(new Event("visibilitychange"));
    await vi.advanceTimersByTimeAsync(2_250);
    expect(pollCalls()).toHaveLength(1);

    resolvePoll([packet, receipt]);
    await vi.advanceTimersByTimeAsync(0);
    expect(oldSubscriber).not.toHaveBeenCalled();
    expect(replacement.mock.calls).toEqual([[packet], [receipt]]);

    queued.push(receipt);
    await vi.advanceTimersByTimeAsync(750);
    expect(pollCalls()).toHaveLength(2);
    expect(replacement).toHaveBeenCalledTimes(3);
  });

  it("does not notify subscribers removed before a pending poll completes", async () => {
    let resolvePoll!: (events: ServiceEvent[]) => void;
    const pending = new Promise<ServiceEvent[]>((resolve) => { resolvePoll = resolve; });
    const received = vi.fn();
    const stop = await subscribe(received);
    tauri.invoke.mockReturnValueOnce(pending);
    await vi.advanceTimersByTimeAsync(750);
    stop();
    resolvePoll([packet, receipt]);
    await vi.advanceTimersByTimeAsync(0);

    expect(received).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("does not notify a subscriber removed by another callback during delivery", async () => {
    let stopRemoved!: () => void;
    const retained = vi.fn(() => stopRemoved());
    const removed = vi.fn();
    await subscribe(retained);
    stopRemoved = await subscribe(removed);
    queued.push(packet, receipt);

    await vi.advanceTimersByTimeAsync(750);

    expect(retained.mock.calls).toEqual([[packet], [receipt]]);
    expect(removed).not.toHaveBeenCalled();
  });

  it("treats repeated registrations of one callback as independent subscriptions", async () => {
    const received = vi.fn();
    const stopFirst = await subscribe(received);
    await subscribe(received);
    queued.push(packet);
    await vi.advanceTimersByTimeAsync(750);
    expect(received).toHaveBeenCalledTimes(2);

    stopFirst();
    queued.push(receipt);
    await vi.advanceTimersByTimeAsync(750);
    expect(received).toHaveBeenCalledTimes(3);
    expect(received).toHaveBeenLastCalledWith(receipt);
    expect(pollCalls()).toHaveLength(2);
  });

  it("isolates a failing subscriber and retries transient native polling errors", async () => {
    const error = new Error("Subscriber failed");
    const logError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const failing = vi.fn(() => { throw error; });
    const healthy = vi.fn();
    await subscribe(failing);
    await subscribe(healthy);
    tauri.invoke.mockRejectedValueOnce(new Error("Service locked"));
    queued.push(packet, receipt);

    await vi.advanceTimersByTimeAsync(750);
    expect(healthy).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(750);

    expect(pollCalls()).toHaveLength(2);
    expect(failing.mock.calls).toEqual([[packet], [receipt]]);
    expect(healthy.mock.calls).toEqual([[packet], [receipt]]);
    expect(logError).toHaveBeenCalledTimes(2);
  });

  it("pauses while hidden and shares the immediate poll when visibility resumes", async () => {
    const visibility = vi.spyOn(document, "visibilityState", "get");
    visibility.mockReturnValue("hidden");
    const ui = vi.fn();
    const bridge = vi.fn();
    await subscribe(ui);
    await subscribe(bridge);
    queued.push(packet, receipt);
    await vi.advanceTimersByTimeAsync(1_500);
    expect(pollCalls()).toHaveLength(0);

    visibility.mockReturnValue("visible");
    document.dispatchEvent(new Event("visibilitychange"));
    document.dispatchEvent(new Event("visibilitychange"));
    await vi.advanceTimersByTimeAsync(0);

    expect(pollCalls()).toHaveLength(1);
    expect(ui.mock.calls).toEqual([[packet], [receipt]]);
    expect(bridge.mock.calls).toEqual([[packet], [receipt]]);
  });

  it("preserves desktop native event delivery without starting a mobile poller", async () => {
    platform = "desktop";
    const received = vi.fn();
    const stop = await subscribe(received);
    const [channel, receiveNativeEvent] = tauri.listen.mock.calls[0];
    expect(channel).toBe("mesh-chat://service-event");
    receiveNativeEvent({ payload: receipt });
    await vi.advanceTimersByTimeAsync(1_500);

    expect(received.mock.calls).toEqual([[receipt]]);
    expect(pollCalls()).toHaveLength(0);
    expect(vi.getTimerCount()).toBe(0);
    stop();
    expect(nativeUnlisten).toHaveBeenCalledTimes(1);
  });
});

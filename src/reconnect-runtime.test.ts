import { afterEach, describe, expect, it, vi } from "vitest";

import { createReconnectDeps, closeNativeReconnectSessions, DISCONNECTED_SESSION_GRACE_MS } from "./reconnect-runtime";
import {
  closeWebRTCSession,
  getWebRTCSessionCount,
  getWebRTCSessions,
  setWebRTCSession,
} from "./webrtc-session";

const { attachMock, commandMock } = vi.hoisted(() => {
  let count = 0;
  return {
    commandMock: vi.fn(async (..._args: unknown[]) => ({})),
    attachMock: vi.fn(async (_channel: RTCDataChannel, _options?: {
      onClosed?: (bridgeId: string) => void; isCurrent?: () => boolean;
    }) => {
      count += 1;
      return {
        bridgeId: `bridge-${count}`,
        maxPacket: 500,
        close: vi.fn(async () => undefined),
      };
    }),
  };
});

vi.mock("./api", () => ({ serviceCommand: commandMock }));

vi.mock("./webrtc-onboarding", () => ({
  attachWebRTCBridge: attachMock,
}));

function peer(key: string) {
  const channel = {
    readyState: "open",
    close: vi.fn(),
  };
  const pc = {
    connectionState: "connected" as RTCPeerConnectionState,
    iceConnectionState: "connected" as RTCIceConnectionState,
    close: vi.fn(),
  };
  return {
    open: async () => channel,
    path: async () => "direct" as const,
    pc,
    channel,
    control: null as RTCDataChannel | null,
    onControl: null as ((control: RTCDataChannel) => void) | null,
    key,
  };
}

function profile(key: string) {
  return {
    id: key,
    contact_id: `contact-${key}`,
    display_name: key,
    local_device_id: "local",
    remote_device_id: "remote",
    auto_reconnect: true,
    allow_direct_ip_disclosure: false,
    relay_consent_scope: "contact",
    peer_auto_reconnect: true,
    peer_allow_direct_ip_disclosure: false,
    has_local_capabilities: true,
    has_peer_capabilities: true,
    capabilities_expires_at: 9_999_999_999,
    peer_capabilities_expires_at: 9_999_999_999,
    state: "idle" as const,
    active: false,
    last_attempt_at: 0,
    last_error: "",
    updated_at: 1,
    effective: {
      ready: true,
      configured: true,
      preferred: true,
      session: "s".repeat(40),
      mailbox_url: "https://signal.example.workers.dev",
      source: "local" as const,
      reasons: [],
    },
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((complete) => { resolve = complete; });
  return { promise, resolve };
}

afterEach(async () => {
  closeNativeReconnectSessions();
  await closeWebRTCSession();
  attachMock.mockClear();
  commandMock.mockClear();
  vi.useRealTimers();
});

describe("production reconnect wiring", () => {
  it.each(["all", "contact", "profile"])("fences a pending service-session refresh when closing %s", async (scope) => {
    const selected = { ...profile("refresh-race"), native_session_id: "native-refresh" };
    const stats = deferred<{ attached: boolean; ice_connection_state: string }>();
    let pending = false;
    commandMock.mockImplementation(async (...args: unknown[]) => {
      if (args[0] === "reconnect_profiles") return { profiles: [selected] };
      if (args[0] === "native_webrtc_stats") return pending ? stats.promise : { attached: true, ice_connection_state: "connected" };
      return {};
    });
    const deps = createReconnectDeps({ refresh: async () => undefined });
    await deps.profiles();
    pending = true;
    const refreshing = deps.profiles();
    await vi.waitFor(() => expect(commandMock.mock.calls.filter(([command]) => command === "native_webrtc_stats")).toHaveLength(2));
    expect(deps.hasSession?.(selected.id, selected.contact_id)).toBe(true);
    if (scope === "profile") await deps.closeSession?.(selected.id);
    else closeNativeReconnectSessions(scope === "contact" ? selected.contact_id : undefined);
    expect(commandMock).toHaveBeenCalledWith("native_webrtc_close", { session_id: selected.native_session_id });
    stats.resolve({ attached: true, ice_connection_state: "connected" });
    await refreshing;
    expect(deps.hasSession?.(selected.id, selected.contact_id)).toBe(false);
  });

  it("closes a service peer first discovered by a refresh that finishes after Disconnect", async () => {
    const response = deferred<{ profiles: Array<ReturnType<typeof profile> & { native_session_id: string }> }>();
    commandMock.mockImplementation(async (...args: unknown[]) => {
      if (args[0] === "reconnect_profiles") return response.promise;
      if (args[0] === "native_webrtc_stats") return { attached: true, ice_connection_state: "connected" };
      return {};
    });
    const deps = createReconnectDeps({ refresh: async () => undefined });
    const refreshing = deps.profiles();
    closeNativeReconnectSessions();
    response.resolve({ profiles: [{ ...profile("late-discovery"), native_session_id: "late-native" }] });
    await refreshing;
    expect(commandMock).toHaveBeenCalledWith("native_webrtc_close", { session_id: "late-native" });
    expect(deps.hasSession?.("late-discovery", "contact-late-discovery")).toBe(false);
  });

  it("keeps a known service peer through transient stats failures and retires a sustained outage", async () => {
    vi.useFakeTimers();
    let unavailable = false;
    commandMock.mockImplementation(async (...args: unknown[]) => {
      if (args[0] === "reconnect_profiles") return { profiles: [{ ...profile("query-error"), native_session_id: "native-query" }] };
      if (args[0] === "native_webrtc_stats") {
        if (unavailable) throw new Error("temporary query failure");
        return { attached: true, ice_connection_state: "connected" };
      }
      return {};
    });
    const deps = createReconnectDeps({ refresh: async () => undefined });
    await deps.profiles();
    unavailable = true;
    await deps.profiles();
    expect(deps.hasSession?.("query-error", "contact-query-error")).toBe(true);
    await vi.advanceTimersByTimeAsync(DISCONNECTED_SESSION_GRACE_MS);
    await deps.profiles();
    expect(deps.hasSession?.("query-error", "contact-query-error")).toBe(false);
    expect(commandMock).toHaveBeenCalledWith("native_webrtc_close", { session_id: "native-query" });
  });

  it("ignores an older health result after a replacement session was discovered", async () => {
    const oldStats = deferred<{ attached: boolean; ice_connection_state: string }>();
    let newest = false;
    commandMock.mockImplementation(async (...args: unknown[]) => {
      if (args[0] === "reconnect_profiles") return { profiles: [{ ...profile("replaced"), native_session_id: newest ? "new-peer" : "old-peer" }] };
      if (args[0] === "native_webrtc_stats") return (args[1] as { session_id: string }).session_id === "old-peer"
        ? oldStats.promise : { attached: true, ice_connection_state: "connected" };
      return {};
    });
    const deps = createReconnectDeps({ refresh: async () => undefined });
    const older = deps.profiles();
    await vi.waitFor(() => expect(commandMock).toHaveBeenCalledWith("native_webrtc_stats", { session_id: "old-peer" }));
    newest = true;
    await deps.profiles();
    oldStats.resolve({ attached: true, ice_connection_state: "disconnected" });
    await older;
    await deps.closeSession?.("replaced");
    expect(commandMock).toHaveBeenCalledWith("native_webrtc_close", { session_id: "new-peer" });
    expect(commandMock).not.toHaveBeenCalledWith("native_webrtc_close", { session_id: "old-peer" });
  });

  it("adopts a live service-owned manual session instead of negotiating a duplicate", async () => {
    commandMock.mockImplementation(async (...args: unknown[]) => {
      if (args[0] === "reconnect_profiles") return { profiles: [{ ...profile("manual"), native_session_id: "native-manual" }] };
      if (args[0] === "native_webrtc_stats") return { attached: true, ice_connection_state: "connected" };
      return {};
    });
    const deps = createReconnectDeps({ refresh: async () => undefined });
    await deps.profiles();
    expect(deps.hasSession?.("manual", "contact-manual")).toBe(true);
    expect(deps.hasSession?.("manual", "another-contact")).toBe(false);
    await deps.closeSession?.("manual");
    expect(commandMock).toHaveBeenCalledWith("native_webrtc_close", { session_id: "native-manual" });
    expect(deps.hasSession?.("manual", "contact-manual")).toBe(false);
    commandMock.mockImplementation(async () => ({}));
  });
  it("registers a late capability-only control channel without changing contact approval", async () => {
    const deps = createReconnectDeps({ refresh: async () => undefined });
    const fake = peer("late-control");
    await deps.attach(fake as never, profile("late-control"));
    const control = Object.assign(new EventTarget(), {
      readyState: "open", label: "meshchat-reconnect", onmessage: null,
      send: vi.fn(), close: vi.fn(),
    }) as unknown as RTCDataChannel;
    fake.onControl?.(control);
    await Promise.resolve();
    const registered = getWebRTCSessions()[0];
    expect(registered.control).toBe(control);
    expect(registered.controlPurpose).toBe("reconnect");
    expect(registered.approvalPending).toBe(false);
    expect(commandMock).toHaveBeenCalledWith("reconnect_capabilities_get", { contact_id: "contact-late-control" });
    expect(control.send).toHaveBeenCalledWith(JSON.stringify({ type: "connection_capabilities_request" }));
  });

  it.each(["closed", "cancelled"])("does not register a %s bridge after path lookup finishes", async (reason) => {
    const onSession = vi.fn();
    const deps = createReconnectDeps({ refresh: async () => undefined, onSession });
    const fake = peer("race");
    const path = deferred<"direct">();
    fake.path = vi.fn(() => path.promise);
    let current = true;
    const attaching = deps.attach(fake as never, profile("race"), () => current);
    const rejected = expect(attaching).rejects.toThrow(/cancelled|superseded/);
    await vi.waitFor(() => expect(fake.path).toHaveBeenCalled());
    if (reason === "closed") fake.channel.readyState = "closed";
    else current = false;
    path.resolve("direct");
    await rejected;

    const bridge = await attachMock.mock.results[0].value;
    expect(bridge.close).toHaveBeenCalledTimes(1);
    expect(fake.pc.close).toHaveBeenCalledTimes(1);
    expect(getWebRTCSessionCount()).toBe(0);
    expect(onSession).not.toHaveBeenCalled();
  });

  it("does not let a delayed close from the old bridge remove its replacement", async () => {
    const deps = createReconnectDeps({ refresh: async () => undefined });
    await deps.attach(peer("same") as never, profile("same"));
    const oldBridge = getWebRTCSessions()[0].bridge;
    const oldClosed = attachMock.mock.calls[0][1]?.onClosed;
    await deps.closeSession?.("same");
    const replacement = peer("same");
    await deps.attach(replacement as never, profile("same"));
    oldClosed?.(oldBridge.bridgeId);

    expect(getWebRTCSessionCount()).toBe(1);
    expect(getWebRTCSessions()[0].bridge.bridgeId).not.toBe(oldBridge.bridgeId);
    expect(replacement.pc.close).not.toHaveBeenCalled();
  });

  it("recognizes a live onboarding session for the contact and ignores dead sessions", () => {
    const fake = peer("onboarding");
    setWebRTCSession({
      key: "onboarding:bridge", bridge: { bridgeId: "manual", maxPacket: 1064, close: async () => undefined },
      channel: fake.channel as unknown as RTCDataChannel,
      pc: fake.pc as unknown as RTCPeerConnection, control: null, path: "direct",
      createdAt: 1, approvalPending: false, contactId: "contact-a",
    });
    const deps = createReconnectDeps({ refresh: async () => undefined });
    expect(deps.hasSession?.("profile-a", "contact-a")).toBe(true);
    expect(deps.hasSession?.("profile-b", "contact-b")).toBe(false);
    fake.channel.readyState = "closed";
    expect(deps.hasSession?.("profile-a", "contact-a")).toBe(false);
  });

  it.each(["connectionState", "iceConnectionState"] as const)(
    "retires a persistently disconnected %s even while its DataChannel stays open",
    async (state) => {
      vi.useFakeTimers();
      const deps = createReconnectDeps({ refresh: async () => undefined });
      const stale = peer("stale");
      const healthy = peer("healthy");
      await deps.attach(stale as never, profile("stale"));
      await deps.attach(healthy as never, profile("healthy"));
      const bridge = getWebRTCSessions().find((session) => session.key === "stale")!.bridge;

      stale.pc[state] = "disconnected";
      expect(deps.hasSession?.("stale", "contact-stale")).toBe(true);
      await vi.advanceTimersByTimeAsync(DISCONNECTED_SESSION_GRACE_MS - 1);
      expect(deps.hasSession?.("stale", "contact-stale")).toBe(true);
      expect(bridge.close).not.toHaveBeenCalled();
      await vi.advanceTimersByTimeAsync(1);
      expect(deps.hasSession?.("stale", "contact-stale")).toBe(false);
      await vi.advanceTimersByTimeAsync(0);

      expect(bridge.close).toHaveBeenCalledTimes(1);
      expect(stale.channel.close).toHaveBeenCalledTimes(1);
      expect(stale.pc.close).toHaveBeenCalledTimes(1);
      expect(getWebRTCSessions().map((session) => session.key)).toEqual(["healthy"]);
      expect(deps.hasSession?.("healthy", "contact-healthy")).toBe(true);
      expect(healthy.pc.close).not.toHaveBeenCalled();

      const replacement = peer("stale");
      await deps.attach(replacement as never, profile("stale"));
      expect(deps.hasSession?.("stale", "contact-stale")).toBe(true);
      expect(replacement.pc.close).not.toHaveBeenCalled();
    },
  );

  it("preserves a recovered session and restarts its grace for a later disconnect", async () => {
    vi.useFakeTimers();
    const deps = createReconnectDeps({ refresh: async () => undefined });
    const fake = peer("recovering");
    await deps.attach(fake as never, profile("recovering"));
    const bridge = getWebRTCSessions()[0].bridge;
    fake.pc.connectionState = "disconnected";
    expect(deps.hasSession?.("recovering", "contact-recovering")).toBe(true);
    await vi.advanceTimersByTimeAsync(DISCONNECTED_SESSION_GRACE_MS / 2);
    fake.pc.connectionState = "connected";
    expect(deps.hasSession?.("recovering", "contact-recovering")).toBe(true);
    await vi.advanceTimersByTimeAsync(DISCONNECTED_SESSION_GRACE_MS);
    fake.pc.iceConnectionState = "disconnected";
    expect(deps.hasSession?.("recovering", "contact-recovering")).toBe(true);
    await vi.advanceTimersByTimeAsync(DISCONNECTED_SESSION_GRACE_MS - 1);
    expect(deps.hasSession?.("recovering", "contact-recovering")).toBe(true);
    expect(bridge.close).not.toHaveBeenCalled();
    expect(fake.pc.close).not.toHaveBeenCalled();
  });

  it.each([
    ["connectionState", "failed"], ["connectionState", "closed"],
    ["iceConnectionState", "failed"], ["iceConnectionState", "closed"],
  ] as const)("retires %s=%s without waiting for the DataChannel to close", async (field, state) => {
    const deps = createReconnectDeps({ refresh: async () => undefined });
    const fake = peer("terminated");
    await deps.attach(fake as never, profile("terminated"));
    const bridge = getWebRTCSessions()[0].bridge;
    fake.pc[field] = state;

    expect(deps.hasSession?.("terminated", "contact-terminated")).toBe(false);
    expect(getWebRTCSessionCount()).toBe(0);
    await Promise.resolve();
    expect(bridge.close).toHaveBeenCalledTimes(1);
    expect(fake.pc.close).toHaveBeenCalledTimes(1);
  });

  it("binds all signaling verification commands to the expected profile", async () => {
    const deps = createReconnectDeps({ refresh: async () => undefined });
    await deps.verifyRequest("request", "workspace-profile");
    await deps.verifyOffer("offer", "workspace-profile");
    await deps.verifyAnswer("answer", "offer", "workspace-profile");
    expect(commandMock.mock.calls).toEqual([
      ["verify_reconnect_request", { document: "request", profile_id: "workspace-profile" }],
      ["verify_reconnect_offer", { document: "offer", profile_id: "workspace-profile" }],
      ["verify_reconnect_answer", { document: "answer", offer_document: "offer", profile_id: "workspace-profile" }],
    ]);
  });

  it("keeps three peer bridges registered and closes only the selected peer", async () => {
    const onSession = vi.fn();
    const deps = createReconnectDeps({
      refresh: async () => undefined,
      onSession,
    });

    for (const key of ["one", "two", "three"]) {
      const fake = peer(key);
      await deps.attach(fake as never, profile(key) as never);
    }

    expect(getWebRTCSessionCount()).toBe(3);
    expect(getWebRTCSessions().map((session) => session.key)).toEqual([
      "one",
      "two",
      "three",
    ]);
    expect(onSession).toHaveBeenCalledTimes(3);
    expect(deps.hasSession?.("one", "contact-one")).toBe(true);
    expect(deps.hasSession?.("two", "contact-two")).toBe(true);
    expect(deps.hasSession?.("three", "contact-three")).toBe(true);

    await deps.closeSession?.("two");
    expect(getWebRTCSessionCount()).toBe(2);
    expect(getWebRTCSessions().map((session) => session.key)).toEqual(["one", "three"]);
    expect(deps.hasSession?.("two", "contact-two")).toBe(false);
  });
});

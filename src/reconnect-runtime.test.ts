import { afterEach, describe, expect, it, vi } from "vitest";

import { createReconnectDeps } from "./reconnect-runtime";
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
  const pc = { close: vi.fn() };
  return {
    open: async () => channel,
    path: async () => "direct" as const,
    pc,
    channel,
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
  await closeWebRTCSession();
  attachMock.mockClear();
  commandMock.mockClear();
});

describe("production reconnect wiring", () => {
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

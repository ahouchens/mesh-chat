import { afterEach, describe, expect, it, vi } from "vitest";

import { createReconnectDeps } from "./reconnect-runtime";
import {
  closeWebRTCSession,
  getWebRTCSessionCount,
  getWebRTCSessions,
} from "./webrtc-session";

const { attachMock } = vi.hoisted(() => {
  let count = 0;
  return {
    attachMock: vi.fn(async () => {
      count += 1;
      return {
        bridgeId: `bridge-${count}`,
        maxPacket: 500,
        close: vi.fn(async () => undefined),
      };
    }),
  };
});

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

afterEach(async () => {
  await closeWebRTCSession();
  attachMock.mockClear();
});

describe("production reconnect wiring", () => {
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

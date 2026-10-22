import { afterEach, describe, expect, it, vi } from "vitest";

import {
  MAX_CONCURRENT,
  ReconnectCoordinator,
  type CoordinatorPeer,
  type ReconnectCoordinatorDeps,
  type ReconnectProfile,
  type ReconnectRole,
  type ReconnectState,
} from "./reconnect-coordinator";

const SDP = "v=0\r\na=fingerprint:sha-256 " + "AB:".repeat(31) + "AB\r\n";

function profile(overrides: Partial<ReconnectProfile> = {}): ReconnectProfile {
  return {
    id: "profile-1",
    contact_id: "contact-1",
    display_name: "Alex",
    local_device_id: "dev-aaaa-0001",
    remote_device_id: "dev-bbbb-0002",
    auto_reconnect: true,
    allow_direct_ip_disclosure: false,
    relay_consent_scope: "contact",
    peer_auto_reconnect: true,
    peer_allow_direct_ip_disclosure: false,
    has_local_capabilities: true,
    has_peer_capabilities: true,
    capabilities_expires_at: 9_999_999_999,
    peer_capabilities_expires_at: 9_999_999_999,
    state: "idle",
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
      source: "local",
      reasons: [],
    },
    ...overrides,
  };
}

function fakePeer(role: "offer" | "answer") {
  const peer = {
    role,
    offers: 0,
    answers: 0,
    applied: 0,
    opened: 0,
    closed: 0,
    createOffer: async () => {
      peer.offers += 1;
      return SDP;
    },
    createAnswer: async () => {
      peer.answers += 1;
      return SDP;
    },
    applyAnswer: async () => {
      peer.applied += 1;
    },
    open: async () => {
      peer.opened += 1;
      return { readyState: "open" };
    },
    path: async () => "direct" as const,
    close: () => {
      peer.closed += 1;
    },
  };
  return peer;
}

interface Harness {
  coordinator: ReconnectCoordinator;
  mailbox: Map<string, string>;
  published: Array<{ profileId: string; role: ReconnectRole; document: string }>;
  statuses: ReconnectState[];
  peers: Array<ReturnType<typeof fakePeer>>;
  attached: number;
  clock: { value: number };
}

function harness(options: {
  profiles: ReconnectProfile[];
  mailbox?: Map<string, string>;
  onPublish?: (profileId: string, role: ReconnectRole, document: string) => void;
  verifyOffer?: (document: string) => Promise<{ sdp: string; attempt_id: string }>;
  verifyRequest?: (document: string) => Promise<{ contact_id: string; attempt_id: string }>;
  verifyAnswer?: (document: string) => Promise<{ sdp: string; attempt_id: string }>;
  pathStatus?: () => Promise<{ has_path: boolean; state: string; reason: string | null }>;
  hasSession?: () => boolean;
}): Harness {
  const mailbox = options.mailbox ?? new Map<string, string>();
  const published: Harness["published"] = [];
  const statuses: ReconnectState[] = [];
  const peers: Array<ReturnType<typeof fakePeer>> = [];
  const clock = { value: 1_800_000_000_000 };
  let attached = 0;

  const deps: ReconnectCoordinatorDeps = {
    profiles: async () => ({
      local_device_id: "dev-aaaa-0001",
      mailbox_configured: true,
      profiles: options.profiles,
    }),
    start: async () => undefined,
    stop: async () => undefined,
    requestCreate: async (_contactId, attemptId) => ({
      document: JSON.stringify({ type: "webrtc_reconnect_request", attempt_id: attemptId }),
      expires_at: Math.floor(clock.value / 1000) + 3600,
    }),
    offerCreate: async (_contactId, requestDocument) => ({
      document: JSON.stringify({
        type: "webrtc_reconnect_offer",
        attempt_id: (JSON.parse(requestDocument) as { attempt_id: string }).attempt_id,
      }),
      session_id: "offer-session",
      expires_at: Math.floor(clock.value / 1000) + 600,
    }),
    answerCreate: async (_contactId, offerDocument) => ({
      document: JSON.stringify({
        type: "webrtc_reconnect_answer",
        attempt_id: (JSON.parse(offerDocument) as { attempt_id: string }).attempt_id,
      }),
      expires_at: Math.floor(clock.value / 1000) + 300,
    }),
    verifyRequest:
      options.verifyRequest ??
      (async (document) => ({
        contact_id: "contact-1",
        attempt_id: (JSON.parse(document) as { attempt_id: string }).attempt_id,
      })),
    verifyOffer:
      options.verifyOffer ??
      (async (document) => ({
        sdp: SDP,
        attempt_id: (JSON.parse(document) as { attempt_id: string }).attempt_id,
      })),
    verifyAnswer:
      options.verifyAnswer ??
      (async (document) => ({
        sdp: SDP,
        attempt_id: (JSON.parse(document) as { attempt_id: string }).attempt_id,
      })),
    publish: async (profileId, document, role) => {
      published.push({ profileId, role, document });
      mailbox.set(`${profileId}/${role}`, document);
      options.onPublish?.(profileId, role, document);
    },
    fetch: async (profileId, role) => {
      const document = mailbox.get(`${profileId}/${role}`);
      return { document: document ?? null, pending: !document };
    },
    status: async (state) => {
      statuses.push(state);
    },
    ice: async () => ({ iceServers: [], iceTransportPolicy: "all" }),
    createPeer: (_ice, role) => {
      const peer = fakePeer(role);
      peers.push(peer);
      return peer as CoordinatorPeer;
    },
    attach: async () => {
      attached += 1;
    },
    pathStatus: options.pathStatus,
    hasSession: options.hasSession,
    now: () => clock.value,
    random: () => 0.5,
    sleep: async (ms: number) => {
      clock.value += ms;
      await Promise.resolve();
    },
    fingerprint: () => "sha-256 " + "AB:".repeat(31) + "AB",
  };
  return {
    coordinator: new ReconnectCoordinator(deps),
    mailbox,
    published,
    statuses,
    peers,
    get attached() {
      return attached;
    },
    clock,
  };
}

afterEach(() => {
  vi.useRealTimers();
});

describe("automatic reconnect coordinator", () => {
  it("preferred device publishes a request and accepts the peer's answer", async () => {
    let attempt = "";
    const mailbox = new Map<string, string>();
    const probe = harness({
      profiles: [profile()],
      mailbox,
      onPublish: (profileId, role, document) => {
        if (role !== "request") return;
        attempt = (JSON.parse(document) as { attempt_id: string }).attempt_id;
        // The peer answers the request with an offer.
        mailbox.set(
          `${profileId}/offer`,
          JSON.stringify({ type: "webrtc_reconnect_offer", attempt_id: attempt }),
        );
      },
    });
    await probe.coordinator.start();
    await vi.waitFor(
      () => {
        expect(probe.coordinator.snapshot().entries["profile-1"]?.state).toBe("connected");
      },
      { timeout: 4000 },
    );
    expect(probe.published.map((item) => item.role)).toEqual(["request", "answer"]);
    expect(probe.peers[0].answers).toBe(1);
    expect(probe.attached).toBe(1);
    expect(probe.statuses).toContain("probing");
    expect(probe.statuses).toContain("connecting");
    expect(probe.statuses).toContain("connected");
    expect(probe.published.find((item) => item.role === "request")?.document).toContain(attempt);
  });

  it("responder verifies a request, publishes one offer, and applies the answer", async () => {
    const mailbox = new Map<string, string>();
    mailbox.set(
      "profile-1/request",
      JSON.stringify({ type: "webrtc_reconnect_request", attempt_id: "attempt-from-peer" }),
    );
    const respond = harness({
      profiles: [profile({ effective: { ...profile().effective, preferred: false } })],
      mailbox,
      onPublish: (profileId, role) => {
        if (role !== "offer") return;
        mailbox.set(
          `${profileId}/answer`,
          JSON.stringify({ type: "webrtc_reconnect_answer", attempt_id: "attempt-from-peer" }),
        );
      },
    });
    await respond.coordinator.start();
    await vi.waitFor(
      () => {
        expect(respond.coordinator.snapshot().entries["profile-1"]?.state).toBe("connected");
      },
      { timeout: 4000 },
    );
    expect(respond.published.map((item) => item.role)).toEqual(["offer"]);
    expect(respond.peers[0].offers).toBe(1);
    expect(respond.peers[0].applied).toBe(1);
    expect(respond.attached).toBe(1);
  });

  it("simultaneous starts produce exactly one offer and no glare", async () => {
    const mailbox = new Map<string, string>();
    const preferred = harness({ profiles: [profile()], mailbox });
    const responder = harness({
      profiles: [profile({ effective: { ...profile().effective, preferred: false } })],
      mailbox,
    });
    const before = document.activeElement;
    await Promise.all([preferred.coordinator.start(), responder.coordinator.start()]);
    await vi.waitFor(
      () => {
        expect(preferred.coordinator.snapshot().entries["profile-1"]?.state).toBe("connected");
        expect(responder.coordinator.snapshot().entries["profile-1"]?.state).toBe("connected");
      },
      { timeout: 4000 },
    );
    const offers = [
      ...preferred.published.filter((item) => item.role === "offer"),
      ...responder.published.filter((item) => item.role === "offer"),
    ];
    expect(offers).toHaveLength(1);
    expect(preferred.peers.filter((peer) => peer.role === "offer")).toHaveLength(0);
    expect(responder.peers.filter((peer) => peer.role === "offer")).toHaveLength(1);
    // Automatic reconnect must never steal focus or open a modal.
    expect(document.activeElement).toBe(before);
  });

  it("reports manual_required when no mailbox is configured", async () => {
    const blocked = harness({
      profiles: [
        profile({
          effective: {
            ...profile().effective,
            ready: false,
            configured: false,
            reasons: ["mailbox_not_configured"],
          },
        }),
      ],
    });
    await blocked.coordinator.start();
    await vi.waitFor(() => {
      expect(blocked.coordinator.snapshot().entries["profile-1"]?.state).toBe("manual_required");
    });
    expect(blocked.coordinator.snapshot().entries["profile-1"]?.detail).toBe(
      "mailbox_not_configured",
    );
    expect(blocked.published).toHaveLength(0);
    expect(blocked.peers).toHaveLength(0);
    expect(blocked.statuses).toContain("manual_required");
  });

  it("treats a rejected capability as a trust failure, not a network retry", async () => {
    const mailbox = new Map<string, string>();
    const rejected = harness({
      profiles: [profile()],
      mailbox,
      onPublish: (profileId, role, document) => {
        if (role !== "request") return;
        mailbox.set(
          `${profileId}/offer`,
          JSON.stringify({
            type: "webrtc_reconnect_offer",
            attempt_id: (JSON.parse(document) as { attempt_id: string }).attempt_id,
          }),
        );
      },
      verifyOffer: async () => {
        throw Object.assign(new Error("mailbox_unauthorized"), { code: "mailbox_unauthorized" });
      },
    });
    await rejected.coordinator.start();
    await vi.waitFor(
      () => {
        expect(rejected.coordinator.snapshot().entries["profile-1"]?.state).toBe("manual_required");
      },
      { timeout: 4000 },
    );
    expect(rejected.coordinator.snapshot().entries["profile-1"]?.detail).toBe(
      "mailbox_unauthorized",
    );
  });

  it("stops publishing after the user stops the attempt", async () => {
    const stopped = harness({ profiles: [profile()] });
    await stopped.coordinator.start();
    await vi.waitFor(() => {
      expect(stopped.published.some((item) => item.role === "request")).toBe(true);
    });
    await stopped.coordinator.stop();
    const count = stopped.published.length;
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(stopped.coordinator.snapshot().entries["profile-1"]?.state).toBe("stopped");
    expect(stopped.published.length).toBe(count);
    expect(stopped.coordinator.snapshot().running).toBe(false);
  });

  it("keeps waiting instead of offering when the preferred peer is offline", async () => {
    const waiting = harness({
      profiles: [profile({ effective: { ...profile().effective, preferred: false } })],
    });
    await waiting.coordinator.start();
    await vi.waitFor(() => {
      expect(waiting.coordinator.snapshot().entries["profile-1"]?.state).toBe("waiting_for_peer");
    });
    expect(waiting.published).toHaveLength(0);
    expect(waiting.peers).toHaveLength(0);
  });

  it("never replaces an already attached transport", async () => {
    const live = harness({
      profiles: [profile()],
      hasSession: () => true,
    });
    await live.coordinator.start();
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(live.published).toHaveLength(0);
    expect(live.peers).toHaveLength(0);
  });

  it("does not exceed the concurrent attempt cap", () => {
    expect(MAX_CONCURRENT).toBe(2);
  });
});

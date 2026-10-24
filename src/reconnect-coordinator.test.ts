import { afterEach, describe, expect, it, vi } from "vitest";

import {
  MAX_CONCURRENT,
  MAILBOX_POLL_MS,
  PATH_TIMEOUT_MS,
  PATH_POLL_MS,
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

function fakePeer(role: "offer" | "answer", failFirstOpen = false) {
  const peer = {
    role,
    offers: 0,
    answers: 0,
    applied: 0,
    opened: 0,
    closed: 0,
    failFirstOpen,
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
      if (failFirstOpen && peer.opened === 1) {
        throw new Error("network switched");
      }
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
  sessions: Set<string>;
  deps: ReconnectCoordinatorDeps;
}

function harness(options: {
  profiles: ReconnectProfile[];
  mailbox?: Map<string, string>;
  onPublish?: (profileId: string, role: ReconnectRole, document: string) => void;
  verifyOffer?: (document: string) => Promise<{ sdp: string; attempt_id: string }>;
  verifyRequest?: (document: string) => Promise<{ contact_id: string; attempt_id: string }>;
  verifyAnswer?: (document: string) => Promise<{ sdp: string; attempt_id: string }>;
  pathStatus?: () => Promise<{ has_path: boolean; state: string; reason: string | null }>;
  hasSession?: (profileId?: string, contactId?: string) => boolean;
  failFirstOpen?: boolean;
  overrides?: Partial<ReconnectCoordinatorDeps>;
}): Harness {
  const mailbox = options.mailbox ?? new Map<string, string>();
  const published: Harness["published"] = [];
  const statuses: ReconnectState[] = [];
  const peers: Array<ReturnType<typeof fakePeer>> = [];
  const clock = { value: 1_800_000_000_000 };
  let attached = 0;
  const sessions = new Set<string>();

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
      const peer = fakePeer(role, Boolean(options.failFirstOpen && peers.length === 0));
      peers.push(peer);
      return peer as CoordinatorPeer;
    },
    attach: async (_peer, profile) => {
      attached += 1;
      sessions.add(profile.id);
    },
    pathStatus: options.pathStatus,
    hasSession: (profileId, contactId) => sessions.has(profileId) || Boolean(options.hasSession?.(profileId, contactId)),
    closeSession: async (profileId) => { sessions.delete(profileId); },
    now: () => clock.value,
    random: () => 0.5,
    sleep: async (ms: number) => {
      // The supervisor persists after success. Always yield to real timers,
      // even when another attempt wakes it before its scheduled refresh.
      await new Promise((resolve) => setTimeout(resolve, 0));
      clock.value += ms;
    },
    fingerprint: () => "sha-256 " + "AB:".repeat(31) + "AB",
    ...options.overrides,
  };
  const coordinator = new ReconnectCoordinator(deps);
  coordinators.push(coordinator);
  return {
    coordinator,
    mailbox,
    published,
    statuses,
    peers,
    get attached() {
      return attached;
    },
    clock,
    sessions,
    deps,
  };
}

const coordinators: ReconnectCoordinator[] = [];

afterEach(async () => {
  // Stop every coordinator so an intentionally passive "waiting for peer"
  // loop cannot keep running (and starving the runner) after its test.
  await Promise.all(
    coordinators.splice(0).map((coordinator) =>
      coordinator.stop().catch(() => undefined),
    ),
  );
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
    // The offer was rejected before any RTCPeerConnection was allocated.
    expect(rejected.peers).toHaveLength(0);
  });

  it("retries with a fresh transport after a network-path failure", async () => {
    const mailbox = new Map<string, string>();
    const retried = harness({
      profiles: [profile()],
      mailbox,
      failFirstOpen: true,
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
    });
    await retried.coordinator.start();
    await vi.waitFor(
      () => {
        expect(retried.coordinator.snapshot().entries["profile-1"]?.state).toBe("connected");
      },
      { timeout: 6000 },
    );
    expect(retried.peers.length).toBeGreaterThanOrEqual(2);
    expect(retried.peers[0].opened).toBe(1);
    expect(retried.published.filter((item) => item.role === "request").length).toBeGreaterThanOrEqual(2);
    expect(retried.statuses).toContain("retry_wait");
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

  it("reconnects another profile when one peer already has a session", async () => {
    const first = profile();
    const second = profile({
      id: "profile-2",
      contact_id: "contact-2",
      display_name: "Bailey",
      effective: { ...profile().effective, preferred: false },
    });
    const mailbox = new Map<string, string>();
    mailbox.set(
      "profile-2/request",
      JSON.stringify({ attempt_id: "attempt-2", contact_id: "contact-2" }),
    );
    mailbox.set(
      "profile-2/answer",
      JSON.stringify({ attempt_id: "attempt-2", sdp: SDP }),
    );
    const live = harness({
      profiles: [first, second],
      mailbox,
      hasSession: (profileId) => profileId === "profile-1",
      verifyRequest: async (document) => ({
        contact_id: "contact-2",
        attempt_id: (JSON.parse(document) as { attempt_id: string }).attempt_id,
      }),
    });
    await live.coordinator.start();
    await vi.waitFor(() => expect(live.attached).toBe(1));
    expect(live.published.filter((item) => item.profileId === "profile-1")).toHaveLength(0);
    expect(live.published.filter((item) => item.profileId === "profile-2").map((item) => item.role)).toEqual(["offer"]);
    expect(live.coordinator.snapshot().entries["profile-2"]?.state).toBe("connected");
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

});

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((complete) => { resolve = complete; });
  return { promise, resolve };
}

function supervised(profiles: ReconnectProfile[], overrides: Partial<ReconnectCoordinatorDeps> = {}) {
  vi.useFakeTimers();
  vi.setSystemTime(1_800_000_000_000);
  const mailbox = new Map<string, string>();
  return harness({
    profiles,
    mailbox,
    onPublish: (id, role, document) => {
      if (role === "request") mailbox.set(id + "/offer", document);
    },
    overrides: {
      now: () => Date.now(),
      sleep: (ms) => new Promise((resolve) => window.setTimeout(resolve, ms)),
      ...overrides,
    },
  });
}

describe("persistent reconnect supervision", () => {
  it.each(["connected", "stopped"] as const)("starts a fresh negotiation after restart with persisted %s state", async (state) => {
    const probe = supervised([profile({ state, active: state === "connected" })]);
    // A cold renderer has no RTCPeerConnections, even when the service's last
    // recorded state was connected (or an orderly shutdown recorded stopped).
    expect(probe.sessions.size).toBe(0);
    await probe.coordinator.start();
    await vi.advanceTimersByTimeAsync(0);

    expect(probe.attached).toBe(1);
    expect(probe.published.map((event) => event.role)).toEqual(["request", "answer"]);
    expect(probe.coordinator.snapshot().entries["profile-1"].state).toBe("connected");
  });

  it.each([
    { auto_reconnect: false, peer_auto_reconnect: true },
    { auto_reconnect: true, peer_auto_reconnect: false },
  ])("does not infer reciprocal consent from a persisted connected state (%j)", async (consent) => {
    const probe = supervised([profile({ state: "connected", active: true, ...consent })]);
    await probe.coordinator.start();
    await vi.advanceTimersByTimeAsync(3_000);

    expect(probe.attached).toBe(0);
    expect(probe.published).toEqual([]);
    expect(probe.peers).toEqual([]);
    const entry = probe.coordinator.snapshot().entries["profile-1"];
    expect(entry.state).toBe(consent.auto_reconnect ? "manual_required" : "stopped");
    expect(entry.detail).toBe(consent.auto_reconnect
      ? "The contact has not enabled automatic reconnect on their device."
      : "Automatic reconnect is off on this device.");
  });

  it("preserves a live manual connection while automatic reconnect is off", async () => {
    const probe = supervised([profile({ state: "connected", auto_reconnect: false, peer_auto_reconnect: false })]);
    probe.sessions.add("profile-1");
    await probe.coordinator.start();
    await vi.advanceTimersByTimeAsync(3_000);

    expect(probe.coordinator.snapshot().entries["profile-1"].state).toBe("connected");
    expect(probe.sessions.has("profile-1")).toBe(true);
    expect(probe.published).toEqual([]);
  });

  it("keeps a healthy session and reconnects after it closes without another user action", async () => {
    const probe = supervised([profile()]);
    await probe.coordinator.start();
    await vi.advanceTimersByTimeAsync(0);
    expect(probe.attached).toBe(1);
    await vi.advanceTimersByTimeAsync(3_000);
    expect(probe.attached).toBe(1);

    probe.sessions.delete("profile-1");
    await vi.advanceTimersByTimeAsync(1_000);

    expect(probe.attached).toBe(2);
    expect(probe.coordinator.snapshot().entries["profile-1"].state).toBe("connected");
    const requests = probe.published.filter((event) => event.role === "request");
    expect(requests).toHaveLength(2);
    expect(requests[0].document).not.toBe(requests[1].document);
  });

  it("discovers new profiles and later peer consent while the app stays open", async () => {
    const profiles: ReconnectProfile[] = [];
    const probe = supervised(profiles);
    await probe.coordinator.start();
    await vi.advanceTimersByTimeAsync(0);
    profiles.push(profile({ peer_auto_reconnect: false }));
    await vi.advanceTimersByTimeAsync(1_000);
    expect(probe.attached).toBe(0);

    profiles[0] = profile();
    profiles.push(profile({ id: "profile-2", contact_id: "contact-2" }));
    await vi.advanceTimersByTimeAsync(1_000);

    expect(probe.sessions).toEqual(new Set(["profile-1", "profile-2"]));
    expect(probe.attached).toBe(2);
  });

  it("serves a third reachable peer when the first two preferred peers are offline", async () => {
    const passive = { ...profile().effective, preferred: false };
    const profiles = [1, 2, 3].map((id) => profile({ id: "profile-" + id, contact_id: "contact-" + id, effective: passive }));
    const probe = supervised(profiles, {
      verifyRequest: async () => ({ contact_id: "contact-3", attempt_id: "third" }),
    });
    probe.mailbox.set("profile-3/request", JSON.stringify({ attempt_id: "third" }));
    probe.mailbox.set("profile-3/answer", JSON.stringify({ attempt_id: "third" }));
    const fetch = vi.spyOn(probe.deps, "fetch");
    await probe.coordinator.start();
    await vi.advanceTimersByTimeAsync(0);

    expect(probe.sessions).toEqual(new Set(["profile-3"]));
    expect(new Set(fetch.mock.calls.map(([id]) => id))).toEqual(new Set(profiles.map((item) => item.id)));
    expect(probe.coordinator.snapshot().entries["profile-1"].state).toBe("waiting_for_peer");
    expect(probe.coordinator.snapshot().entries["profile-2"].state).toBe("waiting_for_peer");
  });

  it("does not make a reachable preferred profile wait behind offline contacts", async () => {
    const profiles = [1, 2, 3].map((id) => profile({ id: "profile-" + id, contact_id: "contact-" + id }));
    const probe = supervised(profiles);
    const publish = probe.deps.publish;
    probe.deps.publish = async (id, document, role) => {
      await publish(id, document, role);
      if (id !== "profile-3") probe.mailbox.delete(id + "/offer");
    };
    await probe.coordinator.start();
    await vi.advanceTimersByTimeAsync(0);
    expect(probe.sessions).toEqual(new Set(["profile-3"]));
    expect(probe.peers).toHaveLength(1);
    expect(new Set(probe.published.filter((event) => event.role === "request").map((event) => event.profileId))).toEqual(
      new Set(profiles.map((item) => item.id)),
    );
  });

  it("paces idle responder mailbox reads without allocating transports", async () => {
    const probe = supervised([profile({ effective: { ...profile().effective, preferred: false } })]);
    const fetch = vi.spyOn(probe.deps, "fetch");
    await probe.coordinator.start();
    await vi.advanceTimersByTimeAsync(MAILBOX_POLL_MS - 1);
    expect(fetch).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(probe.peers).toEqual([]);
  });

  it("keeps retrying past twenty failures and connects when the peer returns", async () => {
    const probe = supervised([profile()]);
    const requestCreate = probe.deps.requestCreate;
    let available = false;
    probe.deps.requestCreate = async (...args) => {
      if (!available) throw new Error("network unavailable");
      return requestCreate(...args);
    };
    await probe.coordinator.start();
    await vi.advanceTimersByTimeAsync(22 * 60_000);
    expect(probe.coordinator.snapshot().entries["profile-1"].attempts).toBeGreaterThan(20);
    expect(probe.coordinator.snapshot().entries["profile-1"].state).toBe("peer_offline");
    available = true;
    await vi.advanceTimersByTimeAsync(60_000);
    expect(probe.attached).toBe(1);
    expect(probe.coordinator.snapshot().entries["profile-1"].state).toBe("connected");
  });

  it("pauses network work offline and wakes without undoing a stopped contact", async () => {
    const profiles = [1, 2].map((id) => profile({ id: "profile-" + id, contact_id: "contact-" + id }));
    const probe = supervised(profiles);
    const read = vi.spyOn(probe.deps, "profiles");
    probe.coordinator.setOnline(false);
    await probe.coordinator.start();
    await probe.coordinator.stop("contact-2");
    await vi.advanceTimersByTimeAsync(10_000);
    expect(read).not.toHaveBeenCalled();
    expect(probe.published).toEqual([]);
    probe.coordinator.setOnline(true);
    probe.coordinator.wake();
    await vi.advanceTimersByTimeAsync(0);
    expect(probe.sessions).toEqual(new Set(["profile-1"]));
    expect(probe.coordinator.snapshot().entries["profile-2"].state).toBe("stopped");
  });

  it("keeps messaging pending after path timeout and marks ready when the route arrives", async () => {
    let ready = false;
    const probe = supervised([profile()], {
      pathStatus: async () => ({ has_path: true, ready, state: "path_available", reason: null }),
    });
    await probe.coordinator.start();
    await vi.advanceTimersByTimeAsync(PATH_TIMEOUT_MS + 1_000);
    expect(probe.attached).toBe(1);
    expect(probe.coordinator.snapshot().entries["profile-1"].state).toBe("connecting");
    expect(probe.peers[0].closed).toBe(0);
    ready = true;
    await vi.advanceTimersByTimeAsync(PATH_POLL_MS);
    expect(probe.coordinator.snapshot().entries["profile-1"].state).toBe("connected");
    expect(probe.attached).toBe(1);
  });

  it.each(["identity_mismatch", "reconnect_replayed"])("ignores a previous mailbox answer rejected as %s until a fresh answer arrives", async (code) => {
    const probe = supervised([profile({ effective: { ...profile().effective, preferred: false } })], {
      verifyRequest: async () => ({ contact_id: "contact-1", attempt_id: "fresh-attempt" }),
      verifyAnswer: async (document) => {
        if (document === "old-answer") throw Object.assign(new Error(code), { code });
        return { sdp: SDP, attempt_id: "fresh-attempt" };
      },
    });
    probe.mailbox.set("profile-1/request", JSON.stringify({ attempt_id: "fresh-attempt" }));
    probe.mailbox.set("profile-1/answer", "old-answer");
    await probe.coordinator.start();
    await vi.advanceTimersByTimeAsync(3_000);
    expect(probe.attached).toBe(0);
    expect(probe.coordinator.snapshot().entries["profile-1"].state).toBe("answer_pending");
    probe.mailbox.set("profile-1/answer", "fresh-answer");
    await vi.advanceTimersByTimeAsync(1_000);
    expect(probe.attached).toBe(1);
    expect(probe.coordinator.snapshot().entries["profile-1"].state).toBe("connected");
  });

  it.each(["ice", "createAnswer", "answerCreate", "open", "attach"] as const)("honors per-contact stop during %s", async (phase) => {
    const probe = supervised([profile()]);
    const gate = deferred<void>();
    const reached = vi.fn();
    if (phase === "ice") {
      const original = probe.deps.ice;
      probe.deps.ice = async (item) => { reached(); await gate.promise; return original(item); };
    } else if (phase === "answerCreate") {
      const original = probe.deps.answerCreate;
      probe.deps.answerCreate = async (...args) => { reached(); await gate.promise; return original(...args); };
    } else if (phase === "attach") {
      const original = probe.deps.attach;
      probe.deps.attach = async (peer, item, isCurrent) => {
        reached();
        await gate.promise;
        if (!isCurrent?.()) throw new Error("cancelled_attach");
        return original(peer, item, isCurrent);
      };
    } else {
      const original = probe.deps.createPeer;
      probe.deps.createPeer = (ice, role) => {
        const peer = original(ice, role);
        if (phase === "createAnswer") {
          const createAnswer = peer.createAnswer;
          peer.createAnswer = async (offer) => { reached(); await gate.promise; return createAnswer(offer); };
        } else {
          const open = peer.open;
          peer.open = async () => { reached(); await gate.promise; return open(); };
        }
        return peer;
      };
    }
    await probe.coordinator.start();
    await vi.advanceTimersByTimeAsync(0);
    expect(reached).toHaveBeenCalledTimes(1);
    await probe.coordinator.stop("contact-1");
    const publicationsAtStop = probe.published.length;
    gate.resolve();
    await vi.advanceTimersByTimeAsync(5_000);

    expect(probe.published).toHaveLength(publicationsAtStop);
    expect(probe.attached).toBe(0);
    expect(probe.sessions.size).toBe(0);
    expect(probe.coordinator.snapshot().entries["profile-1"].state).toBe("stopped");
  });

  it("remembers a contact stop made before the initial profile read finishes", async () => {
    const pending = deferred<Awaited<ReturnType<ReconnectCoordinatorDeps["profiles"]>>>();
    const probe = supervised([profile()], { profiles: () => pending.promise });
    await probe.coordinator.start();
    await probe.coordinator.stop("contact-1");
    pending.resolve({ local_device_id: "local", mailbox_configured: true, profiles: [profile()] });
    await vi.advanceTimersByTimeAsync(2_000);

    expect(probe.published).toHaveLength(0);
    expect(probe.attached).toBe(0);
    expect(probe.coordinator.snapshot().entries["profile-1"].state).toBe("stopped");
  });

  it("bounds simultaneous retries and preserves other attempts and healthy sessions", async () => {
    const profiles = [1, 2, 3].map((id) => profile({ id: "profile-" + id, contact_id: "contact-" + id }));
    const pending: Array<{ id: string; complete: (result: { document: null; pending: boolean }) => void }> = [];
    let active = 0;
    let maximumActive = 0;
    const probe = supervised(profiles, {
      fetch: (id) => {
        active += 1;
        maximumActive = Math.max(maximumActive, active);
        return new Promise((resolve) => pending.push({ id, complete: (result) => { active -= 1; resolve(result); } }));
      },
    });
    probe.sessions.add("profile-3");
    const close = vi.spyOn(probe.deps, "closeSession");
    await probe.coordinator.start();
    await vi.advanceTimersByTimeAsync(0);
    expect(pending.map(({ id }) => id)).toEqual(["profile-1", "profile-2"]);

    await Promise.all([probe.coordinator.retryNow("contact-1"), probe.coordinator.retryNow("contact-1")]);
    await vi.advanceTimersByTimeAsync(2_000);
    expect(pending).toHaveLength(2);
    pending[0].complete({ document: null, pending: true });
    await vi.advanceTimersByTimeAsync(0);

    expect(pending.map(({ id }) => id)).toEqual(["profile-1", "profile-2", "profile-1"]);
    expect(maximumActive).toBe(MAX_CONCURRENT);
    expect(active).toBe(2);
    expect(close).not.toHaveBeenCalled();
    expect(probe.sessions.has("profile-3")).toBe(true);
    await probe.coordinator.stop();
    pending.slice(1).forEach(({ complete }) => complete({ document: null, pending: true }));
    await vi.advanceTimersByTimeAsync(0);
  });

  it("keeps an attached connection when the path-status query fails", async () => {
    const probe = supervised([profile()], { pathStatus: async () => { throw new Error("service temporarily busy"); } });
    await probe.coordinator.start();
    await vi.advanceTimersByTimeAsync(3_000);

    expect(probe.attached).toBe(1);
    expect(probe.peers[0].closed).toBe(0);
    expect(probe.coordinator.snapshot().entries["profile-1"].state).toBe("connecting");
  });

  it("backs off mailbox rate limits for a full minute without occupying a worker", async () => {
    const fetch = vi.fn(async () => { throw Object.assign(new Error("limited"), { code: "mailbox_rate_limited" }); });
    const probe = supervised([profile({ effective: { ...profile().effective, preferred: false } })], { fetch });
    await probe.coordinator.start();
    await vi.advanceTimersByTimeAsync(59_000);
    expect(fetch).toHaveBeenCalledTimes(1);
    probe.coordinator.wake();
    await vi.advanceTimersByTimeAsync(0);
    expect(fetch).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1_000);
    expect(fetch).toHaveBeenCalledTimes(2);
  });
});

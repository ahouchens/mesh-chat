import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  serviceCommand: vi.fn(),
  sendReconnectCapabilities: vi.fn(() => true),
}));

vi.mock("./api", () => ({ serviceCommand: mocks.serviceCommand }));
vi.mock("./reconnect-control", () => ({
  RECONNECT_CAPABILITIES_EVENT: "meshchat:reconnect-capabilities",
  sendReconnectCapabilities: mocks.sendReconnectCapabilities,
  storeReconnectCapabilities: vi.fn(),
}));

import { ReconnectSettings } from "./ReconnectSettings";
import type {
  ReconnectCoordinator,
  ReconnectEntry,
  ReconnectProfile,
  ReconnectProfilesPayload,
} from "./reconnect-coordinator";
import type { Contact } from "./types";

const CONTACT: Contact = {
  id: "contact-1",
  display_name: "Alex",
  public_identity: "public",
  identity_hash: "identity",
  destination_hash: "a".repeat(32),
  fingerprint: "fingerprint",
  trust: "approved",
  connection_hints: [],
  created_at: 1,
  updated_at: 1,
};

function profile(overrides: Partial<ReconnectProfile> = {}): ReconnectProfile {
  return {
    id: "profile-1",
    contact_id: "contact-1",
    display_name: "Alex",
    local_device_id: "dev-aaaa-0001",
    remote_device_id: "dev-bbbb-0002",
    auto_reconnect: false,
    allow_direct_ip_disclosure: false,
    relay_consent_scope: "contact",
    peer_auto_reconnect: false,
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
      ready: false,
      configured: true,
      preferred: true,
      session: "s".repeat(40),
      mailbox_url: "https://signal.example.workers.dev",
      source: "local",
      reasons: ["consent_missing"],
    },
    ...overrides,
  };
}

function coordinator(entry?: ReconnectEntry): ReconnectCoordinator {
  return {
    snapshot: () => ({
      running: true,
      entries: entry ? { [entry.profileId]: entry } : {},
    }),
    subscribe: () => () => undefined,
    stop: vi.fn(async () => undefined),
    retryNow: vi.fn(async () => undefined),
  } as unknown as ReconnectCoordinator;
}

function payload(value: ReconnectProfile = profile()): ReconnectProfilesPayload {
  return {
    local_device_id: "dev-aaaa-0001",
    mailbox_configured: true,
    profiles: [value],
  };
}

beforeEach(() => {
  mocks.serviceCommand.mockReset();
  mocks.sendReconnectCapabilities.mockClear();
});

afterEach(cleanup);

describe("automatic reconnect contact settings", () => {
  it("renders both consents off by default and explains what is missing", async () => {
    mocks.serviceCommand.mockResolvedValue(payload());
    render(
      <ReconnectSettings
        contact={CONTACT}
        coordinator={coordinator()}
        onChanged={async () => undefined}
      />,
    );
    const toggles = await screen.findAllByRole("checkbox");
    expect(toggles).toHaveLength(2);
    expect((toggles[0] as HTMLInputElement).checked).toBe(false);
    expect((toggles[1] as HTMLInputElement).checked).toBe(false);
    expect(screen.getByText("Auto-reconnect is off")).toBeTruthy();
    expect(screen.getByText(/Turn on/)).toBeTruthy();
    expect((screen.getByRole("button", { name: "Retry now" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("saves consent and shares the newly signed capability", async () => {
    mocks.serviceCommand.mockImplementation(async (command: string) => {
      if (command === "reconnect_profiles") return payload();
      if (command === "reconnect_consent_set") {
        return {
          profile: profile({
            auto_reconnect: true,
            allow_direct_ip_disclosure: true,
            effective: {
              ...profile().effective,
              ready: true,
              reasons: [],
            },
          }),
          capabilities: "signed-capability",
          changed: true,
        };
      }
      return {};
    });
    const fake = coordinator();
    render(
      <ReconnectSettings contact={CONTACT} coordinator={fake} onChanged={async () => undefined} />,
    );
    const toggles = await screen.findAllByRole("checkbox");
    fireEvent.click(toggles[0]);
    await waitFor(() => {
      expect(mocks.serviceCommand).toHaveBeenCalledWith("reconnect_consent_set", {
        contact_id: "contact-1",
        auto_reconnect: true,
        allow_direct_ip_disclosure: false,
      });
    });
    expect(mocks.sendReconnectCapabilities).toHaveBeenCalledWith("signed-capability", "contact-1");
    expect(await screen.findByText(/Signed settings were shared/)).toBeTruthy();
  });

  it("shows manual reconnect required instead of pretending to reconnect", async () => {
    mocks.serviceCommand.mockResolvedValue(
      payload(
        profile({
          auto_reconnect: true,
          peer_auto_reconnect: true,
          effective: {
            ...profile().effective,
            ready: false,
            configured: false,
            session: null,
            mailbox_url: null,
            source: null,
            reasons: ["mailbox_not_configured"],
          },
        }),
      ),
    );
    render(
      <ReconnectSettings
        contact={CONTACT}
        coordinator={coordinator({
          profileId: "profile-1",
          contactId: "contact-1",
          displayName: "Alex",
          state: "manual_required",
          detail: "mailbox_not_configured",
          attempts: 0,
          nextAttemptAt: null,
          path: null,
          updatedAt: 1,
        })}
        onChanged={async () => undefined}
      />,
    );
    expect(await screen.findByText("Manual reconnect required")).toBeTruthy();
    expect(screen.getByText(/No signaling mailbox is configured/)).toBeTruthy();
    expect((screen.getByRole("button", { name: "Retry now" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("shows a connected status without any approval prompt", async () => {
    mocks.serviceCommand.mockResolvedValue(
      payload(profile({ auto_reconnect: true, peer_auto_reconnect: true })),
    );
    render(
      <ReconnectSettings
        contact={CONTACT}
        coordinator={coordinator({
          profileId: "profile-1",
          contactId: "contact-1",
          displayName: "Alex",
          state: "connected",
          detail: "",
          attempts: 0,
          nextAttemptAt: null,
          path: "relayed",
          updatedAt: 1,
        })}
        onChanged={async () => undefined}
      />,
    );
    expect(await screen.findByText("Connected")).toBeTruthy();
    expect(screen.getByText("Connected over the community relay.")).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("counts down the retry delay instead of showing a frozen label", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      mocks.serviceCommand.mockResolvedValue(
        payload(profile({ auto_reconnect: true, peer_auto_reconnect: true })),
      );
      const nextAttemptAt = Math.floor(Date.now() / 1000) + 30;
      render(
        <ReconnectSettings
          contact={CONTACT}
          coordinator={coordinator({
            profileId: "profile-1",
            contactId: "contact-1",
            displayName: "Alex",
            state: "retry_wait",
            detail: "network_unavailable",
            attempts: 1,
            nextAttemptAt,
            path: null,
            updatedAt: 1,
          })}
          onChanged={async () => undefined}
        />,
      );
      expect(await screen.findByText(/Reconnecting in 30s/)).toBeTruthy();
      act(() => {
        vi.advanceTimersByTime(5000);
      });
      expect(screen.getByText(/Reconnecting in 25s/)).toBeTruthy();
    } finally {
      vi.useRealTimers();
    }
  });
});

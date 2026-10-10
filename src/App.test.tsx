import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import packageInfo from "../package.json";
import type { ChatMessage, Contact, Group, GroupInvitation, GroupMessage, Snapshot, Workspace, WorkspaceChannel, WorkspaceDirect, WorkspaceMentionPage, WorkspaceMessage, WorkspaceMessagePage, WorkspaceThreadActivityPage, WorkspaceThreadPage } from "./types";

const api = vi.hoisted(() => ({
  initializeService: vi.fn(),
  lockService: vi.fn(),
  onInvitation: vi.fn(),
  onMobileBackButton: vi.fn(),
  onServiceEvent: vi.fn(),
  runtimePlatform: vi.fn(),
  serviceCommand: vi.fn(),
}));

vi.mock("./api", () => api);

import App from "./App";
import type { ServiceEvent } from "./api";

const settings = {
  nearby_discovery: true,
  lan_fallback: true,
  lan_listener_port: null,
  allowed_interfaces: [],
  tcp_clients: [],
  tcp_listener: null,
  help_route: false,
  store_for_offline: false,
  approved_propagation_nodes: [],
};

const profile = {
  display_name: "Alex",
  public_identity: "alex-public",
  identity_hash: "11".repeat(16),
  destination_hash: "22".repeat(16),
  fingerprint: "AAAA BBBB CCCC DDDD",
  created_at: 1,
};

function snapshot(contacts: Contact[] = []): Snapshot {
  return {
    profile,
    contacts,
    messages: [],
    drafts: [],
    settings,
    network: {
      transport_enabled: false,
      propagation_enabled: false,
      interface_available: true,
      interfaces: [{
        name: "Nearby devices",
        online: true,
        receives: true,
        type: "AutoInterface",
        adopted_interface_count: 1,
        self_echo_seen: true,
        carrier_timed_out: false,
        peer_count: 0,
      }],
      outbound_propagation_node: null,
    },
    service_error: null,
  };
}

const incoming: Contact = {
  id: "phone-contact",
  display_name: "Taylor",
  public_identity: "phone-public",
  identity_hash: "33".repeat(16),
  destination_hash: "44".repeat(16),
  fingerprint: "1111 2222 3333 4444",
  trust: "pending_request",
  connection_hints: [],
  created_at: 2,
  updated_at: 2,
};

const approved: Contact = {
  ...incoming,
  trust: "approved",
};

const firstMessage: ChatMessage = {
  id: "first-message",
  conversation_id: "conversation-one",
  contact_id: approved.id,
  direction: "inbound",
  kind: "chat",
  text: "The first message is visible",
  state: "delivered",
  created_at: 1_791_072_018.5,
  expires_at: 1_791_676_818.5,
};

const group: Group = {
  id: "farm-group",
  title: "Farm Operations",
  owner_destination: profile.destination_hash,
  posting_policy: "members",
  status: "active",
  epoch: 1,
  manifest_hash: "55".repeat(32),
  members: [
    {
      destination_hash: profile.destination_hash,
      display_name: profile.display_name,
      role: "owner",
      status: "active",
      fingerprint: profile.fingerprint,
    },
    {
      destination_hash: approved.destination_hash,
      display_name: approved.display_name,
      role: "member",
      status: "active",
      fingerprint: approved.fingerprint,
      contact_id: approved.id,
    },
  ],
  created_at: 3,
  updated_at: 3,
};

const groupMessage: GroupMessage = {
  id: "group-message-one",
  group_id: group.id,
  sender_destination: profile.destination_hash,
  sender_display_name: profile.display_name,
  direction: "outbound",
  kind: "group_chat",
  text: "Meet at the north pasture",
  state: "sending",
  group_epoch: 1,
  group_manifest_hash: group.manifest_hash,
  sender_sequence: 1,
  created_at: 1_791_072_020,
  expires_at: 1_791_676_820,
  delivery_summary: { total: 1, delivered: 0, pending: 1, failed: 0, expired: 0 },
  deliveries: [{ recipient_destination: approved.destination_hash, recipient_display_name: approved.display_name, state: "sending" }],
};

const groupInvitation: GroupInvitation = {
  id: "group-invitation-one",
  group_id: group.id,
  title: group.title,
  owner_display_name: "Taylor",
  owner_destination: approved.destination_hash,
  owner_fingerprint: approved.fingerprint,
  member_count: 2,
  posting_policy: "members",
  expires_at: 2_000_000_000,
};

const workspace: Workspace = {
  id: "11111111-1111-4111-8111-111111111111",
  name: "Lakewatcher",
  description: "Field coordination",
  state: "active",
  local_role: "owner",
  local_member_id: "22222222-2222-4222-8222-222222222222",
  local_device_id: "33333333-3333-4333-8333-333333333333",
  owner_member_id: "22222222-2222-4222-8222-222222222222",
  authority_device_id: "33333333-3333-4333-8333-333333333333",
  epoch: 1,
  manifest_hash: "66".repeat(32),
  genesis_digest: "77".repeat(32),
  general_channel_id: "44444444-4444-4444-8444-444444444444",
  channel_discovery: "converged",
  retention_days: 90,
  policies: { channel_creation: "all_members", posting: "all_members", invitation_requests: "owner_only" },
  members: [{
    id: "22222222-2222-4222-8222-222222222222",
    display_name: "Alex",
    role: "owner",
    status: "active",
    short_id: "222222",
    device: { id: "33333333-3333-4333-8333-333333333333", destination_hash: profile.destination_hash, fingerprint: profile.fingerprint },
  }],
  authorization_generation: 1,
  retention_generation: 1,
  mention_unread_count: 0,
  thread_unread_count: 0,
  created_at: 4,
  updated_at: 4,
};

const workspaceChannel: WorkspaceChannel = {
  id: workspace.general_channel_id!,
  workspace_id: workspace.id,
  name: "general",
  name_key: "general",
  display_name: "general",
  short_id: "444444",
  topic: "",
  visibility: "public",
  member_ids: [],
  state: "active",
  manager_member_id: workspace.local_member_id,
  manager_device_id: workspace.local_device_id,
  version: 1,
  head_hash: "88".repeat(32),
  manifest_digest: workspace.manifest_hash,
  unread_count: 0,
  subscribed: true,
  mentions_muted: false,
  is_general: true,
  duplicate_name: false,
  created_at: 4,
  updated_at: 4,
};

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("startup storage errors", () => {
  it("distinguishes a busy encrypted profile from unavailable protected storage", async () => {
    api.runtimePlatform.mockResolvedValue("desktop");
    api.initializeService.mockRejectedValue(new Error("profile_in_use"));
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);

    render(<App />);

    await screen.findByRole("heading", { name: "Mesh Chat stopped safely" });
    expect(screen.getByText(/encrypted profile is still in use/i)).toBeTruthy();
    expect(screen.getByText(/existing encrypted data is unchanged/i)).toBeTruthy();
    expect(screen.queryByText(/Turn on FileVault/i)).toBeNull();
  });

  it("keeps the fail-closed guidance for a genuine protected-storage failure", async () => {
    api.runtimePlatform.mockResolvedValue("desktop");
    api.initializeService.mockRejectedValue(new Error("protected_storage_unavailable"));
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);

    render(<App />);

    await screen.findByRole("heading", { name: "Mesh Chat stopped safely" });
    expect(screen.getByText(/Turn on FileVault.*EFS-capable NTFS.*fscrypt\/LUKS/i)).toBeTruthy();
  });
});

describe("new chat invitations", () => {
  it("can retry invitation creation after the first attempt fails", async () => {
    const current = snapshot();
    let invitationAttempts = 0;
    api.runtimePlatform.mockResolvedValue("desktop");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);
    api.serviceCommand.mockImplementation(async (command: string) => {
      if (command === "snapshot") return current;
      if (command === "create_invitation") {
        invitationAttempts += 1;
        if (invitationAttempts === 1) throw new Error("service_timeout");
        return {
          link: "meshchat://invite/recovered",
          text: "MESHCHAT1:recovered",
          file: "{}",
          expires_at: 2_000_000_000,
        };
      }
      return {};
    });

    render(<App />);
    await screen.findByRole("heading", { name: "Your private conversations" });
    fireEvent.click(screen.getAllByRole("button", { name: "New chat" })[0]);

    expect((await screen.findByRole("alert")).textContent).toContain("did not respond in time");
    fireEvent.click(screen.getByRole("button", { name: "Retry invitation" }));

    await screen.findByText("Invitation details to share");
    expect(api.serviceCommand.mock.calls.filter(([command]) => command === "create_invitation")).toHaveLength(2);
    expect(screen.queryByRole("button", { name: "Retry invitation" })).toBeNull();
  });
});

describe("incoming connection requests", () => {
  it("replaces an open QR dialog with a foreground Accept/Decline prompt", async () => {
    let current = snapshot();
    let serviceEvent: ((event: { type: "event"; event: "state_changed" }) => void) | undefined;

    api.runtimePlatform.mockResolvedValue("desktop");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockImplementation(async (callback) => {
      serviceEvent = callback;
      return () => undefined;
    });
    api.serviceCommand.mockImplementation(async (command: string) => {
      if (command === "snapshot") return current;
      if (command === "create_invitation") {
        return {
          link: "meshchat://invite/example",
          text: "MESHCHAT1:example",
          file: "{}",
          expires_at: 2_000_000_000,
        };
      }
      if (command === "approve_request") {
        current = snapshot([{ ...incoming, trust: "approved" }]);
        return current.contacts[0];
      }
      return {};
    });

    render(<App />);
    await screen.findByRole("heading", { name: "Your private conversations" });

    fireEvent.click(screen.getAllByRole("button", { name: "New chat" })[0]);
    await screen.findByRole("heading", { name: "New chat" });
    expect(screen.getByText("Invitation details to share")).toBeTruthy();

    current = snapshot([incoming]);
    await act(async () => {
      serviceEvent?.({ type: "event", event: "state_changed" });
    });

    await screen.findByRole("heading", { name: "Connection request" });
    expect(screen.queryByRole("heading", { name: "New chat" })).toBeNull();
    expect(screen.getByText("Taylor wants to connect")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Accept and open chat" }));
    await waitFor(() => {
      expect(api.serviceCommand).toHaveBeenCalledWith("approve_request", {
        contact_id: incoming.id,
      });
    });
    await screen.findByRole("heading", { name: "Taylor" });
    expect(screen.queryByRole("heading", { name: "Connection request" })).toBeNull();
  });

  it("reconciles a timed-out approval that committed in the service", async () => {
    let current = snapshot([incoming]);
    api.runtimePlatform.mockResolvedValue("desktop");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);
    api.serviceCommand.mockImplementation(async (command: string) => {
      if (command === "approve_request") {
        current = snapshot([{ ...incoming, trust: "approved" }]);
        throw new Error("service_timeout");
      }
      if (command === "snapshot") return current;
      return {};
    });

    render(<App />);
    await screen.findByRole("heading", { name: "Connection request" });
    fireEvent.click(screen.getByRole("button", { name: "Accept and open chat" }));

    await screen.findByRole("heading", { name: "Taylor" });
    expect(screen.queryByRole("heading", { name: "Connection request" })).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(api.serviceCommand.mock.calls.some(([command]) => command === "snapshot")).toBe(true);
  });

  it("keeps a pending request open with actionable guidance after a true approval timeout", async () => {
    const current = snapshot([incoming]);
    api.runtimePlatform.mockResolvedValue("desktop");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);
    api.serviceCommand.mockImplementation(async (command: string) => {
      if (command === "approve_request") throw new Error("service_timeout");
      if (command === "snapshot") return current;
      return {};
    });

    render(<App />);
    await screen.findByRole("heading", { name: "Connection request" });
    fireEvent.click(screen.getByRole("button", { name: "Accept and open chat" }));

    expect((await screen.findByRole("alert")).textContent).toContain("still processing this approval");
    expect(screen.getByText(/Keep both apps open, wait a moment, then try again/i)).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Connection request" })).toBeTruthy();
    await waitFor(() => expect((screen.getByRole("button", { name: "Accept and open chat" }) as HTMLButtonElement).disabled).toBe(false));
    expect(api.serviceCommand.mock.calls.some(([command]) => command === "snapshot")).toBe(true);
  });

  it("refreshes the snapshot when the desktop window regains focus", async () => {
    let current = snapshot();
    api.runtimePlatform.mockResolvedValue("desktop");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);
    api.serviceCommand.mockImplementation(async (command: string) => {
      if (command === "snapshot") return current;
      return {};
    });

    render(<App />);
    await screen.findByRole("heading", { name: "Your private conversations" });
    current = snapshot([incoming]);

    await act(async () => {
      window.dispatchEvent(new Event("focus"));
    });

    await screen.findByRole("heading", { name: "Connection request" });
  });
});

describe("network settings", () => {
  it("saves the direct local connection preference", async () => {
    const current = snapshot();
    api.runtimePlatform.mockResolvedValue("desktop");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);
    api.serviceCommand.mockImplementation(async (command: string) => {
      if (command === "snapshot") return current;
      return {};
    });

    render(<App />);
    await screen.findByRole("heading", { name: "Your private conversations" });

    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    expect(screen.getByText(`Mesh Chat ${packageInfo.version}`)).toBeTruthy();
    const fallback = screen.getByRole("checkbox", { name: /Use a direct local connection/ });
    expect((fallback as HTMLInputElement).checked).toBe(true);

    fireEvent.click(fallback);
    fireEvent.click(screen.getByRole("button", { name: "Save settings" }));

    await waitFor(() => {
      expect(api.serviceCommand).toHaveBeenCalledWith("update_settings", {
        settings: { ...settings, lan_fallback: false },
      });
    });
    expect(await screen.findByText("Saved. Restart Mesh Chat to apply networking-role changes.")).toBeTruthy();
  });
});

describe("contact management", () => {
  it("renames, verifies, blocks, and restores a saved contact", async () => {
    let current = snapshot([approved]);
    api.runtimePlatform.mockResolvedValue("desktop");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);
    api.serviceCommand.mockImplementation(async (command: string, payload?: Record<string, unknown>) => {
      if (command === "snapshot") return current;
      if (command === "update_contact") {
        current = { ...current, contacts: [{ ...current.contacts[0], display_name: payload?.display_name as string, profile_name: "Taylor" }] };
        return current.contacts[0];
      }
      if (command === "verify_contact") {
        current = { ...current, contacts: [{ ...current.contacts[0], trust: "verified" }] };
        return current.contacts[0];
      }
      if (command === "block_contact") {
        current = { ...current, contacts: [{ ...current.contacts[0], trust: "blocked", trust_before_block: "verified" }] };
        return current.contacts[0];
      }
      if (command === "unblock_contact") {
        current = { ...current, contacts: [{ ...current.contacts[0], trust: "verified", trust_before_block: undefined }] };
        return current.contacts[0];
      }
      return {};
    });

    render(<App />);
    await screen.findByLabelText("Conversation with Taylor");
    fireEvent.click(screen.getByRole("button", { name: "Contacts" }));
    const dialog = await screen.findByRole("dialog", { name: "Contacts" });
    const name = within(dialog).getByRole("textbox", { name: "Name on this device" });
    fireEvent.change(name, { target: { value: "T. Morgan" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save name" }));
    await waitFor(() => expect(api.serviceCommand).toHaveBeenCalledWith("update_contact", {
      contact_id: approved.id,
      display_name: "T. Morgan",
    }));

    fireEvent.click(await within(dialog).findByRole("button", { name: "Mark verified" }));
    expect(await within(dialog).findByRole("button", { name: "Remove verification" })).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Block" }));
    const blockConfirmation = within(dialog).getByRole("alertdialog", { name: "Block contact" });
    fireEvent.click(within(blockConfirmation).getByRole("button", { name: "Block" }));
    fireEvent.click(await within(dialog).findByRole("button", { name: "Unblock contact" }));
    expect(await within(dialog).findByRole("button", { name: "Remove verification" })).toBeTruthy();
  });

  it("permanently removes a contact after an explicit confirmation", async () => {
    let current = { ...snapshot([approved]), messages: [firstMessage] };
    api.runtimePlatform.mockResolvedValue("desktop");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);
    api.serviceCommand.mockImplementation(async (command: string) => {
      if (command === "snapshot") return current;
      if (command === "delete_contact") {
        current = { ...current, contacts: [], messages: [], drafts: [] };
        return { contact_id: approved.id, deleted_messages: 1 };
      }
      return {};
    });

    render(<App />);
    await screen.findByLabelText("Conversation with Taylor");
    fireEvent.click(screen.getByRole("button", { name: "Contacts" }));
    const dialog = await screen.findByRole("dialog", { name: "Contacts" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete contact" }));
    const confirmation = within(dialog).getByRole("alertdialog", { name: "Delete contact" });
    expect(within(confirmation).getByText(/Group memberships are unchanged/i)).toBeTruthy();
    fireEvent.click(within(confirmation).getByRole("button", { name: "Delete contact" }));

    await waitFor(() => expect(api.serviceCommand).toHaveBeenCalledWith("delete_contact", { contact_id: approved.id }));
    expect(await within(dialog).findByText("No contacts yet.")).toBeTruthy();
    expect(screen.queryByLabelText("Conversation with Taylor")).toBeNull();
  });
});

describe("dialog keyboard behavior", () => {
  it("closes the top dialog with Escape and restores focus to its trigger", async () => {
    const current = snapshot();
    api.runtimePlatform.mockResolvedValue("desktop");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);
    api.serviceCommand.mockImplementation(async (command: string) => command === "snapshot" ? current : {});

    render(<App />);
    await screen.findByRole("heading", { name: "Your private conversations" });
    const trigger = screen.getByRole("button", { name: "Settings" });
    trigger.focus();
    fireEvent.click(trigger);
    await screen.findByRole("heading", { name: "Settings" });
    expect(screen.getByRole("button", { name: "Close" })).toBe(document.activeElement);
    expect(screen.getByText("Emoji artwork: Twemoji (CC BY 4.0)")).toBeTruthy();

    fireEvent.keyDown(document, { key: "Escape" });

    await waitFor(() => expect(screen.queryByRole("heading", { name: "Settings" })).toBeNull());
    expect(trigger).toBe(document.activeElement);
  });
});

describe("message reactions", () => {
  it("replaces and removes the local reaction with the bounded renderer contract", async () => {
    let current: Snapshot = {
      ...snapshot([approved]),
      messages: [{
        ...firstMessage,
        reactions: [{ emoji: "❤️", count: 1, reacted_by_self: true }],
      }],
    };
    api.runtimePlatform.mockResolvedValue("desktop");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);
    api.serviceCommand.mockImplementation(async (command: string, payload: Record<string, unknown>) => {
      if (command === "set_message_reaction") {
        current = {
          ...current,
          messages: current.messages.map((message) => message.id === payload.message_id ? {
            ...message,
            reactions: payload.active ? [{ emoji: String(payload.emoji), count: 1, reacted_by_self: true }] : [],
          } : message),
        };
        return {};
      }
      if (command === "snapshot") return current;
      return {};
    });

    render(<App />);
    const conversation = await screen.findByLabelText("Conversation with Taylor");
    fireEvent.click(within(conversation).getByRole("button", { name: "Change or remove your reaction" }));
    const picker = await screen.findByRole("dialog", { name: "Choose a reaction" });
    fireEvent.click(within(picker).getByRole("button", { name: "React with celebration, replacing your ❤️ reaction" }));

    await waitFor(() => expect(api.serviceCommand).toHaveBeenCalledWith("set_message_reaction", {
      kind: "direct",
      message_id: firstMessage.id,
      emoji: "🎉",
      active: true,
    }));
    const selectedSummary = await within(conversation).findByRole("button", { name: "Remove your celebration reaction; 1 reaction total" });
    fireEvent.click(selectedSummary);

    await waitFor(() => expect(api.serviceCommand).toHaveBeenCalledWith("set_message_reaction", {
      kind: "direct",
      message_id: firstMessage.id,
      emoji: "🎉",
      active: false,
    }));
  });

  it("uses bundled glyphs in summary, quick, category, and catalog positions", async () => {
    const current: Snapshot = {
      ...snapshot([approved]),
      messages: [{ ...firstMessage, reactions: [{ emoji: "🫠", count: 2, reacted_by_self: false }] }],
    };
    api.runtimePlatform.mockResolvedValue("desktop");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);
    api.serviceCommand.mockImplementation(async (command: string) => command === "snapshot" ? current : {});

    render(<App />);
    const conversation = await screen.findByLabelText("Conversation with Taylor");
    const summary = within(conversation).getByRole("button", { name: "React with melting face; 2 reactions total" });
    const summaryGlyph = summary.querySelector<HTMLElement>(".emoji-glyph");
    expect(summaryGlyph?.dataset.emoji).toBe("🫠");
    expect(summaryGlyph?.getAttribute("aria-hidden")).toBe("true");
    expect(summaryGlyph?.textContent).toBe("18");

    fireEvent.click(within(conversation).getByRole("button", { name: "Add a reaction" }));
    const picker = await screen.findByRole("dialog", { name: "Choose a reaction" });
    const quick = within(picker).getByRole("button", { name: "React with thumbs up" });
    expect(quick.querySelector<HTMLElement>(".emoji-glyph")?.dataset.emoji).toBe("👍");

    fireEvent.click(within(picker).getByRole("button", { name: "More emojis" }));
    const smileys = within(picker).getByRole("button", { name: "Smileys" });
    expect(smileys.querySelector<HTMLElement>(".emoji-glyph")?.dataset.emoji).toBe("😀");
    const melting = within(picker).getByRole("button", { name: "React with melting face" });
    const catalogGlyph = melting.querySelector<HTMLElement>(".emoji-glyph");
    expect(catalogGlyph?.dataset.emoji).toBe("🫠");
    const image = catalogGlyph?.querySelector("img");
    expect(image?.getAttribute("src")).toMatch(/^\.?\/emoji\/twemoji\/17\.0\.3\//);
    fireEvent.load(image as HTMLImageElement);
    expect(catalogGlyph?.dataset.artworkState).toBe("loaded");
    expect(within(picker).getByRole("button", { name: "React with melting face" })).toBe(melting);
  });

  it("searches the expanded catalog and exposes useful categories without opening the keyboard", async () => {
    const current: Snapshot = { ...snapshot([approved]), messages: [firstMessage] };
    api.runtimePlatform.mockResolvedValue("android");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);
    api.onMobileBackButton.mockResolvedValue(() => undefined);
    api.serviceCommand.mockImplementation(async (command: string) => command === "snapshot" ? current : {});

    render(<App />);
    const conversation = await screen.findByLabelText("Conversation with Taylor");
    const trigger = within(conversation).getByRole("button", { name: "Add a reaction" });
    fireEvent.click(trigger);
    const picker = await screen.findByRole("dialog", { name: "Choose a reaction" });
    fireEvent.click(within(picker).getByRole("button", { name: "More emojis" }));

    const backToQuick = within(picker).getByRole("button", { name: "Back to quick reactions" });
    await waitFor(() => expect(backToQuick).toBe(document.activeElement));
    const search = within(picker).getByRole("searchbox", { name: "Search emojis" });
    expect(search).not.toBe(document.activeElement);

    const smileysCategory = within(picker).getByRole("button", { name: "Smileys" });
    const gesturesCategory = within(picker).getByRole("button", { name: "People & gestures" });
    smileysCategory.focus();
    fireEvent.keyDown(smileysCategory, { key: "ArrowRight" });
    expect(gesturesCategory).toBe(document.activeElement);
    fireEvent.click(within(picker).getByRole("button", { name: "Nature & travel" }));
    expect(within(picker).getByRole("button", { name: "React with rocket" })).toBeTruthy();

    const useEmojiButton = within(picker).getByRole("button", { name: "Use emoji" });
    useEmojiButton.focus();
    fireEvent.keyDown(useEmojiButton, { key: "Tab" });
    expect(backToQuick).toBe(document.activeElement);
    fireEvent.keyDown(backToQuick, { key: "Tab", shiftKey: true });
    expect(useEmojiButton).toBe(document.activeElement);

    fireEvent.change(search, { target: { value: "farmer" } });
    const farmer = within(picker).getByRole("button", { name: "React with farmer" });
    fireEvent.click(farmer);

    await waitFor(() => expect(api.serviceCommand).toHaveBeenCalledWith("set_message_reaction", {
      kind: "direct",
      message_id: firstMessage.id,
      emoji: "🧑‍🌾",
      active: true,
    }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Choose a reaction" })).toBeNull());
    await waitFor(() => expect(trigger).toBe(document.activeElement));
  });

  it("accepts one custom emoji sequence, rejects multiple emoji, and preserves input arrow keys", async () => {
    const current: Snapshot = { ...snapshot([approved]), messages: [firstMessage] };
    api.runtimePlatform.mockResolvedValue("desktop");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);
    api.serviceCommand.mockImplementation(async (command: string) => command === "snapshot" ? current : {});

    render(<App />);
    const conversation = await screen.findByLabelText("Conversation with Taylor");
    fireEvent.click(within(conversation).getByRole("button", { name: "Add a reaction" }));
    const picker = await screen.findByRole("dialog", { name: "Choose a reaction" });
    fireEvent.click(within(picker).getByRole("button", { name: "More emojis" }));
    const input = within(picker).getByRole("textbox", { name: "Use emoji keyboard" });

    fireEvent.change(input, { target: { value: "😀😃" } });
    fireEvent.click(within(picker).getByRole("button", { name: "Use emoji" }));
    expect((await within(picker).findByRole("alert")).textContent).toContain("Enter one supported emoji from your keyboard.");
    expect(api.serviceCommand.mock.calls.some(([command]) => command === "set_message_reaction")).toBe(false);

    input.focus();
    expect(fireEvent.keyDown(input, { key: "ArrowLeft" })).toBe(true);
    expect(input).toBe(document.activeElement);
    fireEvent.change(input, { target: { value: "🧑🏽‍🌾" } });
    fireEvent.submit(input.closest("form") as HTMLFormElement);

    await waitFor(() => expect(api.serviceCommand).toHaveBeenCalledWith("set_message_reaction", {
      kind: "direct",
      message_id: firstMessage.id,
      emoji: "🧑🏽‍🌾",
      active: true,
    }));
  });

  it("keeps a valid uncatalogued reaction visible and actionable", async () => {
    const current: Snapshot = {
      ...snapshot([approved]),
      messages: [{ ...firstMessage, reactions: [{ emoji: "🪿", count: 3, reacted_by_self: false }] }],
    };
    api.runtimePlatform.mockResolvedValue("desktop");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);
    api.serviceCommand.mockImplementation(async (command: string) => command === "snapshot" ? current : {});

    render(<App />);
    const conversation = await screen.findByLabelText("Conversation with Taylor");
    const custom = within(conversation).getByRole("button", { name: "React with custom emoji 🪿; 3 reactions total" });
    fireEvent.click(custom);
    await waitFor(() => expect(api.serviceCommand).toHaveBeenCalledWith("set_message_reaction", {
      kind: "direct",
      message_id: firstMessage.id,
      emoji: "🪿",
      active: true,
    }));
  });

  it("names an Emoji 18 artwork fallback instead of exposing a tofu glyph", async () => {
    const current: Snapshot = {
      ...snapshot([approved]),
      messages: [{ ...firstMessage, reactions: [{ emoji: "🫫", count: 2, reacted_by_self: false }] }],
    };
    api.runtimePlatform.mockResolvedValue("desktop");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);
    api.serviceCommand.mockImplementation(async (command: string) => command === "snapshot" ? current : {});

    render(<App />);
    const conversation = await screen.findByLabelText("Conversation with Taylor");
    const fallback = within(conversation).getByRole("button", { name: "React with cracking face; 2 reactions total" });
    const glyph = fallback.querySelector<HTMLElement>('[data-artwork-state="missing"]');
    expect(glyph?.textContent).toBe("18");
    expect(fallback.textContent).not.toContain("🫫");
  });

  it("closes the picker with Escape and restores focus to its trigger", async () => {
    const current: Snapshot = { ...snapshot([approved]), messages: [firstMessage] };
    api.runtimePlatform.mockResolvedValue("desktop");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);
    api.serviceCommand.mockImplementation(async (command: string) => command === "snapshot" ? current : {});

    render(<App />);
    const conversation = await screen.findByLabelText("Conversation with Taylor");
    const trigger = within(conversation).getByRole("button", { name: "Add a reaction" });
    fireEvent.click(trigger);
    await screen.findByRole("dialog", { name: "Choose a reaction" });

    fireEvent.keyDown(document, { key: "Escape" });

    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Choose a reaction" })).toBeNull());
    await waitFor(() => expect(trigger).toBe(document.activeElement));
    expect(screen.getByLabelText("Conversation with Taylor")).toBeTruthy();
  });

  it("keeps the picker inside a 320px viewport and flips around the scroll edge", async () => {
    const originalWidth = window.innerWidth;
    const originalHeight = window.innerHeight;
    const originalVisualViewport = Object.getOwnPropertyDescriptor(window, "visualViewport");
    const visualViewport = Object.assign(new EventTarget(), { width: 320, height: 480, offsetLeft: 0, offsetTop: 0 });
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 320 });
    Object.defineProperty(window, "innerHeight", { configurable: true, value: 480 });
    Object.defineProperty(window, "visualViewport", { configurable: true, value: visualViewport });
    try {
      const current: Snapshot = { ...snapshot([approved]), messages: [firstMessage] };
      api.runtimePlatform.mockResolvedValue("android");
      api.initializeService.mockResolvedValue(current);
      api.onInvitation.mockResolvedValue(() => undefined);
      api.onServiceEvent.mockResolvedValue(() => undefined);
      api.onMobileBackButton.mockResolvedValue(() => undefined);
      api.serviceCommand.mockImplementation(async (command: string) => command === "snapshot" ? current : {});

      render(<App />);
      const conversation = await screen.findByLabelText("Conversation with Taylor");
      const trigger = within(conversation).getByRole("button", { name: "Add a reaction" });
      let triggerTop = 2;
      vi.spyOn(trigger, "getBoundingClientRect").mockImplementation(() => ({
        x: 24,
        y: triggerTop,
        left: 24,
        top: triggerTop,
        right: 60,
        bottom: triggerTop + 36,
        width: 36,
        height: 36,
        toJSON: () => ({}),
      } as DOMRect));

      fireEvent.click(trigger);
      const picker = await screen.findByRole("dialog", { name: "Choose a reaction" });
      await waitFor(() => expect(parseFloat(picker.style.left)).toBe(8));
      expect(parseFloat(picker.style.left) + 293).toBeLessThanOrEqual(312);
      expect(parseFloat(picker.style.top)).toBeGreaterThanOrEqual(38);

      triggerTop = 430;
      fireEvent.scroll(window);
      await waitFor(() => expect(parseFloat(picker.style.top)).toBeLessThan(triggerTop));
      expect(parseFloat(picker.style.top)).toBeGreaterThanOrEqual(8);

      fireEvent.click(within(picker).getByRole("button", { name: "More emojis" }));
      await waitFor(() => expect(picker.classList.contains("reaction-picker--catalog")).toBe(true));
      expect(parseFloat(picker.style.maxWidth)).toBe(304);
      expect(parseFloat(picker.style.left) + parseFloat(picker.style.maxWidth)).toBeLessThanOrEqual(312);
      expect(parseFloat(picker.style.maxHeight)).toBe(464);
      expect(within(picker).getByRole("group", { name: "Smileys" }).classList.contains("reaction-picker__catalog")).toBe(true);

      visualViewport.height = 240;
      visualViewport.dispatchEvent(new Event("resize"));
      await waitFor(() => expect(parseFloat(picker.style.maxHeight)).toBe(224));
      expect(parseFloat(picker.style.top)).toBeGreaterThanOrEqual(8);
      expect(parseFloat(picker.style.top) + parseFloat(picker.style.maxHeight)).toBeLessThanOrEqual(232);
      expect(picker.classList.contains("reaction-picker--catalog")).toBe(true);
      const customInput = within(picker).getByRole("textbox", { name: "Use emoji keyboard" });
      customInput.focus();
      expect(customInput).toBe(document.activeElement);
    } finally {
      Object.defineProperty(window, "innerWidth", { configurable: true, value: originalWidth });
      Object.defineProperty(window, "innerHeight", { configurable: true, value: originalHeight });
      if (originalVisualViewport) Object.defineProperty(window, "visualViewport", originalVisualViewport);
      else Reflect.deleteProperty(window, "visualViewport");
    }
  });
});

describe("Android system Back navigation", () => {
  it("returns from a direct conversation to the conversation list and releases Back at the root", async () => {
    const current = snapshot([approved]);
    let back: (() => void) | undefined;
    const unregister = vi.fn();
    api.runtimePlatform.mockResolvedValue("android");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);
    api.onMobileBackButton.mockImplementation(async (callback: () => void) => {
      back = callback;
      return unregister;
    });
    api.serviceCommand.mockImplementation(async (command: string) => {
      if (command === "snapshot") return current;
      return {};
    });

    render(<App />);
    await screen.findByLabelText("Conversation with Taylor");
    await waitFor(() => expect(back).toBeTypeOf("function"));

    act(() => back?.());

    await screen.findByRole("heading", { name: "Your private conversations" });
    await waitFor(() => expect(unregister).toHaveBeenCalledTimes(1));
    expect(api.onMobileBackButton).toHaveBeenCalledTimes(1);
  });

  it("closes an open dialog before leaving its underlying conversation", async () => {
    const current = snapshot([approved]);
    let back: (() => void) | undefined;
    api.runtimePlatform.mockResolvedValue("android");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);
    api.onMobileBackButton.mockImplementation(async (callback: () => void) => {
      back = callback;
      return () => undefined;
    });
    api.serviceCommand.mockImplementation(async (command: string) => {
      if (command === "snapshot") return current;
      return {};
    });

    render(<App />);
    await screen.findByLabelText("Conversation with Taylor");
    await waitFor(() => expect(back).toBeTypeOf("function"));
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    await screen.findByRole("heading", { name: "Settings" });
    expect(api.onMobileBackButton).toHaveBeenCalledTimes(1);

    act(() => back?.());

    await waitFor(() => expect(screen.queryByRole("heading", { name: "Settings" })).toBeNull());
    expect(screen.getByLabelText("Conversation with Taylor")).toBeTruthy();
    expect(api.onMobileBackButton).toHaveBeenCalledTimes(1);

    act(() => back?.());
    await screen.findByRole("heading", { name: "Your private conversations" });
  });

  it("dismisses delete confirmation before leaving the conversation", async () => {
    const current = snapshot([approved]);
    let back: (() => void) | undefined;
    api.runtimePlatform.mockResolvedValue("android");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);
    api.onMobileBackButton.mockImplementation(async (callback: () => void) => {
      back = callback;
      return () => undefined;
    });
    api.serviceCommand.mockImplementation(async (command: string) => command === "snapshot" ? current : {});

    render(<App />);
    await screen.findByLabelText("Conversation with Taylor");
    fireEvent.click(screen.getByRole("button", { name: "Delete conversation with Taylor" }));
    await screen.findByRole("heading", { name: "Delete conversation?" });
    expect(api.onMobileBackButton).toHaveBeenCalledTimes(1);

    act(() => back?.());

    await waitFor(() => expect(screen.queryByRole("heading", { name: "Delete conversation?" })).toBeNull());
    expect(screen.getByLabelText("Conversation with Taylor")).toBeTruthy();
    expect(api.serviceCommand.mock.calls.some(([command]) => command === "delete_conversation")).toBe(false);
  });

  it("keeps one native listener registered while snapshots and dialogs change", async () => {
    let current = snapshot([approved]);
    let back: (() => void) | undefined;
    let serviceEvent: ((event: { type: "event"; event: "state_changed" }) => void) | undefined;
    const unregister = vi.fn();
    api.runtimePlatform.mockResolvedValue("android");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockImplementation(async (callback) => {
      serviceEvent = callback;
      return () => undefined;
    });
    api.onMobileBackButton.mockImplementation(async (callback: () => void) => {
      back = callback;
      return unregister;
    });
    api.serviceCommand.mockImplementation(async (command: string) => command === "snapshot" ? current : {});

    render(<App />);
    await screen.findByLabelText("Conversation with Taylor");
    await waitFor(() => expect(back).toBeTypeOf("function"));

    current = { ...current, messages: [firstMessage] };
    await act(async () => { serviceEvent?.({ type: "event", event: "state_changed" }); });
    await screen.findAllByText(firstMessage.text);
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    await screen.findByRole("heading", { name: "Settings" });

    expect(api.onMobileBackButton).toHaveBeenCalledTimes(1);
    expect(unregister).not.toHaveBeenCalled();
    act(() => back?.());
    await waitFor(() => expect(screen.queryByRole("heading", { name: "Settings" })).toBeNull());
    expect(screen.getByLabelText("Conversation with Taylor")).toBeTruthy();
    expect(api.onMobileBackButton).toHaveBeenCalledTimes(1);
  });

  it("dismisses a foreground request before the suspended delete confirmation", async () => {
    let current = snapshot([approved]);
    let back: (() => void) | undefined;
    let serviceEvent: ((event: { type: "event"; event: "state_changed" }) => void) | undefined;
    const jordan: Contact = {
      ...incoming,
      id: "jordan-request",
      display_name: "Jordan",
      destination_hash: "66".repeat(16),
    };
    api.runtimePlatform.mockResolvedValue("android");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockImplementation(async (callback) => {
      serviceEvent = callback;
      return () => undefined;
    });
    api.onMobileBackButton.mockImplementation(async (callback: () => void) => {
      back = callback;
      return () => undefined;
    });
    api.serviceCommand.mockImplementation(async (command: string) => command === "snapshot" ? current : {});

    render(<App />);
    await screen.findByLabelText("Conversation with Taylor");
    fireEvent.click(screen.getByRole("button", { name: "Delete conversation with Taylor" }));
    await screen.findByRole("heading", { name: "Delete conversation?" });

    current = snapshot([approved, jordan]);
    await act(async () => { serviceEvent?.({ type: "event", event: "state_changed" }); });
    await screen.findByRole("heading", { name: "Connection request" });
    expect(screen.queryByRole("heading", { name: "Delete conversation?" })).toBeNull();

    act(() => back?.());
    await screen.findByRole("heading", { name: "Delete conversation?" });
    expect(screen.queryByRole("heading", { name: "Connection request" })).toBeNull();
    expect(screen.getByLabelText("Conversation with Taylor")).toBeTruthy();

    act(() => back?.());
    await waitFor(() => expect(screen.queryByRole("heading", { name: "Delete conversation?" })).toBeNull());
    expect(api.serviceCommand.mock.calls.some(([command]) => command === "delete_conversation")).toBe(false);
    expect(api.onMobileBackButton).toHaveBeenCalledTimes(1);
  });

  it("closes conversation details before returning to the list", async () => {
    const current = snapshot([approved]);
    let back: (() => void) | undefined;
    api.runtimePlatform.mockResolvedValue("android");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);
    api.onMobileBackButton.mockImplementation(async (callback: () => void) => {
      back = callback;
      return () => undefined;
    });
    api.serviceCommand.mockImplementation(async (command: string) => command === "snapshot" ? current : {});

    render(<App />);
    const conversation = await screen.findByLabelText("Conversation with Taylor");
    const summary = within(conversation).getByText("Security details");
    const details = summary.closest("details") as HTMLDetailsElement;
    fireEvent.click(summary);
    await waitFor(() => expect(details.open).toBe(true));

    act(() => back?.());
    await waitFor(() => expect(details.open).toBe(false));
    expect(screen.getByLabelText("Conversation with Taylor")).toBeTruthy();

    act(() => back?.());
    await screen.findByRole("heading", { name: "Your private conversations" });
  });

  it("backs out of the emoji catalog, then the picker, before returning to the conversation list", async () => {
    const current: Snapshot = { ...snapshot([approved]), messages: [firstMessage] };
    let back: (() => void) | undefined;
    api.runtimePlatform.mockResolvedValue("android");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);
    api.onMobileBackButton.mockImplementation(async (callback: () => void) => {
      back = callback;
      return () => undefined;
    });
    api.serviceCommand.mockImplementation(async (command: string) => command === "snapshot" ? current : {});

    render(<App />);
    const conversation = await screen.findByLabelText("Conversation with Taylor");
    fireEvent.click(within(conversation).getByRole("button", { name: "Add a reaction" }));
    const picker = await screen.findByRole("dialog", { name: "Choose a reaction" });
    fireEvent.click(within(picker).getByRole("button", { name: "More emojis" }));
    await within(picker).findByRole("searchbox", { name: "Search emojis" });
    await waitFor(() => expect(back).toBeTypeOf("function"));

    act(() => back?.());

    await waitFor(() => expect(within(picker).queryByRole("searchbox", { name: "Search emojis" })).toBeNull());
    expect(screen.getByRole("dialog", { name: "Choose a reaction" })).toBeTruthy();
    expect(within(picker).getByRole("button", { name: "More emojis" })).toBeTruthy();

    act(() => back?.());

    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Choose a reaction" })).toBeNull());
    expect(screen.getByLabelText("Conversation with Taylor")).toBeTruthy();
    expect(api.onMobileBackButton).toHaveBeenCalledTimes(1);

    act(() => back?.());
    await screen.findByRole("heading", { name: "Your private conversations" });
  });

  it("clears a group confirmation when Back closes member details", async () => {
    const current: Snapshot = {
      ...snapshot(),
      groups: [group],
      group_messages: [],
      group_drafts: [],
      group_invitations: [],
    };
    let back: (() => void) | undefined;
    api.runtimePlatform.mockResolvedValue("android");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);
    api.onMobileBackButton.mockImplementation(async (callback: () => void) => {
      back = callback;
      return () => undefined;
    });
    api.serviceCommand.mockImplementation(async (command: string) => command === "snapshot" ? current : {});

    render(<App />);
    const conversation = await screen.findByLabelText(`Group conversation ${group.title}`);
    const summary = within(conversation).getByText("Members & security");
    const details = summary.closest("details") as HTMLDetailsElement;
    fireEvent.click(summary);
    await waitFor(() => expect(details.open).toBe(true));
    fireEvent.click(within(conversation).getByRole("button", { name: "Close group" }));
    expect(within(conversation).getByRole("alertdialog", { name: "Confirm group change" })).toBeTruthy();

    act(() => back?.());

    await waitFor(() => expect(details.open).toBe(false));
    await waitFor(() => expect(conversation.querySelector(".group-confirm")).toBeNull());
    expect(screen.getByLabelText(`Group conversation ${group.title}`)).toBeTruthy();
  });
});

describe("connected conversation", () => {
  it("keeps the first message in the flexible message region when the optional banner is absent", async () => {
    const current = snapshot([approved]);
    current.messages = [firstMessage];
    api.runtimePlatform.mockResolvedValue("desktop");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);
    api.serviceCommand.mockImplementation(async (command: string) => {
      if (command === "snapshot") return current;
      return {};
    });

    render(<App />);
    const conversation = await screen.findByLabelText("Conversation with Taylor");
    const renderedMessage = within(conversation).getByText(firstMessage.text);
    const messageList = renderedMessage.closest(".message-list");
    const composer = screen.getByRole("textbox", { name: "Message Taylor" }).closest(".composer");
    expect(messageList).toBeTruthy();
    expect(composer).toBeTruthy();
  });

  it("renders a safe label for an invalid stored message time", async () => {
    const current = snapshot([approved]);
    current.messages = [{ ...firstMessage, created_at: Number.NaN }];
    api.runtimePlatform.mockResolvedValue("desktop");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);
    api.serviceCommand.mockImplementation(async (command: string) => {
      if (command === "snapshot") return current;
      return {};
    });

    render(<App />);
    expect((await screen.findAllByText("Unknown time")).length).toBeGreaterThan(0);
  });

  it("restores the draft and shows an error if sending fails", async () => {
    const current = snapshot([approved]);
    api.runtimePlatform.mockResolvedValue("desktop");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);
    api.serviceCommand.mockImplementation(async (command: string) => {
      if (command === "snapshot") return current;
      if (command === "send_message") throw new Error("test send failure");
      return {};
    });

    render(<App />);
    const composer = await screen.findByRole("textbox", { name: "Message Taylor" });
    fireEvent.change(composer, { target: { value: "Please keep this draft" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Your text is still in the composer.");
    expect(alert.textContent).toContain("Check the conversation before sending it again.");
    expect((composer as HTMLTextAreaElement).value).toBe("Please keep this draft");
  });

  it.each([
    ["service_timeout", "did not respond in time"],
    ["service_busy", "finishing earlier delivery work"],
    ["service_stopped", "messaging service stopped"],
  ])("keeps a direct draft and explains %s", async (code, guidance) => {
    const current = snapshot([approved]);
    api.runtimePlatform.mockResolvedValue("desktop");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);
    api.serviceCommand.mockImplementation(async (command: string) => {
      if (command === "snapshot") return current;
      if (command === "send_message") throw new Error(code);
      return {};
    });

    render(<App />);
    const composer = await screen.findByRole("textbox", { name: "Message Taylor" });
    fireEvent.change(composer, { target: { value: "Keep this exact reply" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain(guidance);
    expect(alert.textContent).toContain("Your text is still in the composer.");
    expect(alert.textContent).toContain("Check the conversation before sending it again.");
    expect((composer as HTMLTextAreaElement).value).toBe("Keep this exact reply");
  });

  it("shows a sent direct message after a stale refresh was already in flight on mobile", async () => {
    const stale = snapshot([approved]);
    let current = stale;
    let serviceEvent: ((event: { type: "event"; event: "state_changed" }) => void) | undefined;
    let snapshotCalls = 0;
    const staleRefresh = deferred<Snapshot>();
    const outbound: ChatMessage = {
      ...firstMessage,
      id: "outbound-after-stale-refresh",
      contact_id: approved.id,
      direction: "outbound",
      text: "The message remains visible",
      state: "queued",
    };
    api.runtimePlatform.mockResolvedValue("android");
    api.initializeService.mockResolvedValue(stale);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockImplementation(async (callback: typeof serviceEvent) => {
      serviceEvent = callback;
      return () => undefined;
    });
    api.serviceCommand.mockImplementation(async (command: string) => {
      if (command === "snapshot") {
        snapshotCalls += 1;
        return snapshotCalls === 1 ? staleRefresh.promise : current;
      }
      if (command === "send_message") {
        current = { ...current, messages: [outbound] };
        return outbound;
      }
      return {};
    });

    render(<App />);
    const composer = await screen.findByRole("textbox", { name: "Message Taylor" });
    expect(serviceEvent).toBeTypeOf("function");
    act(() => serviceEvent?.({ type: "event", event: "state_changed" }));
    await waitFor(() => expect(snapshotCalls).toBe(1));

    fireEvent.change(composer, { target: { value: outbound.text } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await waitFor(() => expect(api.serviceCommand).toHaveBeenCalledWith("send_message", {
      contact_id: approved.id,
      text: outbound.text,
    }));
    await act(async () => staleRefresh.resolve(stale));

    const conversation = screen.getByLabelText("Conversation with Taylor");
    expect(await within(conversation).findByText(outbound.text)).toBeTruthy();
    expect(screen.getByText("Saved on this device")).toBeTruthy();
    expect(snapshotCalls).toBe(2);
  });

  it("shows the durable mobile send result before draft cleanup or snapshot refresh finishes", async () => {
    const current = snapshot([approved]);
    const draftCleanup = deferred<unknown>();
    const outbound: ChatMessage = {
      ...firstMessage,
      id: "outbound-before-mobile-cleanup",
      contact_id: approved.id,
      direction: "outbound",
      text: "Visible as soon as it is saved",
      state: "sending",
    };
    let snapshotCalls = 0;
    api.runtimePlatform.mockResolvedValue("android");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);
    api.serviceCommand.mockImplementation(async (command: string, payload: Record<string, unknown>) => {
      if (command === "send_message") return outbound;
      if (command === "save_draft" && payload.text === "") return draftCleanup.promise;
      if (command === "snapshot") {
        snapshotCalls += 1;
        return current;
      }
      return {};
    });

    render(<App />);
    const composer = await screen.findByRole("textbox", { name: "Message Taylor" });
    fireEvent.change(composer, { target: { value: outbound.text } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    const conversation = screen.getByLabelText("Conversation with Taylor");
    expect(await within(conversation).findByText(outbound.text)).toBeTruthy();
    expect(within(conversation).getByText("Sending…")).toBeTruthy();
    expect(snapshotCalls).toBe(0);

    await act(async () => draftCleanup.resolve({}));
  });

  it("coalesces a rapid Android draft burst and sends the latest text exactly once", async () => {
    const current = snapshot([approved]);
    const outbound: ChatMessage = {
      ...firstMessage,
      id: "outbound-after-rapid-input",
      contact_id: approved.id,
      direction: "outbound",
      text: "Latest mobile text",
      state: "queued",
    };
    api.runtimePlatform.mockResolvedValue("android");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);
    api.serviceCommand.mockImplementation(async (command: string) => {
      if (command === "send_message") return outbound;
      if (command === "snapshot") return { ...current, messages: [outbound] };
      return {};
    });

    render(<App />);
    const composer = await screen.findByRole("textbox", { name: "Message Taylor" });
    fireEvent.input(composer, { target: { value: "Latest" } });
    fireEvent.input(composer, { target: { value: "Latest mobile" } });
    fireEvent.input(composer, { target: { value: outbound.text } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    // A second submit can arrive before React paints the disabled button. The
    // synchronous in-flight guard must still prevent a duplicate native send.
    fireEvent.submit(composer.closest("form") as HTMLFormElement);

    await waitFor(() => expect(api.serviceCommand).toHaveBeenCalledWith("send_message", {
      contact_id: approved.id,
      text: outbound.text,
    }));
    await new Promise((resolve) => window.setTimeout(resolve, 275));

    expect(api.serviceCommand.mock.calls.filter(([command]) => command === "send_message")).toHaveLength(1);
    const draftWrites = api.serviceCommand.mock.calls
      .filter(([command]) => command === "save_draft")
      .map(([, payload]) => payload);
    expect(draftWrites).toEqual([{ contact_id: approved.id, text: "" }]);
  });

  it("does not submit an Android IME composition as a premature Enter send", async () => {
    const current = snapshot([approved]);
    const outbound: ChatMessage = {
      ...firstMessage,
      id: "outbound-after-ime-composition",
      contact_id: approved.id,
      direction: "outbound",
      text: "Composed mobile text",
      state: "queued",
    };
    api.runtimePlatform.mockResolvedValue("android");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);
    api.serviceCommand.mockImplementation(async (command: string) => {
      if (command === "send_message") return outbound;
      if (command === "snapshot") return { ...current, messages: [outbound] };
      return {};
    });

    render(<App />);
    const composer = await screen.findByRole("textbox", { name: "Message Taylor" });
    fireEvent.compositionStart(composer);
    fireEvent.input(composer, { target: { value: outbound.text }, isComposing: true });
    fireEvent.keyDown(composer, { key: "Enter", isComposing: true });
    expect(api.serviceCommand.mock.calls.filter(([command]) => command === "send_message")).toHaveLength(0);

    fireEvent.compositionEnd(composer);
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await waitFor(() => expect(api.serviceCommand).toHaveBeenCalledWith("send_message", {
      contact_id: approved.id,
      text: outbound.text,
    }));
  });

  it("queues a trailing mobile snapshot when a service event arrives during refresh", async () => {
    const stale = snapshot([approved]);
    stale.messages = [{ ...firstMessage, direction: "outbound", state: "sending" }];
    const latest: Snapshot = {
      ...stale,
      messages: [{ ...stale.messages[0], state: "delivered" }],
    };
    let serviceEvent: ((event: { type: "event"; event: "message_status" }) => void) | undefined;
    let snapshotCalls = 0;
    const staleRefresh = deferred<Snapshot>();
    api.runtimePlatform.mockResolvedValue("android");
    api.initializeService.mockResolvedValue(stale);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockImplementation(async (callback: typeof serviceEvent) => {
      serviceEvent = callback;
      return () => undefined;
    });
    api.serviceCommand.mockImplementation(async (command: string) => {
      if (command !== "snapshot") return {};
      snapshotCalls += 1;
      return snapshotCalls === 1 ? staleRefresh.promise : latest;
    });

    render(<App />);
    await screen.findByText("Sending…");
    expect(serviceEvent).toBeTypeOf("function");
    act(() => serviceEvent?.({ type: "event", event: "message_status" }));
    await waitFor(() => expect(snapshotCalls).toBe(1));
    act(() => serviceEvent?.({ type: "event", event: "message_status" }));
    await act(async () => staleRefresh.resolve(stale));

    expect(await screen.findByText("Delivered")).toBeTruthy();
    expect(snapshotCalls).toBe(2);
  });

  it("does not call an already-saved message unsent when draft cleanup fails", async () => {
    let current = snapshot([approved]);
    const outbound: ChatMessage = {
      ...firstMessage,
      id: "outbound-with-draft-cleanup-failure",
      contact_id: approved.id,
      direction: "outbound",
      text: "Send this only once",
      state: "queued",
    };
    api.runtimePlatform.mockResolvedValue("android");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);
    api.serviceCommand.mockImplementation(async (command: string, payload: Record<string, unknown>) => {
      if (command === "snapshot") return current;
      if (command === "send_message") {
        current = { ...current, messages: [outbound] };
        return outbound;
      }
      if (command === "save_draft" && payload.text === "") throw new Error("draft cleanup failed");
      return {};
    });

    render(<App />);
    const composer = await screen.findByRole("textbox", { name: "Message Taylor" });
    fireEvent.change(composer, { target: { value: outbound.text } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    const conversation = screen.getByLabelText("Conversation with Taylor");
    expect(await within(conversation).findByText(outbound.text)).toBeTruthy();
    const warning = await screen.findByRole("alert");
    expect(warning.textContent).toContain("Your message was saved");
    expect(warning.textContent).not.toContain("unsent text");
    expect((composer as HTMLTextAreaElement).value).toBe("");
    expect(api.serviceCommand.mock.calls.filter(([command]) => command === "send_message")).toHaveLength(1);
  });
});

describe("local conversation deletion", () => {
  it("deletes a direct thread, preserves the contact, and restores it through search", async () => {
    let current: Snapshot = {
      ...snapshot([approved]),
      messages: [firstMessage],
      drafts: [{ contact_id: approved.id, text: "unfinished private note" }],
    };
    api.runtimePlatform.mockResolvedValue("desktop");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);
    api.serviceCommand.mockImplementation(async (command: string, payload: Record<string, unknown>) => {
      if (command === "delete_conversation") {
        current = {
          ...current,
          messages: [],
          drafts: [],
          hidden_conversations: [{ kind: "direct", id: approved.id }],
        };
        return { kind: "direct", id: approved.id, deleted_messages: 1 };
      }
      if (command === "restore_conversation") {
        current = { ...current, hidden_conversations: [] };
        return { kind: "direct", id: approved.id, restored: true };
      }
      if (command === "snapshot") return current;
      return {};
    });

    render(<App />);
    const directConversation = await screen.findByLabelText("Conversation with Taylor");
    expect(within(directConversation).getByText(firstMessage.text)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Delete conversation with Taylor" }));

    expect(await screen.findByRole("heading", { name: "Delete conversation?" })).toBeTruthy();
    expect(screen.getByText(/Taylor remains an approved contact/i)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Delete locally" }));

    await waitFor(() => expect(api.serviceCommand).toHaveBeenCalledWith("delete_conversation", {
      kind: "direct",
      id: approved.id,
    }));
    await screen.findByRole("heading", { name: "Your private conversations" });
    expect(screen.queryByText(firstMessage.text)).toBeNull();
    expect(current.contacts).toEqual([approved]);
    expect(screen.queryByRole("button", { name: "Restore conversation with Taylor" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Show deleted conversations (1)" }));
    expect(await screen.findByRole("button", { name: "Restore conversation with Taylor" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Hide deleted conversations" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Restore conversation with Taylor" })).toBeNull());

    fireEvent.change(screen.getByRole("textbox", { name: "Search conversations" }), { target: { value: "Taylor" } });
    const restore = await screen.findByRole("button", { name: "Restore conversation with Taylor" });
    expect(within(restore).getByText("Deleted locally · open to restore")).toBeTruthy();
    fireEvent.click(restore);

    await waitFor(() => expect(api.serviceCommand).toHaveBeenCalledWith("restore_conversation", {
      kind: "direct",
      id: approved.id,
    }));
    expect(await screen.findByLabelText("Conversation with Taylor")).toBeTruthy();
    expect(screen.queryByText(firstMessage.text)).toBeNull();
  });

  it("deletes a group thread without leaving or closing its membership", async () => {
    let current: Snapshot = {
      ...snapshot(),
      groups: [group],
      group_messages: [groupMessage],
      group_drafts: [{ group_id: group.id, text: "unfinished group note" }],
      group_invitations: [],
    };
    api.runtimePlatform.mockResolvedValue("desktop");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);
    api.serviceCommand.mockImplementation(async (command: string) => {
      if (command === "delete_conversation") {
        current = {
          ...current,
          group_messages: [],
          group_drafts: [],
          hidden_conversations: [{ kind: "group", id: group.id }],
        };
        return { kind: "group", id: group.id, deleted_messages: 1 };
      }
      if (command === "restore_conversation") {
        current = { ...current, hidden_conversations: [] };
        return { kind: "group", id: group.id, restored: true };
      }
      if (command === "snapshot") return current;
      return {};
    });

    render(<App />);
    const groupConversation = await screen.findByLabelText(`Group conversation ${group.title}`);
    expect(within(groupConversation).getByText(groupMessage.text)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: `Delete conversation ${group.title}` }));

    expect(await screen.findByText(/You remain a member of Farm Operations/i)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Delete locally" }));

    await waitFor(() => expect(api.serviceCommand).toHaveBeenCalledWith("delete_conversation", {
      kind: "group",
      id: group.id,
    }));
    await screen.findByRole("heading", { name: "Your private conversations" });
    expect(current.groups).toEqual([group]);
    expect(screen.queryByText(groupMessage.text)).toBeNull();

    fireEvent.change(screen.getByRole("textbox", { name: "Search conversations" }), { target: { value: "Farm" } });
    const restore = await screen.findByRole("button", { name: `Restore conversation ${group.title}` });
    fireEvent.click(restore);

    await waitFor(() => expect(api.serviceCommand).toHaveBeenCalledWith("restore_conversation", {
      kind: "group",
      id: group.id,
    }));
    expect(await screen.findByLabelText(`Group conversation ${group.title}`)).toBeTruthy();
    expect(screen.queryByText(groupMessage.text)).toBeNull();
  });
});

describe("small private groups", () => {
  it("creates a group from approved contacts with the eight-person cap contract", async () => {
    let current = snapshot([approved]);
    api.runtimePlatform.mockResolvedValue("desktop");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);
    api.serviceCommand.mockImplementation(async (command: string) => {
      if (command === "snapshot") return current;
      if (command === "create_group") {
        current = { ...current, groups: [group], group_messages: [], group_drafts: [], group_invitations: [] };
        return group;
      }
      return {};
    });

    render(<App />);
    await screen.findByRole("heading", { name: "Taylor" });
    fireEvent.click(screen.getByRole("button", { name: "New group" }));
    await screen.findByRole("heading", { name: "Create a private group" });
    expect(screen.getByText(/this conversation can have 8 people/i)).toBeTruthy();
    fireEvent.click(screen.getByRole("radio", { name: /Announcement channel/ }));
    expect(screen.getByRole("heading", { name: "Create an announcement channel" })).toBeTruthy();
    expect(screen.getByText("Only the owner can post")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Create channel" })).toBeTruthy();
    fireEvent.click(screen.getByRole("radio", { name: /Private group/ }));
    fireEvent.change(screen.getByRole("textbox", { name: "Name" }), { target: { value: "Farm Operations" } });
    fireEvent.click(screen.getByRole("checkbox", { name: /Taylor/ }));
    fireEvent.click(screen.getByRole("button", { name: "Create group" }));

    await waitFor(() => {
      expect(api.serviceCommand).toHaveBeenCalledWith("create_group", {
        title: "Farm Operations",
        member_ids: [approved.id],
        posting_policy: "members",
      });
    });
    expect(await screen.findByRole("heading", { name: group.title })).toBeTruthy();
  });

  it("shows per-member delivery progress for an outgoing group message", async () => {
    const current = { ...snapshot(), groups: [group], group_messages: [groupMessage], group_drafts: [], group_invitations: [] };
    api.runtimePlatform.mockResolvedValue("desktop");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);
    api.serviceCommand.mockImplementation(async (command: string) => command === "snapshot" ? current : {});

    render(<App />);
    const conversation = await screen.findByLabelText(`Group conversation ${group.title}`);
    expect(within(conversation).getByText(groupMessage.text)).toBeTruthy();
    const summary = within(conversation).getByText("Sending to 1");
    fireEvent.click(summary);
    expect(within(conversation).getByText("Sending…")).toBeTruthy();
  });

  it("shows an unreachable invitee and lets the owner retry immediately", async () => {
    const pendingGroup: Group = {
      ...group,
      members: [
        group.members[0],
        {
          ...group.members[1],
          status: "invited",
          invite_delivery_state: "waiting_for_keys",
          invite_attempt_count: 2,
        },
      ],
    };
    const current = { ...snapshot(), groups: [pendingGroup], group_messages: [], group_drafts: [], group_invitations: [] };
    api.runtimePlatform.mockResolvedValue("desktop");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);
    api.serviceCommand.mockImplementation(async (command: string) => command === "snapshot" ? current : pendingGroup);

    render(<App />);
    const conversation = await screen.findByLabelText(`Group conversation ${pendingGroup.title}`);
    expect(within(conversation).getByText(/Trying to reach Taylor/)).toBeTruthy();
    fireEvent.click(within(conversation).getByText("Members & security"));
    expect(within(conversation).getByText("Trying to find device")).toBeTruthy();
    fireEvent.click(within(conversation).getByRole("button", { name: "Retry invitation to Taylor" }));
    await waitFor(() => expect(api.serviceCommand).toHaveBeenCalledWith("retry_group_invitation", {
      group_id: pendingGroup.id,
      destination_hash: approved.destination_hash,
    }));
  });

  it("disables the composer for a member of an announcement channel", async () => {
    const channel: Group = {
      ...group,
      id: "announcements",
      title: "Farm Announcements",
      owner_destination: approved.destination_hash,
      posting_policy: "owner_admins",
      members: group.members.map((member) => member.destination_hash === profile.destination_hash ? { ...member, role: "member" } : { ...member, role: "owner" }),
    };
    const channelMessage: GroupMessage = {
      ...groupMessage,
      id: "announcement-message",
      group_id: channel.id,
      sender_destination: approved.destination_hash,
      sender_display_name: approved.display_name,
      direction: "inbound",
      deliveries: undefined,
      delivery_summary: undefined,
    };
    const current = { ...snapshot(), groups: [channel], group_messages: [channelMessage], group_drafts: [], group_invitations: [] };
    api.runtimePlatform.mockResolvedValue("desktop");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);
    api.serviceCommand.mockImplementation(async (command: string) => command === "snapshot" ? current : {});

    render(<App />);
    const conversation = await screen.findByLabelText(`Announcement channel ${channel.title}`);
    expect(screen.getAllByText("Only the owner can post in this announcement channel.").length).toBeGreaterThan(0);
    expect(screen.queryByRole("textbox", { name: `Message ${channel.title}` })).toBeNull();
    fireEvent.click(within(conversation).getByRole("button", { name: "Add a reaction" }));
    fireEvent.click(within(await screen.findByRole("dialog", { name: "Choose a reaction" })).getByRole("button", { name: "React with thumbs up" }));
    await waitFor(() => expect(api.serviceCommand).toHaveBeenCalledWith("set_message_reaction", {
      kind: "group",
      message_id: channelMessage.id,
      emoji: "👍",
      active: true,
    }));
  });

  it("does not offer a composer when nobody else is an active member", async () => {
    const emptyGroup: Group = {
      ...group,
      members: group.members.map((member) => member.destination_hash === approved.destination_hash ? { ...member, status: "removed" } : member),
    };
    const current = { ...snapshot(), groups: [emptyGroup], group_messages: [], group_drafts: [], group_invitations: [] };
    api.runtimePlatform.mockResolvedValue("desktop");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);
    api.serviceCommand.mockImplementation(async (command: string) => command === "snapshot" ? current : {});

    render(<App />);
    await screen.findByLabelText(`Group conversation ${emptyGroup.title}`);
    expect(screen.getAllByText("There are no other active members to receive a message.").length).toBeGreaterThan(0);
    expect(screen.queryByRole("textbox", { name: `Message ${emptyGroup.title}` })).toBeNull();
  });

  it("pauses the composer while a signed membership update is pending", async () => {
    const updatingGroup: Group = { ...group, membership_update_pending: true };
    const current = { ...snapshot(), groups: [updatingGroup], group_messages: [], group_drafts: [], group_invitations: [] };
    api.runtimePlatform.mockResolvedValue("desktop");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);
    api.serviceCommand.mockImplementation(async (command: string) => command === "snapshot" ? current : {});

    render(<App />);
    const conversation = await screen.findByLabelText(`Group conversation ${updatingGroup.title}`);
    expect(within(conversation).getByText("A membership update is still reaching the group. Messaging is paused until it arrives.")).toBeTruthy();
    expect(within(conversation).getAllByText("Messaging is paused until the signed membership update reaches every current member.").length).toBeGreaterThan(0);
    expect(screen.queryByRole("textbox", { name: `Message ${updatingGroup.title}` })).toBeNull();
    expect(api.serviceCommand).not.toHaveBeenCalledWith("send_group_message", expect.anything());
  });

  it("requires explicit acceptance of a signed group invitation", async () => {
    let current: Snapshot = { ...snapshot(), groups: [], group_messages: [], group_drafts: [], group_invitations: [groupInvitation] };
    api.runtimePlatform.mockResolvedValue("desktop");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);
    api.serviceCommand.mockImplementation(async (command: string) => {
      if (command === "snapshot") return current;
      if (command === "accept_group_invitation") {
        current = { ...current, groups: [group], group_invitations: [] };
        return group;
      }
      return {};
    });

    render(<App />);
    await screen.findByRole("heading", { name: "Group invitation" });
    expect(screen.getByText("Starts when you join")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Accept invitation" }));
    await waitFor(() => expect(api.serviceCommand).toHaveBeenCalledWith("accept_group_invitation", { invitation_id: groupInvitation.id }));
    expect(await screen.findByRole("heading", { name: group.title })).toBeTruthy();
  });
});

describe("desktop workspaces", () => {
  it("opens, sends, hides, and reopens a workspace DM without creating a Contact", async () => {
    const member = {
      id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      display_name: "Bailey",
      role: "member" as const,
      status: "active" as const,
      short_id: "aaaaaa",
      device: { id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", destination_hash: "99".repeat(16), fingerprint: "BBBB CCCC DDDD EEEE" },
    };
    const expanded: Workspace = { ...workspace, members: [...workspace.members, member] };
    const direct: WorkspaceDirect = {
      id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
      workspace_id: workspace.id,
      participant_member_ids: [workspace.local_member_id, member.id].sort(),
      peer_member_id: member.id,
      peer_display_name: member.display_name,
      peer_short_id: member.short_id,
      state: "open",
      unread_count: 0,
      created_at: 10,
      updated_at: 10,
    };
    let current: Snapshot = {
      ...snapshot(),
      workspaces: [expanded],
      workspace_channels: [workspaceChannel],
      workspace_directs: [],
      workspace_join_requests: [],
      workspace_invitations: [],
      workspace_drafts: [],
    };
    api.runtimePlatform.mockResolvedValue("desktop");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);
    api.serviceCommand.mockImplementation(async (command: string, payload: Record<string, unknown>) => {
      if (command === "snapshot") return current;
      if (command === "list_workspace_messages" || command === "list_workspace_direct_messages") return { messages: [], next_cursor: null, high_water: 0 } satisfies WorkspaceMessagePage;
      if (command === "open_workspace_direct") {
        current = { ...current, workspace_directs: [direct] };
        return direct;
      }
      if (command === "send_workspace_direct_message") {
        return {
          id: String(payload.event_id),
          workspace_id: workspace.id,
          conversation_id: direct.id,
          direction: "outbound",
          author_member_id: workspace.local_member_id,
          author_display_name: "Alex",
          text: String(payload.text),
          sequence: 1,
          event_digest: "99".repeat(32),
          created_at: 20,
        } satisfies WorkspaceMessage;
      }
      if (command === "hide_workspace_direct") {
        current = { ...current, workspace_directs: [] };
        return { hidden: true };
      }
      return {};
    });

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Workspace Lakewatcher" }));
    fireEvent.click(await screen.findByRole("button", { name: "People in Lakewatcher" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Message" }));
    await waitFor(() => expect(api.serviceCommand).toHaveBeenCalledWith("open_workspace_direct", expect.objectContaining({ workspace_id: workspace.id, member_id: member.id, operation_id: expect.any(String) })));
    let conversation = await screen.findByLabelText("Workspace direct message with Bailey");
    expect(within(conversation).getByText(/does not create a global Contact/i)).toBeTruthy();
    const composer = within(conversation).getByRole("textbox", { name: "Message Bailey" });
    fireEvent.paste(composer, {
      clipboardData: {
        files: [new File(["image"], "private.png", { type: "image/png" })],
        items: [{ kind: "file" }],
      },
    });
    expect(await within(conversation).findByText(/Attachments are not supported yet/i)).toBeTruthy();
    fireEvent.change(composer, { target: { value: "Private workspace hello" } });
    fireEvent.click(within(conversation).getByRole("button", { name: "Send workspace direct message" }));
    await waitFor(() => expect(api.serviceCommand).toHaveBeenCalledWith("send_workspace_direct_message", expect.objectContaining({ workspace_id: workspace.id, conversation_id: direct.id, text: "Private workspace hello", event_id: expect.any(String), operation_id: expect.any(String) })));

    fireEvent.click(within(conversation).getByRole("button", { name: "Hide workspace conversation with Bailey" }));
    await waitFor(() => expect(api.serviceCommand).toHaveBeenCalledWith("hide_workspace_direct", expect.objectContaining({ workspace_id: workspace.id, conversation_id: direct.id, operation_id: expect.any(String) })));
    expect(await screen.findByText("Start a private workspace chat from People.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "People in Lakewatcher" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Message" }));
    conversation = await screen.findByLabelText("Workspace direct message with Bailey");
    expect(conversation).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Contacts" }));
    expect(within(screen.getByRole("dialog", { name: "Contacts" })).getByText("No contacts yet.")).toBeTruthy();
  });

  it("uses the bounded workspace summary command for scoped invalidations", async () => {
    const current: Snapshot = { ...snapshot(), workspaces: [workspace], workspace_channels: [workspaceChannel], workspace_join_requests: [], workspace_invitations: [], workspace_drafts: [] };
    let serviceEvent: ((event: { type: "event"; event: "workspace_changed"; workspace_id: string; resource_kind: string; generation: number }) => void) | undefined;
    api.runtimePlatform.mockResolvedValue("desktop");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockImplementation(async (callback) => {
      serviceEvent = callback;
      return () => undefined;
    });
    api.serviceCommand.mockImplementation(async (command: string) => {
      if (command === "workspace_snapshot") {
        return {
          workspaces: [{ ...workspace, name: "Lakewatcher Updated" }],
          workspace_channels: [workspaceChannel],
          workspace_join_requests: [],
          workspace_invitations: [],
          workspace_drafts: [],
        };
      }
      if (command === "snapshot") return current;
      return {};
    });

    render(<App />);
    await screen.findByRole("button", { name: "Workspace Lakewatcher" });
    api.serviceCommand.mockClear();
    await act(async () => {
      serviceEvent?.({ type: "event", event: "workspace_changed", workspace_id: workspace.id, resource_kind: "workspace", generation: 2 });
    });
    expect(await screen.findByRole("button", { name: "Workspace Lakewatcher Updated" })).toBeTruthy();
    expect(api.serviceCommand).toHaveBeenCalledWith("workspace_snapshot");
    expect(api.serviceCommand.mock.calls.some(([command]) => command === "snapshot")).toBe(false);
  });

  it("keeps the open general channel stable across polling and non-message invalidations", async () => {
    const current: Snapshot = { ...snapshot(), workspaces: [workspace], workspace_channels: [workspaceChannel], workspace_join_requests: [], workspace_invitations: [], workspace_drafts: [] };
    const initialPage: WorkspaceMessagePage = {
      messages: [{
        id: "55555555-5555-4555-8555-555555555555",
        workspace_id: workspace.id,
        conversation_id: workspaceChannel.id,
        direction: "inbound",
        author_member_id: workspace.local_member_id,
        author_display_name: "Taylor",
        text: "Lake level is stable",
        sequence: 1,
        event_digest: "99".repeat(32),
        created_at: 1_791_072_021,
      }],
      next_cursor: null,
      high_water: 1,
    };
    const updatedPage: WorkspaceMessagePage = {
      ...initialPage,
      messages: [...initialPage.messages, { ...initialPage.messages[0], id: "66666666-6666-4666-8666-666666666666", text: "Dock inspection complete", sequence: 2 }],
      high_water: 2,
    };
    const backgroundReload = deferred<WorkspaceMessagePage>();
    let deferMessageReload = false;
    let serviceEvent: ((event: ServiceEvent) => void) | undefined;
    api.runtimePlatform.mockResolvedValue("desktop");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockImplementation(async (callback) => {
      serviceEvent = callback;
      return () => undefined;
    });
    api.serviceCommand.mockImplementation(async (command: string) => {
      if (command === "snapshot") return { ...current };
      if (command === "workspace_snapshot") {
        return {
          workspaces: current.workspaces,
          workspace_channels: current.workspace_channels,
          workspace_join_requests: [],
          workspace_invitations: [],
          workspace_drafts: [],
        };
      }
      if (command === "list_workspace_messages") return deferMessageReload ? backgroundReload.promise : initialPage;
      return {};
    });

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Workspace Lakewatcher" }));
    const conversation = await screen.findByLabelText("Workspace channel general");
    expect(await within(conversation).findByText("Lake level is stable")).toBeTruthy();
    const messageRequestCount = () => api.serviceCommand.mock.calls.filter(([command]) => command === "list_workspace_messages").length;
    expect(messageRequestCount()).toBe(1);

    await act(async () => {
      window.dispatchEvent(new Event("focus"));
    });
    await waitFor(() => expect(api.serviceCommand.mock.calls.some(([command]) => command === "snapshot")).toBe(true));
    expect(messageRequestCount()).toBe(1);
    expect(within(conversation).getByText("Lake level is stable")).toBeTruthy();

    await act(async () => {
      serviceEvent?.({ type: "event", event: "workspace_changed", workspace_id: workspace.id, conversation_id: workspaceChannel.id, resource_kind: "draft", generation: 2 });
    });
    await waitFor(() => expect(api.serviceCommand.mock.calls.some(([command]) => command === "workspace_snapshot")).toBe(true));
    expect(messageRequestCount()).toBe(1);
    expect(within(conversation).getByText("Lake level is stable")).toBeTruthy();

    deferMessageReload = true;
    await act(async () => {
      serviceEvent?.({ type: "event", event: "workspace_changed", workspace_id: workspace.id, conversation_id: workspaceChannel.id, resource_kind: "message", generation: 3 });
    });
    await waitFor(() => expect(messageRequestCount()).toBe(2));
    expect(within(conversation).getByText("Lake level is stable")).toBeTruthy();
    expect(within(conversation).queryByText("Loading messages…")).toBeNull();
    await act(async () => {
      backgroundReload.resolve(updatedPage);
      await backgroundReload.promise;
    });
    expect(await within(conversation).findByText("Dock inspection complete")).toBeTruthy();
  });

  it("creates a workspace only after showing the owner and peer-delivery facts", async () => {
    let current = snapshot();
    api.runtimePlatform.mockResolvedValue("desktop");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);
    api.serviceCommand.mockImplementation(async (command: string) => {
      if (command === "create_workspace") {
        current = { ...current, workspaces: [workspace], workspace_channels: [workspaceChannel], workspace_join_requests: [], workspace_invitations: [], workspace_drafts: [] };
        return workspace;
      }
      if (command === "snapshot") return current;
      if (command === "list_workspace_messages") return { messages: [], next_cursor: null, high_water: 0 } satisfies WorkspaceMessagePage;
      return {};
    });

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Create workspace" }));
    expect(await screen.findByText(/This device becomes the owner authority/i)).toBeTruthy();
    expect(screen.getByText(/encrypted separately for each member device/i)).toBeTruthy();
    expect(screen.getByText(/there is no hosted workspace server/i)).toBeTruthy();
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByRole("textbox", { name: "Workspace name" }), { target: { value: "Lakewatcher" } });
    fireEvent.change(within(dialog).getByRole("textbox", { name: "Workspace description" }), { target: { value: "Field coordination" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Create workspace" }));

    await waitFor(() => expect(api.serviceCommand).toHaveBeenCalledWith("create_workspace", expect.objectContaining({ name: "Lakewatcher", description: "Field coordination", operation_id: expect.any(String) })));
    expect(await screen.findByRole("heading", { name: "general" })).toBeTruthy();
  });

  it("pages general-channel messages, reports attachment rejection, and sends with durable IDs", async () => {
    let page: WorkspaceMessagePage = {
      messages: [{
        id: "55555555-5555-4555-8555-555555555555",
        workspace_id: workspace.id,
        conversation_id: workspaceChannel.id,
        direction: "inbound",
        author_member_id: workspace.local_member_id,
        author_display_name: "Taylor",
        text: "Lake level is stable",
        sequence: 1,
        event_digest: "99".repeat(32),
        created_at: 1_791_072_021,
      }],
      next_cursor: null,
      high_water: 1,
    };
    const current: Snapshot = { ...snapshot(), workspaces: [workspace], workspace_channels: [workspaceChannel], workspace_join_requests: [], workspace_invitations: [], workspace_drafts: [] };
    api.runtimePlatform.mockResolvedValue("desktop");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);
    api.serviceCommand.mockImplementation(async (command: string, payload: Record<string, unknown>) => {
      if (command === "snapshot") return current;
      if (command === "list_workspace_messages") return page;
      if (command === "send_workspace_message") {
        page = { ...page, messages: [...page.messages, { ...page.messages[0], id: String(payload.event_id), direction: "outbound", author_display_name: "Alex", text: String(payload.text), sequence: 2, delivery_summary: { people_total: 0, people_reached: 0, devices_total: 0, devices_reached: 0, devices_pending: 0, devices_failed: 0 } }] };
        return page.messages.at(-1);
      }
      return {};
    });

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Workspace Lakewatcher" }));
    const conversation = await screen.findByLabelText("Workspace channel general");
    expect(within(conversation).getByText("Lake level is stable")).toBeTruthy();
    fireEvent.click(within(conversation).getByRole("button", { name: "Add attachment" }));
    expect(await within(conversation).findByText(/Attachments are not supported yet/i)).toBeTruthy();
    const composer = within(conversation).getByRole("textbox", { name: "Message general" });
    fireEvent.paste(composer, {
      clipboardData: {
        files: [new File(["image"], "lake.png", { type: "image/png" })],
        items: [{ kind: "file" }],
      },
    });
    expect(await within(conversation).findByText(/Attachments are not supported yet/i)).toBeTruthy();
    fireEvent.change(composer, { target: { value: "Owner update" } });
    fireEvent.click(within(conversation).getByRole("button", { name: "Send workspace message" }));
    await waitFor(() => expect(api.serviceCommand).toHaveBeenCalledWith("send_workspace_message", expect.objectContaining({ workspace_id: workspace.id, channel_id: workspaceChannel.id, text: "Owner update", event_id: expect.any(String), operation_id: expect.any(String) })));
    expect(await within(conversation).findByText("Owner update")).toBeTruthy();
    expect(within(conversation).getByText(/Saved locally/i)).toBeTruthy();
  });

  it("inserts structured mentions, persists their draft IDs, and clears the Mentions inbox", async () => {
    const member = {
      id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      display_name: "Bailey",
      role: "member" as const,
      status: "active" as const,
      short_id: "aaaaaa",
      device: { id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", destination_hash: "99".repeat(16), fingerprint: "BBBB CCCC DDDD EEEE" },
    };
    const expanded: Workspace = { ...workspace, members: [...workspace.members, member], mention_unread_count: 1 };
    const incoming: WorkspaceMessage = {
      id: "78787878-7878-4878-8878-787878787878",
      workspace_id: workspace.id,
      conversation_id: workspaceChannel.id,
      direction: "inbound",
      author_member_id: member.id,
      author_display_name: member.display_name,
      text: "@Alex inspect the south marker",
      mention_member_ids: [workspace.local_member_id],
      sequence: 1,
      event_digest: "ab".repeat(32),
      created_at: 1_791_072_030,
    };
    let current: Snapshot = { ...snapshot(), workspaces: [expanded], workspace_channels: [workspaceChannel], workspace_join_requests: [], workspace_invitations: [], workspace_drafts: [] };
    const mentionPage: WorkspaceMentionPage = {
      mentions: [{ position: 1, read: false, conversation: { id: workspaceChannel.id, kind: "channel", name: "general", visibility: "public" }, message: incoming }],
      next_cursor: null,
      high_water: 1,
      unread_count: 1,
    };
    api.runtimePlatform.mockResolvedValue("desktop");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);
    api.serviceCommand.mockImplementation(async (command: string, payload: Record<string, unknown>) => {
      if (command === "snapshot") return current;
      if (command === "list_workspace_messages") return { messages: [], next_cursor: null, high_water: 0 } satisfies WorkspaceMessagePage;
      if (command === "list_workspace_mentions") return mentionPage;
      if (command === "send_workspace_message") return {
        ...incoming,
        id: String(payload.event_id),
        direction: "outbound",
        author_member_id: workspace.local_member_id,
        author_display_name: "Alex",
        text: String(payload.text),
        mention_member_ids: payload.mention_member_ids as string[],
      } satisfies WorkspaceMessage;
      if (command === "mark_workspace_mentions_read") {
        current = { ...current, workspaces: [{ ...expanded, mention_unread_count: 0 }] };
        return { workspace_id: workspace.id, high_water: 1, unread_count: 0 };
      }
      return {};
    });

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Workspace Lakewatcher" }));
    const conversation = await screen.findByLabelText("Workspace channel general");
    fireEvent.click(within(conversation).getByRole("button", { name: "Mention a workspace member" }));
    fireEvent.click(within(await screen.findByRole("dialog", { name: "Choose a member to mention" })).getByRole("button", { name: /Bailey/ }));
    expect(within(conversation).getByLabelText("Selected mentions").textContent).toContain("Bailey");
    const composer = within(conversation).getByRole("textbox", { name: "Message general" });
    expect((composer as HTMLTextAreaElement).value).toBe("@Bailey ");
    fireEvent.change(composer, { target: { value: "@Bailey inspect the north gauge" } });
    await waitFor(() => expect(api.serviceCommand).toHaveBeenCalledWith("save_workspace_draft", expect.objectContaining({ workspace_id: workspace.id, channel_id: workspaceChannel.id, text: "@Bailey inspect the north gauge", mention_member_ids: [member.id], operation_id: expect.any(String) })));
    fireEvent.click(within(conversation).getByRole("button", { name: "Send workspace message" }));
    await waitFor(() => expect(api.serviceCommand).toHaveBeenCalledWith("send_workspace_message", expect.objectContaining({ workspace_id: workspace.id, channel_id: workspaceChannel.id, text: "@Bailey inspect the north gauge", mention_member_ids: [member.id], event_id: expect.any(String), operation_id: expect.any(String) })));

    fireEvent.click(screen.getByRole("button", { name: /Mentions/ }));
    const mentions = await screen.findByLabelText("Mentions in Lakewatcher");
    expect(within(mentions).getByText("@Alex inspect the south marker")).toBeTruthy();
    expect(within(mentions).getByText("New")).toBeTruthy();
    fireEvent.click(within(mentions).getByRole("button", { name: "Mark all read" }));
    await waitFor(() => expect(api.serviceCommand).toHaveBeenCalledWith("mark_workspace_mentions_read", expect.objectContaining({ workspace_id: workspace.id, high_water: 1, operation_id: expect.any(String) })));

    fireEvent.click(within(mentions).getByRole("button", { name: /@Alex inspect the south marker/ }));
    const reopened = await screen.findByLabelText("Workspace channel general");
    fireEvent.click(within(reopened).getByRole("button", { name: "Mute mentions in general" }));
    await waitFor(() => expect(api.serviceCommand).toHaveBeenCalledWith("set_workspace_channel_mentions_muted", expect.objectContaining({ workspace_id: workspace.id, channel_id: workspaceChannel.id, muted: true, operation_id: expect.any(String) })));
  });

  it("drops a stale draft mention ID without discarding its ordinary text", async () => {
    const staleMemberId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
    const current: Snapshot = {
      ...snapshot(),
      workspaces: [workspace],
      workspace_channels: [workspaceChannel],
      workspace_join_requests: [],
      workspace_invitations: [],
      workspace_drafts: [{
        workspace_id: workspace.id,
        conversation_id: workspaceChannel.id,
        text: "@Former keep this field note",
        mention_member_ids: [staleMemberId],
      }],
    };
    api.runtimePlatform.mockResolvedValue("desktop");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);
    api.serviceCommand.mockImplementation(async (command: string, payload: Record<string, unknown>) => {
      if (command === "snapshot") return current;
      if (command === "list_workspace_messages") return { messages: [], next_cursor: null, high_water: 0 } satisfies WorkspaceMessagePage;
      if (command === "send_workspace_message") return {
        id: String(payload.event_id),
        workspace_id: workspace.id,
        conversation_id: workspaceChannel.id,
        direction: "outbound",
        author_member_id: workspace.local_member_id,
        author_display_name: "Alex",
        text: String(payload.text),
        mention_member_ids: payload.mention_member_ids as string[],
        sequence: 1,
        event_digest: "cd".repeat(32),
        created_at: 1_791_072_040,
      } satisfies WorkspaceMessage;
      return {};
    });

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Workspace Lakewatcher" }));
    const conversation = await screen.findByLabelText("Workspace channel general");
    expect(within(conversation).queryByLabelText("Selected mentions")).toBeNull();
    expect((within(conversation).getByRole("textbox", { name: "Message general" }) as HTMLTextAreaElement).value).toBe("@Former keep this field note");
    fireEvent.click(within(conversation).getByRole("button", { name: "Send workspace message" }));
    await waitFor(() => expect(api.serviceCommand).toHaveBeenCalledWith("send_workspace_message", expect.objectContaining({
      workspace_id: workspace.id,
      channel_id: workspaceChannel.id,
      text: "@Former keep this field note",
      mention_member_ids: [],
    })));
  });

  it("edits, reacts to, and tombstones workspace messages with durable mutation IDs", async () => {
    const member = {
      id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      display_name: "Bailey",
      role: "member" as const,
      status: "active" as const,
      short_id: "aaaaaa",
      device: { id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", destination_hash: "99".repeat(16), fingerprint: "BBBB CCCC DDDD EEEE" },
    };
    const expanded: Workspace = { ...workspace, members: [...workspace.members, member] };
    let message: WorkspaceMessage = {
      id: "56565656-5656-4656-8656-565656565656",
      workspace_id: workspace.id,
      conversation_id: workspaceChannel.id,
      direction: "outbound",
      author_member_id: workspace.local_member_id,
      author_display_name: "Alex",
      text: "Original field note",
      revision: 0,
      deleted: false,
      mutation_conflict: false,
      mutation_frozen: false,
      reactions: [],
      sequence: 1,
      event_digest: "77".repeat(32),
      created_at: 1_791_072_021,
    };
    const current: Snapshot = { ...snapshot(), workspaces: [expanded], workspace_channels: [workspaceChannel], workspace_join_requests: [], workspace_invitations: [], workspace_drafts: [] };
    api.runtimePlatform.mockResolvedValue("desktop");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);
    api.serviceCommand.mockImplementation(async (command: string, payload: Record<string, unknown>) => {
      if (command === "snapshot") return current;
      if (command === "list_workspace_messages") return { messages: [message], next_cursor: null, high_water: 1 } satisfies WorkspaceMessagePage;
      if (command === "edit_workspace_message") {
        message = { ...message, text: String(payload.text), mention_member_ids: payload.mention_member_ids as string[], revision: 1 };
        return message;
      }
      if (command === "set_workspace_reaction") {
        message = { ...message, reactions: [{ emoji: String(payload.emoji), count: 1, reacted_by_self: true }] };
        return message;
      }
      if (command === "delete_workspace_message") {
        message = { ...message, text: "", revision: 2, deleted: true };
        return message;
      }
      return {};
    });

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Workspace Lakewatcher" }));
    const conversation = await screen.findByLabelText("Workspace channel general");
    fireEvent.click(within(conversation).getByRole("button", { name: "Edit" }));
    fireEvent.click(within(conversation).getAllByRole("button", { name: "Mention a workspace member" })[0]);
    fireEvent.click(within(await screen.findByRole("dialog", { name: "Choose a member to mention" })).getByRole("button", { name: /Bailey/ }));
    fireEvent.change(within(conversation).getByRole("textbox", { name: "Edit workspace message" }), { target: { value: "Corrected field note" } });
    fireEvent.click(within(conversation).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.serviceCommand).toHaveBeenCalledWith("edit_workspace_message", expect.objectContaining({ workspace_id: workspace.id, event_id: message.id, text: "Corrected field note", mention_member_ids: [member.id], operation_id: expect.any(String), mutation_event_id: expect.any(String) })));
    expect(await within(conversation).findByText("Corrected field note")).toBeTruthy();
    expect(within(conversation).getByText("Edited")).toBeTruthy();

    fireEvent.click(within(conversation).getByRole("button", { name: "Add a reaction" }));
    fireEvent.click(within(await screen.findByRole("dialog", { name: "Choose a reaction" })).getByRole("button", { name: "React with thumbs up" }));
    await waitFor(() => expect(api.serviceCommand).toHaveBeenCalledWith("set_workspace_reaction", expect.objectContaining({ workspace_id: workspace.id, event_id: message.id, emoji: "👍", active: true, operation_id: expect.any(String), mutation_event_id: expect.any(String) })));
    expect(await within(conversation).findByRole("button", { name: /Remove your thumbs up reaction; 1 reaction total/ })).toBeTruthy();

    fireEvent.click(within(conversation).getByRole("button", { name: "Delete" }));
    fireEvent.click(within(conversation).getAllByRole("button", { name: "Delete" }).at(-1)!);
    await waitFor(() => expect(api.serviceCommand).toHaveBeenCalledWith("delete_workspace_message", expect.objectContaining({ workspace_id: workspace.id, event_id: message.id, operation_id: expect.any(String), mutation_event_id: expect.any(String) })));
    expect(await within(conversation).findByText("Message deleted by its author.")).toBeTruthy();
    expect(within(conversation).queryByText("Corrected field note")).toBeNull();
  });

  it("reuses durable workspace send IDs after an uncertain failure", async () => {
    const current: Snapshot = { ...snapshot(), workspaces: [workspace], workspace_channels: [workspaceChannel], workspace_join_requests: [], workspace_invitations: [], workspace_drafts: [] };
    const sentPayloads: Record<string, unknown>[] = [];
    api.runtimePlatform.mockResolvedValue("desktop");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);
    api.serviceCommand.mockImplementation(async (command: string, payload: Record<string, unknown>) => {
      if (command === "snapshot") return current;
      if (command === "list_workspace_messages") return { messages: [], next_cursor: null, high_water: 0 } satisfies WorkspaceMessagePage;
      if (command === "send_workspace_message") {
        sentPayloads.push(payload);
        if (sentPayloads.length === 1) throw new Error("service_timeout");
        return {
          id: String(payload.event_id),
          workspace_id: workspace.id,
          conversation_id: workspaceChannel.id,
          direction: "outbound",
          author_member_id: workspace.local_member_id,
          author_display_name: "Alex",
          text: String(payload.text),
          sequence: 1,
          event_digest: "88".repeat(32),
          created_at: 1_791_072_022,
          delivery_summary: { people_total: 0, people_reached: 0, devices_total: 0, devices_reached: 0, devices_pending: 0, devices_failed: 0 },
        } satisfies WorkspaceMessage;
      }
      return {};
    });

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Workspace Lakewatcher" }));
    const conversation = await screen.findByLabelText("Workspace channel general");
    const composer = within(conversation).getByRole("textbox", { name: "Message general" });
    fireEvent.change(composer, { target: { value: "Retry safely" } });
    fireEvent.click(within(conversation).getByRole("button", { name: "Send workspace message" }));
    expect(await within(conversation).findByText(/retrying will reuse the same durable message ID/i)).toBeTruthy();
    fireEvent.click(within(conversation).getByRole("button", { name: "Send workspace message" }));
    await waitFor(() => expect(sentPayloads).toHaveLength(2));
    expect(sentPayloads[1].operation_id).toBe(sentPayloads[0].operation_id);
    expect(sentPayloads[1].event_id).toBe(sentPayloads[0].event_id);
    expect(await within(conversation).findByText("Retry safely")).toBeTruthy();
  });

  it("offers only valid paused-state actions and confirms terminal closure", async () => {
    let current: Snapshot = { ...snapshot(), workspaces: [workspace], workspace_channels: [workspaceChannel], workspace_join_requests: [], workspace_invitations: [], workspace_drafts: [] };
    api.runtimePlatform.mockResolvedValue("desktop");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);
    api.serviceCommand.mockImplementation(async (command: string) => {
      if (command === "snapshot") return current;
      if (command === "list_workspace_messages") return { messages: [], next_cursor: null, high_water: 0 } satisfies WorkspaceMessagePage;
      if (command === "close_workspace") {
        current = { ...current, workspaces: [{ ...workspace, state: "closed" }] };
        return current.workspaces?.[0];
      }
      return {};
    });

    const view = render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Workspace Lakewatcher" }));
    fireEvent.click(await screen.findByRole("button", { name: "Lakewatcher settings" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Close workspace…" }));
    expect(api.serviceCommand).not.toHaveBeenCalledWith("close_workspace", expect.anything());
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Confirm close workspace" }));
    await waitFor(() => expect(api.serviceCommand).toHaveBeenCalledWith("close_workspace", expect.objectContaining({ workspace_id: workspace.id })));

    view.unmount();
    current = { ...current, workspaces: [{ ...workspace, state: "forked", security_error: "manifest_fork" }] };
    api.initializeService.mockResolvedValue(current);
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Workspace Lakewatcher" }));
    fireEvent.click(await screen.findByRole("button", { name: "Lakewatcher settings" }));
    const paused = screen.getByRole("dialog");
    expect(within(paused).getByText(/will not choose between conflicting signed histories/i)).toBeTruthy();
    expect(within(paused).queryByRole("button", { name: /close workspace/i })).toBeNull();
    expect(within(paused).queryByRole("button", { name: /leave workspace/i })).toBeNull();
  });

  it("manages multiple concurrent workspace invitations independently", async () => {
    const invitations = [
      { id: "invite-one", workspace_id: workspace.id, offered_manifest_digest: workspace.manifest_hash, state: "active" as const, created_at: 10, expires_at: 2_000_000_000 },
      { id: "invite-two", workspace_id: workspace.id, offered_manifest_digest: workspace.manifest_hash, state: "active" as const, created_at: 11, expires_at: 2_000_000_100 },
    ];
    const current: Snapshot = { ...snapshot(), workspaces: [workspace], workspace_channels: [workspaceChannel], workspace_join_requests: [], workspace_invitations: invitations, workspace_drafts: [] };
    api.runtimePlatform.mockResolvedValue("desktop");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);
    api.serviceCommand.mockImplementation(async (command: string) => {
      if (command === "snapshot") return current;
      if (command === "list_workspace_messages") return { messages: [], next_cursor: null, high_water: 0 } satisfies WorkspaceMessagePage;
      if (command === "create_workspace_invitation") return { id: "invite-three", workspace_id: workspace.id, link: "meshchat://workspace/three", text: "MESHWORKSPACE1:three", value: "three", expires_at: 2_000_000_200 };
      return {};
    });

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Workspace Lakewatcher" }));
    fireEvent.click(await screen.findByRole("button", { name: "Invite people to Lakewatcher" }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getAllByText(/One-use invitation · expires/i)).toHaveLength(2);
    fireEvent.click(within(dialog).getAllByRole("button", { name: "Revoke" })[0]);
    await waitFor(() => expect(api.serviceCommand).toHaveBeenCalledWith("revoke_workspace_invitation", expect.objectContaining({ workspace_id: workspace.id, invitation_id: "invite-one", operation_id: expect.any(String) })));
    expect(within(dialog).getAllByText(/One-use invitation · expires/i)).toHaveLength(1);
    fireEvent.click(within(dialog).getByRole("button", { name: "Create another invitation" }));
    await waitFor(() => expect(api.serviceCommand).toHaveBeenCalledWith("create_workspace_invitation", expect.objectContaining({ workspace_id: workspace.id, operation_id: expect.any(String) })));
    expect((await within(dialog).findByRole("textbox", { name: "Workspace invitation text" }) as HTMLTextAreaElement).value).toBe("MESHWORKSPACE1:three");
  });

  it("allows an owner to replace a removed member at the eight-person history limit", async () => {
    const historicalMembers = Array.from({ length: 7 }, (_, index) => ({
      id: `member-${index}`,
      display_name: `Member ${index}`,
      role: "member" as const,
      status: index === 6 ? "removed" as const : "active" as const,
      short_id: `member${index}`,
      device: { id: `device-${index}`, destination_hash: String(index).repeat(32), fingerprint: `fingerprint-${index}` },
    }));
    const current: Snapshot = {
      ...snapshot(),
      workspaces: [{ ...workspace, members: [...workspace.members, ...historicalMembers] }],
      workspace_channels: [workspaceChannel],
      workspace_join_requests: [],
      workspace_invitations: [],
      workspace_drafts: [],
    };
    api.runtimePlatform.mockResolvedValue("desktop");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);
    api.serviceCommand.mockImplementation(async (command: string) => {
      if (command === "snapshot") return current;
      if (command === "list_workspace_messages") return { messages: [], next_cursor: null, high_water: 0 } satisfies WorkspaceMessagePage;
      return {};
    });

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Workspace Lakewatcher" }));
    expect(await screen.findByRole("button", { name: "Invite people to Lakewatcher" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Invite people" })).toBeTruthy();
  });

  it("exposes owner administration, name requests, and explicit propagation consent", async () => {
    const member = {
      id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      display_name: "Bailey",
      role: "member" as const,
      status: "active" as const,
      short_id: "aaaaaa",
      device: { id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", destination_hash: "88".repeat(16), fingerprint: "BBBB CCCC DDDD EEEE" },
    };
    const expanded = { ...workspace, members: [...workspace.members, member] };
    const current: Snapshot = {
      ...snapshot(),
      workspaces: [expanded],
      workspace_channels: [workspaceChannel],
      workspace_join_requests: [],
      workspace_display_name_requests: [{ id: "name-request", workspace_id: workspace.id, manifest_digest: workspace.manifest_hash, member_id: member.id, device_id: member.device.id, display_name: "River lead", state: "pending", created_at: 12 }],
      workspace_invitations: [],
      workspace_drafts: [],
    };
    api.runtimePlatform.mockResolvedValue("desktop");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);
    api.serviceCommand.mockImplementation(async (command: string) => {
      if (command === "snapshot") return current;
      if (command === "list_workspace_messages") return { messages: [], next_cursor: null, high_water: 0 } satisfies WorkspaceMessagePage;
      return {};
    });

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Workspace Lakewatcher" }));
    fireEvent.click(await screen.findByRole("button", { name: "People in Lakewatcher" }));
    let dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(api.serviceCommand).toHaveBeenCalledWith("decide_workspace_display_name", expect.objectContaining({ workspace_id: workspace.id, request_id: "name-request", approve: true, operation_id: expect.any(String) })));
    fireEvent.click(within(dialog).getByRole("button", { name: /Remove/i }));
    await waitFor(() => expect(api.serviceCommand).toHaveBeenCalledWith("remove_workspace_member", expect.objectContaining({ workspace_id: workspace.id, member_id: member.id, operation_id: expect.any(String) })));
    const ownName = within(dialog).getByRole("textbox", { name: "Your workspace display name" });
    fireEvent.change(ownName, { target: { value: "Alex North" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Request name change" }));
    await waitFor(() => expect(api.serviceCommand).toHaveBeenCalledWith("request_workspace_display_name", expect.objectContaining({ workspace_id: workspace.id, display_name: "Alex North", operation_id: expect.any(String) })));
    fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));

    fireEvent.click(await screen.findByRole("button", { name: "Lakewatcher settings" }));
    dialog = screen.getByRole("dialog");
    const node = within(dialog).getByRole("textbox", { name: "Propagation-node address" });
    fireEvent.change(node, { target: { value: "ab".repeat(16) } });
    expect((within(dialog).getByRole("button", { name: "Approve node" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /I approve this node/i }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Approve node" }));
    await waitFor(() => expect(api.serviceCommand).toHaveBeenCalledWith("update_settings", { settings: expect.objectContaining({ approved_propagation_nodes: ["ab".repeat(16)] }) }));
  });

  it("shows per-person workspace delivery states without exposing transport addresses", async () => {
    const message: WorkspaceMessage = {
      id: "delivery-message",
      workspace_id: workspace.id,
      conversation_id: workspaceChannel.id,
      direction: "outbound",
      author_member_id: workspace.local_member_id,
      author_display_name: "Alex",
      text: "Fan out safely",
      sequence: 1,
      event_digest: "99".repeat(32),
      created_at: 1_791_072_021,
      delivery_summary: { people_total: 2, people_reached: 1, people_partial: 0, people_pending: 0, people_failed: 1, devices_total: 2, devices_reached: 1, devices_pending: 0, devices_failed: 0, devices_expired: 1, devices_cancelled: 0 },
      deliveries: [
        { member_id: "member-one", member_display_name: "Bailey", device_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", device_short_id: "aaaaaa", state: "received_by_endpoint" },
        { member_id: "member-two", member_display_name: "Casey", device_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", device_short_id: "bbbbbb", state: "expired" },
      ],
    };
    const current: Snapshot = { ...snapshot(), workspaces: [workspace], workspace_channels: [workspaceChannel], workspace_join_requests: [], workspace_invitations: [], workspace_drafts: [] };
    api.runtimePlatform.mockResolvedValue("desktop");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);
    api.serviceCommand.mockImplementation(async (command: string) => {
      if (command === "snapshot") return current;
      if (command === "list_workspace_messages") return { messages: [message], next_cursor: null, high_water: 1 } satisfies WorkspaceMessagePage;
      return {};
    });

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Workspace Lakewatcher" }));
    const conversation = await screen.findByLabelText("Workspace channel general");
    fireEvent.click(await within(conversation).findByText(/Reached 1 of 2 people/i));
    expect(within(conversation).getByText("Bailey · device aaaaaa")).toBeTruthy();
    expect(within(conversation).getByText("Casey · device bbbbbb")).toBeTruthy();
    expect(within(conversation).getByText("Expired")).toBeTruthy();
    expect(conversation.textContent).not.toContain("destination");
  });

  it("browses an incomplete public directory, disambiguates duplicates, and invokes sync and subscription actions", async () => {
    const member = {
      id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      display_name: "Bailey",
      role: "member" as const,
      status: "active" as const,
      short_id: "aaaaaa",
      device: { id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", destination_hash: "99".repeat(16), fingerprint: "BBBB CCCC DDDD EEEE" },
    };
    const memberWorkspace: Workspace = { ...workspace, local_role: "member", local_member_id: member.id, local_device_id: member.device.id, channel_discovery: "incomplete", members: [...workspace.members, member] };
    const duplicateChannels: WorkspaceChannel[] = [
      { ...workspaceChannel, id: "55555555-5555-4555-8555-555555555555", name: "Ops", name_key: "ops", display_name: "Ops · 555555", short_id: "555555", is_general: false, subscribed: false, duplicate_name: true, topic: "North team" },
      { ...workspaceChannel, id: "66666666-6666-4666-8666-666666666666", name: "ops", name_key: "ops", display_name: "ops · 666666", short_id: "666666", is_general: false, subscribed: false, duplicate_name: true, topic: "South team" },
    ];
    const created = { ...duplicateChannels[0], id: "77777777-7777-4777-8777-777777777777", name: "Field notes", name_key: "field notes", display_name: "Field notes", short_id: "777777", duplicate_name: false, subscribed: true };
    const current: Snapshot = { ...snapshot(), workspaces: [memberWorkspace], workspace_channels: [workspaceChannel, ...duplicateChannels], workspace_channel_transfers: [], workspace_join_requests: [], workspace_invitations: [], workspace_drafts: [] };
    api.runtimePlatform.mockResolvedValue("desktop");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);
    api.serviceCommand.mockImplementation(async (command: string) => {
      if (command === "snapshot") return current;
      if (command === "list_workspace_messages") return { messages: [], next_cursor: null, high_water: 0 } satisfies WorkspaceMessagePage;
      if (command === "create_workspace_channel") return created;
      return {};
    });

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Workspace Lakewatcher" }));
    fireEvent.click(await screen.findByRole("button", { name: /Browse channels/ }));
    let dialog = screen.getByRole("dialog", { name: "Browse channels in Lakewatcher" });
    expect(within(dialog).getByText(/Directory may be incomplete/i)).toBeTruthy();
    expect(within(dialog).getByText("Ops · 555555")).toBeTruthy();
    expect(within(dialog).getByText("ops · 666666")).toBeTruthy();
    fireEvent.click(within(dialog).getAllByRole("button", { name: "Subscribe" })[0]);
    await waitFor(() => expect(api.serviceCommand).toHaveBeenCalledWith("set_workspace_channel_subscription", expect.objectContaining({ workspace_id: workspace.id, channel_id: duplicateChannels[0].id, subscribed: true, operation_id: expect.any(String) })));
    fireEvent.click(within(dialog).getByRole("button", { name: "Sync directory" }));
    await waitFor(() => expect(api.serviceCommand).toHaveBeenCalledWith("sync_workspace_channels", expect.objectContaining({ workspace_id: workspace.id, operation_id: expect.any(String) })));
    fireEvent.click(within(dialog).getByRole("button", { name: "Create channel" }));
    dialog = await screen.findByRole("dialog", { name: "Create a channel" });
    fireEvent.change(within(dialog).getByRole("textbox", { name: "Channel name" }), { target: { value: "Field notes" } });
    fireEvent.change(within(dialog).getByRole("textbox", { name: /Topic/ }), { target: { value: "Daily observations" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Create public channel" }));
    await waitFor(() => expect(api.serviceCommand).toHaveBeenCalledWith("create_workspace_channel", expect.objectContaining({ workspace_id: workspace.id, name: "Field notes", topic: "Daily observations", operation_id: expect.any(String) })));
  });

  it("creates and manages a signed private-channel roster", async () => {
    const member = {
      id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      display_name: "Bailey",
      role: "member" as const,
      status: "active" as const,
      short_id: "aaaaaa",
      device: { id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", destination_hash: "99".repeat(16), fingerprint: "BBBB CCCC DDDD EEEE" },
    };
    const withMember: Workspace = { ...workspace, members: [...workspace.members, member] };
    const privateChannel: WorkspaceChannel = {
      ...workspaceChannel,
      id: "77777777-7777-4777-8777-777777777777",
      name: "incident-room",
      name_key: "incident-room",
      display_name: "incident-room",
      short_id: "777777",
      topic: "Need to know",
      visibility: "private",
      member_ids: [workspace.local_member_id, member.id].sort(),
      is_general: false,
      manager_member_id: workspace.local_member_id,
      manager_device_id: workspace.local_device_id,
    };
    const current: Snapshot = { ...snapshot(), workspaces: [withMember], workspace_channels: [workspaceChannel, privateChannel], workspace_join_requests: [], workspace_invitations: [], workspace_drafts: [] };
    api.runtimePlatform.mockResolvedValue("desktop");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);
    api.serviceCommand.mockImplementation(async (command: string) => {
      if (command === "snapshot") return current;
      if (command === "list_workspace_messages") return { messages: [], next_cursor: null, high_water: 0 } satisfies WorkspaceMessagePage;
      if (command === "create_workspace_channel") return privateChannel;
      return privateChannel;
    });

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Workspace Lakewatcher" }));
    fireEvent.click(await screen.findByRole("button", { name: "Create channel" }));
    let dialog = screen.getByRole("dialog", { name: "Create a channel" });
    fireEvent.change(within(dialog).getByRole("combobox", { name: "Visibility" }), { target: { value: "private" } });
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /Bailey/ }));
    fireEvent.change(within(dialog).getByRole("textbox", { name: "Channel name" }), { target: { value: "incident-room" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Create private channel" }));
    await waitFor(() => expect(api.serviceCommand).toHaveBeenCalledWith("create_workspace_channel", expect.objectContaining({ workspace_id: workspace.id, visibility: "private", member_ids: expect.arrayContaining([workspace.local_member_id, member.id]), operation_id: expect.any(String) })));

    const conversation = await screen.findByLabelText("Workspace channel incident-room");
    expect(within(conversation).getByText(/signed roster receives/i)).toBeTruthy();
    fireEvent.click(within(conversation).getByRole("button", { name: "Manage incident-room channel" }));
    dialog = screen.getByRole("dialog", { name: "Manage #incident-room" });
    expect(within(dialog).getByText("Private roster")).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /Bailey/ }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Publish roster change" }));
    await waitFor(() => expect(api.serviceCommand).toHaveBeenCalledWith("update_workspace_private_channel_members", expect.objectContaining({ workspace_id: workspace.id, channel_id: privateChannel.id, member_ids: [workspace.local_member_id], operation_id: expect.any(String) })));
  });

  it("hides disallowed owner-only controls, blocks posting, and permits only a named transfer acceptance", async () => {
    const member = {
      id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      display_name: "Bailey",
      role: "member" as const,
      status: "active" as const,
      short_id: "aaaaaa",
      device: { id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", destination_hash: "99".repeat(16), fingerprint: "BBBB CCCC DDDD EEEE" },
    };
    const restricted: Workspace = { ...workspace, local_role: "member", local_member_id: member.id, local_device_id: member.device.id, policies: { ...workspace.policies, channel_creation: "owner_and_admins", posting: "owner_and_admins" }, members: [...workspace.members, member] };
    const managed: WorkspaceChannel = { ...workspaceChannel, id: "55555555-5555-4555-8555-555555555555", name: "field-reports", name_key: "field-reports", display_name: "field-reports", short_id: "555555", is_general: false, subscribed: true, manager_member_id: workspace.local_member_id, manager_device_id: workspace.local_device_id };
    const current: Snapshot = {
      ...snapshot(),
      workspaces: [restricted],
      workspace_channels: [{ ...workspaceChannel, manager_member_id: workspace.local_member_id, manager_device_id: workspace.local_device_id }, managed],
      workspace_channel_transfers: [{ id: "transfer-local", workspace_id: workspace.id, channel_id: managed.id, channel_head: managed.head_hash, manifest_digest: workspace.manifest_hash, manager_member_id: workspace.local_member_id, successor_member_id: member.id, successor_device_id: member.device.id, state: "offered", created_at: 10, expires_at: 2_000_000_000 }],
      workspace_join_requests: [], workspace_invitations: [], workspace_drafts: [],
    };
    api.runtimePlatform.mockResolvedValue("desktop");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);
    api.serviceCommand.mockImplementation(async (command: string) => {
      if (command === "snapshot") return current;
      if (command === "list_workspace_messages") return { messages: [], next_cursor: null, high_water: 0 } satisfies WorkspaceMessagePage;
      return {};
    });

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Workspace Lakewatcher" }));
    expect(await screen.findByText("Only the workspace owner can post under the current signed policy.")).toBeTruthy();
    expect(screen.queryByRole("textbox", { name: "Message general" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Create channel" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Browse channels/ }));
    const browse = screen.getByRole("dialog", { name: "Browse channels in Lakewatcher" });
    expect(within(browse).queryByRole("button", { name: "Create channel" })).toBeNull();
    fireEvent.click(within(browse).getAllByRole("button", { name: "Open" })[1]);
    const conversation = await screen.findByLabelText("Workspace channel field-reports");
    expect(within(conversation).getByText("Only the workspace owner can post under the current signed policy.")).toBeTruthy();
    fireEvent.click(within(conversation).getByRole("button", { name: "Manage field-reports channel" }));
    const manage = screen.getByRole("dialog", { name: "Manage #field-reports" });
    expect(within(manage).queryByRole("button", { name: "Publish channel update" })).toBeNull();
    expect(within(manage).queryByRole("button", { name: /Archive channel/ })).toBeNull();
    fireEvent.click(within(manage).getByRole("button", { name: "Accept management" }));
    await waitFor(() => expect(api.serviceCommand).toHaveBeenCalledWith("accept_workspace_channel_transfer", expect.objectContaining({ workspace_id: workspace.id, transfer_id: "transfer-local", operation_id: expect.any(String) })));
    expect(api.serviceCommand).not.toHaveBeenCalledWith("create_workspace_channel", expect.anything());
    expect(api.serviceCommand).not.toHaveBeenCalledWith("send_workspace_message", expect.anything());
  });

  it("exposes manager update, transfer, terminal archive, and owner recovery commands", async () => {
    const member = {
      id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      display_name: "Bailey",
      role: "member" as const,
      status: "active" as const,
      short_id: "aaaaaa",
      device: { id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", destination_hash: "99".repeat(16), fingerprint: "BBBB CCCC DDDD EEEE" },
    };
    const expanded: Workspace = { ...workspace, members: [...workspace.members, member] };
    const channel: WorkspaceChannel = { ...workspaceChannel, id: "55555555-5555-4555-8555-555555555555", name: "field-reports", name_key: "field-reports", display_name: "field-reports", short_id: "555555", is_general: false, subscribed: true, topic: "Daily notes" };
    let current: Snapshot = { ...snapshot(), workspaces: [expanded], workspace_channels: [workspaceChannel, channel], workspace_channel_transfers: [], workspace_join_requests: [], workspace_invitations: [], workspace_drafts: [] };
    api.runtimePlatform.mockResolvedValue("desktop");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);
    api.serviceCommand.mockImplementation(async (command: string, payload: Record<string, unknown>) => {
      if (command === "snapshot") return current;
      if (command === "list_workspace_messages") return { messages: [], next_cursor: null, high_water: 0 } satisfies WorkspaceMessagePage;
      if (command === "update_workspace_channel") return { ...channel, name: String(payload.name), topic: String(payload.topic), state: payload.archived ? "archived" : "active" };
      return {};
    });

    const view = render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Workspace Lakewatcher" }));
    fireEvent.click(await screen.findByRole("button", { name: /field-reports/ }));
    const conversation = await screen.findByLabelText("Workspace channel field-reports");
    fireEvent.click(within(conversation).getByRole("button", { name: "Manage field-reports channel" }));
    let dialog = screen.getByRole("dialog", { name: "Manage #field-reports" });
    fireEvent.change(within(dialog).getByRole("textbox", { name: "Channel name" }), { target: { value: "field-updates" } });
    fireEvent.change(within(dialog).getByRole("textbox", { name: "Topic" }), { target: { value: "Validated notes" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Publish channel update" }));
    await waitFor(() => expect(api.serviceCommand).toHaveBeenCalledWith("update_workspace_channel", expect.objectContaining({ workspace_id: workspace.id, channel_id: channel.id, name: "field-updates", topic: "Validated notes", archived: false, operation_id: expect.any(String) })));
    fireEvent.change(within(dialog).getByRole("combobox", { name: "Successor manager" }), { target: { value: member.id } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Offer transfer" }));
    await waitFor(() => expect(api.serviceCommand).toHaveBeenCalledWith("offer_workspace_channel_transfer", expect.objectContaining({ workspace_id: workspace.id, channel_id: channel.id, successor_member_id: member.id, operation_id: expect.any(String) })));
    fireEvent.click(within(dialog).getByRole("button", { name: "Archive channel…" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm archive" }));
    await waitFor(() => expect(api.serviceCommand).toHaveBeenCalledWith("update_workspace_channel", expect.objectContaining({ workspace_id: workspace.id, channel_id: channel.id, archived: true, operation_id: expect.any(String) })));

    view.unmount();
    current = { ...current, workspace_channels: [workspaceChannel, { ...channel, manager_member_id: member.id, manager_device_id: member.device.id }] };
    api.initializeService.mockResolvedValue(current);
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Workspace Lakewatcher" }));
    fireEvent.click(await screen.findByRole("button", { name: /field-reports/ }));
    fireEvent.click(within(await screen.findByLabelText("Workspace channel field-reports")).getByRole("button", { name: "Manage field-reports channel" }));
    dialog = screen.getByRole("dialog", { name: "Manage #field-reports" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Recover to owner" }));
    await waitFor(() => expect(api.serviceCommand).toHaveBeenCalledWith("recover_workspace_channel", expect.objectContaining({ workspace_id: workspace.id, channel_id: channel.id, operation_id: expect.any(String) })));
  });

  it("opens mentioned threads, persists reply drafts, marks read, and resumes from Threads", async () => {
    const member = {
      id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      display_name: "Bailey",
      role: "member" as const,
      status: "active" as const,
      short_id: "aaaaaa",
      device: { id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", destination_hash: "99".repeat(16), fingerprint: "BBBB CCCC DDDD EEEE" },
    };
    const root: WorkspaceMessage = {
      id: "78787878-7878-4878-8878-787878787878",
      workspace_id: workspace.id,
      conversation_id: workspaceChannel.id,
      direction: "inbound",
      author_member_id: member.id,
      author_display_name: member.display_name,
      text: "Inspect the north relay",
      reply_count: 1,
      thread_unread_count: 1,
      sequence: 1,
      event_digest: "ab".repeat(32),
      created_at: 1_791_072_030,
    };
    const reply: WorkspaceMessage = {
      ...root,
      id: "89898989-8989-4989-8989-898989898989",
      text: "@Alex the relay is stable",
      mention_member_ids: [workspace.local_member_id],
      thread_root: root.id,
      thread_position: 1,
      sequence: 2,
      event_digest: "cd".repeat(32),
      created_at: 1_791_072_040,
    };
    const expanded: Workspace = { ...workspace, members: [...workspace.members, member], mention_unread_count: 1, thread_unread_count: 1 };
    let current: Snapshot = { ...snapshot(), workspaces: [expanded], workspace_channels: [workspaceChannel], workspace_join_requests: [], workspace_invitations: [], workspace_drafts: [] };
    const threadPage: WorkspaceThreadPage = {
      root,
      replies: [reply],
      next_cursor: null,
      high_water: 1,
      unread_count: 1,
      conversation: { id: workspaceChannel.id, kind: "channel", name: "general", visibility: "public", state: "active" },
    };
    const activityPage: WorkspaceThreadActivityPage = {
      threads: [{ root, conversation: threadPage.conversation, reply_count: 1, unread_count: 1, high_water: 1, updated_at: reply.created_at }],
      next_cursor: null,
      high_water: 1,
      unread_count: 1,
    };
    const mentionPage: WorkspaceMentionPage = {
      mentions: [{ position: 1, read: false, conversation: { id: workspaceChannel.id, kind: "channel", name: "general", visibility: "public" }, message: reply, thread_root_id: root.id }],
      next_cursor: null,
      high_water: 1,
      unread_count: 1,
    };
    api.runtimePlatform.mockResolvedValue("desktop");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);
    api.serviceCommand.mockImplementation(async (command: string, payload: Record<string, unknown>) => {
      if (command === "snapshot") return current;
      if (command === "list_workspace_messages") return { messages: [root], next_cursor: null, high_water: 1 } satisfies WorkspaceMessagePage;
      if (command === "list_workspace_thread_messages") return threadPage;
      if (command === "list_workspace_threads") return activityPage;
      if (command === "list_workspace_mentions") return mentionPage;
      if (command === "mark_workspace_thread_read") {
        current = { ...current, workspaces: [{ ...expanded, thread_unread_count: 0 }] };
        return { workspace_id: workspace.id, thread_root_id: root.id, high_water: 1, unread_count: 0 };
      }
      if (command === "send_workspace_thread_reply") return { ...reply, id: String(payload.event_id), direction: "outbound", author_member_id: workspace.local_member_id, author_display_name: "Alex", text: String(payload.text), mention_member_ids: payload.mention_member_ids as string[], sequence: 3 } satisfies WorkspaceMessage;
      return {};
    });

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Workspace Lakewatcher" }));
    const conversation = await screen.findByLabelText("Workspace channel general");
    fireEvent.click(within(conversation).getByRole("button", { name: /Thread · 1 · 1 new/ }));
    const thread = await screen.findByLabelText("Thread in Lakewatcher");
    expect(within(thread).getByText("Original message")).toBeTruthy();
    expect(within(thread).getByText("@Alex the relay is stable")).toBeTruthy();
    await waitFor(() => expect(api.serviceCommand).toHaveBeenCalledWith("mark_workspace_thread_read", expect.objectContaining({ workspace_id: workspace.id, thread_root_id: root.id, high_water: 1, operation_id: expect.any(String) })));

    const composer = within(thread).getByRole("textbox", { name: "Reply in thread" });
    fireEvent.change(composer, { target: { value: "Thread reply after restart" } });
    await waitFor(() => expect(api.serviceCommand).toHaveBeenCalledWith("save_workspace_thread_draft", expect.objectContaining({ workspace_id: workspace.id, conversation_id: workspaceChannel.id, thread_root_id: root.id, text: "Thread reply after restart", operation_id: expect.any(String) })));
    fireEvent.click(within(thread).getByRole("button", { name: "Send thread reply" }));
    await waitFor(() => expect(api.serviceCommand).toHaveBeenCalledWith("send_workspace_thread_reply", expect.objectContaining({ workspace_id: workspace.id, conversation_id: workspaceChannel.id, thread_root_id: root.id, text: "Thread reply after restart", event_id: expect.any(String), operation_id: expect.any(String) })));

    fireEvent.click(screen.getByRole("button", { name: /Threads/ }));
    const threads = await screen.findByLabelText("Threads in Lakewatcher");
    expect(within(threads).getByText("1 reply")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Mentions/ }));
    const mentions = await screen.findByLabelText("Mentions in Lakewatcher");
    fireEvent.click(within(mentions).getByRole("button", { name: /@Alex the relay is stable/ }));
    expect(await screen.findByLabelText("Thread in Lakewatcher")).toBeTruthy();
  });

  it("publishes cooperative retention and runs a bounded local prune", async () => {
    const current: Snapshot = { ...snapshot(), workspaces: [workspace], workspace_channels: [workspaceChannel], workspace_join_requests: [], workspace_invitations: [], workspace_drafts: [] };
    api.runtimePlatform.mockResolvedValue("desktop");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);
    api.serviceCommand.mockImplementation(async (command: string) => {
      if (command === "snapshot" || command === "workspace_snapshot") return current;
      if (command === "list_workspace_messages") return { messages: [], next_cursor: null, high_water: 0, history_status: "complete", pruned_count: 0, permanent_gaps: [] } satisfies WorkspaceMessagePage;
      if (command === "prune_workspace_history") return { workspace_id: workspace.id, status: "running", scanned: 500, pruned: 480, scanned_this_batch: 500, pruned_this_batch: 480, needs_more: true, retention_generation: 3, cutoff: 1_700_000_000 };
      return {};
    });

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Workspace Lakewatcher" }));
    fireEvent.click(await screen.findByRole("button", { name: "History & retention" }));
    const dialog = screen.getByRole("dialog", { name: "History & retention" });
    expect(within(dialog).getByText(/cannot remotely delete plaintext, exports, or backups/i)).toBeTruthy();
    fireEvent.change(within(dialog).getByRole("combobox", { name: "Cooperative retention" }), { target: { value: "30" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Publish signed retention update" }));
    await waitFor(() => expect(api.serviceCommand).toHaveBeenCalledWith("update_workspace_retention", expect.objectContaining({ workspace_id: workspace.id, retention_days: 30, operation_id: expect.any(String) })));
    fireEvent.click(within(dialog).getByRole("button", { name: "Prune local history now" }));
    await waitFor(() => expect(api.serviceCommand).toHaveBeenCalledWith("prune_workspace_history", expect.objectContaining({ workspace_id: workspace.id, max_events: 500, operation_id: expect.any(String) })));
    expect(await within(dialog).findByText(/480 events removed · 500 checked/i)).toBeTruthy();
  });

  it("shows permanent gaps plus bounded revision and deletion history", async () => {
    const message: WorkspaceMessage = {
      id: "98989898-9898-4989-8989-989898989898",
      workspace_id: workspace.id,
      conversation_id: workspaceChannel.id,
      direction: "inbound",
      author_member_id: workspace.local_member_id,
      author_display_name: "Alex",
      text: "Corrected retained field note",
      revision: 2,
      sequence: 5,
      event_digest: "ef".repeat(32),
      created_at: 1_791_072_050,
    };
    const current: Snapshot = { ...snapshot(), workspaces: [workspace], workspace_channels: [workspaceChannel], workspace_join_requests: [], workspace_invitations: [], workspace_drafts: [] };
    api.runtimePlatform.mockResolvedValue("desktop");
    api.initializeService.mockResolvedValue(current);
    api.onInvitation.mockResolvedValue(() => undefined);
    api.onServiceEvent.mockResolvedValue(() => undefined);
    api.serviceCommand.mockImplementation(async (command: string) => {
      if (command === "snapshot") return current;
      if (command === "list_workspace_messages") return { messages: [message], next_cursor: null, high_water: 9, history_status: "permanent_gap", pruned_count: 4, permanent_gaps: [{ start: 1, end: 4, reason: "pruned" }] } satisfies WorkspaceMessagePage;
      if (command === "list_workspace_message_revisions") return { message, revisions: [{ event_id: "edit-one", event_type: "edit", revision: 1, author_member_id: workspace.local_member_id, created_at: 1_791_072_040, text: "Earlier retained note" }], next_cursor: null, high_water: 1, history_status: "pruned" };
      if (command === "list_workspace_tombstones") return { tombstones: [{ position: 1, deleted_at: 1_791_072_045, message: { ...message, id: "deleted-one", text: "", deleted: true } }], next_cursor: null, high_water: 1, history_status: "pruned" };
      return {};
    });

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Workspace Lakewatcher" }));
    const conversation = await screen.findByLabelText("Workspace channel general");
    expect(within(conversation).getByText(/permanently unavailable/i)).toBeTruthy();
    fireEvent.click(within(conversation).getByRole("button", { name: "Inspect revisions for message from Alex" }));
    let dialog = await screen.findByRole("dialog", { name: "Message history" });
    expect(within(dialog).getByText("Earlier retained note")).toBeTruthy();
    expect(within(dialog).getByText(/Earlier revisions were pruned/i)).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    fireEvent.click(within(conversation).getByRole("button", { name: "Deleted messages in general" }));
    dialog = await screen.findByRole("dialog", { name: "Deleted-message history" });
    expect(within(dialog).getByText(/Message deleted by its author/i)).toBeTruthy();
    expect(within(dialog).getByText(/Older tombstones were safely pruned/i)).toBeTruthy();
  });
});

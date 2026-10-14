import { afterEach, describe, expect, it, vi } from "vitest";

const tauri = vi.hoisted(() => ({
  invoke: vi.fn(),
  listen: vi.fn(async () => () => undefined),
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

import { onInvitation } from "./api";

afterEach(() => {
  vi.useRealTimers();
  vi.clearAllMocks();
});

describe("Android invitation ingress", () => {
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

import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ConnectionStatus } from "./ConnectionStatus";
import { rememberWebRTCDiagnostics } from "./webrtc-diagnostics";

afterEach(() => { cleanup(); rememberWebRTCDiagnostics(""); vi.unstubAllGlobals(); });

function setup(pendingCount = 0) {
  const actions = { onReview: vi.fn(), onReconnect: vi.fn(async () => {}), onDisconnect: vi.fn(async () => {}) };
  render(<ConnectionStatus count={1} path="relayed" pendingCount={pendingCount} {...actions} />);
  return actions;
}

describe("compact connection status", () => {
  it("keeps healthy status compact and preserves explicit connection actions", async () => {
    const actions = setup();
    const summary = screen.getByRole("button", { name: /Connected · Relayed/ });
    expect(summary.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByRole("button", { name: "Disconnect" })).toBeNull();
    fireEvent.click(summary);
    expect(summary.getAttribute("aria-expanded")).toBe("true");
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Reconnect" })));
    expect(actions.onReconnect).toHaveBeenCalledTimes(1);
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Disconnect" })));
    expect(actions.onDisconnect).toHaveBeenCalledTimes(1);
  });

  it("keeps pending contact approvals actionable", () => {
    const actions = setup(2);
    expect(screen.getByText("2 contact requests awaiting approval.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Review request" }));
    expect(actions.onReview).toHaveBeenCalledTimes(1);
  });

  it("confirms copying diagnostics and explains missing or denied clipboard access", async () => {
    const writeText = vi.fn(async () => {});
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    setup();
    fireEvent.click(screen.getByRole("button", { name: /Connected · Relayed/ }));
    const copy = screen.getByRole("button", { name: "Copy diagnostics" });
    fireEvent.click(copy);
    expect(screen.getByText("No diagnostics available yet.")).toBeTruthy();
    expect(writeText).not.toHaveBeenCalled();
    rememberWebRTCDiagnostics("sanitized diagnostics");
    await act(async () => fireEvent.click(copy));
    expect(writeText).toHaveBeenCalledWith("sanitized diagnostics");
    expect(screen.getByText("Diagnostics copied.")).toBeTruthy();
    writeText.mockRejectedValueOnce(new Error("Denied"));
    await act(async () => fireEvent.click(copy));
    expect(screen.getByText("Could not copy diagnostics. Try again.")).toBeTruthy();
  });
});

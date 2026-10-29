import { useEffect, useState } from "react";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { WorkspaceSettingsPage, type WorkspaceSettingsSection } from "./WorkspaceSettingsPage";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

function Draft({ mounted }: { mounted: () => void }) {
  const [value, setValue] = useState("Original name");
  useEffect(mounted, [mounted]);
  return <label>Workspace name<input value={value} onChange={event => setValue(event.target.value)} /></label>;
}
function Harness({ close, mounted, busy = false, register }: { close: () => void; mounted: () => void; busy?: boolean; register?: (handler: (() => void) | null) => void }) {
  const [section, setSection] = useState<WorkspaceSettingsSection>("general");
  return <WorkspaceSettingsPage name="Test team" role="owner" section={section} busy={busy} pendingRequests={2} pendingDevices={1} pendingAuthority={1}
    onSelect={setSection} onClose={close} onBackHandlerChange={register} panels={{
      general: <Draft mounted={mounted} />, people: <p>Member administration</p>, history: <label>Retention<select defaultValue="90"><option>30</option><option>90</option></select></label>,
      devices: <p>My devices</p>, authority: <p>Transfer ownership</p>, access: <p>Access approval</p>, connections: <p>Connection recovery</p>,
    }} />;
}

describe("consolidated workspace settings", () => {
  it("keeps drafts across sections and mounts each section only when visited", () => {
    const mounted = vi.fn();
    render(<Harness close={vi.fn()} mounted={mounted} />);
    expect(screen.queryByLabelText("Retention")).toBeNull();
    fireEvent.change(screen.getByLabelText("Workspace name"), { target: { value: "New team name" } });
    fireEvent.click(screen.getByRole("button", { name: /^History & retention/ }));
    fireEvent.change(screen.getByLabelText("Retention"), { target: { value: "30" } });
    expect(screen.queryByRole("textbox", { name: "Workspace name" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /^General/ }));
    expect((screen.getByLabelText("Workspace name") as HTMLInputElement).value).toBe("New team name");
    fireEvent.click(screen.getByRole("button", { name: /^History & retention/ }));
    expect((screen.getByLabelText("Retention") as HTMLSelectElement).value).toBe("30");
    expect(mounted).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("button", { name: /People.*2 pending/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Devices.*1 pending/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Ownership.*1 pending/ })).toBeTruthy();
  });

  it("routes Android Back from a section to the settings list, then out", () => {
    vi.stubGlobal("innerWidth", 393);
    const close = vi.fn(); let handler: (() => void) | null = null;
    const register = (next: (() => void) | null) => { handler = next; };
    render(<Harness close={close} mounted={vi.fn()} register={register} />);
    fireEvent.click(screen.getByRole("button", { name: /^People/ }));
    act(() => handler?.());
    expect(close).not.toHaveBeenCalled();
    expect(screen.getByRole("region", { name: "Workspace settings for Test team" }).className).toContain("--index");
    act(() => handler?.());
    expect(close).toHaveBeenCalledTimes(1);
  });

  it("prevents navigation and native Back while an administration action saves", () => {
    vi.stubGlobal("innerWidth", 1280);
    const close = vi.fn(); let handler: (() => void) | null = null;
    render(<Harness busy close={close} mounted={vi.fn()} register={next => { handler = next; }} />);
    expect((screen.getByRole("button", { name: /^People/ }) as HTMLButtonElement).disabled).toBe(true);
    act(() => handler?.());
    expect(close).not.toHaveBeenCalled();
    expect(screen.getByRole("status").textContent).toContain("Saving");
  });

  it("lets a foreground dialog handle Escape and restores focus on leaving", () => {
    vi.stubGlobal("innerWidth", 1280);
    const opener = document.createElement("button"); document.body.append(opener); opener.focus();
    const close = vi.fn();
    const view = render(<Harness close={close} mounted={vi.fn()} />);
    const dialog = document.createElement("div"); dialog.setAttribute("role", "dialog"); document.body.append(dialog);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(close).not.toHaveBeenCalled();
    dialog.remove();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(close).toHaveBeenCalledTimes(1);
    view.unmount();
    expect(document.activeElement).toBe(opener);
    opener.remove();
  });
});

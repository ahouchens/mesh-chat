import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
const host = vi.hoisted(() => ({ invoke: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({ invoke: host.invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen: vi.fn() }));
vi.mock("@tauri-apps/plugin-deep-link", () => ({ getCurrent: vi.fn(), onOpenUrl: vi.fn() }));
vi.mock("@tauri-apps/api/app", () => ({ onBackButtonPress: vi.fn() }));
import { CreateWorkspaceDialog } from "./CreateWorkspaceDialog";
import { ProfileLifetime, ProfileLifetimeContext } from "./profile-lifetime";

afterEach(() => { cleanup(); host.invoke.mockReset(); });

it("does not create a workspace when its old profile lookup completes after reopening", async () => {
  let resolve!: (value: unknown) => void;
  const profile = new Promise((finish) => { resolve = finish; });
  host.invoke.mockImplementation(async (command) => command === "core_api_profile" ? profile : {});
  const lifetime = new ProfileLifetime();
  const created = vi.fn(async () => undefined);
  render(<ProfileLifetimeContext.Provider value={lifetime}><CreateWorkspaceDialog onClose={() => undefined} onCreated={created} /></ProfileLifetimeContext.Provider>);
  fireEvent.change(screen.getByRole("textbox", { name: "Workspace name" }), { target: { value: "Original workspace" } });
  fireEvent.click(screen.getByRole("button", { name: "Create workspace" }));
  await act(async () => {
    await lifetime.retire();
    lifetime.finishOpening(lifetime.beginOpening());
    resolve({ profile: "original-profile" });
  });
  expect(host.invoke.mock.calls.map(([command]) => command)).toEqual(["core_api_profile"]);
  expect(created).not.toHaveBeenCalled();
});

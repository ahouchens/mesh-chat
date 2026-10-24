import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { WorkspaceMessageMenu } from "./WorkspaceMessageMenu";

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

const actions = (onSelect = () => undefined) => [
  { id: "history", label: "History", icon: null, onSelect },
  { id: "edit", label: "Edit", icon: null, onSelect },
  { id: "hide", label: "Hide on this device", icon: null, onSelect },
];

describe("workspace message actions", () => {
  it("opens outside the scrolling message container, navigates by keyboard, and restores focus on Escape", () => {
    const { container } = render(<div style={{ overflow: "hidden" }}><WorkspaceMessageMenu authorName="Alex" actions={actions()} /></div>);
    const trigger = screen.getByRole("button", { name: "More actions for message from Alex" });
    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    const menu = screen.getByRole("menu", { name: "Actions for message from Alex" });
    expect(container.contains(menu)).toBe(false);
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    expect(document.activeElement).toBe(screen.getByRole("menuitem", { name: "History" }));
    fireEvent.keyDown(document.activeElement!, { key: "ArrowDown" });
    expect(document.activeElement).toBe(screen.getByRole("menuitem", { name: "Edit" }));
    fireEvent.keyDown(document.activeElement!, { key: "End" });
    expect(document.activeElement).toBe(screen.getByRole("menuitem", { name: "Hide on this device" }));
    fireEvent.keyDown(document.activeElement!, { key: "ArrowDown" });
    expect(document.activeElement).toBe(screen.getByRole("menuitem", { name: "History" }));
    const consumedEscape = new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true });
    consumedEscape.preventDefault();
    fireEvent(document, consumedEscape);
    expect(screen.getByRole("menu")).toBe(menu);
    fireEvent.keyDown(document.activeElement!, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
    expect(document.activeElement).toBe(trigger);
    fireEvent.keyDown(trigger, { key: "ArrowUp" });
    expect(document.activeElement).toBe(screen.getByRole("menuitem", { name: "Hide on this device" }));
    fireEvent.keyDown(document.activeElement!, { key: "Tab" });
    expect(screen.queryByRole("menu")).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it("closes after an action, outside pointer input, and a second trigger click", () => {
    const select = vi.fn();
    render(<><WorkspaceMessageMenu authorName="Alex" actions={actions(select)} /><button>Another control</button></>);
    const trigger = screen.getByRole("button", { name: "More actions for message from Alex" });
    fireEvent.click(trigger);
    fireEvent.pointerDown(screen.getByRole("menuitem", { name: "History" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "History" }));
    expect(select).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("menu")).toBeNull();
    expect(document.activeElement).toBe(trigger);
    fireEvent.click(trigger);
    fireEvent.pointerDown(screen.getByRole("button", { name: "Another control" }));
    expect(screen.queryByRole("menu")).toBeNull();
    fireEvent.click(trigger);
    trigger.focus();
    fireEvent.click(trigger);
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("keeps the menu inside a narrow viewport and dismisses it when the message list scrolls", () => {
    vi.stubGlobal("innerWidth", 320);
    vi.stubGlobal("innerHeight", 400);
    vi.stubGlobal("visualViewport", undefined);
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
      return this.classList.contains("workspace-message-menu-trigger")
        ? new DOMRect(290, 360, 30, 30) : new DOMRect(0, 0, 240, 190);
    });
    const { container } = render(<div><WorkspaceMessageMenu authorName="Alex" actions={actions()} /></div>);
    fireEvent.click(screen.getByRole("button", { name: "More actions for message from Alex" }));
    const menu = screen.getByRole("menu");
    const left = parseFloat(menu.style.left);
    const top = parseFloat(menu.style.top);
    expect(left).toBeGreaterThanOrEqual(8);
    expect(left + 240).toBeLessThanOrEqual(312);
    expect(top).toBeGreaterThanOrEqual(8);
    expect(top + 190).toBeLessThanOrEqual(392);
    fireEvent.scroll(container.firstElementChild!);
    expect(screen.queryByRole("menu")).toBeNull();
  });
});

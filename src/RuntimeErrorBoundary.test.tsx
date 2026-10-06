import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import RuntimeErrorBoundary from "./RuntimeErrorBoundary";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

it("keeps a visible recovery screen when a child renderer fails", () => {
  vi.spyOn(console, "error").mockImplementation(() => undefined);
  const Broken = () => {
    throw new Error("test renderer failure");
  };

  render(
    <RuntimeErrorBoundary>
      <Broken />
    </RuntimeErrorBoundary>,
  );

  expect(screen.getByRole("heading", { name: "Mesh Chat needs to reload" })).toBeTruthy();
  expect(screen.getByText("Your profile, contacts, and saved messages are safe.")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Reload Mesh Chat" })).toBeTruthy();
});

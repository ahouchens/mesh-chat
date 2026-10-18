import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
const api = vi.hoisted(() => ({ serviceCommand: vi.fn(), appBuildInfo: vi.fn() }));
vi.mock("./api", () => api);
import { ConnectionDiagnostics, diagnosticReport, versionDetails } from "./ConnectionDiagnostics";
import packageInfo from "../package.json";
beforeEach(() => { api.serviceCommand.mockReset(); api.appBuildInfo.mockResolvedValue({ installed_version: packageInfo.version, native_version: packageInfo.version, platform: "android", android_version_code: 2050 }); });
afterEach(cleanup);

it("copies a bounded allowlisted log without seeded credentials or addresses", () => {
  const secret = "private-key-MESHWORKSPACE-192.0.2.1";
  const text = diagnosticReport({ platform: secret, build_commit: secret }, { format_version:1,
    text:secret, private_key:secret, events:Array.from({length:400}, () => ({ phase:secret, event:"state", kind:"offer", address:secret, attempt:secret })) }, true);
  expect(text).not.toContain(secret);
  expect(JSON.parse(text).events).toHaveLength(200);
  expect(new TextEncoder().encode(text).length).toBeLessThan(65536);
});

it("offers selectable diagnostics when clipboard and service are unavailable", async () => {
  api.serviceCommand.mockRejectedValue(new Error("secret-path"));
  Object.defineProperty(navigator, "clipboard", { configurable:true, value:{ writeText:vi.fn().mockRejectedValue(new Error("denied")) } });
  render(<ConnectionDiagnostics full />);
  fireEvent.click(screen.getByText("Copy diagnostics"));
  const box = await screen.findByLabelText("Diagnostic report") as HTMLTextAreaElement;
  expect(box.value).toContain(packageInfo.version);
  expect(box.value).toContain('"service_status": "unavailable"');
  expect(box.value).not.toContain("secret-path");
  expect(screen.getByText("Save diagnostics")).toBeTruthy();
  expect(screen.queryByText("Copied")).toBeNull();
  expect(api.serviceCommand).toHaveBeenCalledTimes(1);
});

it("confirms copy only after clipboard success and keeps Android installed metadata", async () => {
  let finish!: () => void;
  const write = vi.fn((_text: string) => new Promise<void>(resolve => { finish=resolve; }));
  Object.defineProperty(navigator, "clipboard", { configurable:true, value:{ writeText:write } });
  api.serviceCommand.mockResolvedValue({ format_version:1, service_version:packageInfo.version, events:[] });
  render(<ConnectionDiagnostics full />);
  await waitFor(() => expect(api.appBuildInfo).toHaveBeenCalled());
  fireEvent.click(screen.getByText("Copy version details"));
  await waitFor(() => expect(write).toHaveBeenCalled());
  expect(screen.queryByText("Copied")).toBeNull();
  finish();
  expect(await screen.findByText("Copied")).toBeTruthy();
  expect(JSON.parse(write.mock.calls[0][0] as string).android_version_code).toBe(2050);
});

it("reports component mismatch instead of relabeling an older native component", () => {
  const value = versionDetails({ installed_version:"0.1.0", native_version:"0.1.0", platform:"windows" });
  expect(value.version_mismatch).toBe(true);
  expect(value.native_version).toBe("0.1.0");
});

it("clears only diagnostic history", async () => {
  api.serviceCommand.mockResolvedValue({});
  render(<ConnectionDiagnostics full />);
  fireEvent.click(screen.getByText("Clear diagnostic history"));
  expect(await screen.findByText(/Diagnostic history cleared/)).toBeTruthy();
  expect(api.serviceCommand.mock.calls).toEqual([["clear_connection_diagnostics"]]);
});

import { expect, it, vi } from "vitest";
import { DesktopTransportProtocol } from "./desktop-transport-protocol";
import type { DesktopTransport } from "./desktop-transport";

const epoch = "a".repeat(32);
const request = (id: string, value: object) => ({ v: 1, type: "desktop_transport", epoch, id, request: value });
const options = { resource: "native-one", ice: { iceTransportPolicy: "relay" },
  channels: [{ label: "mesh-reticulum", binary: true, ordered: true }] };

function fixture() {
  const driver = {
    createOffer: vi.fn(async () => ({ sdp: "private", fingerprint: "bound" })),
    acceptOffer: vi.fn(async () => ({ sdp: "answer", fingerprint: "bound" })),
    applyAnswer: vi.fn(async () => {}), inspect: vi.fn(() => ({ data_channel_state: "open" })),
    send: vi.fn(() => true), sendControl: vi.fn(() => false), close: vi.fn(), closeAll: vi.fn(),
  };
  return { driver, protocol: new DesktopTransportProtocol(epoch, driver as unknown as DesktopTransport) };
}

it("translates the inherited native host contract without altering ICE policy", async () => {
  const { driver, protocol } = fixture();
  expect(await protocol.handle(request("1", { op: "createOffer", options }))).toEqual({
    v: 1, type: "desktop_transport_reply", epoch, id: "1", ok: true, result: { sdp: "private", fingerprint: "bound" },
  });
  expect(driver.createOffer).toHaveBeenCalledWith(options);
  await protocol.handle(request("2", { op: "send", resource: options.resource, packet: "AQI=" }));
  expect(driver.send).toHaveBeenCalledWith(options.resource, new Uint8Array([1, 2]));
  expect((await protocol.handle(request("3", { op: "sendControl", resource: options.resource,
    label: "meshchat-reconnect", text: "consent" }))).result).toBe(false);
});

it("rejects stale epochs and monotonic request replays before invoking the adapter", async () => {
  const { driver, protocol } = fixture();
  await expect(protocol.handle({ ...request("1", { op: "close", resource: "native-one" }), epoch: "b".repeat(32) })).rejects.toThrow("invalid_transport_frame");
  await protocol.handle(request("2", { op: "inspect", resource: "native-one" }));
  await expect(protocol.handle(request("1", { op: "close", resource: "native-one" }))).rejects.toThrow("transport_replay");
  await expect(protocol.handle(request("2", { op: "close", resource: "native-one" }))).rejects.toThrow("transport_replay");
  expect(driver.close).not.toHaveBeenCalled();
});

it.each([
  { op: "createOffer", options: { ...options, extra: "authority" } },
  { op: "close", resource: "native-one", extra: "scope" },
  { op: "send", resource: "native-one", packet: "!" },
  { op: "send", resource: "native-one", packet: btoa("x".repeat(1065)) },
  { op: "applyAnswer", resource: "native-one", answer: "x".repeat(65537) },
  { op: "sendControl", resource: "native-one", label: "media", text: "x" },
  { op: "inspect", resource: "unsafe/id" },
  { op: "dispatch", command: "contact_approve" },
])("rejects unsupported private payloads: %j", async (payload) => {
  const { driver, protocol } = fixture();
  expect(await protocol.handle(request("1", payload))).toMatchObject({ ok: false, result: null });
  expect(driver.createOffer).not.toHaveBeenCalled();
  expect(driver.close).not.toHaveBeenCalled();
  expect(driver.send).not.toHaveBeenCalled();
  expect(driver.applyAnswer).not.toHaveBeenCalled();
});

it("redacts driver errors and prevents allocation after reset", async () => {
  const { driver, protocol } = fixture();
  driver.createOffer.mockRejectedValueOnce(new Error("private SDP credential"));
  expect(await protocol.handle(request("1", { op: "createOffer", options }))).toMatchObject({ ok: false, result: null });
  expect(await protocol.handle(request("2", { op: "reset" }))).toMatchObject({ ok: true, result: null });
  expect(driver.closeAll).toHaveBeenCalledOnce();
  expect(await protocol.handle(request("3", { op: "createOffer", options }))).toMatchObject({ ok: false, result: null });
  expect(driver.createOffer).toHaveBeenCalledOnce();
});

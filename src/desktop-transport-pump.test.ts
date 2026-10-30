import { afterEach, expect, it, vi } from "vitest";
import { DesktopTransportPump } from "./desktop-transport-pump";
import type { DesktopTransport, TransportEvent } from "./desktop-transport";

const epoch = "a".repeat(32);
const request = (id = 1) => ({ v: 1, type: "desktop_transport", epoch, id: String(id), request: {
  op: "createOffer", options: { resource: `native-${id}`, ice: { iceTransportPolicy: "relay" },
    channels: [{ label: "mesh-reticulum", binary: true, ordered: true }] },
} });

function fixture(exchange = vi.fn(async (_frames: Record<string, unknown>[], _fault: boolean): Promise<unknown[]> => [])) {
  const driver = { createOffer: vi.fn(async () => ({ sdp: "sdp", fingerprint: "bound" })), closeAll: vi.fn() };
  let emit!: (event: TransportEvent) => boolean;
  const pump = new DesktopTransportPump(exchange, sink => {
    emit = sink;
    return driver as unknown as DesktopTransport;
  });
  return { pump, driver, exchange, emit };
}

async function settled() { for (let index = 0; index < 5; index++) await Promise.resolve(); }
afterEach(() => vi.useRealTimers());

it("routes private requests and keeps lifecycle admission independent of bulk packets", async () => {
  const { pump, driver, exchange, emit } = fixture();
  exchange.mockResolvedValueOnce([request()]);
  await pump.step();
  await settled();
  expect(driver.createOffer).toHaveBeenCalledOnce();
  const admitted = Array.from({ length: 300 }, () => emit({ event: "message", resource: "native-1", data: "AQI=" }));
  expect(admitted.filter(Boolean)).toHaveLength(256);
  expect(emit({ event: "ice", resource: "native-1", data: "connected" })).toBe(true);
  await pump.step();
  const frames = exchange.mock.calls[1][0];
  expect(frames).toHaveLength(64);
  expect(frames[0]).toMatchObject({ type: "desktop_transport_reply", epoch, id: "1", ok: true });
  expect(frames[1]).toMatchObject({ type: "desktop_transport_event", epoch, event: "ice" });
  expect(driver.closeAll).not.toHaveBeenCalled();
  pump.stop();
});

it("retires the host once when critical observation capacity is lost", async () => {
  const { pump, driver, exchange, emit } = fixture();
  exchange.mockResolvedValueOnce([request()]);
  await pump.step();
  for (let index = 0; index < 256; index++) expect(emit({ event: "ice", resource: "native-1", data: "checking" })).toBe(true);
  expect(emit({ event: "control", resource: "native-1", data: "revocation" })).toBe(false);
  expect(driver.closeAll).toHaveBeenCalledOnce();
  expect(exchange.mock.calls.at(-1)).toEqual([[], true]);
  await pump.step();
  pump.stop();
  expect(exchange).toHaveBeenCalledTimes(2);
});

it("times out a stalled private invoke and ignores its late commands", async () => {
  vi.useFakeTimers();
  const { pump, driver, exchange } = fixture();
  let finish!: (requests: unknown[]) => void;
  exchange.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  const pending = pump.step();
  await vi.advanceTimersByTimeAsync(5000);
  await pending;
  expect(driver.closeAll).toHaveBeenCalledOnce();
  expect(exchange.mock.calls.at(-1)).toEqual([[], true]);
  finish([request()]);
  await settled();
  expect(driver.createOffer).not.toHaveBeenCalled();
  expect(vi.getTimerCount()).toBe(0);
});

it("rejects a second simultaneous poll without opening another host call", async () => {
  const { pump, exchange } = fixture();
  let finish!: (requests: unknown[]) => void;
  exchange.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  const pending = pump.step();
  await expect(pump.step()).rejects.toThrow("transport_poll_in_progress");
  expect(exchange).toHaveBeenCalledOnce();
  finish([]);
  await pending;
  pump.stop();
});

it("quarantines replayed frames and bounds asynchronous adapter work", async () => {
  const first = fixture();
  first.exchange.mockResolvedValueOnce([request(), request()]);
  await first.pump.step();
  await settled();
  expect(first.driver.createOffer).toHaveBeenCalledOnce();
  expect(first.driver.closeAll).toHaveBeenCalledOnce();
  const second = fixture();
  second.driver.createOffer.mockImplementation(() => new Promise(() => {}));
  second.exchange.mockResolvedValueOnce(Array.from({ length: 16 }, (_, index) => request(index + 1)));
  await second.pump.step();
  second.exchange.mockResolvedValueOnce([request(17)]);
  await second.pump.step();
  expect(second.driver.createOffer).toHaveBeenCalledTimes(16);
  expect(second.driver.closeAll).toHaveBeenCalledOnce();
});

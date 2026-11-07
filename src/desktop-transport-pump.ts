import { DesktopTransport, type TransportEvent } from "./desktop-transport";
import { DesktopTransportProtocol } from "./desktop-transport-protocol";

type Frame = Record<string, unknown>;
type Exchange = (frames: Frame[], fault: boolean) => Promise<unknown[]>;
const size = (value: unknown) => new TextEncoder().encode(JSON.stringify(value)).length;

class Frames {
  private values: { frame: Frame; bytes: number }[] = [];
  private bytes = 0;
  constructor(private readonly countLimit: number, private readonly byteLimit: number) {}
  push(frame: Frame) {
    const bytes = size(frame);
    if (bytes > 256 * 1024 || this.values.length >= this.countLimit || this.bytes + bytes > this.byteLimit) return false;
    this.values.push({ frame, bytes });
    this.bytes += bytes;
    return true;
  }
  drain(output: Frame[], remaining: number) {
    while (output.length < 64 && this.values.length && this.values[0].bytes <= remaining) {
      const next = this.values.shift()!;
      this.bytes -= next.bytes;
      remaining -= next.bytes;
      output.push(next.frame);
    }
    return remaining;
  }
  clear() {
    const frames = this.values.map(value => value.frame);
    this.values = [];
    this.bytes = 0;
    return frames;
  }
}

/** One private IPC pump. Its timer moves frames; it never schedules peer retries. */
export class DesktopTransportPump {
  private readonly driver: DesktopTransport;
  private readonly replies = new Frames(16, 4 * 1024 * 1024);
  private readonly critical = new Frames(256, 2 * 1024 * 1024);
  private readonly packets = new Frames(256, 512 * 1024);
  private protocol: DesktopTransportProtocol | null = null;
  private epoch: string | null = null;
  private stopped = false;
  private polling = false;
  private pending = 0;
  private suspended = false;
  private generation = 0n;

  constructor(private readonly exchange: Exchange,
              driver = (emit: (event: TransportEvent) => boolean) => new DesktopTransport(emit)) {
    this.driver = driver(event => this.observe(event));
  }

  private observe(event: TransportEvent) {
    if (this.stopped || !this.epoch) return false;
    if (this.suspended) {
      if (event.event !== "message" && event.event !== "closed") this.driver.close(event.resource);
      return true;
    }
    const frame = { v: 1, type: "desktop_transport_event", epoch: this.epoch, ...event };
    if (event.event === "message") return this.packets.push(frame);
    if (this.critical.push(frame)) return true;
    this.stop();
    return false;
  }

  async step() {
    if (this.stopped) return;
    if (this.polling) throw new Error("transport_poll_in_progress");
    this.polling = true;
    const outgoing: Frame[] = [];
    let remaining = this.replies.drain(outgoing, 2 * 1024 * 1024 - 128);
    remaining = this.critical.drain(outgoing, remaining);
    this.packets.drain(outgoing, remaining);
    try {
      const requests = await this.boundedExchange(outgoing);
      if (this.stopped) return;
      if (!Array.isArray(requests) || requests.length > 18 || size(requests) > 4 * 1024 * 1024 + 1024) {
        throw new Error("invalid_transport_batch");
      }
      for (const request of requests) {
        if ((request as Frame | null)?.type === "desktop_transport_binding") this.bind(request, outgoing);
        else this.execute(request);
      }
    } catch {
      this.stop();
    } finally { this.polling = false; }
  }

  private execute(request: unknown) {
    if (this.stopped || this.suspended || this.pending >= 16) { this.stop(); return; }
    if (!this.protocol) {
      const epoch = (request as Frame | null)?.epoch;
      if (typeof epoch !== "string") throw new Error("invalid_transport_epoch");
      this.protocol = new DesktopTransportProtocol(epoch, this.driver);
      this.epoch = epoch;
    }
    this.pending++;
    const generation = this.generation;
    void this.protocol.handle(request).then(reply => {
      if (!this.stopped && generation === this.generation && !this.replies.push(reply)) this.stop();
    }, () => { if (generation === this.generation) this.stop(); }).finally(() => {
      if (generation === this.generation) this.pending--;
    });
  }

  private bind(value: unknown, outgoing: Frame[]) {
    if (this.stopped) return;
    const frame = value as Frame;
    if (Object.keys(frame).sort().join(",") !== "action,epoch,generation,type,v" || frame.v !== 1 ||
        typeof frame.generation !== "string" || !/^[1-9][0-9]{0,19}$/.test(frame.generation)) {
      throw new Error("invalid_transport_binding");
    }
    const generation = BigInt(frame.generation);
    if (generation <= this.generation || generation > 18446744073709551615n) throw new Error("stale_transport_binding");
    if (frame.action === "suspend" && !this.suspended && frame.epoch === this.epoch) {
      this.suspended = true;
      this.generation = generation;
      this.pending = 0;
      this.driver.suspend();
      this.replies.clear();
      this.packets.clear();
      const critical = [...outgoing, ...this.critical.clear()];
      for (const event of critical) {
        if (event.type === "desktop_transport_event" && event.event !== "message" && typeof event.resource === "string") {
          this.driver.close(event.resource);
        }
      }
      return;
    }
    if (frame.action === "bind" && this.suspended && typeof frame.epoch === "string" &&
        /^[0-9a-f]{32}$/.test(frame.epoch) && frame.epoch !== this.epoch) {
      this.protocol = new DesktopTransportProtocol(frame.epoch, this.driver);
      this.epoch = frame.epoch;
      this.generation = generation;
      this.driver.resume();
      this.suspended = false;
      return;
    }
    throw new Error("invalid_transport_binding_transition");
  }

  private async boundedExchange(frames: Frame[]) {
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      return await Promise.race([
        this.exchange(frames, false),
        new Promise<never>((_, reject) => { timer = setTimeout(() => reject(new Error("transport_host_timeout")), 5000); }),
      ]);
    } finally { clearTimeout(timer); }
  }

  async run() {
    while (!this.stopped) {
      await this.step();
      if (!this.stopped) await new Promise(resolve => setTimeout(resolve, 16));
    }
  }

  stop() {
    if (this.stopped) return;
    this.stopped = true;
    this.driver.closeAll();
    // One best-effort fault notification; no retry loop or replacement host.
    void this.exchange([], true).catch(() => {});
  }
}

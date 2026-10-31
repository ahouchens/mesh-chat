/** Private host protocol. Never register this handler in application commands. */
import type { CreateTransport, DesktopTransport } from "./desktop-transport";
export { DesktopTransport } from "./desktop-transport";

type RecordValue = Record<string, unknown>;

function record(value: unknown): RecordValue {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("invalid_transport_payload");
  return value as RecordValue;
}

function fields(value: RecordValue, expected: string[]) {
  if (Object.keys(value).length !== expected.length || expected.some(key => !(key in value))) {
    throw new Error("invalid_transport_payload");
  }
}

function text(value: unknown, limit = 65536): string {
  if (typeof value !== "string" || !value.length || value.length > limit || new TextEncoder().encode(value).length > limit) {
    throw new Error("invalid_transport_payload");
  }
  return value;
}

function resource(value: unknown) {
  const name = text(value, 128);
  if (!/^[A-Za-z0-9_-]+$/.test(name)) throw new Error("invalid_transport_payload");
  return name;
}

function configuration(value: unknown): CreateTransport {
  const options = record(value);
  fields(options, ["resource", "ice", "channels"]);
  resource(options.resource);
  record(options.ice);
  if (!Array.isArray(options.channels)) throw new Error("invalid_transport_payload");
  // The driver validates channel purposes, ICE policy and per-field bounds.
  return options as unknown as CreateTransport;
}

function packet(value: unknown): Uint8Array {
  const encoded = text(value, 1420);
  if (!/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(encoded)) {
    throw new Error("invalid_transport_payload");
  }
  const decoded = atob(encoded);
  if (!decoded.length || decoded.length > 1064 || btoa(decoded) !== encoded) throw new Error("invalid_transport_payload");
  return Uint8Array.from(decoded, character => character.charCodeAt(0));
}

export class DesktopTransportProtocol {
  private lastRequest = 0n;
  private stopped = false;
  private pending = 0;

  constructor(private readonly epoch: string, private readonly driver: DesktopTransport) {
    if (!/^[a-f0-9]{32}$/.test(epoch)) throw new Error("invalid_transport_epoch");
  }

  async handle(input: unknown) {
    const frame = this.frame(input);
    const response = { v: 1, type: "desktop_transport_reply", epoch: this.epoch, id: frame.id, ok: false, result: null as unknown };
    try {
      const request = record(frame.request);
      if (request.op === "reset") {
        fields(request, ["op"]);
        this.stopped = true;
        this.driver.closeAll();
      } else {
        if (this.stopped || this.pending >= 16) return response;
        this.pending++;
        try { response.result = (await this.execute(request)) ?? null; }
        finally { this.pending--; }
      }
      response.ok = true;
    } catch { /* Browser and input details never cross the private error boundary. */ }
    return response;
  }

  private frame(input: unknown) {
    let frame: RecordValue;
    try {
      frame = record(input);
      fields(frame, ["v", "type", "epoch", "id", "request"]);
      if (frame.v !== 1 || frame.type !== "desktop_transport" || frame.epoch !== this.epoch ||
          typeof frame.id !== "string" || !/^[1-9][0-9]{0,19}$/.test(frame.id) ||
          BigInt(frame.id) > 18446744073709551615n ||
          new TextEncoder().encode(JSON.stringify(frame)).length > 256 * 1024) throw new Error();
    } catch { throw new Error("invalid_transport_frame"); }
    const sequence = BigInt(frame.id as string);
    if (sequence <= this.lastRequest) throw new Error("transport_replay");
    this.lastRequest = sequence;
    return frame;
  }

  private execute(request: RecordValue): unknown {
    switch (request.op) {
      case "createOffer":
        fields(request, ["op", "options"]);
        return this.driver.createOffer(configuration(request.options));
      case "acceptOffer":
        fields(request, ["op", "options", "offer"]);
        return this.driver.acceptOffer(configuration(request.options), text(request.offer));
      case "applyAnswer":
        fields(request, ["op", "resource", "answer"]);
        return this.driver.applyAnswer(resource(request.resource), text(request.answer));
      case "inspect":
        fields(request, ["op", "resource"]);
        return this.driver.inspect(resource(request.resource));
      case "inventory":
        fields(request, ["op"]);
        return this.driver.inventory();
      case "activate":
        fields(request, ["op", "resource"]);
        return this.driver.activate(resource(request.resource));
      case "close":
        fields(request, ["op", "resource"]);
        return this.driver.close(resource(request.resource));
      case "send":
        fields(request, ["op", "resource", "packet"]);
        return this.driver.send(resource(request.resource), packet(request.packet));
      case "sendControl":
        fields(request, ["op", "resource", "label", "text"]);
        if (request.label !== "meshchat-reconnect" && request.label !== "mesh-onboarding") throw new Error("invalid_transport_payload");
        return this.driver.sendControl(resource(request.resource), request.label, text(request.text));
      default:
        throw new Error("invalid_transport_operation");
    }
  }
}

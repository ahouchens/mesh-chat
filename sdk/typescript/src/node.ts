/** Bounded Node stream adapter. The caller owns endpoint authentication. */
import { connect, type Socket } from "node:net";
import { TextDecoder } from "node:util";
import { Duplex, type Readable, type Writable } from "node:stream";
import { MAX_FRAME_BYTES } from "./framing.js";
import { ProtocolError, TransportClosedError } from "./errors.js";
import type { LineTransport } from "./transport.js";

export class NodeStreamTransport implements LineTransport {
  #buffer = Buffer.alloc(0);
  #line: string | null = null;
  #error: Error | null = null;
  #closed = false;
  #waiting: { resolve: (line: string | null) => void; reject: (error: Error) => void } | null = null;

  constructor(readonly socket: Duplex) {
    socket.on("data", chunk => this.#data(Buffer.from(chunk)));
    socket.on("error", () => this.#fail(new TransportClosedError()));
    socket.on("end", () => this.#fail(new TransportClosedError()));
    socket.on("close", () => this.#fail(new TransportClosedError()));
  }

  #data(chunk: Buffer): void {
    if (this.#closed) return;
    if (chunk.length > MAX_FRAME_BYTES - this.#buffer.length) {
      this.#fail(new ProtocolError("response frame exceeds byte limit")); return;
    }
    this.#buffer = Buffer.concat([this.#buffer, chunk]);
    const end = this.#buffer.indexOf(10);
    if (end < 0) return;
    if (this.#line !== null || end !== this.#buffer.length - 1) {
      this.#fail(new ProtocolError("unsolicited or multiple response frames")); return;
    }
    let line: string;
    try { line = new TextDecoder("utf-8", { fatal: true }).decode(this.#buffer); }
    catch { this.#fail(new ProtocolError("response is not UTF-8")); return; }
    this.#buffer = Buffer.alloc(0);
    if (this.#waiting !== null) {
      const waiting = this.#waiting; this.#waiting = null; waiting.resolve(line);
    } else this.#line = line;
  }

  #fail(error: Error): void {
    if (this.#closed) return;
    this.#error = error; this.#closed = true;
    const waiting = this.#waiting; this.#waiting = null;
    waiting?.reject(error); this.socket.destroy();
  }

  async readLine(): Promise<string | null> {
    if (this.#line !== null) { const line = this.#line; this.#line = null; return line; }
    if (this.#error !== null) throw this.#error;
    if (this.#waiting !== null) throw new ProtocolError("concurrent response reads");
    return new Promise((resolve, reject) => { this.#waiting = { resolve, reject }; });
  }

  async writeLine(line: string): Promise<void> {
    if (this.#closed) throw this.#error ?? new TransportClosedError();
    if (!line.endsWith("\n") || line.indexOf("\n") !== line.length - 1 || Buffer.byteLength(line) > MAX_FRAME_BYTES) throw new ProtocolError("invalid frame");
    await new Promise<void>((resolve, reject) => {
      this.socket.write(line, "utf8", error => error ? reject(new TransportClosedError()) : resolve());
    });
  }

  close(): void { this.#fail(new TransportClosedError()); }
}

/** Use only host-inherited streams; this grants no runtime ownership. */
export function createStdioTransport(input: Readable = process.stdin, output: Writable = process.stdout): NodeStreamTransport {
  return new NodeStreamTransport(Duplex.from({ readable: input, writable: output }));
}

/** Connect only to an explicitly supplied local Windows named pipe. */
export async function connectNamedPipe(path: string, timeoutMs = 10000): Promise<NodeStreamTransport> {
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 3600000) throw new ProtocolError("invalid connect timeout");
  if (process.platform !== "win32" || !/^\\\\\.\\pipe\\[A-Za-z0-9._-]{1,200}$/.test(path)) {
    throw new ProtocolError("a local Windows pipe path is required");
  }
  const socket = connect(path);
  await new Promise<void>((resolve, reject) => {
    const timer = setTimeout(() => { socket.destroy(); reject(new TransportClosedError()); }, timeoutMs);
    socket.once("connect", () => { clearTimeout(timer); resolve(); });
    socket.once("error", () => { clearTimeout(timer); reject(new TransportClosedError()); });
  });
  return new NodeStreamTransport(socket);
}

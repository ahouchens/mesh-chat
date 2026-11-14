// Independent application: imports only Node and the installed public SDK.
import { CoreClient, CoreError } from "@mesh-chat/core-client";
import { connectNamedPipe } from "@mesh-chat/core-client/node";
import { once } from "node:events";
import { TextDecoder } from "node:util";
import { launchRuntime } from "./runtime.mjs";
import { PrivateConsumerInput } from "./public-process-helper.mjs";

const MAX_FRAME = 256 * 1024;
process.stdout.on("error", () => process.exit(1));
const decoder = new TextDecoder("utf-8", { fatal: true });
const operations = new Set([
  "runtime.capabilities", "profile.create", "profile.query", "application.snapshot",
  "peer.pairing_begin", "peer.pairing_query", "peer.pairing_cancel", "peer.approve", "contact.invitation",
  "settings.query", "settings.update", "call.settings_query", "call.settings_update",
  "call.ice_servers", "call.media_query", "call.control",
  "connection.snapshot", "connection.start", "connection.stop",
  "message.enqueue", "message.query", "message.list", "message.received", "events.poll", "events.ack",
]);

function request(value) {
  if (value === null || typeof value !== "object" || Array.isArray(value)
      || !Object.keys(value).every(key => ["id", "operation", "params", "idempotency_key"].includes(key))
      || typeof value.id !== "string" || !/^[A-Za-z0-9:_-]{1,64}$/.test(value.id)
      || !operations.has(value.operation)
      || value.params === null || typeof value.params !== "object" || Array.isArray(value.params)
      || (value.idempotency_key !== undefined && (typeof value.idempotency_key !== "string"
        || value.idempotency_key.length < 16 || value.idempotency_key.length > 128))) {
    throw new Error("invalid_application_request");
  }
  return value;
}

async function* frames(input) {
  let pending = Buffer.alloc(0);
  for await (const chunk of input) {
    // A bounded input chunk may contain multiple small commands; each command
    // is dispatched serially and no read-ahead queue of commands is retained.
    const bytes = Buffer.from(chunk);
    let offset = 0;
    while (offset < bytes.length) {
      const end = bytes.indexOf(10, offset);
      const next = end < 0 ? bytes.length : end + 1;
      if (pending.length + next - offset > MAX_FRAME) throw new Error("application_frame_budget");
      pending = Buffer.concat([pending, bytes.subarray(offset, next)]);
      offset = next;
      if (end >= 0) {
        yield JSON.parse(decoder.decode(pending));
        pending = Buffer.alloc(0);
      }
    }
  }
  if (pending.length) throw new Error("incomplete_application_frame");
}

async function reply(value) {
  const frame = JSON.stringify(value) + "\n";
  if (Buffer.byteLength(frame) > MAX_FRAME) throw new Error("application_reply_budget");
  if (!process.stdout.write(frame)) await once(process.stdout, "drain");
}

async function main() {
  const args = process.argv.slice(2);
  let runtime, client, transport;
  try {
    let pipe, privateMode = false;
    if (args.length === 2 && args[0] === "--pipe") pipe = args[1];
    else if (args.length === 3 && args[0] === "--private-helper" && args[1] === "--pipe") {
      privateMode = true;
      pipe = args[2];
    }
    else if (args.length === 4 && args[0] === "--runtime" && args[2] === "--data-directory") {
      runtime = await launchRuntime(args[1], args[3]);
      pipe = runtime.pipe;
    } else throw new Error("explicit_host_bootstrap_required");
    const privateInput = privateMode ? new PrivateConsumerInput(process.stdin) : null;
    const invitation = privateInput ? await privateInput.invitation() : null;
    transport = await connectNamedPipe(pipe);
    if (invitation !== null) await transport.writeLine(`MESH-HELPER/1 ${invitation}\n`);
    client = await CoreClient.open(transport, { requestTimeoutMs: 30000 });
    for await (const value of privateInput ? privateInput.frames() : frames(process.stdin)) {
      const command = request(value);
      try {
        // Keys and consent decisions come only from the application's caller.
        // The SDK and this application never retry or invent a mutation key.
        const result = await client.request(command.operation, command.params,
          command.idempotency_key === undefined ? {} : { idempotencyKey: command.idempotency_key });
        await reply({ id: command.id, ok: true, result });
      } catch (error) {
        if (!(error instanceof CoreError)) throw error;
        await reply({ id: command.id, ok: false, error: { code: error.code } });
      }
    }
  } finally {
    // Closing this SDK client detaches; it does not stop or replace its host.
    try { if (client) client.close(); else transport?.close(); }
    finally { if (runtime) await runtime.stop(); }
  }
}

try { await main(); }
catch {
  // No upstream error text, pairing code, message, caller key or profile path.
  process.stderr.write("Independent public consumer failed.\n");
  process.exitCode = 1;
}

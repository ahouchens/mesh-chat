// Cross-language conformance: the compiled TypeScript client against a real host
// over inherited stdio. The host supplies the stream and grant; this script owns
// no runtime policy.
import readline from "node:readline";

import { CoreClient } from "./dist/index.js";

const lines = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
const iterator = lines[Symbol.asyncIterator]();

const transport = {
  async readLine() {
    const { value, done } = await iterator.next();
    return done ? null : `${value}\n`;
  },
  async writeLine(line) {
    await new Promise((resolve) => process.stdout.write(line, resolve));
  },
  close() {
    lines.close();
  },
};

function finish(payload, code) {
  lines.close();
  process.stderr.write(`${JSON.stringify(payload)}\n`, () => process.exit(code));
}

try {
  const client = await CoreClient.open(transport);
  const profile = client.capabilities.profiles[0];
  const view = await client.profileQuery(profile);
  const page = await client.received(profile);
  const invitation = await client.pairingCreate(profile);
  const snapshot = await client.request("message.list", { profile, cursor: null, limit: 8 });
  const events = await client.pollEvents(profile, snapshot.events_cursor);
  const stopped = await client.stopRuntime();
  client.close();
  finish({
    ok: true,
    operations: client.capabilities.operations.length,
    peers: view.peers.length,
    messages: page.messages.length,
    events: events.events.length,
    invitation: invitation.file.length > 0,
    stopped: stopped.stopping,
    api_major: client.capabilities.api_major,
  }, 0);
} catch (error) {
  finish({ ok: false, error: String(error && error.message) }, 1);
}

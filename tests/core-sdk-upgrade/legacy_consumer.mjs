// Only the installed public package and Node stdlib; works with SDK0.2/0.3.
import { CoreClient } from "@mesh-chat/core-client";
import { createInterface } from "node:readline";
const reader = createInterface({ input: process.stdin });
const lines = reader[Symbol.asyncIterator]();
const transport = {
  async writeLine(line) { await new Promise((resolve, reject) => process.stdout.write(line, error => error ? reject(error) : resolve())); },
  async readLine() { const item = await lines.next(); return item.done ? null : item.value + "\n"; },
  close() { reader.close(); process.stdin.destroy(); },
};
const client = await CoreClient.open(transport);
try {
  const profile = client.capabilities.profiles[0];
  const peer = (await client.profileQuery(profile)).peers[0];
  const accepted = await client.enqueue(profile, peer, "Upgrade legacy enqueue", "upgrade-legacy-message-key-0001");
  const report = { accepted: accepted.accepted, api_minor: client.capabilities.api_minor,
    installed_package: import.meta.resolve("@mesh-chat/core-client").includes("node_modules") };
  if (process.argv.includes("--expect-no-composer")) {
    try { await client.composerQuery(profile, peer); throw new Error("unexpected composer"); }
    catch (error) { if (error.code !== "unsupported_operation") throw error; report.composer_locally_refused = true; }
  }
  console.error(JSON.stringify(report));
} finally { client.close(); }

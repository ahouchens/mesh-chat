// Installed public SDK + normal installed runtime checks; no private fixture.
import { CoreClient, CoreError } from "@mesh-chat/core-client";
import { connectNamedPipe } from "@mesh-chat/core-client/node";
import { randomUUID } from "node:crypto";
import { launchRuntime } from "./runtime.mjs";

let phase = "arguments";

async function check(executable, directory) {
  const key = randomUUID(); // This application explicitly owns this logical mutation.
  const displayName = "Independent application";
  let identity;
  for (let incarnation = 0; incarnation < 2; incarnation++) {
    phase = "runtime_start";
    const runtime = await launchRuntime(executable, directory);
    let client;
    try {
      phase = "capabilities";
      client = await CoreClient.open(await connectNamedPipe(runtime.pipe));
      if (client.capabilities.profiles.length !== incarnation
          || !client.capabilities.operations.includes("profile.create")
          || client.capabilities.operations.includes("native.command")) throw new Error();
      phase = "profile_create";
      const first = await client.request("profile.create", { display_name: displayName }, { idempotencyKey: key });
      phase = "key_replay";
      const repeated = await client.request("profile.create", { display_name: displayName }, { idempotencyKey: key });
      if (JSON.stringify(first) !== JSON.stringify(repeated)) throw new Error();
      phase = "changed_payload";
      try {
        await client.request("profile.create", { display_name: "Changed intent" }, { idempotencyKey: key });
        throw new Error();
      } catch (error) {
        if (!(error instanceof CoreError) || error.code !== "idempotency_conflict") throw error;
      }
      phase = "observations";
      const caps = await client.request("runtime.capabilities", {});
      if (caps.profiles.length !== 1) throw new Error();
      const profile = await client.request("profile.query", { profile: caps.profiles[0] });
      const snapshot = await client.request("application.snapshot", {});
      if (profile.display_name !== displayName || snapshot.profile.display_name !== displayName
          || typeof profile.destination !== "string"
          || snapshot.contacts.length || snapshot.messages.length) throw new Error();
      if (incarnation === 0) identity = profile.destination;
      else if (identity !== profile.destination) throw new Error();
    } finally {
      try { client?.close(); }
      finally {
        const previous = phase;
        phase = "retirement";
        await runtime.stop();
        phase = previous;
      }
    }
  }
  return { fresh_without_profile: true, public_only_capabilities: true,
    explicit_profile_create_and_key_replay: true, changed_key_payload_rejected: true,
    reopen_same_public_identity: true, clean_host_exits: 2 };
}

try {
  const args = process.argv.slice(2);
  if (args.length !== 4 || args[0] !== "--runtime" || args[2] !== "--data-directory") throw new Error();
  process.stdout.write(JSON.stringify(await check(args[1], args[3])) + "\n");
} catch (error) {
  const code = error instanceof CoreError && /^[a-z_]{1,64}$/.test(error.code) ? error.code : "unavailable";
  process.stdout.write(JSON.stringify({ passed: false, phase, error_code: code }) + "\n");
  process.stderr.write("Independent application bootstrap check failed.\n");
  process.exitCode = 1;
}

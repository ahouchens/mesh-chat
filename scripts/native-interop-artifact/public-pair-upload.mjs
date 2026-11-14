import { createHash } from "node:crypto";
import { readFile, stat, writeFile } from "node:fs/promises";
import path from "node:path";

// Separate public-pair admission; the package's pinned ArtifactClient is shared.
try {
  const [name, suppliedPath, suppliedIdentity] = process.argv.slice(2);
  const file = path.resolve(suppliedPath ?? "");
  const identity = path.resolve(suppliedIdentity ?? "");
  if (path.basename(file) !== "bundle.json" || (await stat(file)).size > 32 * 1024
      || path.basename(identity) !== "identity.json" || path.dirname(identity) !== path.dirname(file)) throw new Error();
  const value = JSON.parse(await readFile(file, "utf8"));
  const context = value.context;
  const role = value.role ?? value.sender;
  const jobs = { windows: "windows_public", android: "android_public" };
  const phases = {
    offer_code: ["windows"], invitation_accepted: ["android"], approved: ["windows"],
    ready: ["windows", "android"], done: ["windows", "android"],
    owner_stopped: ["windows"], android_continuous: ["android"], owner_reopened: ["windows"],
    restart_ready: ["windows", "android"], restart_done: ["windows", "android"],
  };
  const phase = value.public_key ? "key" : value.phase;
  const owns = (object, key) => Object.prototype.hasOwnProperty.call(object, key);
  const exactKeys = (object, keys) => object && typeof object === "object" && !Array.isArray(object)
    && Object.keys(object).length === keys.length && keys.every(key => owns(object, key));
  const contextKeys = ["repository", "repository_id", "run_id", "run_attempt", "source_commit", "pair_id"];
  if (!exactKeys(context, contextKeys) || !owns(jobs, role)
      || phase !== "key" && (!owns(phases, phase) || !phases[phase].includes(role))
      || value.v !== 1 || value.producer_job !== jobs[role]
      || process.env.GITHUB_JOB !== jobs[role] || process.env.GITHUB_ACTIONS !== "true"
      || process.env.GITHUB_EVENT_NAME !== "workflow_dispatch"
      || context.repository !== process.env.GITHUB_REPOSITORY
      || context.repository_id !== Number(process.env.GITHUB_REPOSITORY_ID)
      || context.run_id !== Number(process.env.GITHUB_RUN_ID)
      || context.run_attempt !== Number(process.env.GITHUB_RUN_ATTEMPT)
      || context.source_commit !== process.env.GITHUB_SHA
      || !/^[a-f0-9]{40}$/.test(context.source_commit)
      || !/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(context.repository)
      || context.repository.split("/").some(part => part === "." || part === "..")
      || !Number.isSafeInteger(context.repository_id) || context.repository_id <= 0
      || !Number.isSafeInteger(context.run_id) || context.run_id <= 0
      || !Number.isSafeInteger(context.run_attempt) || context.run_attempt <= 0) throw new Error();
  const source = Object.fromEntries(Object.entries(context)
    .filter(([key]) => key !== "pair_id")
    .sort(([left], [right]) => left < right ? -1 : left > right ? 1 : 0));
  const expectedPair = createHash("sha256").update("public-core-pair:v1:" + JSON.stringify(source))
    .digest("hex").slice(0, 32);
  if (context.pair_id !== expectedPair) throw new Error();
  const expected = `public-core-pair-v1-${context.run_id}-${context.run_attempt}-${context.source_commit.slice(0, 12)}-${context.pair_id}-${role}-${phase}`;
  if (name !== expected || !process.env.ACTIONS_RUNTIME_TOKEN) throw new Error();
  const common = ["v", "context", "producer_job", "created_at", "expires_at"];
  const fields = phase === "key" ? [...common, "role", "public_key"]
    : [...common, "phase", "sender", "recipient", "nonce", "ciphertext"];
  if (!exactKeys(value, fields) || !Number.isSafeInteger(value.created_at)
      || !Number.isSafeInteger(value.expires_at)
      || value.expires_at !== value.created_at + (phase === "key" ? 1800 : 600)) throw new Error();
  const decode = (text, length) => {
    if (typeof text !== "string" || !/^[A-Za-z0-9_-]+$/.test(text)) throw new Error();
    const bytes = Buffer.from(text, "base64url");
    if (bytes.toString("base64url") !== text || length !== undefined && bytes.length !== length) throw new Error();
    return bytes;
  };
  if (phase === "key") {
    if (value.role !== role) throw new Error();
    decode(value.public_key, 32);
  } else {
    if (value.phase !== phase || value.sender !== role
        || value.recipient !== (role === "windows" ? "android" : "windows")) throw new Error();
    decode(value.nonce, 12);
    const ciphertext = decode(value.ciphertext);
    if (ciphertext.length < 16 || ciphertext.length > 2048 + 1024) throw new Error();
  }
  const { DefaultArtifactClient } = await import("@actions/artifact");
  const result = await new DefaultArtifactClient().uploadArtifact(name, [file], path.dirname(file), {
    retentionDays: 1, compressionLevel: 0,
  });
  if (!Number.isSafeInteger(result.id) || result.id <= 0
      || !Number.isSafeInteger(result.size) || result.size <= 0 || result.size > 64 * 1024) throw new Error();
  await writeFile(identity, JSON.stringify({ passed: true, id: result.id, size: result.size }) + "\n",
    { encoding: "utf8", flag: "wx" });
} catch {
  process.exitCode = 1;
}

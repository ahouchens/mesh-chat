// Upload only an exact, bounded sealed R5 setup phase for this run and source.
import { createHash } from "node:crypto";
import { readFile, stat, writeFile } from "node:fs/promises";
import path from "node:path";

try {
  const [name, suppliedBundle, suppliedIdentity] = process.argv.slice(2);
  const bundle = path.resolve(suppliedBundle ?? "");
  const identity = path.resolve(suppliedIdentity ?? "");
  if (path.basename(bundle) !== "bundle.json" || path.basename(identity) !== "identity.json"
      || path.dirname(bundle) !== path.dirname(identity) || (await stat(bundle)).size > 32 * 1024) throw new Error();
  const value = JSON.parse(await readFile(bundle, "utf8"));
  const context = value.context;
  const role = value.role ?? value.sender;
  const phase = value.public_key ? "key" : value.phase;
  const jobs = { gui: "call_gui", peer: "call_peer" };
  const senders = {
    offer_code: ["peer"], invitation_accepted: ["gui"], approved: ["peer"],
    ready: ["gui", "peer"], precall_gui_sent: ["gui"], precall_peer_sent: ["peer"],
    call_started: ["gui"], call_active: ["gui", "peer"], during_peer_sent: ["peer"],
    call_hungup: ["gui"], postcall_gui_sent: ["gui"], postcall_peer_sent: ["peer"],
    done: ["gui", "peer"],
  };
  const own = (object, key) => Object.prototype.hasOwnProperty.call(object, key);
  const exact = (object, keys) => object && typeof object === "object" && !Array.isArray(object)
    && Object.keys(object).length === keys.length && keys.every((key) => own(object, key));
  const fields = ["repository", "repository_id", "run_id", "run_attempt",
    "source_commit", "source_tree", "pair_id"];
  if (!exact(context, fields) || !own(jobs, role) || phase !== "key" &&
      (!own(senders, phase) || !senders[phase].includes(role))
      || value.v !== 1 || value.producer_job !== jobs[role]
      || process.env.GITHUB_JOB !== jobs[role] || process.env.GITHUB_ACTIONS !== "true"
      || !["workflow_dispatch", "push"].includes(process.env.GITHUB_EVENT_NAME)
      || context.repository !== process.env.GITHUB_REPOSITORY
      || context.repository_id !== Number(process.env.GITHUB_REPOSITORY_ID)
      || context.run_id !== Number(process.env.GITHUB_RUN_ID)
      || context.run_attempt !== Number(process.env.GITHUB_RUN_ATTEMPT)
      || context.source_commit !== process.env.GITHUB_SHA
      || context.source_tree !== process.env.PACKAGED_CALL_TREE
      || !/^[a-f0-9]{40}$/.test(context.source_commit)
      || !/^[a-f0-9]{40}$/.test(context.source_tree)
      || !/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(context.repository)
      || context.repository.split("/").some((part) => part === "." || part === "..")
      || ![context.repository_id, context.run_id, context.run_attempt].every(
        (number) => Number.isSafeInteger(number) && number > 0)) throw new Error();
  const source = Object.fromEntries(Object.entries(context).filter(([key]) => key !== "pair_id")
    .sort(([left], [right]) => left < right ? -1 : left > right ? 1 : 0));
  const expectedPair = createHash("sha256").update("packaged-call:v1:" + JSON.stringify(source))
    .digest("hex").slice(0, 32);
  const expectedName = `packaged-call-v1-${context.run_id}-${context.run_attempt}-`
    + `${context.source_commit.slice(0, 12)}-${context.pair_id}-${role}-${phase}`;
  if (context.pair_id !== expectedPair || name !== expectedName
      || !process.env.ACTIONS_RUNTIME_TOKEN || !process.env.ACTIONS_RESULTS_URL) throw new Error();
  const common = ["v", "context", "producer_job", "created_at", "expires_at"];
  const keys = phase === "key" ? [...common, "role", "public_key"]
    : [...common, "phase", "sender", "recipient", "nonce", "ciphertext"];
  if (!exact(value, keys) || !Number.isSafeInteger(value.created_at)
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
        || value.recipient !== (role === "gui" ? "peer" : "gui")) throw new Error();
    decode(value.nonce, 12);
    const ciphertext = decode(value.ciphertext);
    if (ciphertext.length < 16 || ciphertext.length > 3072) throw new Error();
  }
  const { DefaultArtifactClient } = await import("@actions/artifact");
  const result = await new DefaultArtifactClient().uploadArtifact(name, [bundle], path.dirname(bundle), {
    retentionDays: 1, compressionLevel: 0,
  });
  if (!Number.isSafeInteger(result.id) || result.id <= 0
      || !Number.isSafeInteger(result.size) || result.size <= 0 || result.size > 64 * 1024) throw new Error();
  await writeFile(identity, JSON.stringify({ passed: true, id: result.id, size: result.size }) + "\n",
    { encoding: "utf8", flag: "wx" });
} catch {
  process.exitCode = 1;
}

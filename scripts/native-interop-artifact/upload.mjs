import { readFile, stat } from "node:fs/promises";
import path from "node:path";

// Called only by a trusted local Node Action, which supplies the runtime token.
// The Python caller captures ALL stdout/stderr; raw SDK errors never reach logs.
try {
  const [name, suppliedPath] = process.argv.slice(2);
  const file = path.resolve(suppliedPath ?? "");
  if (path.basename(file) !== "bundle.json" || (await stat(file)).size > 96 * 1024) throw new Error();
  const value = JSON.parse(await readFile(file, "utf8"));
  const context = value.context;
  const role = value.role ?? value.sender;
  const jobs = { windows: "native_windows_peer", android: "native_android_peer" };
  if (value.v !== 1 || !context || !Object.hasOwn(jobs, role)
      || value.producer_job !== jobs[role] || process.env.GITHUB_JOB !== jobs[role]
      || context.repository !== process.env.GITHUB_REPOSITORY
      || context.repository_id !== Number(process.env.GITHUB_REPOSITORY_ID)
      || context.run_id !== Number(process.env.GITHUB_RUN_ID)
      || context.run_attempt !== Number(process.env.GITHUB_RUN_ATTEMPT)
      || context.source_commit !== process.env.GITHUB_SHA) throw new Error();
  const phase = value.public_key ? "key" : value.phase;
  if (!["key", "offer", "answer", "approved", "control", "result"].includes(phase)) throw new Error();
  const expected = `mesh-native-v1-${context.run_id}-${context.run_attempt}-${context.source_commit.slice(0, 12)}-${role}-${phase}`;
  if (name !== expected || !process.env.ACTIONS_RUNTIME_TOKEN) throw new Error();
  const fields = phase === "key"
    ? ["v", "context", "role", "producer_job", "public_key", "created_at", "expires_at"]
    : ["v", "context", "phase", "sender", "recipient", "producer_job", "created_at", "expires_at", "nonce", "ciphertext"];
  if (Object.keys(value).length !== fields.length || fields.some(key => !Object.hasOwn(value, key))) throw new Error();
  const { DefaultArtifactClient } = await import("@actions/artifact");
  const result = await new DefaultArtifactClient().uploadArtifact(name, [file], path.dirname(file), {
    retentionDays: 1, compressionLevel: 0,
  });
  process.stdout.write(JSON.stringify({ passed: true, id: result.id, size: result.size }) + "\n");
} catch {
  process.stdout.write(JSON.stringify({ passed: false }) + "\n");
  process.exitCode = 1;
}

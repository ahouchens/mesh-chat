#!/usr/bin/env node
// Archive/install smoke only. Real installed-SDK/Core flows are separate tests.
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdtempSync, mkdirSync, copyFileSync, rmSync, writeFileSync, readFileSync, realpathSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const packageDir = join(root, "sdk/typescript");
const where = process.platform === "win32" ? "where.exe" : "which";
const shim = execFileSync(where, [process.platform === "win32" ? "npm.cmd" : "npm"], { encoding: "utf8" }).trim().split(/\r?\n/)[0];
const npmCli = process.env.MESH_NPM_CLI ?? (process.platform === "win32"
  ? join(dirname(shim), "node_modules/npm/bin/npm-cli.js") : realpathSync(shim));
if (!existsSync(npmCli)) throw new Error("A local npm CLI is required");
const argument = process.argv.indexOf("--output-dir");
const output = resolve(argument >= 0 ? process.argv[argument + 1] : join(root, "dist/sdk/typescript"));
const work = mkdtempSync(join(tmpdir(), "mesh-core-typescript-distribution-"));
const env = { ...process.env, npm_config_cache: join(work, "npm-cache") };
function npm(args, cwd) {
  return execFileSync(process.execPath, [npmCli, ...args], { cwd, env, encoding: "utf8", timeout: 120000, stdio: ["ignore", "pipe", "pipe"] });
}
try {
  mkdirSync(output, { recursive: true });
  const packed = JSON.parse(npm(["pack", "--json", "--ignore-scripts", "--offline"], packageDir));
  const entry = packed[0];
  if (!entry?.filename || basename(entry.filename) !== entry.filename) throw new Error("Invalid package filename");
  const allowed = new Set(["package.json", "README.md", "LICENSE", ...["index", "client", "consumer", "transport", "errors", "framing", "node", "types"].flatMap(name => ["dist/" + name + ".js", "dist/" + name + ".d.ts"])]);
  const files = entry.files.map(value => value.path);
  if (!files.includes("LICENSE")) throw new Error("SDK archive omits license");
  if (files.length !== new Set(files).size || files.some(name => !allowed.has(name))) throw new Error("Unexpected implementation/test payload in SDK archive");
  const artifact = join(output, entry.filename);
  copyFileSync(join(packageDir, entry.filename), artifact);
  rmSync(join(packageDir, entry.filename));
  const project = join(work, "consumer"); mkdirSync(project);
  writeFileSync(join(project, "package.json"), JSON.stringify({ name: "isolated-sdk-consumer", private: true, type: "module" }));
  npm(["install", artifact, "--ignore-scripts", "--no-audit", "--no-fund", "--offline", "--package-lock=false"], project);
  const smoke = `
import assert from "node:assert/strict";
import { CoreClient } from "@mesh-chat/core-client";
import { createStdioTransport } from "@mesh-chat/core-client/node";
assert.equal(typeof CoreClient, "function");
assert.equal(typeof CoreClient.prototype.enqueueDraft, "function");
for (const name of ["callOperationList", "callOperationQuery", "callOperationAbandon", "pairingBegin", "pairingQuery", "pairingCancel"]) {
  assert.equal(typeof CoreClient.prototype[name], "function", name);
}
assert.equal(typeof createStdioTransport, "function");
assert.ok(import.meta.resolve("@mesh-chat/core-client").includes("node_modules"));
console.log(JSON.stringify({installed_outside_checkout:true,imports_public_package:true}));
`;
  writeFileSync(join(project, "smoke.mjs"), smoke);
  const consumer = JSON.parse(execFileSync(process.execPath, ["smoke.mjs"], { cwd: project, env, encoding: "utf8", timeout: 30000 }));
  const report = { artifact: entry.filename, artifact_path: artifact, sha256: createHash("sha256").update(readFileSync(artifact)).digest("hex"), version: "0.3.0-experimental", node: process.version, files, consumer, qualification: "archive_and_isolated_import_only; real-host tests reported separately" };
  writeFileSync(join(output, "distribution-report.json"), JSON.stringify(report, null, 2) + "\n");
  console.log(JSON.stringify(report));
} finally {
  const owned = realpathSync(work);
  if (dirname(owned) !== realpathSync(tmpdir()) || !basename(owned).startsWith("mesh-core-typescript-distribution-")) throw new Error("Refusing cleanup outside owned temporary directory");
  rmSync(owned, { recursive: true, force: true });
}

#!/usr/bin/env node
// Pack the TypeScript client, install it into an empty project and exercise the
// public entry point. This qualifies the packaged artifact without publishing it.
import { execFileSync } from "node:child_process";
import { mkdtempSync, mkdirSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..");
const packageDir = join(root, "sdk", "typescript");
const work = mkdtempSync(join(tmpdir(), "mesh-core-package-"));

function run(command, args, options = {}) {
  return execFileSync(command, args, {
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
    shell: process.platform === "win32" && command === "npm.cmd",
    ...options,
  });
}
const npm = process.platform === "win32" ? "npm.cmd" : "npm";

try {
  const packed = JSON.parse(run(npm, ["pack", "--json"], { cwd: packageDir }));
  const filename = packed[0]?.filename;
  if (!filename) throw new Error("npm pack produced no artifact");
  const tarball = join(work, filename);
  renameSync(join(packageDir, filename), tarball);
  const project = join(work, "project");
  mkdirSync(project);
  writeFileSync(join(project, "package.json"), JSON.stringify({ name: "consumer", private: true, type: "module" }));
  run(npm, ["install", tarball, "--ignore-scripts", "--no-audit", "--no-fund", "--prefer-offline"], { cwd: project });

  const smoke = `
import assert from "node:assert/strict";
import { CoreClient } from "@mesh-chat/core-client";
assert.equal(typeof CoreClient, "function");
const response = JSON.stringify({
  api_version: 1,
  request_id: "client:1",
  ok: true,
  result: {
    api_major: 1,
    api_minor: 0,
    stability: "experimental",
    operations: ["runtime.capabilities"],
    profiles: [],
    limits: { frame_bytes: 4194304 },
  },
}) + "\\n";
const transport = {
  readLine: async () => response,
  writeLine: () => undefined,
};
const client = await CoreClient.open(transport);
assert.equal(client.capabilities.api_major, 1);
assert.equal(typeof client.workspaceDeviceRemove, "function");
assert.equal(typeof client.workspaceChannelTransferOffer, "function");
`;
  writeFileSync(join(project, "smoke.mjs"), smoke);
  const output = run(process.execPath, ["smoke.mjs"], { cwd: project });
  rmSync(tarball, { force: true });
  console.log(JSON.stringify({ passed: true, package: filename, entry: "@mesh-chat/core-client", smoke: output.trim() }));
} finally {
  rmSync(work, { recursive: true, force: true });
}

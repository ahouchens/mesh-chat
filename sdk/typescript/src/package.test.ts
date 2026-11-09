import { readFileSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import test from "node:test";
import assert from "node:assert/strict";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const packageJson = JSON.parse(readFileSync(join(root, "package.json"), "utf8"));

test("the package is private, experimental and version-bound to the contract", () => {
  const declaration = JSON.parse(
    readFileSync(join(root, "..", "..", "contracts", "core-api", "compatibility-v1.json"), "utf8"),
  );
  assert.equal(packageJson.private, true);
  assert.equal(packageJson.version, declaration.typescript_client.version);
  assert.equal(declaration.typescript_client.packaged, false);
  assert.match(packageJson.version, /^0\.\d+\.\d+-experimental$/);
  assert.match(packageJson.description, /experimental/i);
});

test("every declared entry point ships from dist", () => {
  assert.ok(packageJson.files.includes("!dist/**/*.test.js"));
  const entryPoints = [
    packageJson.main,
    packageJson.types,
    packageJson.exports["."].import,
    packageJson.exports["."].types,
  ];
  for (const relative of entryPoints) {
    assert.match(relative, /^\.\/dist\//, relative);
    assert.ok(statSync(join(root, relative)).isFile(), relative);
  }
});

test("the emitted declarations expose the workspace surface", () => {
  const declarations = [
    readFileSync(join(root, "dist", "client.d.ts"), "utf8"),
    readFileSync(join(root, "dist", "types.d.ts"), "utf8"),
  ].join("\n");
  for (const name of [
    "CoreClient",
    "workspaceChannels",
    "workspaceChannelCreate",
    "workspaceChannelArchive",
    "workspaceDeviceLinkCreate",
    "workspaceDeviceLinkPreview",
  ]) {
    assert.match(declarations, new RegExp(name), name);
  }
});

import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { brotliCompressSync } from "node:zlib";

import { verifyPackagedEmojiArtwork } from "./verify_packaged_emoji_artwork.mjs";

function fixture({ inline = false, omitLogicalPath = false } = {}) {
  const root = mkdtempSync(join(tmpdir(), "mesh-chat-artwork-verifier-"));
  const assets = join(root, "assets");
  const codegen = join(root, "build", "out", "tauri-codegen-assets");
  mkdirSync(assets, { recursive: true });
  mkdirSync(codegen, { recursive: true });

  const values = new Map([
    ["curated.png", Buffer.from("a tiny png fixture")],
    ["ATTRIBUTION.txt", Buffer.from("attribution")],
    ["LICENSE-GRAPHICS.txt", Buffer.from("license")],
  ]);
  const manifest = Buffer.from(JSON.stringify({ files: [{ name: "curated.png" }] }));
  values.set("manifest.json", manifest);

  const binaryParts = [];
  for (const [name, contents] of values) {
    writeFileSync(join(assets, name), contents);
    const encoded = brotliCompressSync(contents);
    const digest = createHash("sha256").update(contents).digest("hex");
    writeFileSync(join(codegen, `${digest}.asset`), encoded);
    const logicalPath = Buffer.from(`emoji/twemoji/17.0.3/${name}`);
    if (inline) {
      if (!(omitLogicalPath && name === "curated.png")) binaryParts.push(logicalPath);
      binaryParts.push(encoded);
    } else {
      binaryParts.push(encoded);
      if (!(omitLogicalPath && name === "curated.png")) binaryParts.push(logicalPath);
    }
  }
  const binary = join(root, "mesh-chat.bin");
  writeFileSync(binary, Buffer.concat(binaryParts));
  return { root, assets, codegenRoot: join(root, "build"), binary };
}

test("verifies decoded source bytes, embedded codegen blobs, and logical paths", () => {
  const value = fixture();
  try {
    const result = verifyPackagedEmojiArtwork({
      assetRoot: value.assets,
      binaryPath: value.binary,
      codegenRoot: value.codegenRoot,
    });
    assert.equal(result.files.length, 4);
    assert.deepEqual(result.files.map(({ name }) => name), [
      "ATTRIBUTION.txt",
      "curated.png",
      "LICENSE-GRAPHICS.txt",
      "manifest.json",
    ]);
  } finally {
    rmSync(value.root, { recursive: true, force: true });
  }
});

test("rejects a package whose logical asset path is absent", () => {
  const value = fixture({ omitLogicalPath: true });
  try {
    assert.throws(
      () => verifyPackagedEmojiArtwork({
        assetRoot: value.assets,
        binaryPath: value.binary,
        codegenRoot: value.codegenRoot,
      }),
      /logical asset path/,
    );
  } finally {
    rmSync(value.root, { recursive: true, force: true });
  }
});

test("verifies inline Brotli payloads without retaining a build directory", () => {
  const value = fixture({ inline: true });
  try {
    const result = verifyPackagedEmojiArtwork({
      assetRoot: value.assets,
      binaryPath: value.binary,
    });
    assert.equal(result.mode, "inline");
    assert.equal(result.files.length, 4);
    assert.ok(result.files.every(({ encodedBytes }) => encodedBytes > 0));
  } finally {
    rmSync(value.root, { recursive: true, force: true });
  }
});

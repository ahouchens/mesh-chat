import { createHash } from "node:crypto";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { basename, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { brotliDecompressSync } from "node:zlib";

const DEFAULT_ASSET_ROOT = "public/emoji/twemoji/17.0.3";
const LOGICAL_PREFIX = "emoji/twemoji/17.0.3";

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function codegenDirectories(root) {
  const absolute = resolve(root);
  if (!existsSync(absolute)) return [];
  if (basename(absolute) === "tauri-codegen-assets") return [absolute];

  const matches = [];
  const pending = [absolute];
  while (pending.length) {
    const directory = pending.pop();
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      if (!entry.isDirectory()) continue;
      const child = join(directory, entry.name);
      if (entry.name === "tauri-codegen-assets") matches.push(child);
      else pending.push(child);
    }
  }
  return matches.sort((left, right) => statSync(right).mtimeMs - statSync(left).mtimeMs);
}

function expectedFiles(assetRoot) {
  const manifestPath = join(assetRoot, "manifest.json");
  const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
  const generated = manifest.files.map((entry) => entry.name);
  const names = ["ATTRIBUTION.txt", ...generated, "LICENSE-GRAPHICS.txt", "manifest.json"];
  for (const name of names) {
    if (basename(name) !== name || name.includes("..")) {
      throw new Error(`Unsafe artwork filename in manifest: ${name}`);
    }
  }
  return names;
}

function decodedCodegenAssets(directory) {
  const decoded = new Map();
  for (const name of readdirSync(directory)) {
    const path = join(directory, name);
    if (!statSync(path).isFile()) continue;
    const encoded = readFileSync(path);
    let contents;
    try {
      contents = brotliDecompressSync(encoded);
    } catch {
      contents = encoded;
    }
    const digest = sha256(contents);
    const candidates = decoded.get(digest) ?? [];
    candidates.push({ encoded, name });
    decoded.set(digest, candidates);
  }
  return decoded;
}

function verifyDirectory({ assetRoot, binary, directory, logicalPrefix }) {
  const decoded = decodedCodegenAssets(directory);
  const verified = [];
  for (const name of expectedFiles(assetRoot)) {
    const source = readFileSync(join(assetRoot, name));
    const candidates = decoded.get(sha256(source)) ?? [];
    const match = candidates.find(({ encoded }) => binary.indexOf(encoded) !== -1);
    if (!match) {
      throw new Error(`${name} is not embedded in ${directory}`);
    }
    const logicalPath = Buffer.from(`${logicalPrefix}/${name}`, "utf8");
    if (binary.indexOf(logicalPath) === -1) {
      throw new Error(`Packaged binary is missing the logical asset path ${logicalPrefix}/${name}`);
    }
    verified.push({ name, bytes: source.length, codegenFile: match.name });
  }
  return verified;
}

function inlineBrotliLength(binary, start, expected) {
  const remaining = binary.length - start;
  let low = 1;
  let high = Math.min(remaining, Math.max(65_536, expected.length * 2 + 65_536));
  const matches = (length) => {
    try {
      return brotliDecompressSync(binary.subarray(start, start + length)).equals(expected);
    } catch {
      return false;
    }
  };
  if (!matches(high)) return null;
  while (low < high) {
    const middle = Math.floor((low + high) / 2);
    if (matches(middle)) high = middle;
    else low = middle + 1;
  }
  return low;
}

function verifyInlineAssets({ assetRoot, binary, logicalPrefix }) {
  const verified = [];
  for (const name of expectedFiles(assetRoot)) {
    const source = readFileSync(join(assetRoot, name));
    const logicalPath = Buffer.from(`${logicalPrefix}/${name}`, "utf8");
    let pathOffset = binary.indexOf(logicalPath);
    let encodedBytes = null;
    while (pathOffset !== -1) {
      encodedBytes = inlineBrotliLength(binary, pathOffset + logicalPath.length, source);
      if (encodedBytes !== null) break;
      pathOffset = binary.indexOf(logicalPath, pathOffset + 1);
    }
    if (encodedBytes === null) {
      throw new Error(`Packaged binary does not contain ${logicalPrefix}/${name} followed by its Brotli payload`);
    }
    verified.push({ name, bytes: source.length, encodedBytes });
  }
  return verified;
}

export function verifyPackagedEmojiArtwork({
  assetRoot = DEFAULT_ASSET_ROOT,
  binaryPath,
  codegenRoot,
  logicalPrefix = LOGICAL_PREFIX,
}) {
  if (!binaryPath) throw new Error("binaryPath is required");
  const binary = readFileSync(resolve(binaryPath));
  const resolvedAssets = resolve(assetRoot);
  const failures = [];
  if (codegenRoot) {
    const directories = codegenDirectories(codegenRoot);
    if (!directories.length) {
      failures.push(`No tauri-codegen-assets directory found below ${resolve(codegenRoot)}`);
    }
    for (const directory of directories) {
      try {
        const files = verifyDirectory({
          assetRoot: resolvedAssets,
          binary,
          directory,
          logicalPrefix,
        });
        return {
          binaryPath: resolve(binaryPath),
          codegenDirectory: directory,
          files,
          mode: "codegen",
          totalBytes: files.reduce((total, file) => total + file.bytes, 0),
        };
      } catch (error) {
        failures.push(`${directory}: ${error instanceof Error ? error.message : String(error)}`);
      }
    }
  }
  try {
    const files = verifyInlineAssets({
      assetRoot: resolvedAssets,
      binary,
      logicalPrefix,
    });
    return {
      binaryPath: resolve(binaryPath),
      codegenDirectory: null,
      files,
      mode: "inline",
      totalBytes: files.reduce((total, file) => total + file.bytes, 0),
    };
  } catch (error) {
    failures.push(error instanceof Error ? error.message : String(error));
  }
  throw new Error(`Packaged artwork verification failed:\n${failures.join("\n")}`);
}

function argument(name) {
  const index = process.argv.indexOf(name);
  return index === -1 ? undefined : process.argv[index + 1];
}

function main() {
  const result = verifyPackagedEmojiArtwork({
    assetRoot: argument("--asset-root") ?? DEFAULT_ASSET_ROOT,
    binaryPath: argument("--binary"),
    codegenRoot: argument("--codegen-root"),
  });
  console.log(
    `Verified ${result.files.length} bundled emoji artwork files (${result.totalBytes} source bytes) in ${result.binaryPath}`,
  );
  console.log(
    result.codegenDirectory
      ? `Tauri codegen assets: ${result.codegenDirectory}`
      : "Tauri asset encoding: inline Brotli streams",
  );
}

if (process.argv[1] && fileURLToPath(import.meta.url) === resolve(process.argv[1])) {
  try {
    main();
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  }
}

import react from "@vitejs/plugin-react";
import { createHash } from "node:crypto";
import { readdir, readFile, rename, rm, mkdir, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "vite";

const repository = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const output = path.join(repository, "dist", "web");
const stampPath = path.join(repository, "dist", ".cache", "web-build.json");

async function filesBelow(candidate) {
  const details = await stat(candidate).catch(() => null);
  if (!details) return [];
  if (details.isFile()) return [candidate];
  const entries = await readdir(candidate, { withFileTypes: true });
  const nested = await Promise.all(
    entries
      .sort((left, right) => left.name.localeCompare(right.name))
      .map((entry) => filesBelow(path.join(candidate, entry.name))),
  );
  return nested.flat();
}

async function inputDigest() {
  const candidates = [
    "index.html",
    "package.json",
    "pnpm-lock.yaml",
    "tsconfig.json",
    "tsconfig.app.json",
    "tsconfig.node.json",
    "vite.config.ts",
    "src",
    "public",
    "scripts/run-frontend-build.mjs",
  ];
  const inputs = (await Promise.all(candidates.map((item) => filesBelow(path.join(repository, item)))))
    .flat()
    .sort();
  const digest = createHash("sha256");
  digest.update(`node=${process.versions.node}\0`);
  const buildEnvironment = Object.entries(process.env)
    .filter(([name]) => name.startsWith("VITE_") || name.startsWith("TAURI_ENV_"))
    .sort(([left], [right]) => left.localeCompare(right));
  for (const [name, value] of buildEnvironment) {
    digest.update(`${name}=${value ?? ""}\0`);
  }
  for (const input of inputs) {
    digest.update(`${path.relative(repository, input).replaceAll("\\", "/")}\0`);
    digest.update(await readFile(input));
    digest.update("\0");
  }
  return digest.digest("hex");
}

const digest = await inputDigest();
const previous = await readFile(stampPath, "utf8")
  .then((value) => JSON.parse(value))
  .catch(() => null);
const outputExists = await stat(path.join(output, "index.html"))
  .then((value) => value.isFile())
  .catch(() => false);
if (
  process.env.MESH_CHAT_FORCE_WEB_BUILD !== "1" &&
  outputExists &&
  previous?.schema_version === 1 &&
  previous?.input_sha256 === digest
) {
  console.log(`Reusing frontend bundle (${digest.slice(0, 12)}).`);
  process.exit(0);
}

await build({
  configFile: false,
  plugins: [react()],
  clearScreen: false,
  envPrefix: ["VITE_", "TAURI_ENV_*"],
  build: {
    outDir: "dist/web",
    target: ["es2022", "chrome105", "safari13"],
    minify: process.env.TAURI_ENV_DEBUG ? false : "esbuild",
    sourcemap: Boolean(process.env.TAURI_ENV_DEBUG),
  },
});

await mkdir(path.dirname(stampPath), { recursive: true });
const temporary = `${stampPath}.${process.pid}.tmp`;
await writeFile(
  temporary,
  `${JSON.stringify({ schema_version: 1, input_sha256: digest }, null, 2)}\n`,
  "utf8",
);
await rm(stampPath, { force: true });
await rename(temporary, stampPath);
console.log(`Frontend bundle cache key: ${digest.slice(0, 12)}.`);

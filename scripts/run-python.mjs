import { existsSync } from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const repository = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const configured = process.env.MESH_CHAT_PYTHON;
const virtualEnvironment = path.join(
  repository,
  ".venv",
  process.platform === "win32" ? "Scripts" : "bin",
  process.platform === "win32" ? "python.exe" : "python",
);
const candidates = [configured, virtualEnvironment, "python3", "python"].filter(Boolean);

let python = null;
for (const candidate of candidates) {
  if (path.isAbsolute(candidate) && !existsSync(candidate)) continue;
  const probe = spawnSync(candidate, ["--version"], { stdio: "ignore", shell: false });
  if (!probe.error && probe.status === 0) {
    python = candidate;
    break;
  }
}
if (!python) {
  console.error("Python was not found. Create .venv or set MESH_CHAT_PYTHON.");
  process.exit(1);
}

const result = spawnSync(python, process.argv.slice(2), {
  cwd: repository,
  env: process.env,
  stdio: "inherit",
  shell: false,
});
if (result.error) {
  console.error(result.error.message);
  process.exit(1);
}
process.exit(result.status ?? 1);

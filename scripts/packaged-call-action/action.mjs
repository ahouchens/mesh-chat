import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const CONTROLLER_MS = 1_620_000; // The Python role has a 1500-second budget plus cleanup.
const RETIREMENT_MS = 15_000;

function admitted() {
  const role = process.env.INPUT_ROLE;
  const jobs = { gui: "call_gui", peer: "call_peer" };
  const event = process.env.GITHUB_EVENT_NAME;
  if (!Object.prototype.hasOwnProperty.call(jobs, role)
      || process.env.GITHUB_JOB !== jobs[role]
      || process.env.GITHUB_ACTIONS !== "true"
      || !["workflow_dispatch", "push"].includes(event)
      || (event === "push" && process.env.GITHUB_REF !== "refs/heads/codex/mesh-core-restart-diagnostic")
      || !/^[a-f0-9]{40}$/.test(process.env.GITHUB_SHA || "")
      || !/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(process.env.GITHUB_REPOSITORY || "")
      || process.env.GITHUB_REPOSITORY.split("/").some(part => part === "." || part === "..")
      || !["GITHUB_REPOSITORY_ID", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT"].every(key =>
        /^[1-9][0-9]*$/.test(process.env[key] || "")
        && Number.isSafeInteger(Number(process.env[key])))
      || !process.env.GITHUB_TOKEN || !process.env.ACTIONS_RUNTIME_TOKEN
      || !process.env.ACTIONS_RESULTS_URL) throw new Error();
  return role;
}

async function runExactChild(command, args, cwd) {
  const child = spawn(command, args, {
    cwd, env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1" },
    stdio: ["ignore", "pipe", "pipe"], windowsHide: true,
  });
  // Keep pairing data and bearer setup out of workflow logs.
  child.stdout.on("data", () => {});
  child.stderr.on("data", () => {});
  let spawnFailed = false;
  child.on("error", () => { spawnFailed = true; });
  const outcome = await new Promise(resolve => {
    let settled = false;
    let expired = false;
    let retirement;
    const finish = (result) => {
      if (settled) return;
      settled = true;
      clearTimeout(controller);
      clearTimeout(retirement);
      resolve({ ...result, expired, spawnFailed });
    };
    const controller = setTimeout(() => {
      expired = true;
      try { child.kill(); } catch { /* Exact child may already have exited. */ }
      retirement = setTimeout(() => {
        child.stdout.destroy();
        child.stderr.destroy();
        child.unref();
        finish({ closed: false, code: null });
      }, RETIREMENT_MS);
    }, CONTROLLER_MS);
    child.once("close", code => finish({ closed: true, code }));
  });
  return outcome.closed && !outcome.expired && !outcome.spawnFailed && outcome.code === 0;
}

try {
  const role = admitted();
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
  const controller = path.join(root, "scripts/packaged_call_controller.py");
  const passed = await runExactChild(process.env.INPUT_PYTHON || "python",
    [controller, "--role", role, "--expected-source", process.env.GITHUB_SHA], root);
  process.stdout.write(`Installed call ${role} controller ${passed ? "passed" : "failed"}.\n`);
  if (!passed) process.exitCode = 1;
} catch {
  process.stdout.write("Installed call controller admission failed.\n");
  process.exitCode = 1;
}

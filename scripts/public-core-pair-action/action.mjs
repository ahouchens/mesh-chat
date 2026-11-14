import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const CONTROLLER_MS = 1_500_000; // 1200-second controller maximum plus bounded cleanup.
const RETIREMENT_MS = 15_000;
const PARTITION_ANDROID_MS = 2_400_000; // 35-minute gateway receive bound plus setup and cleanup.
const PARTITION_ANDROID_RETIREMENT_MS = 120_000;

function admitted() {
  const role = process.env.INPUT_ROLE;
  const scenario = process.env.INPUT_SCENARIO || "fresh";
  const jobs = { windows: "windows_public", android: "android_public" };
  const serial = process.env["INPUT_DISPOSABLE-EMULATOR-SERIAL"] || "";
  if (!["fresh", "owner_restart", "partition"].includes(scenario)
      || !Object.prototype.hasOwnProperty.call(jobs, role)
      || process.env.GITHUB_JOB !== jobs[role]
      || process.env.GITHUB_ACTIONS !== "true"
      || process.env.GITHUB_EVENT_NAME !== "workflow_dispatch"
      || !/^[a-f0-9]{40}$/.test(process.env.GITHUB_SHA || "")
      || !/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(process.env.GITHUB_REPOSITORY || "")
      || process.env.GITHUB_REPOSITORY.split("/").some(part => part === "." || part === "..")
      || !["GITHUB_REPOSITORY_ID", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT"].every(key =>
        /^[1-9][0-9]*$/.test(process.env[key] || "")
        && Number.isSafeInteger(Number(process.env[key])))
      || !process.env.GITHUB_TOKEN || !process.env.ACTIONS_RUNTIME_TOKEN
      || (role === "android" ? serial !== "emulator-5554" : serial !== "")) throw new Error();
  return { role, serial, scenario };
}

async function runExactChild(command, args, cwd, scenario, role) {
  const partitionAndroid = scenario === "partition" && role === "android";
  const child = spawn(command, args, {
    cwd, env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1", PUBLIC_PAIR_SCENARIO: scenario },
    stdio: ["ignore", "pipe", "pipe"], windowsHide: true,
  });
  // Drain without logging product, pairing, token or Python exception output.
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
    // The Android gateway's 35-minute receive bound starts after setup.
    // Leave time for exact gateway teardown before this outer backstop.
    const controller = setTimeout(() => {
      expired = true;
      try { child.kill(); } catch { /* Exact child may already have exited. */ }
      retirement = setTimeout(() => {
        // No tree-kill or positive retirement claim when exact child close is absent.
        child.stdout.destroy();
        child.stderr.destroy();
        child.unref();
        finish({ closed: false, code: null });
      }, partitionAndroid ? PARTITION_ANDROID_RETIREMENT_MS : RETIREMENT_MS);
    }, partitionAndroid ? PARTITION_ANDROID_MS : CONTROLLER_MS);
    child.once("close", code => finish({ closed: true, code }));
  });
  return outcome.closed && !outcome.expired && !outcome.spawnFailed && outcome.code === 0;
}

try {
  const { role, serial, scenario } = admitted();
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
  const restart = scenario === "owner_restart";
  const partition = scenario === "partition";
  const controller = path.join(root, partition
    ? role === "android" ? "scripts/public_core_android_gateway_runtime.py" : "scripts/public_core_partition_controller.py"
    : restart ? "scripts/public_core_restart_controller.py" : "scripts/public_core_pair_controller.py");
  const prefix = partition ? "public-core-partition" : restart ? "public-core-restart" : "public-core-pair";
  const output = path.join(root, `dist/reports/${prefix}-${role}.json`);
  const args = [controller, "--role", role, "--expected-source", process.env.GITHUB_SHA,
    "--output", output];
  if (role === "android") args.push("--disposable-emulator-serial", serial);
  const passed = await runExactChild(process.env.INPUT_PYTHON || "python", args, root, scenario, role);
  process.stdout.write(`Public Core pair ${role} controller ${passed ? "passed" : "failed"}.\n`);
  if (!passed) process.exitCode = 1;
} catch {
  process.stdout.write("Public Core pair controller admission failed.\n");
  process.exitCode = 1;
}

import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

// A Node Action receives the artifact runtime token. The controller captures
// all uploader diagnostics; neither bearer setup nor product output is logged.
try {
  const role = process.env.INPUT_ROLE;
  const workload = process.env.INPUT_WORKLOAD;
  const diagnostic = workload === "b8_first_cold";
  const jobs = { windows: "native_windows_peer", android: "native_android_peer" };
  if (!Object.hasOwn(jobs, role) || process.env.GITHUB_JOB !== jobs[role]
      || !["quick", "full", "b8_first_cold"].includes(workload)
      || (diagnostic && (process.env.GITHUB_ACTIONS !== "true"
        || process.env.GITHUB_EVENT_NAME !== "workflow_dispatch"))
      || (workload === "quick" && process.env.GITHUB_EVENT_NAME !== "pull_request")
      || !/^[a-f0-9]{40}$/.test(process.env.GITHUB_SHA ?? "")
      || !process.env.ACTIONS_RUNTIME_TOKEN || !process.env.GITHUB_TOKEN) throw new Error();
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
  const controller = path.join(root, role === "android"
    ? "scripts/native_interop_gateway_runtime.py" : "scripts/native_interop_controller.py");
  const reportPrefix = diagnostic ? "native-interop-b8-first-cold" : "native-interop";
  const output = path.join(root, `dist/reports/${reportPrefix}-${role}.json`);
  const child = spawn(process.env.INPUT_PYTHON || "python", [controller, "--role", role,
    "--expected-source", process.env.GITHUB_SHA, "--workload", workload, "--output", output], {
    cwd: root, env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1" }, stdio: ["ignore", "pipe", "pipe"],
  });
  child.stdout.on("data", () => {});
  child.stderr.on("data", () => {});
  const timer = setTimeout(() => child.kill(), 55 * 60 * 1000);
  const code = await new Promise(resolve => {
    child.once("error", () => resolve(1));
    child.once("exit", value => resolve(value ?? 1));
  });
  clearTimeout(timer);
  process.stdout.write(`Packaged native ${role} controller ${code === 0 ? "passed" : "failed"}.\n`);
  if (code !== 0) process.exitCode = 1;
} catch {
  process.stdout.write("Packaged native controller admission failed.\n");
  process.exitCode = 1;
}

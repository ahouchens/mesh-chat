// Installed public SDK against one ordinary frozen Windows owner and two Node image paths.
import { CoreClient, TransportClosedError } from "@mesh-chat/core-client";
import { connectNamedPipe } from "@mesh-chat/core-client/node";
import { spawn } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import { createReadStream } from "node:fs";
import { copyFile, lstat, readFile, readdir, realpath, unlink } from "node:fs/promises";
import { basename, dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { performance } from "node:perf_hooks";
import { fileURLToPath } from "node:url";

const SCOPE = "Installed public SDK Windows image-path admission on one ordinary frozen owner; no same-image cross-application, pairing, media or full R7 acceptance";
const TOTAL_MS = 120000;
const WORK_MS = 105000;
const OUTPUT_LIMIT = 4096;
const SOURCE = fileURLToPath(import.meta.url);

function remaining(deadline, cap = 30000) {
  const value = Math.min(cap, Math.floor(deadline - performance.now()));
  if (!Number.isSafeInteger(value) || value < 1) throw new Error("image_deadline");
  return value;
}

async function bounded(action, deadline, cap = 30000) {
  let timer;
  try {
    return await Promise.race([action, new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error("image_deadline")), remaining(deadline, cap));
    })]);
  } finally { clearTimeout(timer); }
}

function cleanEnvironment() {
  return Object.fromEntries(Object.entries(process.env).filter(([key]) =>
    !["MESH_", "GITHUB_", "ACTIONS_", "INPUT_"].some(prefix => key.toUpperCase().startsWith(prefix))
    && !["NODE_OPTIONS", "NODE_PATH", "PYTHONPATH", "PYTHONHOME"].includes(key.toUpperCase())));
}

async function digest(path) {
  const hash = createHash("sha256");
  for await (const chunk of createReadStream(path)) hash.update(chunk);
  return hash.digest("hex");
}

async function sdkDigest() {
  const entry = fileURLToPath(import.meta.resolve("@mesh-chat/core-client"));
  const root = dirname(dirname(entry));
  if (!root.includes(`${sep}node_modules${sep}@mesh-chat${sep}core-client`)) throw new Error("sdk_not_installed");
  const packageInfo = JSON.parse(await readFile(join(root, "package.json"), "utf8"));
  if (packageInfo.name !== "@mesh-chat/core-client" || packageInfo.version !== "0.3.0-experimental") {
    throw new Error("sdk_version");
  }
  const files = [];
  async function visit(directory) {
    for (const item of await readdir(directory, { withFileTypes: true })) {
      const path = join(directory, item.name);
      if (item.isDirectory()) await visit(path);
      else if (item.isFile()) files.push(path);
      else throw new Error("sdk_tree_changed");
      if (files.length > 256) throw new Error("sdk_tree_budget");
    }
  }
  await visit(root);
  files.sort();
  const hash = createHash("sha256");
  let total = 0;
  for (const path of files) {
    const info = await lstat(path);
    total += info.size;
    if (!info.isFile() || info.size > 2 * 1024 * 1024 || total > 8 * 1024 * 1024) {
      throw new Error("sdk_file_budget");
    }
    const bytes = await readFile(path);
    if (bytes.length !== info.size) throw new Error("sdk_tree_changed");
    hash.update(relative(root, path)).update("\0").update(createHash("sha256").update(bytes).digest("hex"));
  }
  return hash.digest("hex");
}

function exactImage(expected) {
  return isAbsolute(expected) && resolve(process.execPath).toLowerCase() === resolve(expected).toLowerCase();
}

async function probe(mode, pipe, expected) {
  if (!exactImage(expected) || !/^\\\\\.\\pipe\\mesh-chat-[A-Za-z0-9._-]{1,200}$/.test(pipe)) {
    throw new Error("probe_arguments");
  }
  if (mode === "preflight") {
    if (typeof CoreClient.open !== "function" || typeof connectNamedPipe !== "function") throw new Error("sdk_import");
    return { v: 1, mode, ready: true };
  }
  if (mode !== "allow" && mode !== "deny") throw new Error("probe_mode");
  // A failed connect is never image-rejection evidence. Count bytes after a
  // successful OS pipe connection, before public Core negotiation.
  const transport = await connectNamedPipe(pipe, 5000);
  let client;
  try {
    try {
      client = await CoreClient.open(transport, { requestTimeoutMs: 5000 });
    } catch (error) {
      if (mode === "deny" && error instanceof TransportClosedError && transport.socket?.bytesRead === 0) {
        return { v: 1, mode, connected: true, closed_before_core_reply: true };
      }
      throw error;
    }
    if (mode !== "allow") throw new Error("wrong_image_admitted");
    const handles = client.capabilities.profiles;
    if (!Array.isArray(handles) || handles.length !== 1 || typeof handles[0] !== "string"
        || client.capabilities.operations?.includes("native.command")) throw new Error("public_capabilities");
    const profile = await client.request("profile.query", { profile: handles[0] }, { timeoutMs: 5000 });
    if (!profile || typeof profile.destination !== "string" || !profile.destination) throw new Error("public_profile");
    return { v: 1, mode, connected: true, negotiated: true, profile_read: true };
  } finally { try { client?.close(); } finally { transport.close(); } }
}

async function runChild(image, args, deadline, retirementDeadline, children, cap = 10000) {
  const child = spawn(image, [SOURCE, ...args], { cwd: dirname(SOURCE), env: cleanEnvironment(),
    stdio: ["ignore", "pipe", "pipe"], windowsHide: true });
  let stdout = Buffer.alloc(0), stderrBytes = 0, overflow = false, spawnError = false;
  child.stdout.on("data", chunk => {
    if (stdout.length + chunk.length > OUTPUT_LIMIT) overflow = true;
    else stdout = Buffer.concat([stdout, chunk]);
  });
  child.stderr.on("data", chunk => { stderrBytes += chunk.length; if (stderrBytes > OUTPUT_LIMIT) overflow = true; });
  const closed = new Promise(resolve => {
    child.once("close", (code, signal) => resolve({ code, signal }));
    child.once("error", () => { spawnError = true; });
  });
  children.set(child, closed);
  let closedConfirmed = false;
  if (!Number.isSafeInteger(child.pid) || child.pid < 1 || child.pid === process.pid) {
    if (child.exitCode === null) child.kill();
    try { await bounded(closed, retirementDeadline, 3000); closedConfirmed = true; } catch {}
    if (closedConfirmed) children.delete(child);
    throw new Error("child_identity");
  }
  let outcome;
  try { outcome = await bounded(closed, deadline, cap); closedConfirmed = true; }
  catch {
    if (child.exitCode === null) child.kill();
    try { await bounded(closed, retirementDeadline, 3000); closedConfirmed = true; } catch {}
    throw new Error("child_deadline");
  } finally { if (closedConfirmed) children.delete(child); }
  if (spawnError || overflow || stderrBytes !== 0 || outcome.code !== 0 || outcome.signal !== null
      || stdout.length > OUTPUT_LIMIT || !stdout.toString("utf8").endsWith("\n")
      || stdout.toString("utf8").trim().includes("\n")) throw new Error("child_result");
  const value = JSON.parse(stdout.toString("utf8"));
  if (value === null || typeof value !== "object" || Array.isArray(value) || value.v !== 1) {
    throw new Error("child_result");
  }
  return value;
}

function fileWorkArguments(mode, image, copy) {
  return ["prepare", "verify"].includes(mode) && isAbsolute(image) && isAbsolute(copy)
    && dirname(resolve(copy)).toLowerCase() === dirname(resolve(SOURCE)).toLowerCase()
    && /^node-image-[0-9a-f-]{36}\.exe$/i.test(basename(copy))
    && exactImage(image);
}

async function fileWork(mode, image, copy) {
  if (!fileWorkArguments(mode, image, copy)) throw new Error("file_work_arguments");
  if (mode === "prepare") await copyFile(image, copy);
  if ((await realpath(copy)).toLowerCase() === (await realpath(image)).toLowerCase()
      || !(await lstat(copy)).isFile()) throw new Error("image_not_distinct");
  const originalHash = await digest(image);
  const copyHash = await digest(copy);
  const sdkHash = await sdkDigest();
  if (copyHash !== originalHash) throw new Error("image_bytes_changed");
  return { v: 1, mode, original_hash: originalHash, copy_hash: copyHash, sdk_hash: sdkHash };
}

function checkedFileWork(result, mode) {
  if (Object.keys(result).sort().join() !== "copy_hash,mode,original_hash,sdk_hash,v"
      || result.mode !== mode || ![result.original_hash, result.copy_hash, result.sdk_hash]
        .every(value => typeof value === "string" && /^[0-9a-f]{64}$/.test(value))) {
    throw new Error("file_work_result");
  }
  return result;
}

async function check(executable, dataDirectory) {
  const started = performance.now(), workDeadline = started + WORK_MS, finalDeadline = started + TOTAL_MS;
  let phase = "arguments", runtime, owner, copy, passed = false, retired = false;
  const children = new Map();
  let originalHash, copyHash, sdkHash;
  try {
    if (process.platform !== "win32" || !isAbsolute(executable) || !isAbsolute(dataDirectory)) {
      throw new Error("arguments");
    }
    phase = "owner_start";
    const { launchRuntime } = await import("./runtime.mjs");
    runtime = await launchRuntime(executable, dataDirectory,
      { timeoutMs: remaining(workDeadline), onOwned: value => { runtime = value; } });
    owner = await CoreClient.open(await connectNamedPipe(runtime.pipe, remaining(workDeadline, 10000)),
      { requestTimeoutMs: remaining(workDeadline) });
    const handle = owner.capabilities.profiles?.[0];
    if (typeof handle !== "string" || owner.capabilities.profiles.length !== 1
        || owner.capabilities.operations?.includes("native.command")) throw new Error("owner_capabilities");
    await owner.request("profile.create", { display_name: "Image admission" },
      { idempotencyKey: randomUUID(), timeoutMs: remaining(workDeadline) });
    const original = await owner.request("profile.query", { profile: handle },
      { timeoutMs: remaining(workDeadline) });
    if (typeof original?.destination !== "string" || !original.destination) throw new Error("owner_profile");
    phase = "positive_control";
    const positive = await runChild(process.execPath, ["--probe", "allow", runtime.pipe, process.execPath],
      workDeadline, finalDeadline, children);
    if (Object.keys(positive).sort().join() !== "connected,mode,negotiated,profile_read,v"
        || positive.mode !== "allow" || positive.connected !== true || positive.negotiated !== true
        || positive.profile_read !== true) throw new Error("positive_control");
    phase = "copy_preflight";
    copy = join(dirname(SOURCE), `node-image-${randomUUID()}.exe`);
    const prepared = checkedFileWork(await runChild(process.execPath,
      ["--file-work", "prepare", process.execPath, copy], workDeadline, finalDeadline, children, 30000), "prepare");
    originalHash = prepared.original_hash;
    copyHash = prepared.copy_hash;
    sdkHash = prepared.sdk_hash;
    const preflight = await runChild(copy, ["--probe", "preflight", runtime.pipe, copy],
      workDeadline, finalDeadline, children);
    if (Object.keys(preflight).sort().join() !== "mode,ready,v" || preflight.mode !== "preflight"
        || preflight.ready !== true) throw new Error("copy_preflight");
    phase = "wrong_image";
    const denied = await runChild(copy, ["--probe", "deny", runtime.pipe, copy],
      workDeadline, finalDeadline, children);
    if (Object.keys(denied).sort().join() !== "closed_before_core_reply,connected,mode,v"
        || denied.mode !== "deny" || denied.connected !== true || denied.closed_before_core_reply !== true) {
      throw new Error("wrong_image_not_rejected");
    }
    phase = "owner_survives";
    const after = await owner.request("profile.query", { profile: handle },
      { timeoutMs: remaining(workDeadline) });
    if (after?.destination !== original.destination) throw new Error("owner_changed");
    const fresh = await runChild(process.execPath, ["--probe", "allow", runtime.pipe, process.execPath],
      workDeadline, finalDeadline, children);
    if (fresh.mode !== "allow" || fresh.connected !== true || fresh.negotiated !== true
        || fresh.profile_read !== true) throw new Error("fresh_allowed_failed");
    phase = "artifact_binding";
    const verified = checkedFileWork(await runChild(process.execPath,
      ["--file-work", "verify", process.execPath, copy], workDeadline, finalDeadline, children, 30000), "verify");
    if (verified.original_hash !== originalHash || verified.copy_hash !== copyHash
        || verified.sdk_hash !== sdkHash) throw new Error("inputs_changed");
    passed = true;
  } catch { passed = false; }
  finally {
    try { owner?.close(); } catch { passed = false; }
    for (const [child, closed] of children) {
      try {
        if (child.exitCode === null && child.signalCode === null) child.kill();
        await bounded(closed, finalDeadline, 3000);
        children.delete(child);
      } catch { passed = false; }
    }
    if (children.size) passed = false;
    if (runtime) {
      try {
        const stopBudget = Math.min(30000, Math.max(0, Math.floor(finalDeadline - performance.now())));
        const done = await runtime.stop(stopBudget);
        retired = done?.stopped === true && done.exit_code === 0;
      } catch { retired = false; }
      if (!retired) passed = false;
    }
    // A timed-out file worker may still be copying or hashing. Keep its path
    // intact unless the child close event has confirmed every child retired.
    if (copy && children.size === 0) { try { await unlink(copy); } catch { passed = false; } }
  }
  if (performance.now() > finalDeadline) passed = false;
  return { v: 1, passed, scope: SCOPE, ...(passed ? { checks: {
    original_image_positive: true, copied_image_preflight: true, copied_image_denied_before_reply: true,
    original_owner_survived: true, fresh_allowed_helper: true, exact_child_exits: true,
    frozen_host_retired: retired, inputs_unchanged: true,
  } } : { phase }), duration_ms: Math.min(120000, Math.max(0, Math.floor(performance.now() - started))) };
}

async function main(args) {
  if (args.length === 4 && args[0] === "--file-work") {
    try { return await fileWork(args[1], args[2], args[3]); }
    catch { return { v: 1, mode: "file-work", passed: false }; }
  }
  if (args.length === 4 && args[0] === "--probe") {
    try { return await probe(args[1], args[2], args[3]); }
    catch { return { v: 1, mode: ["allow", "deny", "preflight"].includes(args[1]) ? args[1] : "unknown",
      passed: false }; }
  }
  if (args.length === 4 && args[0] === "--runtime" && args[2] === "--data-directory") {
    return check(args[1], args[3]);
  }
  return { v: 1, passed: false, scope: SCOPE, phase: "arguments", duration_ms: 0 };
}

const result = await main(process.argv.slice(2));
process.stdout.on("error", () => process.exit(1));
process.stdout.write(JSON.stringify(result) + "\n", () => process.exit(result.passed === false ? 1 : 0));

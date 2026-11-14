// Bounded transport helpers shared by the UI driver and focused behavior tests.
const UI_FAILURE_CODES = new Set([
  "ui_startup_deadline", "ui_mount_deadline", "ui_bridge_deadline",
  "ui_cdp_failed", "ui_cdp_frame_invalid", "ui_cdp_frame_unbounded",
  "ui_channel_missing", "ui_config_deadline", "ui_config_invalid",
  "ui_config_stream_failed", "ui_config_unbounded", "ui_control_unavailable",
  "ui_deadline_invalid", "ui_draft_missing", "ui_hashes_invalid",
  "ui_input_limits_invalid", "ui_markers_not_distinct", "ui_message_missing",
  "ui_message_not_visible", "ui_observation_failed", "ui_port_invalid",
  "ui_profile_not_fresh", "ui_readback_deadline", "ui_readback_invalid",
  "ui_socket_closed", "ui_socket_deadline", "ui_socket_failed",
  "ui_socket_retirement_deadline", "ui_socket_retirement_failed",
  "ui_source_mismatch", "ui_step_deadline", "ui_target_ambiguous",
  "ui_target_invalid", "ui_target_unavailable", "ui_workspace_missing",
  "ui_profile_unavailable", "ui_profile_changed", "ui_snapshot_unavailable", "ui_timeline_unavailable",
]);

export function fixedUiFailure(error) {
  return error instanceof Error && UI_FAILURE_CODES.has(error.message)
    ? error.message : "ui_contract_failed";
}

export class UiCleanupFailure extends Error {
  constructor(primary, cleanup, actionFailed) {
    super("ui_cleanup_failed");
    this.primary = primary;
    this.cleanup = cleanup;
    this.actionFailed = actionFailed;
  }
}

export function withDeadline(promise, milliseconds, code, timers = globalThis) {
  if (!Number.isInteger(milliseconds) || milliseconds < 1 || milliseconds > 60_000) {
    throw new Error("ui_deadline_invalid");
  }
  let timer;
  const deadline = new Promise((_, reject) => {
    timer = timers.setTimeout(() => reject(new Error(code)), milliseconds);
  });
  return Promise.race([promise, deadline]).finally(() => timers.clearTimeout(timer));
}

export function readBoundedInput(stream, limit = 2_048, deadlineMs = 5_000) {
  if (!Number.isInteger(limit) || limit < 1 || limit > 16_384
      || !Number.isInteger(deadlineMs) || deadlineMs < 1 || deadlineMs > 60_000) {
    throw new Error("ui_input_limits_invalid");
  }
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    let finished = false;
    let timer;
    const cleanup = () => {
      clearTimeout(timer);
      stream.off("data", onData);
      stream.off("end", onEnd);
      stream.off("error", onError);
      stream.pause();
    };
    const finish = (error, value) => {
      if (finished) return;
      finished = true;
      cleanup();
      if (error) {
        stream.destroy();
        reject(error);
      } else resolve(value);
    };
    const onData = (chunk) => {
      const bytes = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
      size += bytes.length;
      if (size > limit) finish(new Error("ui_config_unbounded"));
      else chunks.push(bytes);
    };
    const onEnd = () => finish(null, Buffer.concat(chunks).toString("utf8"));
    const onError = () => finish(new Error("ui_config_stream_failed"));
    stream.on("data", onData);
    stream.once("end", onEnd);
    stream.once("error", onError);
    timer = setTimeout(() => finish(new Error("ui_config_deadline")), deadlineMs);
    stream.resume();
  });
}

export function boundedCdpFrame(data, limit = 65_536) {
  if (typeof data !== "string" || Buffer.byteLength(data, "utf8") > limit) {
    throw new Error("ui_cdp_frame_unbounded");
  }
  const frame = JSON.parse(data);
  if (frame === null || typeof frame !== "object" || Array.isArray(frame)) {
    throw new Error("ui_cdp_frame_invalid");
  }
  return frame;
}

export async function closeBoundedSocket(socket, deadlineMs = 3_000, timers = globalThis) {
  if (!socket || socket.readyState === 3) return true;
  let onClose;
  let onError;
  const closed = new Promise((resolve, reject) => {
    onClose = () => resolve(true);
    onError = () => reject(new Error("ui_socket_retirement_failed"));
    socket.addEventListener("close", onClose);
    socket.addEventListener("error", onError);
  });
  try {
    if (socket.readyState < 2) socket.close();
    await withDeadline(closed, deadlineMs, "ui_socket_retirement_deadline", timers);
    return true;
  } finally {
    socket.removeEventListener("close", onClose);
    socket.removeEventListener("error", onError);
  }
}

export async function closeCheckedSocket(socket, protocolFailed) {
  await closeBoundedSocket(socket);
  if (protocolFailed()) throw new Error("ui_cdp_frame_invalid");
  return true;
}

export async function completeAfterCleanup(action, cleanup) {
  let value;
  let primary, actionFailed = false;
  try { value = await action(); }
  catch (error) { primary = error; actionFailed = true; }
  try { await cleanup(); }
  catch (error) { throw new UiCleanupFailure(primary, error, actionFailed); }
  if (actionFailed) throw primary;
  return value;
}

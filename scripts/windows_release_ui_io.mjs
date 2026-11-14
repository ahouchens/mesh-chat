// Bounded transport helpers shared by the UI driver and focused behavior tests.
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
  try { value = await action(); }
  finally { await cleanup(); }
  return value;
}

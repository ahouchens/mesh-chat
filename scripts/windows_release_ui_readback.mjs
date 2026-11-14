// Runs wholly in the app origin. Only hashes or a fixed failure code leave it.
export async function readInstalledUi(invoke, markers, project) {
  let step = "ui_profile_unavailable";
  try {
    const candidate = markers.phase === "observe";
    const request = (operation, params = {}) => invoke("core_api_request", {
      operation, params, idempotencyKey: null,
    });
    const profile = candidate ? await invoke("core_api_profile") : null;
    if (candidate && (!profile || !/^[a-f0-9]{64}$/.test(profile.profile)
        || !/^[a-f0-9]{32}$/.test(profile.destination))) throw new Error(step);
    step = "ui_snapshot_unavailable";
    const snapshot = candidate ? await request("application.snapshot")
      : await invoke("service_command", { command: "snapshot", payload: {} });
    step = "ui_workspace_missing";
    const workspaces = snapshot?.workspaces?.filter(item => item?.name === markers.workspace_name);
    if (workspaces?.length !== 1) throw new Error(step);
    const workspace = workspaces[0];
    step = "ui_channel_missing";
    const channels = snapshot?.workspace_channels?.filter(
      item => item?.workspace_id === workspace.id && item.name === "general");
    if (channels?.length !== 1) throw new Error(step);
    step = "ui_profile_changed";
    if (candidate && (snapshot.profile?.destination_hash !== profile.destination
        || !/^[a-f0-9]{64}$/.test(workspace.core_handle))) throw new Error(step);
    step = "ui_timeline_unavailable";
    // This API takes an opaque workspace handle and a domain channel ID, as the
    // shipping renderer does. The returned message IDs remain domain IDs.
    let page;
    if (candidate) {
      const response = await request("workspace.timeline_query", { profile: profile.profile,
          workspace: workspace.core_handle, view: "channel_messages",
          channel: channels[0].id, cursor: null, limit: 50 });
      step = "ui_profile_changed";
      if (response?.profile !== profile.profile || response?.workspace !== workspace.core_handle) {
        throw new Error(step);
      }
      page = response.result;
    } else {
      page = await invoke("service_command", { command: "list_workspace_messages",
          payload: { workspace_id: workspace.id, channel_id: channels[0].id,
            cursor: null, limit: 50 } });
    }
    if (candidate) {
      step = "ui_profile_unavailable";
      const after = await invoke("core_api_profile");
      step = "ui_profile_changed";
      if (after?.profile !== profile.profile || after?.destination !== profile.destination) {
        throw new Error(step);
      }
    }
    step = "ui_readback_invalid";
    try { return { hashes: await project(snapshot, page, markers) }; }
    catch (error) {
      if (["ui_readback_invalid", "ui_workspace_missing", "ui_channel_missing",
           "ui_draft_missing", "ui_message_missing"].includes(error?.message)) step = error.message;
      throw error;
    }
  } catch { return { failure_kind: step }; }
}

export async function settledUiReadback(read, milliseconds, {
  now = Date.now, pause = (ms) => new Promise(resolve => setTimeout(resolve, ms)),
} = {}) {
  const until = now() + milliseconds;
  let last = new Error("ui_readback_deadline");
  while (now() < until) {
    try { return await read(Math.max(1, until - now())); }
    catch (error) { last = error; }
    await pause(Math.min(200, Math.max(0, until - now())));
  }
  throw last;
}

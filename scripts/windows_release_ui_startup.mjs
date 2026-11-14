import { fixedUiFailure, withDeadline } from "./windows_release_ui_io.mjs";

export const emptyStartupObservation = () => ({
  bridge_ready: false, build_info_seen: false, source_matches: false,
  version_matches: false, root_mounted: false, title_matches: false,
});

export class UiStartupFailure extends Error {
  constructor(error, observation) {
    super(fixedUiFailure(error));
    this.observation = { ...observation };
  }
}

// Runs in the app page. Only fixed booleans leave the WebView.
export async function observeStartup(expectedSource, expectedVersion) {
  const invoke = window.__TAURI_INTERNALS__?.invoke;
  const bridge = typeof invoke === "function";
  const info = bridge ? await invoke("app_build_info") : null;
  return {
    bridge_ready: bridge,
    build_info_seen: info !== null && typeof info === "object",
    source_matches: info?.build_commit === expectedSource,
    version_matches: info?.installed_version === expectedVersion,
    root_mounted: Boolean(document.querySelector("#root > *")),
    title_matches: document.title === "Mesh Chat",
  };
}

export async function waitForStartup(observe, until, record, {
  now = Date.now, pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
} = {}) {
  let last = emptyStartupObservation();
  while (now() < until) {
    const remaining = Math.max(1, until - now());
    const value = await withDeadline(observe(remaining), remaining, "ui_startup_deadline");
    if (!value || Object.keys(value).length !== Object.keys(last).length
        || !Object.keys(last).every((key) => typeof value[key] === "boolean")) {
      throw new Error("ui_observation_failed");
    }
    last = value;
    record(last);
    if (last.build_info_seen && (!last.source_matches || !last.version_matches)) {
      throw new Error("ui_source_mismatch");
    }
    if (Object.values(last).every(Boolean)) return;
    await pause(Math.min(100, Math.max(0, until - now())));
  }
  throw new Error(last.bridge_ready && last.build_info_seen ? "ui_mount_deadline" : "ui_bridge_deadline");
}

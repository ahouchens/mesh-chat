const phase = new URLSearchParams(location.search).get("phase") ?? "waiting_for_ready";
const state = { setup_id:"synthetic-setup", workspace_id:"synthetic-workspace", state:phase,
  expires_at: phase === "refresh_required" ? 0 : Math.floor(Date.now()/1000)+240, candidate_count:0 };
export async function serviceCommand(command: string) {
  if (command === "resume_direct_setup") return { ...state, ...(phase === "waiting_for_ready" ? { text:"mesh-direct:synthetic-layout-fixture" } : {}) };
  if (command === "direct_setup_status") return state;
  if (command === "connection_diagnostics") throw new Error("Synthetic offline service");
  throw new Error("No mutation is available in this presentation fixture");
}
export async function appBuildInfo() { return {}; }
export async function runtimePlatform() { return "desktop"; }
export async function pickInvitationFile() { return null; }

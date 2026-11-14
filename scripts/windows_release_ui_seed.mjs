import { fixedUiFailure } from "./windows_release_ui_io.mjs";

export class UiSeedFailure extends Error {
  constructor(step, error) {
    super(fixedUiFailure(error));
    this.step = step;
  }
}

export async function seedReleasedUi(gui, markers) {
  const step = async (name, action) => {
    try { return await action(); }
    catch (error) { throw new UiSeedFailure(name, error); }
  };
  // The released app mounts a loading screen before initialize_service settles.
  // This visible control appears only after the initial snapshot is available.
  await step("onboarding_ready", () => gui.waitRect("button", "Start a chat", "page"));
  await step("fresh_profile", async () => {
    const fresh = await gui.evaluate(`window.__TAURI_INTERNALS__?.invoke('service_command',
      {command:'snapshot',payload:{}}).then(value => value?.profile == null
        && Array.isArray(value.workspaces) && value.workspaces.length === 0
        && Array.isArray(value.workspace_drafts) && value.workspace_drafts.length === 0)`, true);
    if (fresh !== true) throw new Error("ui_profile_not_fresh");
  });
  await step("onboarding_start", () => gui.click("button", "Start a chat", "page"));
  await step("profile_name", () => gui.fill("Display name", "R8 CI Owner", "page"));
  await step("profile_create", () => gui.click("button", "Create my invite", "page"));
  await step("onboarding_finish", async () => {
    if (await gui.waitEither("Create workspace", "Open Mesh Chat") === "Open Mesh Chat") {
      await gui.click("button", "Open Mesh Chat", "page");
    }
  });
  await step("workspace_open", () => gui.click("button", "Create workspace", "page"));
  await step("workspace_name", () => gui.fill("Name", markers.workspace_name, "dialog"));
  await step("workspace_create", () => gui.click("button", "Create workspace", "dialog"));
  await step("composer_ready", () => gui.waitRect("field", "Message general", "page"));
  await step("message_text", () => gui.fill("Message general", markers.message_text, "page"));
  await step("message_send", () => gui.click("button", "Send workspace message", "page"));
  await step("message_visible", () => gui.waitMessage(markers.message_text));
  await step("draft_text", () => gui.fill("Message general", markers.draft_text, "page"));
  return step("seed_readback", () => gui.settledReadback(markers));
}

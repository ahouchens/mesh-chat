import { invoke } from "@tauri-apps/api/core";
import { DesktopTransportPump } from "./desktop-transport-pump";

const bootstrap = (window as unknown as { __MESH_TRANSPORT_BOOTSTRAP__?: { token: string } }).__MESH_TRANSPORT_BOOTSTRAP__;
if (bootstrap && /^[a-f0-9]{32}$/.test(bootstrap.token)) {
  const pump = new DesktopTransportPump((frames, fault) =>
    invoke("desktop_transport_exchange", { token: bootstrap.token, frames, fault }));
  window.addEventListener("pagehide", () => pump.stop(), { once: true });
  void pump.run();
}

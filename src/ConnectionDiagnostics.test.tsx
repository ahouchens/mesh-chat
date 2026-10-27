import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
const api = vi.hoisted(() => ({ serviceCommand: vi.fn(), appBuildInfo: vi.fn() }));
vi.mock("./api", () => api);
import { ConnectionDiagnostics, currentWebRTCState, diagnosticReport, versionDetails } from "./ConnectionDiagnostics";
import { closeWebRTCSession, setWebRTCSession, type WebRTCSession } from "./webrtc-session";
import packageInfo from "../package.json";
beforeEach(() => { api.serviceCommand.mockReset(); api.appBuildInfo.mockResolvedValue({ installed_version: packageInfo.version, native_version: packageInfo.version, platform: "android", android_version_code: 2050 }); });
afterEach(async () => { cleanup(); await closeWebRTCSession(); });

it("copies a bounded allowlisted log without seeded credentials or addresses", () => {
  const secret = "private-key-MESHWORKSPACE-192.0.2.1";
  const text = diagnosticReport({ platform: secret, build_commit: secret }, { format_version:1,
    text:secret, private_key:secret, events:Array.from({length:400}, () => ({ phase:secret, event:"state", kind:"offer", address:secret, attempt:secret })) }, true);
  expect(text).not.toContain(secret);
  expect(JSON.parse(text).events.length).toBeGreaterThan(0);
  expect(JSON.parse(text).events.length).toBeLessThanOrEqual(200);
  expect(new TextEncoder().encode(text).length).toBeLessThan(65536);
});

it("offers selectable diagnostics when clipboard and service are unavailable", async () => {
  api.serviceCommand.mockRejectedValue(new Error("secret-path"));
  Object.defineProperty(navigator, "clipboard", { configurable:true, value:{ writeText:vi.fn().mockRejectedValue(new Error("denied")) } });
  render(<ConnectionDiagnostics full />);
  fireEvent.click(screen.getByText("Copy diagnostics"));
  const box = await screen.findByLabelText("Diagnostic report") as HTMLTextAreaElement;
  expect(box.value).toContain(packageInfo.version);
  expect(box.value).toContain('"service_status": "unavailable"');
  expect(box.value).not.toContain("secret-path");
  expect(screen.getByText("Save diagnostics")).toBeTruthy();
  expect(screen.queryByText("Copied")).toBeNull();
  expect(api.serviceCommand).toHaveBeenCalledTimes(1);
});

it("confirms copy only after clipboard success and keeps Android installed metadata", async () => {
  let finish!: () => void;
  const write = vi.fn((_text: string) => new Promise<void>(resolve => { finish=resolve; }));
  Object.defineProperty(navigator, "clipboard", { configurable:true, value:{ writeText:write } });
  api.serviceCommand.mockResolvedValue({ format_version:1, service_version:packageInfo.version, events:[] });
  render(<ConnectionDiagnostics full />);
  await waitFor(() => expect(api.appBuildInfo).toHaveBeenCalled());
  fireEvent.click(screen.getByText("Copy version details"));
  await waitFor(() => expect(write).toHaveBeenCalled());
  expect(screen.queryByText("Copied")).toBeNull();
  finish();
  expect(await screen.findByText("Copied")).toBeTruthy();
  expect(JSON.parse(write.mock.calls[0][0] as string).android_version_code).toBe(2050);
});

it("reports component mismatch instead of relabeling an older native component", () => {
  const value = versionDetails({ installed_version:"0.1.0", native_version:"0.1.0", platform:"windows" });
  expect(value.version_mismatch).toBe(true);
  expect(value.native_version).toBe("0.1.0");
});

it("clears only diagnostic history", async () => {
  api.serviceCommand.mockResolvedValue({});
  render(<ConnectionDiagnostics full />);
  fireEvent.click(screen.getByText("Clear diagnostic history"));
  expect(await screen.findByText(/Diagnostic history cleared/)).toBeTruthy();
  expect(api.serviceCommand.mock.calls).toEqual([["clear_connection_diagnostics"]]);
});

it("includes recent events in a summary copy and reports why it is truncated", () => {
  const events = Array.from({length:20}, (_, index) => ({time:index+1, event:"state", phase:"connecting"}));
  const report = JSON.parse(diagnosticReport({}, {format_version:1, events}, false));
  expect(report.events).toHaveLength(12);
  expect(report.events_included).toBe(12);
  expect(report.history_event_count).toBe(20);
  expect(report.truncated).toBe(true);
});

it("exports call signaling, carrier history and route evidence without private documents", () => {
  const secret = "private-peer-sdp-address-call-id";
  const report = JSON.parse(diagnosticReport({}, { format_version: 1,
    current_calls: { status: "available", window_seconds: 600, peers: 1, peers_with_route: 0,
      peers_with_keys: 1, peers_unchecked: 0, states: { dialing: 1 }, outbound_signals: { sending: 1 }, sdp: secret },
    events: [{ event: "call_outbound", phase: "sending", component: "call_signal", signal: "call_invite",
      command: "send_call_signal", document: secret },
      { event: "transport_state", phase: "failed", component: "ice", command: "native_webrtc_event" },
      { event: "call_rejected", phase: "failed", error_code: "identity_mismatch", signal: "call_invite" }],
  }, false));
  expect(report.current_calls.states.dialing).toBe(1);
  expect(report.current_calls.outbound_signals.sending).toBe(1);
  expect(report.current_calls.peers_with_route).toBe(0);
  expect(report.events[0]).toMatchObject({ event: "call_outbound", component: "call_signal", phase: "sending", signal: "call_invite" });
  expect(report.events[1]).toMatchObject({ event: "transport_state", component: "ice", phase: "failed" });
  expect(report.events[2]).toMatchObject({ event: "call_rejected", error_code: "identity_mismatch" });
  expect(JSON.stringify(report)).not.toContain(secret);
});

it("exports the saved-workspace failure reason and state only when allowlisted", () => {
  const failure = {time:1, event:"action_failed", phase:"failed", command:"prepare_direct_answer",
    error_code:"workspace_already_known", failure_stage:"join_authorization",
    failure_reason:"invitation_mismatch", workspace_state:"joining"};
  const report = JSON.parse(diagnosticReport({}, {format_version:1, events:[failure], last_failure:failure}, false));
  expect(report.last_failure.failure_reason).toBe("invitation_mismatch");
  expect(report.last_failure.workspace_state).toBe("joining");
  const rejected = diagnosticReport({}, {format_version:1, events:[{time:1, event:"action_failed",
    phase:"failed", failure_reason:"private-document", workspace_state:"private-document"}]}, false);
  expect(JSON.parse(rejected).events[0].failure_reason).toBe("unavailable");
  expect(JSON.parse(rejected).events[0].workspace_state).toBe("unavailable");
  expect(rejected).not.toContain("private-document");
});

it("exports an allowlisted network reachability failure without addresses", () => {
  const failure = {time:1, event:"action_failed", phase:"failed", command:"prepare_direct_offer",
    error_code:"invalid_request", failure_stage:"prepare_candidates",
    failure_reason:"upnp_no_discovery"};
  const report = JSON.parse(diagnosticReport({}, {format_version:1, events:[failure], last_failure:failure}, false));
  expect(report.last_failure.failure_reason).toBe("upnp_no_discovery");
  expect(report.last_failure.command).toBe("prepare_direct_offer");
});

it("includes fresh service and renderer transport evidence separately from old setup failures", () => {
  const secret = "private-name-address-session-key";
  const session = { key: secret, contactId: secret, path: "relayed", approvalPending: false,
    channel: { readyState: "open", label: secret },
    pc: { connectionState: "connected", iceConnectionState: "completed", remoteDescription: secret },
    bridge: { bridgeId: secret, close: vi.fn() }, createdAt: 10, control: null };
  setWebRTCSession(session as unknown as WebRTCSession);
  const text = diagnosticReport({}, {format_version:1, events:[{time:1, event:"state", phase:"cancelled"}],
    current_state: {captured_at:2000, network_running:true, interface_available:true,
      webrtc_bridges:1, webrtc_online_bridges:1, webrtc_received_bytes:123, webrtc_sent_bytes:456,
      direct_outbox_status:"available", pending_direct_messages:{queued:0, sending:1, delivered:secret},
      pending_direct_contacts:1, pending_contacts_with_route:0, pending_contacts_with_keys:1,
      oldest_pending_direct_message_age_seconds:120, destination:secret}});
  const report = JSON.parse(text);
  expect(report.events[0].time).toBe(1);
  expect(report.current_service.captured_at).toBe(2000);
  expect(report.current_service.pending_direct_messages.sending).toBe(1);
  expect(report.current_service.pending_contacts_with_route).toBe(0);
  expect(report.current_service.webrtc_received_bytes).toBe(123);
  expect(report.current_webrtc.channels.open).toBe(1);
  expect(report.current_webrtc.connections.connected).toBe(1);
  expect(report.current_webrtc.ice.completed).toBe(1);
  expect(report.current_webrtc.paths.relayed).toBe(1);
  expect(text).not.toContain(secret);
  session.channel.readyState = "closed";
  session.pc.connectionState = "disconnected";
  const fresh = JSON.parse(diagnosticReport({}, null));
  expect(fresh.current_webrtc.channels.open).toBe(0);
  expect(fresh.current_webrtc.channels.closed).toBe(1);
  expect(fresh.current_webrtc.connections.disconnected).toBe(1);
});

it("does not turn missing or invalid current evidence into a healthy transport", () => {
  const text = diagnosticReport({}, {current_state:{network_running:"secret", interface_available:"secret",
    direct_outbox_status:"secret", webrtc_bridges:-1, pending_contacts_with_route:Infinity,
    pending_direct_messages:{sending:NaN}}});
  const current = JSON.parse(text).current_service;
  expect(current.network_running).toBeNull();
  expect(current.interface_available).toBeNull();
  expect(current.webrtc_bridges).toBeNull();
  expect(current.pending_contacts_with_route).toBeNull();
  expect(current.pending_direct_messages.sending).toBeNull();
  expect(current.direct_outbox_status).toBe("unavailable");
  expect(text).not.toContain("secret");
  const renderer = currentWebRTCState([{key:"secret", path:"secret", approvalPending:"secret",
    channel:{readyState:"secret"}, pc:{connectionState:"secret", iceConnectionState:"secret"}}]);
  expect(renderer.channels.unavailable).toBe(1);
  expect(renderer.connections.connected).toBe(0);
  expect(renderer.pending_approvals).toBe(0);
  expect(JSON.stringify(renderer)).not.toContain("secret");
});

it("distinguishes native Android sessions from the empty browser registry", () => {
  const text = diagnosticReport({}, {current_native_webrtc: {status: "available", sessions: 1, attached: 1,
    stats_unavailable: 0, received_packets: 12, received_controls: 3,
    channels: {open: 1}, ice: {completed: 1}, session_id: "private-session", sdp: "private-sdp"}});
  const report = JSON.parse(text);
  expect(report.current_webrtc.source).toBe("renderer");
  expect(report.current_webrtc.sessions).toBe(0);
  expect(report.current_native_webrtc.source).toBe("native_service");
  expect(report.current_native_webrtc.sessions).toBe(1);
  expect(report.current_native_webrtc.channels.open).toBe(1);
  expect(report.current_native_webrtc.ice.completed).toBe(1);
  expect(report.current_native_webrtc.received_controls).toBe(3);
  expect(text).not.toContain("private-");
  const missing = JSON.parse(diagnosticReport({}, {})).current_native_webrtc;
  expect(missing.status).toBe("unavailable");
  expect(missing.sessions).toBeNull();
  expect(missing.channels.open).toBeNull();
});

it("reports background service evidence separately from the enabled preference", () => {
  const text = diagnosticReport({}, {current_background: {status: "available", enabled: true,
    native_enabled: true, health: "stopped", service_running: false, notification_visible: false,
    restorations: 1, failure: "private-error", token: "private-token"}});
  const current = JSON.parse(text).current_background;
  expect(current.enabled).toBe(true);
  expect(current.service_running).toBe(false);
  expect(current.notification_visible).toBe(false);
  expect(current.health).toBe("stopped");
  expect(current.restorations).toBe(1);
  expect(current.failure).toBe("unavailable");
  expect(text).not.toContain("private-");
  const missing = JSON.parse(diagnosticReport({}, {})).current_background;
  expect(missing.status).toBe("unavailable");
  expect(missing.service_running).toBeNull();
});

it("includes reconnect readiness reasons after restart without private pairing details", () => {
  const text = diagnosticReport({}, {current_reconnect:{status:"available", mailbox_configured:true,
    profiles:1, profiles_ready:0, profiles_with_mailbox:1, local_consent:0, peer_consent:0,
    states:{idle:1, "private-state":3}, reasons:{consent_missing:1, peer_consent_missing:1,
      local_capabilities_expired:1, "private-reason":3}, token:"private-token", session:"private-session"}});
  const report = JSON.parse(text);
  expect(report.current_webrtc.sessions).toBe(0);
  expect(report.current_reconnect.profiles_ready).toBe(0);
  expect(report.current_reconnect.reasons.consent_missing).toBe(1);
  expect(report.current_reconnect.reasons.local_capabilities_expired).toBe(1);
  expect(text).not.toContain("private-");
});

import { useEffect, useState } from "react";
import { appBuildInfo, serviceCommand } from "./api";
import packageInfo from "../package.json";
import { getWebRTCSessions } from "./webrtc-session";

const unavailable = "unavailable";
const phases = new Set(["waiting_for_reply", "waiting_for_ready", "ready_to_share", "ready_received", "connecting",
  "bootstrap_connected", "relationship_active", "admitted_path", "existing_routes_only", "refresh_required",
  "cancelled", "failed", "verified", "recovery", "unavailable", "connected", "reconnecting", "connection_update_needed", "dormant", "checking", "no_route", "network_changed", "test_failed", "both_no_address", "address_prepared", "no_local_address", "testing", "peer_verified", "complete"]);
const events = new Set(["state", "import_verified", "import_rejected", "action_failed", "lifecycle_interrupted"]);
const kinds = new Set(["offer", "answer", "ready", "recovery"]);
const commands = new Set(["preview_direct_connection", "prepare_direct_offer", "prepare_direct_answer", "prepare_direct_ready",
  "accept_direct_ready", "connect_direct_setup", "configure_direct_firewall", "direct_setup_status", "check_direct_setup", "retry_direct_setup", "cancel_direct_setup", "resume_direct_setup"]);
const errorCodes = new Set(["internal_error", "invalid_request", "identity_mismatch", "invitation_invalid", "invitation_expired",
  "workspace_already_known", "workspace_limit_reached", "protected_storage_unavailable", "profile_in_use", "network_unavailable",
  "direct_connection_unavailable", "native_unavailable", "contact_not_approved", "contact_in_use", "recipient_keys_unavailable",
  "stale_cursor", "history_pruned"]);
const failureStages = new Set(["runtime_check", "document_verification", "save_join_request", "join_authorization", "prepare_candidates",
  "sign_reply", "save_reply", "arm_socket", "verify_socket", "export_reply", "save_setup"]);
const failureReasons = new Set(["invitation_mismatch", "request_stopped", "request_expired", "identity_mismatch",
  "saved_request_invalid", "workspace_active", "workspace_not_pending",
  "ready_to_prepare", "no_default_route", "no_global_ipv4", "no_global_ipv6",
  "upnp_no_discovery", "upnp_wan_private", "upnp_wan_shared", "upnp_mapping_denied",
  "upnp_unsupported_lease", "nat_pmp_no_response", "nat_pmp_mapping_denied",
  "pcp_no_response", "pcp_mapping_denied", "upstream_nat_detected", "listener_bind_failed",
  "windows_firewall_blocked", "windows_firewall_permission_required", "firewall_check_unsupported",
  "session_limit", "direct_public_ipv4", "global_ipv6_available", "mapping_prepared",
  "router_state_changed", "manual_setup_required", "no_public_candidate", "no_eligible_route",
  "no_global_ipv6_route", "no_global_ipv6_address", "no_public_ipv4", "ipv6_pinhole_unavailable",
  "manual_forward_configured", "manual_forward_available", "mapping_not_attempted",
  "firewall_not_checked", "no_prepared_candidate"]);
const workspaceStates = new Set(["unavailable", "none", "joining", "active", "linking", "leaving", "left", "removed",
  "closed", "forked", "incomplete_sync"]);
function object(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}
const token = (value: unknown, pattern: RegExp) => typeof value === "string" && value.length < 100 && pattern.test(value) ? value : unavailable;
const version = (value: unknown) => token(value, /^\d+\.\d+\.\d+(?:[-+.][a-zA-Z0-9.]+)?$/);
const number = (value: unknown, max: number) => typeof value === "number" && Number.isSafeInteger(value) && value >= 0 && value <= max ? value : null;
const choice = (value: unknown, allowed: Set<string>) => typeof value === "string" && allowed.has(value) ? value : unavailable;
const boolean = (value: unknown) => typeof value === "boolean" ? value : null;
const pendingMessageStates = ["waiting_for_keys", "queued", "sending", "stored_for_delivery", "received_by_endpoint"];
const reconnectReasons = ["local_capabilities_missing", "peer_capabilities_missing", "peer_capabilities_expired",
  "local_capabilities_expired", "consent_missing", "peer_consent_missing", "relay_required", "mailbox_not_configured", "workspace_peer_inactive"];
const reconnectStates = ["idle", "waiting_for_peer", "probing", "offer_pending", "answer_pending", "connecting",
  "connected", "retry_wait", "peer_offline", "manual_required", "stopped", unavailable];

function currentReconnectState(raw: unknown) {
  const value = object(raw);
  return {
    status: choice(value.status, new Set(["available", unavailable])),
    mailbox_configured: boolean(value.mailbox_configured),
    ...Object.fromEntries(["profiles", "profiles_ready", "profiles_with_mailbox", "local_consent", "peer_consent"]
      .map(key => [key, number(value[key], Number.MAX_SAFE_INTEGER)])),
    states: Object.fromEntries(reconnectStates.map(key => [key, number(object(value.states)[key], Number.MAX_SAFE_INTEGER)])),
    reasons: Object.fromEntries(reconnectReasons.map(key => [key, number(object(value.reasons)[key], Number.MAX_SAFE_INTEGER)])),
  };
}

function currentServiceState(raw: unknown) {
  const value = object(raw);
  return {
    captured_at: number(value.captured_at, Number.MAX_SAFE_INTEGER),
    network_running: boolean(value.network_running), interface_available: boolean(value.interface_available),
    ...Object.fromEntries(["webrtc_bridges", "webrtc_online_bridges", "webrtc_received_bytes", "webrtc_sent_bytes",
      "pending_direct_contacts", "pending_contacts_with_route", "pending_contacts_with_keys", "pending_contacts_unchecked",
      "oldest_pending_direct_message_age_seconds"].map(key => [key, number(value[key], Number.MAX_SAFE_INTEGER)])),
    direct_outbox_status: choice(value.direct_outbox_status, new Set(["available", unavailable])),
    pending_direct_messages: Object.fromEntries(pendingMessageStates.map(key => [key,
      number(object(value.pending_direct_messages)[key], Number.MAX_SAFE_INTEGER)])),
  };
}

export function currentWebRTCState(raw: unknown = getWebRTCSessions()) {
  const sessions = (Array.isArray(raw) ? raw : []).map(object);
  const counts = (values: unknown[], allowed: string[]) => {
    const choices = new Set(allowed);
    return Object.fromEntries([...allowed, unavailable].map(key => [key,
      values.filter(value => choice(value, choices) === key).length]));
  };
  return {
    source: "renderer",
    sessions: sessions.length,
    channels: counts(sessions.map(session => object(session.channel).readyState), ["connecting", "open", "closing", "closed"]),
    connections: counts(sessions.map(session => object(session.pc).connectionState), ["new", "connecting", "connected", "disconnected", "failed", "closed"]),
    ice: counts(sessions.map(session => object(session.pc).iceConnectionState), ["new", "checking", "connected", "completed", "disconnected", "failed", "closed"]),
    paths: counts(sessions.map(session => session.path), ["direct", "relayed", "unknown"]),
    pending_approvals: sessions.filter(session => session.approvalPending === true).length,
  };
}

function currentNativeWebRTCState(raw: unknown) {
  const value = object(raw);
  const counts = (key: string, states: string[]) => Object.fromEntries(states.map(state =>
    [state, number(object(value[key])[state], Number.MAX_SAFE_INTEGER)]));
  return {
    source: "native_service",
    status: choice(value.status, new Set(["available", unavailable])),
    ...Object.fromEntries(["sessions", "attached", "stats_unavailable", "received_packets", "received_controls"]
      .map(key => [key, number(value[key], Number.MAX_SAFE_INTEGER)])),
    channels: counts("channels", ["connecting", "open", "closing", "closed", unavailable]),
    ice: counts("ice", ["new", "checking", "connected", "completed", "disconnected", "failed", "closed", unavailable]),
  };
}

export function versionDetails(raw: unknown) {
  const value = object(raw);
  const installed = version(value.installed_version);
  const native = version(value.native_version);
  return { renderer_version: packageInfo.version, installed_version: installed, native_version: native,
    platform: choice(value.platform, new Set(["windows", "android", "ios", "linux", "macos"])),
    os_version: token(value.os_version, /^[0-9][0-9. -]{0,40}$/),
    android_version_code: number(value.android_version_code, 2_100_000_000),
    build_commit: token(value.build_commit, /^[0-9a-f]{40}$/),
    version_mismatch: [installed, native].some(v => v !== unavailable && v !== packageInfo.version) };
}

export function diagnosticReport(build: unknown, raw: unknown, log = false) {
  const value = object(raw);
  const cleanEvent = (rawEvent: unknown) => {
    const event = object(rawEvent);
    return { time: number(event.time, 2**53 - 1), attempt: token(event.attempt, /^[0-9a-f]{12}$/),
      event: choice(event.event, events), phase: choice(event.phase, phases), kind: choice(event.kind, kinds),
      command: choice(event.command, commands), error_code: choice(event.error_code, errorCodes), failure_stage: choice(event.failure_stage, failureStages),
      failure_reason: choice(event.failure_reason, failureReasons), workspace_state: choice(event.workspace_state, workspaceStates),
      candidate_count: number(event.candidate_count, 8),
      route: choice(event.route, new Set(["available", "unavailable"])),
      socket: choice(event.socket, new Set(["retained", "unavailable"])),
      mapping: choice(event.mapping, new Set(["prepared_unverified", "unavailable", "not_needed"])),
      firewall: choice(event.firewall, new Set(["udp_permission_unverified", "windows_profile_known_udp_unverified", "windows_profile_unavailable_udp_unverified"])), expires_at: number(event.expires_at, 2**53 - 1),
      receipt_status: choice(event.receipt_status, new Set(["confirmed", "not_confirmed"])),
      approval_status: choice(event.approval_status, new Set(["approved", "pending"])),
      candidate_sources: Object.fromEntries(["ipv4", "ipv6", "local_global", "pcp", "upnp", "upnp_ipv6", "nat_pmp"].map(key => [key, number(object(event.candidate_sources)[key], 8)])),
      checks_started: number(event.checks_started, 64), checks_authenticated: number(event.checks_authenticated, 128), elapsed_ms: number(event.elapsed_ms, 3600_000) };
  };
  const history = Array.isArray(value.events) ? value.events : [];
  const rows = history.slice(log ? -200 : -12).map(cleanEvent);
  const serviceVersion = version(value.service_version);
  const report = { report_format: 1, captured_at: new Date().toISOString(), timezone_offset_minutes: new Date().getTimezoneOffset(),
    ...versionDetails(build), service_version: serviceVersion,
    service_version_mismatch: serviceVersion !== unavailable && serviceVersion !== packageInfo.version,
    service_status: value.format_version === 1 ? "available" : unavailable,
    current_service: currentServiceState(value.current_state), current_webrtc: currentWebRTCState(),
    current_native_webrtc: currentNativeWebRTCState(value.current_native_webrtc),
    current_reconnect: currentReconnectState(value.current_reconnect),
    native_check_counts: rows.at(-1)?.checks_started !== null && rows.length ? "see_event_counts" : unavailable, receipt_status: "see_event_timestamp", approval_status: "see_event_timestamp",
    retention_days: 7, event_limit: 200, events_included: rows.length, history_event_count: history.length,
    truncated: value.truncated === true || rows.length < history.length,
    last_failure: value.last_failure ? cleanEvent(value.last_failure) : null,
    events: rows };
  let text = JSON.stringify(report, null, 2);
  while (new TextEncoder().encode(text).length > 65536 && report.events.length) {
    report.events.shift(); report.events_included = report.events.length; report.truncated = true; text = JSON.stringify(report, null, 2);
  }
  return text;
}

export function ConnectionDiagnostics({ full = false }: { full?: boolean }) {
  const [build, setBuild] = useState<unknown>(null);
  const [feedback, setFeedback] = useState("");
  const [fallback, setFallback] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let active = true;
    void (async () => { try { const value = await appBuildInfo(); if (active) setBuild(value); } catch { /* Bundled version remains visible offline. */ } })();
    return () => { active = false; };
  }, []);
  const copy = async (mode: "summary" | "log" | "version") => {
    setBusy(true); setFeedback(""); setFallback("");
    let report: unknown = null;
    try { report = await serviceCommand("connection_diagnostics"); } catch { /* Copy app information even when the service cannot start. */ }
    const text = mode === "version"
      ? JSON.stringify({ ...versionDetails(build), service_version: version(object(report).service_version) }, null, 2)
      : diagnosticReport(build, report, mode === "log");
    try { await navigator.clipboard.writeText(text); setFeedback("Copied"); }
    catch { setFallback(text); setFeedback("Copy is unavailable. Select the report below or save it to a file."); }
    finally { setBusy(false); }
  };
  const clear = async () => {
    setBusy(true); setFeedback("");
    try { await serviceCommand("clear_connection_diagnostics"); setFallback(""); setFeedback("Diagnostic history cleared. Your workspace and messages are unchanged."); }
    catch { setFeedback("Diagnostic history could not be cleared. Try again when the app is unlocked."); }
    finally { setBusy(false); }
  };
  const save = () => {
    const url = URL.createObjectURL(new Blob([fallback], { type: "text/plain;charset=utf-8" }));
    const link = document.createElement("a"); link.href = url; link.download = "mesh-chat-diagnostics.txt"; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const details = versionDetails(build);
  return <section className="connection-diagnostics form-stack" aria-label="Connection diagnostics">
    <p className="muted">Mesh Chat version {packageInfo.version}</p>
    {details.version_mismatch && <p role="alert">App components have different versions. Copy version details before updating.</p>}
    <div className="dialog-actions"><button className="button button--secondary" disabled={busy} onClick={() => void copy("summary")}>Copy diagnostics</button>
      {full && <><button className="button button--secondary" disabled={busy} onClick={() => void copy("log")}>Copy connection log</button><button className="button button--secondary" disabled={busy} onClick={() => void copy("version")}>Copy version details</button></>}
    </div>
    {full && <><p className="muted">Recent connection events are kept on this device for 7 days, up to 200 events. Reports exclude addresses, invitation contents and messages. Nothing is uploaded.</p><button className="button button--secondary" disabled={busy} onClick={() => void clear()}>Clear diagnostic history</button></>}
    {feedback && <p role="status">{feedback}</p>}
    {fallback && <><label>Diagnostic report<textarea readOnly value={fallback} rows={8} onFocus={event => event.currentTarget.select()} /></label><button className="button button--secondary" onClick={save}>Save diagnostics</button></>}
  </section>;
}

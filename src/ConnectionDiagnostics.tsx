import { useEffect, useState } from "react";
import { appBuildInfo, serviceCommand } from "./api";
import packageInfo from "../package.json";

const unavailable = "unavailable";
const phases = new Set(["waiting_for_reply", "waiting_for_ready", "ready_to_share", "ready_received", "connecting",
  "bootstrap_connected", "relationship_active", "admitted_path", "existing_routes_only", "refresh_required",
  "cancelled", "failed", "verified", "recovery", "unavailable"]);
const events = new Set(["state", "import_verified", "import_rejected", "action_failed", "lifecycle_interrupted"]);
const kinds = new Set(["offer", "answer", "ready", "recovery"]);
function object(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}
const token = (value: unknown, pattern: RegExp) => typeof value === "string" && value.length < 100 && pattern.test(value) ? value : unavailable;
const version = (value: unknown) => token(value, /^\d+\.\d+\.\d+(?:[-+.][a-zA-Z0-9.]+)?$/);
const number = (value: unknown, max: number) => typeof value === "number" && Number.isSafeInteger(value) && value >= 0 && value <= max ? value : null;
const choice = (value: unknown, allowed: Set<string>) => typeof value === "string" && allowed.has(value) ? value : unavailable;

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
      candidate_count: number(event.candidate_count, 8), expires_at: number(event.expires_at, 2**53 - 1) };
  };
  const rows = Array.isArray(value.events) ? value.events.slice(-200).map(cleanEvent) : [];
  const serviceVersion = version(value.service_version);
  return JSON.stringify({ report_format: 1, captured_at: new Date().toISOString(), timezone_offset_minutes: new Date().getTimezoneOffset(),
    ...versionDetails(build), service_version: serviceVersion,
    service_version_mismatch: serviceVersion !== unavailable && serviceVersion !== packageInfo.version,
    service_status: value.format_version === 1 ? "available" : unavailable,
    native_check_counts: unavailable, receipt_status: unavailable, approval_status: unavailable,
    retention_days: 7, event_limit: 200, truncated: value.truncated === true,
    last_failure: value.last_failure ? cleanEvent(value.last_failure) : null,
    events: log ? rows : rows.slice(-1) }, null, 2);
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
    <div className="dialog-actions"><button disabled={busy} onClick={() => void copy("summary")}>Copy diagnostics</button>
      {full && <><button disabled={busy} onClick={() => void copy("log")}>Copy connection log</button><button disabled={busy} onClick={() => void copy("version")}>Copy version details</button></>}
    </div>
    {full && <><p className="muted">Recent connection events are kept on this device for 7 days, up to 200 events. Reports exclude addresses, invitation contents and messages. Nothing is uploaded.</p><button disabled={busy} onClick={() => void clear()}>Clear diagnostic history</button></>}
    {feedback && <p role="status">{feedback}</p>}
    {fallback && <><label>Diagnostic report<textarea readOnly value={fallback} rows={8} onFocus={event => event.currentTarget.select()} /></label><button onClick={save}>Save diagnostics</button></>}
  </section>;
}

import { useCallback, useEffect, useState } from "react";
import { RefreshCw, ShieldAlert } from "lucide-react";

import { serviceCommand } from "./api";
import {
  RECONNECT_CAPABILITIES_EVENT,
  sendReconnectCapabilities,
} from "./reconnect-control";
import {
  reconnectStatusDetail,
  reconnectStatusLabel,
  type ReconnectCoordinator,
  type ReconnectEntry,
  type ReconnectProfile,
  type ReconnectProfilesPayload,
  type ReconnectSnapshot,
} from "./reconnect-coordinator";
import type { Contact } from "./types";

const EMPTY: ReconnectSnapshot = { running: false, entries: {} };

function reasonLabel(code: string): string {
  switch (code) {
    case "contact_not_approved":
      return "Only an approved, non-blocked contact can reconnect automatically.";
    case "invalid_request":
      return "These reconnect settings are not valid for this contact yet.";
    case "mailbox_unauthorized":
      return "The signaling mailbox rejected this device's capability. Exchange a fresh link.";
    case "mailbox_rate_limited":
      return "The signaling mailbox is rate limiting this device. Try again shortly.";
    case "network_unavailable":
      return "The signaling mailbox is unreachable right now.";
    default:
      return code || "The reconnect setting could not be saved.";
  }
}

function setupHints(profile: ReconnectProfile | null): string[] {
  if (!profile) return [];
  return profile.effective.reasons.map((reason) => {
    switch (reason) {
      case "mailbox_not_configured":
        return "Automatic reconnect needs a signaling mailbox. Configure one in Settings → Advanced → WebRTC calls.";
      case "local_capabilities_missing":
      case "peer_capabilities_missing":
        return "Reconnect settings have not been exchanged yet. Keep the contact connected to finish setup.";
      case "peer_capabilities_expired":
      case "local_capabilities_expired":
        return "The reconnect settings expired. They need to be refreshed while the contact is connected.";
      case "consent_missing":
        return "Automatic reconnect is turned off for this contact.";
      case "peer_consent_missing":
        return "Automatic reconnect is turned off on the contact’s device.";
      case "relay_required":
        return "Direct IP disclosure is off. Enable the community relay or allow direct IP disclosure.";
      default:
        return "";
    }
  }).filter(Boolean);
}

export function ReconnectSettings({
  contact,
  coordinator,
  onChanged,
}: {
  contact: Contact;
  coordinator: ReconnectCoordinator | null;
  onChanged: () => Promise<void>;
}) {
  const [payload, setPayload] = useState<ReconnectProfilesPayload | null>(null);
  const [snapshot, setSnapshot] = useState<ReconnectSnapshot>(() =>
    coordinator ? coordinator.snapshot() : EMPTY,
  );
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const eligible = contact.trust === "approved" || contact.trust === "verified";

  const load = useCallback(async () => {
    if (!eligible) {
      setPayload(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const value = await serviceCommand<ReconnectProfilesPayload>("reconnect_profiles");
      setPayload(value && Array.isArray(value.profiles) ? value : null);
    } catch {
      // The service may be locked between renders.
    } finally {
      setLoading(false);
    }
  }, [eligible]);

  useEffect(() => {
    void load();
  }, [load, contact.id]);

  useEffect(() => {
    if (!coordinator) return;
    setSnapshot(coordinator.snapshot());
    return coordinator.subscribe(() => setSnapshot(coordinator.snapshot()));
  }, [coordinator]);

  useEffect(() => {
    const listener = () => void load();
    window.addEventListener(RECONNECT_CAPABILITIES_EVENT, listener);
    return () => window.removeEventListener(RECONNECT_CAPABILITIES_EVENT, listener);
  }, [load]);

  const profile = Array.isArray(payload?.profiles)
    ? payload.profiles.find((item) => item.contact_id === contact.id) ?? null
    : null;
  const entry: ReconnectEntry | undefined = Object.values(snapshot.entries).find(
    (item) => item.contactId === contact.id,
  );
  const retryPending = entry?.state === "retry_wait";
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!retryPending) return;
    // The label reads the current clock, so re-render once per second while a
    // backoff is pending to keep "Reconnecting in Ns" honest.
    const timer = window.setInterval(() => setTick((value) => value + 1), 1000);
    return () => window.clearInterval(timer);
  }, [retryPending]);

  const save = async (
    autoReconnect: boolean,
    allowDirectIpDisclosure: boolean,
  ) => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await serviceCommand<{
        profile: ReconnectProfile;
        capabilities: string | null;
        changed: boolean;
      }>("reconnect_consent_set", {
        contact_id: contact.id,
        auto_reconnect: autoReconnect,
        allow_direct_ip_disclosure: allowDirectIpDisclosure,
      });
      const shared = result.capabilities
        ? sendReconnectCapabilities(result.capabilities, contact.id)
        : false;
      if (autoReconnect) {
        setNotice(
          shared
            ? "Saved. Signed settings were shared with the contact."
            : "Saved. The signed settings will be shared the next time both devices are connected.",
        );
      } else {
        setNotice(
          shared
            ? "Automatic reconnect is off and the change was shared."
            : "Automatic reconnect is off on this device.",
        );
      }
      await load();
      await onChanged();
      if (!autoReconnect) {
        await coordinator?.stop(contact.id);
      } else if (result.profile.effective.ready) {
        await coordinator?.retryNow(contact.id);
      }
    } catch (reason) {
      const code =
        reason && typeof reason === "object" && "code" in reason
          ? String((reason as { code?: unknown }).code ?? "")
          : reason instanceof Error
            ? reason.message
            : "";
      setError(reasonLabel(code));
    } finally {
      setBusy(false);
    }
  };

  if (!eligible) {
    return (
      <section className="reconnect-settings" aria-label="Automatic reconnect">
        <p className="muted">Automatic reconnect becomes available after this contact is approved.</p>
      </section>
    );
  }

  const hints = setupHints(profile);
  const statusLabel = entry
    ? reconnectStatusLabel(entry)
    : loading
      ? "Loading reconnect settings…"
      : !profile
        ? "Reconnect settings unavailable"
        : !profile.auto_reconnect
          ? "Auto-reconnect is off"
          : profile.effective.ready
            ? "Waiting for contact"
            : "Reconnect setup incomplete";
  const statusDetail = entry
    ? reconnectStatusDetail(entry)
    : profile?.auto_reconnect && profile.effective.ready
      ? "Automatic reconnect is ready. Waiting for the contact to be online."
      : "";
  return (
    <section className="reconnect-settings stack" aria-label="Automatic reconnect">
      <div className="reconnect-settings__heading">
        <RefreshCw size={18} aria-hidden="true" />
        <span>
          <strong>Automatic reconnect</strong>
          <small className={entry?.state === "manual_required" ? "reconnect-status reconnect-status--warning" : "reconnect-status"} role="status">
            {statusLabel}
          </small>
        </span>
      </div>
      <p className="muted">
        Automatic reconnect is on by default for new approved contacts. Once setup is ready,
        they reconnect when both apps are open and unlocked. Your direct IP and relay choices still apply.
      </p>
      <label className="toggle-row">
        <span>
          <strong>Reconnect automatically</strong>
          <small>Messages wait safely while the contact is offline. You can turn reconnect off for this contact.</small>
        </span>
        <input
          type="checkbox"
          checked={Boolean(profile?.auto_reconnect)}
          disabled={busy || loading}
          onChange={() =>
            void save(!profile?.auto_reconnect, Boolean(profile?.allow_direct_ip_disclosure))
          }
        />
        <i aria-hidden="true" />
      </label>
      <label className="toggle-row">
        <span>
          <strong>Allow direct IP disclosure</strong>
          <small>Separate from contact approval. Without it, reconnect prefers the relay.</small>
        </span>
        <input
          type="checkbox"
          checked={Boolean(profile?.allow_direct_ip_disclosure)}
          disabled={busy || loading}
          onChange={() =>
            void save(Boolean(profile?.auto_reconnect), !profile?.allow_direct_ip_disclosure)
          }
        />
        <i aria-hidden="true" />
      </label>
      {statusDetail && (
        <p className="muted" role="status">{statusDetail}</p>
      )}
      {hints.length > 0 && (
        <ul className="reconnect-hints">
          {hints.map((hint) => (
            <li key={hint}><ShieldAlert size={15} aria-hidden="true" /> {hint}</li>
          ))}
        </ul>
      )}
      {notice && <p className="muted" role="status">{notice}</p>}
      {error && <p className="form-error" role="alert">{error}</p>}
      <div className="dialog-actions">
        <button
          className="button button--secondary"
          type="button"
          disabled={busy || !profile?.effective.ready}
          onClick={() => void coordinator?.retryNow(contact.id)}
        >
          Retry now
        </button>
        <button
          className="button button--secondary"
          type="button"
          disabled={busy || !profile?.auto_reconnect}
          onClick={() => void coordinator?.stop(contact.id)}
        >
          Stop
        </button>
        <button
          className="button button--ghost"
          type="button"
          disabled={busy || (!profile?.auto_reconnect && !profile?.has_local_capabilities)}
          onClick={() => void save(false, false)}
        >
          Forget auto-reconnect
        </button>
      </div>
    </section>
  );
}

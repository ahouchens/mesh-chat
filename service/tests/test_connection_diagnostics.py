import json
import os
import time
from types import SimpleNamespace

import pytest

from mesh_chat import connection_diagnostics as diagnostics


class Store:
    def __init__(self):
        self.rows = {}
    def get(self, kind, key):
        return self.rows.get((kind, key))
    def put(self, kind, key, value):
        self.rows[kind, key] = value
    def delete(self, kind, key):
        self.rows.pop((kind, key), None)
    def list(self, kind):
        return [value for (row_kind, _), value in self.rows.items() if row_kind == kind]


def test_allowlist_excludes_seeded_secrets_and_unexpected_structures():
    service = SimpleNamespace(store=Store())
    secret = "MESHWORKSPACE-secret-key-192.0.2.1-person-name"
    diagnostics.record(service, "state", {"setup_id":secret, "state":"existing_routes_only", "kind":"ready",
        "candidate_count":2, "expires_at":int(time.time())+60, "text":secret, "private_key":secret})
    value = diagnostics.report(service)
    assert secret not in json.dumps(value)
    assert value["last_failure"]["phase"] == "existing_routes_only"
    assert len(value["last_failure"]["attempt"]) == 12
    assert diagnostics.sanitize({"event":[], "phase":{}, "kind":secret})["phase"] == "unavailable"


def test_history_bounded_and_latest_failure_survives_new_service_instance():
    service = SimpleNamespace(store=Store())
    diagnostics.record(service, "action_failed", {"state":"failed"})
    for index in range(220):
        diagnostics.record(service, "state", {"state":"connecting", "setup_id":str(index)})
    reopened = SimpleNamespace(store=service.store)
    value = diagnostics.report(reopened)
    assert 0 < len(value["events"]) <= 200
    assert len(service.store.get("connection_diagnostics", "history")["events"]) == 200
    assert value["truncated"] is True
    assert value["last_failure"]["phase"] == "failed"
    assert len(json.dumps(value).encode()) < 65536


@pytest.mark.parametrize("phase", ["no_route", "network_changed", "test_failed", "both_no_address"])
def test_readiness_failure_survives_later_success_and_history_rollover(phase):
    service = SimpleNamespace(store=Store())
    diagnostics.record(service, "state", {"state": phase, "setup_id": "failed-attempt"})
    for index in range(diagnostics.LIMIT + 1):
        diagnostics.record(service, "state", {"state": "peer_verified", "setup_id": str(index)})
    reopened = SimpleNamespace(store=service.store)
    report = diagnostics.report(reopened)
    assert all(row["phase"] == "peer_verified" for row in report["events"])
    assert report["last_failure"]["phase"] == phase


def test_one_sided_preparation_is_not_saved_as_a_failure():
    service = SimpleNamespace(store=Store())
    diagnostics.record(service, "state", {"state": "no_local_address"})
    assert diagnostics.report(service)["last_failure"] is None


def test_expired_diagnostics_are_not_exported(monkeypatch):
    service = SimpleNamespace(store=Store())
    diagnostics.record(service, "action_failed", {"state":"failed"})
    future = time.time() + diagnostics.RETENTION + 1
    monkeypatch.setattr(diagnostics.time, "time", lambda:future)
    assert diagnostics.report(service)["events"] == []
    assert diagnostics.report(service)["last_failure"] is None
    assert service.store.get("connection_diagnostics", "history")["events"] == []
    assert service.store.get("connection_diagnostics", "history")["last_failure"] is None


def test_capture_failure_does_not_change_operation_outcome():
    class BrokenStore(Store):
        def put(self, *args):
            raise OSError("private-path-and-secret")
    diagnostics.record(SimpleNamespace(store=BrokenStore()), "action_failed", {"state":"failed"})


def test_report_captures_current_outbox_and_transport_without_private_content(monkeypatch):
    monkeypatch.setattr(diagnostics.time, "time", lambda: 2000)
    secret = "private-contact-name-invitation-message"
    store = Store()
    store.put("contact", secret, {"destination_hash": "ab" * 16, "display_name": secret})
    for index, (direction, kind, state) in enumerate([
        ("outbound", "chat", "sending"), ("outbound", "chat", "queued"),
        ("outbound", "chat", "received_by_endpoint"), ("outbound", "chat", "delivered"),
        ("outbound", "reaction", "queued"), ("inbound", "chat", "queued"),
    ]):
        store.put("message", str(index), {"direction": direction, "kind": kind, "state": state,
            "contact_id": secret, "created_at": 1800 + index, "text": secret})
    service = SimpleNamespace(store=store, network=SimpleNamespace(interface_available=True,
        path_known=lambda destination: False, recipient_ready=lambda destination: True),
        _webrtc_bridges={secret: SimpleNamespace(online=True, rxb=123, txb=456)})
    diagnostics.record(service, "action_failed", {"state": "failed"})
    report = diagnostics.report(service)
    current = report["current_state"]
    assert current["captured_at"] == 2000
    assert current["pending_direct_messages"] == {"waiting_for_keys": 0, "queued": 1,
        "sending": 1, "stored_for_delivery": 0, "received_by_endpoint": 1}
    assert current["oldest_pending_direct_message_age_seconds"] == 200
    assert current["pending_direct_contacts"] == 1
    assert current["pending_contacts_with_route"] == 0
    assert current["pending_contacts_with_keys"] == 1
    assert current["webrtc_online_bridges"] == 1
    assert current["webrtc_received_bytes"] == 123
    assert current["webrtc_sent_bytes"] == 456
    assert secret not in json.dumps(report)
    assert "ab" * 16 not in json.dumps(report)
    service.network = None
    service._webrtc_bridges.clear()
    current = diagnostics.report(service)["current_state"]
    assert current["network_running"] is False
    assert current["webrtc_bridges"] == 0
    assert current["pending_direct_messages"]["sending"] == 1


def test_native_diagnostics_survive_renderer_absence_without_exporting_session_details():
    secret = "private-session-peer-sdp-control-message"
    service = SimpleNamespace(store=Store(), _native_webrtc_live={secret},
        native_webrtc_stats=lambda session_id: {
            "attached": True, "data_channel_state": "open", "ice_connection_state": "completed",
            "received_packets": 12, "received_controls": 3, "session_id": session_id, "sdp": secret,
        })
    current = diagnostics.report(service)["current_native_webrtc"]
    assert current["status"] == "available"
    assert current["sessions"] == current["attached"] == 1
    assert current["channels"]["open"] == current["ice"]["completed"] == 1
    assert current["received_controls"] == 3
    assert secret not in json.dumps(current)
    service._native_webrtc_live.clear()
    assert diagnostics.report(service)["current_native_webrtc"]["sessions"] == 0


def test_missing_native_statistics_are_unknown_and_do_not_hide_other_sessions():
    def stats(session_id):
        if session_id == "closed-during-inspection":
            raise RuntimeError("private-native-error")
        return {"attached": "yes", "data_channel_state": {}, "ice_connection_state": "private-state",
                "received_packets": -1, "received_controls": True}
    service = SimpleNamespace(store=Store(), _native_webrtc_live={"closed-during-inspection", "other"},
        native_webrtc_stats=stats)
    current = diagnostics.report(service)["current_native_webrtc"]
    assert current["sessions"] == 2
    assert current["stats_unavailable"] == 1
    assert current["attached"] == 0
    assert current["channels"]["unavailable"] == current["ice"]["unavailable"] == 2
    assert current["received_packets"] == current["received_controls"] == 0
    assert "private-" not in json.dumps(current)
    assert diagnostics.native_webrtc_state(SimpleNamespace()) == {"status": "unavailable"}


def test_background_diagnostics_distinguish_opt_in_from_running_service():
    service = SimpleNamespace(store=Store(), background_availability_status=lambda: {
        "enabled": True, "health": "stopped", "lifecycle_state": "background_available",
        "native": {"enabled": True, "service_running": False, "runtime_initialized": True,
                   "notification_visible": False, "restorations": 1, "private": "secret"},
    })
    current = diagnostics.report(service)["current_background"]
    assert current["enabled"] is True
    assert current["service_running"] is False
    assert current["notification_visible"] is False
    assert current["health"] == "stopped"
    assert current["restorations"] == 1
    assert "secret" not in json.dumps(current)
    service.background_availability_status = lambda: {
        "enabled": "secret", "health": {}, "native": {"failure": "secret", "restorations": True}}
    current = diagnostics.report(service)["current_background"]
    assert current["enabled"] is None
    assert current["health"] == current["failure"] == "unavailable"
    assert current["restorations"] is None
    assert "secret" not in json.dumps(current)


def test_unreadable_current_outbox_does_not_hide_historical_failure():
    class BrokenListStore(Store):
        def list(self, kind):
            raise OSError("private-path-and-secret")
    service = SimpleNamespace(store=BrokenListStore())
    diagnostics.record(service, "action_failed", {"state": "failed"})
    report = diagnostics.report(service)
    assert report["last_failure"]["phase"] == "failed"
    assert report["current_state"]["direct_outbox_status"] == "unavailable"
    assert "private-path" not in json.dumps(report)


def test_unreadable_interface_status_is_unknown_and_keeps_outbox_evidence():
    class BrokenNetwork:
        @property
        def interface_available(self):
            raise RuntimeError("private-network-details")
    report = diagnostics.report(SimpleNamespace(store=Store(), network=BrokenNetwork()))
    assert report["current_state"]["interface_available"] is None
    assert report["current_state"]["network_running"] is True
    assert report["current_state"]["direct_outbox_status"] == "available"
    assert "private-network-details" not in json.dumps(report)


def test_reconnect_summary_reports_readiness_and_consent_without_tokens_or_mutations(monkeypatch):
    from mesh_chat.reconnect_service import ReconnectServiceMixin
    from mesh_chat import reconnect_service
    monkeypatch.setattr(reconnect_service, "_now", lambda: 2000)
    secret = "private-mailbox-token-url-document-name"
    class Service(ReconnectServiceMixin):
        pass
    service = Service()
    service.store = Store()
    service._call_settings = SimpleNamespace(signal_mailbox_url=secret, turn_url=None,
        turn_broker_url=None, turn_broker_consent=False)
    expired = {"id": secret, "contact_id": secret, "state": secret,
        "local_capabilities": secret, "remote_capabilities": secret,
        "local_capabilities_expires_at": 1999, "remote_capabilities_expires_at": 1999,
        "auto_reconnect": False, "remote_auto_reconnect": False,
        "allow_direct_ip_disclosure": False, "mailbox_url": secret,
        "mailbox_pair_token": secret, "mailbox_expires_at": 1999}
    service.store.put("reconnect_profile", "expired", expired)
    service.store.put("reconnect_profile", "ready", {**expired, "state": "idle",
        "local_capabilities_expires_at": 3000, "remote_capabilities_expires_at": 3000,
        "auto_reconnect": True, "remote_auto_reconnect": True,
        "allow_direct_ip_disclosure": True, "mailbox_expires_at": 3000})
    before = dict(service.store.rows)
    current = diagnostics.reconnect_state(service)
    assert current["profiles"] == 2
    assert current["profiles_ready"] == 1
    assert current["profiles_with_mailbox"] == 1
    assert current["mailbox_configured"] is True
    assert current["local_consent"] == current["peer_consent"] == 1
    for reason in ("local_capabilities_expired", "peer_capabilities_expired", "consent_missing",
                   "peer_consent_missing", "relay_required", "mailbox_not_configured"):
        assert current["reasons"][reason] == 1
    assert current["states"]["unavailable"] == 1
    assert current["states"]["idle"] == 1
    assert service.store.rows == before
    assert secret not in json.dumps(current)


def test_failure_context_is_allowlisted_and_missing_attempt_is_not_a_fake_identifier():
    service = SimpleNamespace(store=Store())
    secret = "private-key-192.0.2.1-invitation-document"
    diagnostics.record(service, "action_failed", {"state":"failed",
        "command":"prepare_direct_answer", "error_code":"workspace_already_known",
        "failure_stage":"join_authorization", "failure_reason":"invitation_mismatch",
        "workspace_state":"joining", "exception":secret, "document":secret})
    row = diagnostics.report(service)["last_failure"]
    assert row["command"] == "prepare_direct_answer"
    assert row["error_code"] == "workspace_already_known"
    assert row["failure_stage"] == "join_authorization"
    assert row["failure_reason"] == "invitation_mismatch"
    assert row["workspace_state"] == "joining"
    assert row["attempt"] == "unavailable"
    assert secret not in json.dumps(row)
    diagnostics.record(service, "action_failed", {"state":"failed",
        "command":secret, "error_code":secret, "failure_stage":secret,
        "failure_reason":secret, "workspace_state":secret})
    row = diagnostics.report(service)["last_failure"]
    assert all(row[key] == "unavailable" for key in ("command", "error_code", "failure_stage"))
    assert row["failure_reason"] == "unavailable"
    assert row["workspace_state"] == "unavailable"
    assert secret not in json.dumps(diagnostics.report(service))


def test_unknown_workspace_state_is_unavailable_not_silently_none():
    service = SimpleNamespace(store=Store())
    diagnostics.record(service, "action_failed", {"state":"failed", "command":"prepare_direct_answer"})
    row = diagnostics.report(service)["last_failure"]
    assert row["workspace_state"] == "unavailable"
    assert row["failure_reason"] == "unavailable"


def test_network_failure_reason_is_allowlisted_and_secrets_are_not():
    service = SimpleNamespace(store=Store())
    diagnostics.record(service, "action_failed", {"state":"failed",
        "command":"prepare_direct_offer", "failure_stage":"prepare_candidates",
        "failure_reason":"upnp_no_discovery", "workspace_state":"unavailable"})
    row = diagnostics.report(service)["last_failure"]
    assert row["failure_reason"] == "upnp_no_discovery"
    diagnostics.record(service, "action_failed", {"state":"failed",
        "failure_reason":"private-router-192.0.2.1", "workspace_state":"joining"})
    row = diagnostics.report(service)["last_failure"]
    assert row["failure_reason"] == "unavailable"
    assert "private-router" not in json.dumps(diagnostics.report(service))


def test_failure_survives_encrypted_vault_reopen_and_clear_preserves_workspace(tmp_path):
    from mesh_chat.vault import VaultStore
    key = os.urandom(32)
    store = VaultStore(tmp_path / "profile", key, allow_unprotected_for_tests=True)
    secret = "synthetic-secret-document-never-in-diagnostics"
    try:
        store.put("workspace", "saved", {"state":"joining", "request":"preserve-this-request"})
        diagnostics.record(SimpleNamespace(store=store), "state", {
            "setup_id":"attempt", "state":"existing_routes_only", "document":secret})
    finally:
        store.close()
    reopened = VaultStore(tmp_path / "profile", key, allow_unprotected_for_tests=True)
    try:
        report = diagnostics.report(SimpleNamespace(store=reopened))
        assert report["last_failure"]["phase"] == "existing_routes_only"
        assert secret not in json.dumps(report)
        before = reopened.get("workspace", "saved")
        reopened.delete("connection_diagnostics", "history")
        assert diagnostics.report(SimpleNamespace(store=reopened))["events"] == []
        assert reopened.get("workspace", "saved") == before
    finally:
        reopened.close()
    assert secret.encode() not in (tmp_path / "profile" / "mesh-chat.vault").read_bytes()

from __future__ import annotations

from pathlib import Path

from mesh_chat.background_availability import BackgroundAvailabilityMixin

ROOT = Path(__file__).resolve().parents[2]


class Store:
    def __init__(self) -> None:
        self.records: dict[tuple[str, str], dict] = {}

    def opaque_id(self, namespace: str, *parts: str) -> str:
        return f"{namespace}:{':'.join(parts)}"

    def get(self, kind: str, identifier: str):
        value = self.records.get((kind, identifier))
        return dict(value) if value is not None else None

    def put(self, kind: str, identifier: str, value: dict) -> None:
        self.records[(kind, identifier)] = dict(value)


class Host(BackgroundAvailabilityMixin):
    def __init__(self) -> None:
        self.store = Store()
        self.changed = 0

    def _workspace_lifecycle_state(self) -> dict:
        return {"state": "foreground"}

    def _changed(self) -> None:
        self.changed += 1


def test_default_is_off_and_status_is_sanitized() -> None:
    host = Host()
    status = host.background_availability_status()
    assert status["enabled"] is False
    assert status["state"] == "disabled"
    assert status["mode"] == "native_webrtc"
    assert status["lifecycle_state"] == "foreground"
    assert set(status) == {
        "enabled", "mode", "state", "reason", "lifecycle_state", "updated_at", "health",
    }


def test_enable_and_disable_are_idempotent() -> None:
    host = Host()
    enabled = host.set_background_availability(True)
    assert enabled["enabled"] is True
    assert enabled["state"] == "enabled"
    assert enabled["reason"] == "user_enabled"
    assert host.changed == 1

    again = host.set_background_availability(True)
    assert again["enabled"] is True
    assert host.changed == 1

    disabled = host.set_background_availability(False)
    assert disabled["enabled"] is False
    assert disabled["state"] == "disabled"
    assert disabled["reason"] == "user_disabled"
    assert host.changed == 2


def test_lock_overrides_a_persisted_opt_in() -> None:
    host = Host()
    host.set_background_availability(True)
    locked = host.lock_background_availability()
    assert locked["enabled"] is False
    assert locked["state"] == "locked"
    assert locked["reason"] == "explicit_lock"
    assert host._background_availability_enabled() is False


def test_available_requires_the_actual_native_service_and_initialized_runtime(monkeypatch):
    host = Host()
    host.set_background_availability(True)
    native = {"enabled": True, "service_running": False, "runtime_initialized": False}
    monkeypatch.setattr(host, "_native_background_status", lambda: dict(native))
    assert host.background_availability_status()["health"] == "starting"
    native.update(service_running=True, runtime_initialized=True)
    assert host.background_availability_status()["health"] == "available"
    native["service_running"] = False
    assert host.background_availability_status()["health"] != "available"
    native.update(enabled=False, failure="foreground_start_denied")
    assert host.background_availability_status()["health"] == "failed"


def test_enabled_lifecycle_does_not_retire_native_transports() -> None:
    lifecycle = (ROOT / "service" / "src" / "mesh_chat" / "workspace_service.py").read_text(
        encoding="utf-8"
    )
    assert '"suspended" and getattr(' in lifecycle
    assert '"_background_availability_enabled", lambda: False' in lifecycle
    assert 'state = "background_available"' in lifecycle
    assert '"background_available", "suspended"' in lifecycle

    service = (ROOT / "service" / "src" / "mesh_chat" / "service.py").read_text(
        encoding="utf-8"
    )
    assert '"set_background_availability"' in service
    assert '"background_status"' in service
    assert '"native_webrtc_offer"' in service
    assert '"native_webrtc_accept"' in service
    assert '"background_availability": self.background_availability_status()' in service

    rust = (ROOT / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
    assert '| "set_background_availability"' in rust
    assert '| "background_status"' in rust


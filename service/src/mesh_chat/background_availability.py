"""Device-local background availability preference and status.

This is not a canonical protocol record. It only says whether this device has
asked Android to keep the messaging runtime and native WebRTC transport alive
while the screen is off. The Android foreground service is the authority for
whether the process is actually being kept alive; the renderer must merge that
native status rather than trusting this record alone.
"""

from __future__ import annotations

import time
import json
import hashlib
import uuid
from contextlib import nullcontext
from typing import Any

from .errors import ValidationError

KIND = "background_availability"
VERSION = 1
STATES = {"disabled", "enabled", "locked"}
MAX_REASON = 64


class BackgroundAvailabilityMixin:
    def _background_availability_id(self) -> str:
        return self.store.opaque_id("mobile-background-availability", "device")

    def _background_availability_record(self) -> dict[str, Any]:
        record = self.store.get(KIND, self._background_availability_id())
        if record is None:
            return {
                "v": VERSION,
                "enabled": False,
                "mode": "native_webrtc",
                "enabled_at": 0,
                "disabled_at": 0,
                "last_state": "disabled",
                "last_reason": "not_configured",
                "updated_at": 0,
            }
        if (
            not isinstance(record, dict)
            or record.get("v") != VERSION
            or not isinstance(record.get("enabled"), bool)
        ):
            return {
                "v": VERSION,
                "enabled": False,
                "mode": "native_webrtc",
                "enabled_at": 0,
                "disabled_at": 0,
                "last_state": "disabled",
                "last_reason": "invalid_record",
                "updated_at": 0,
            }
        return record

    def _background_availability_enabled(self) -> bool:
        return self._background_availability_record().get("enabled") is True

    def _write_background_availability(
        self,
        *,
        enabled: bool,
        state: str,
        reason: str,
    ) -> dict[str, Any]:
        record = self._prepare_background_availability(enabled=enabled, state=state, reason=reason)
        self.store.put(KIND, self._background_availability_id(), record)
        return record

    def _prepare_background_availability(
        self, *, enabled: bool, state: str, reason: str,
    ) -> dict[str, Any]:
        if not isinstance(enabled, bool) or state not in STATES:
            raise ValidationError("Background availability state is invalid")
        if not isinstance(reason, str) or not 1 <= len(reason) <= MAX_REASON:
            raise ValidationError("Background availability reason is invalid")
        now = int(time.time())
        current = self._background_availability_record()
        return {
            "v": VERSION,
            "enabled": enabled,
            "mode": "native_webrtc",
            "enabled_at": now if enabled and not current.get("enabled") else int(
                current.get("enabled_at", 0)
            ),
            "disabled_at": 0 if enabled else now,
            "last_state": state,
            "last_reason": reason,
            "updated_at": now,
        }

    def background_availability_status(self) -> dict[str, Any]:
        record = self._background_availability_record()
        lifecycle = self._workspace_lifecycle_state()
        status = {
            "enabled": record.get("enabled") is True,
            "mode": "native_webrtc",
            "state": record.get("last_state", "disabled"),
            "reason": record.get("last_reason", "not_configured"),
            "lifecycle_state": lifecycle.get("state", "foreground"),
            "updated_at": int(record.get("updated_at", 0)),
        }
        native = self._native_background_status()
        if native is not None:
            if native.get("enabled") and not status["enabled"] and status["reason"] == "not_configured":
                # Android's first-unlock migration establishes the default
                # before its foreground service persists the runtime state.
                status.update(enabled=True, state="enabled", reason="default_enabled")
            status["native"] = native
            status["health"] = (
                "off" if not status["enabled"] else
                "permission_required" if native.get("enabled") and native.get("notification_state") in {"not_requested", "denied", "blocked"} else
                "failed" if not native.get("enabled") or native.get("failure") else
                "stopped" if not native.get("service_running") and not native.get("start_requested") else
                ("degraded" if native.get("native_webrtc_ready") is False else "available")
                if native.get("service_running") and native.get("runtime_initialized") else
                "starting"
            )
        else:
            status["health"] = "unknown" if status["enabled"] else "off"
        return status

    @staticmethod
    def _native_background_status() -> dict[str, Any] | None:
        try:
            from java import jclass

            value = json.loads(str(jclass("com.meshchat.runtime.BackgroundRuntime").status()))
            return value if isinstance(value, dict) else None
        except Exception:
            return None

    def _sync_background_reconnect(self) -> None:
        if getattr(self, "_connection_policy", "legacy") == "shared-native":
            # Foreground/background are observations of the same policy owner.
            return
        supervisor = getattr(self, "_background_reconnect_supervisor", None)
        if not self._background_availability_enabled():
            if supervisor is not None:
                supervisor.stop()
                self._background_reconnect_supervisor = None
            return
        if supervisor is not None:
            return
        if not all(
            hasattr(self, name)
            for name in (
                "reconnect_profiles",
                "native_webrtc_offer",
                "call_ice_servers",
            )
        ):
            return
        try:
            from .background_reconnect import BackgroundReconnectSupervisor

            supervisor = BackgroundReconnectSupervisor(self)
            supervisor.start()
            self._background_reconnect_supervisor = supervisor
        except Exception:
            # Availability remains enabled; the foreground renderer can still
            # establish the link. Do not corrupt the local preference because a
            # background thread could not start.
            self._background_reconnect_supervisor = None

    def set_background_availability(
        self, enabled: Any, *, operation_id: str | None = None,
    ) -> dict[str, Any]:
        with getattr(self, "_dispatch_lock", nullcontext()):
            return self._set_background_availability(enabled, operation_id)

    def _set_background_availability(self, enabled: Any, operation_id: str | None) -> dict[str, Any]:
        if not isinstance(enabled, bool):
            raise ValidationError("Background availability value is invalid")
        digest = None
        if operation_id is not None:
            if self._identity is None or self._shutdown.is_set():
                raise ValidationError("Local profile is unavailable")
            self._require_profile()
            try:
                if not isinstance(operation_id, str) or str(uuid.UUID(operation_id)) != operation_id:
                    raise ValueError
            except (ValueError, AttributeError) as error:
                raise ValidationError("Operation ID is invalid") from error
            material = json.dumps({"command": "set_background_availability", "enabled": enabled},
                                  sort_keys=True, ensure_ascii=True, separators=(",", ":"))
            digest = hashlib.sha256(material.encode("ascii")).hexdigest()
            if self.store.operation_result(operation_id, digest) is not None:
                # A receipt proves only committed intent. A newer preference,
                # lock or runtime failure must remain visible on replay.
                self._sync_background_reconnect()
                return self.background_availability_status()
        record = self._background_availability_record()
        changed = record.get("enabled") is not enabled or (
            operation_id is not None and record.get("last_reason") in {"not_configured", "invalid_record"})
        if changed:
            record = self._prepare_background_availability(
                enabled=enabled,
                state="enabled" if enabled else "disabled",
                reason="user_enabled" if enabled else "user_disabled",
            )
        if operation_id is not None:
            self.store.commit_operation(operation_id, digest, {"enabled": enabled},
                [(KIND, self._background_availability_id(), record)] if changed else ())
        elif changed:
            self.store.put(KIND, self._background_availability_id(), record)
        if changed:
            self._changed()
        self._sync_background_reconnect()
        return self.background_availability_status()

    def lock_background_availability(self) -> dict[str, Any]:
        """Lock always wins over a persisted opt-in."""
        with getattr(self, "_dispatch_lock", nullcontext()):
            return self._lock_background_availability()

    def _lock_background_availability(self) -> dict[str, Any]:
        self._write_background_availability(
            enabled=False,
            state="locked",
            reason="explicit_lock",
        )
        self._sync_background_reconnect()
        self._changed()
        return self.background_availability_status()

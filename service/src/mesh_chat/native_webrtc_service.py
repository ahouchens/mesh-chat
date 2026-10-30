"""Private native WebRTC service adapter and exact-resource bridge lifecycle.

The shared supervisor owns lifecycle decisions. This adapter executes native
operations and routes observations/packets under its current authority lease.
Legacy compatibility behavior stays here until migration parity is qualified.
"""
from __future__ import annotations

import base64
import json
import queue
import threading
import time
import uuid
from typing import Any

import RNS

from . import connection_diagnostics
from .errors import (
    ContactNotApproved, IdentityMismatch, NativeUnavailable, NetworkUnavailable, ValidationError,
)
from .native_webrtc_control import NativeWebRTCControlMixin
from .webrtc_interface import WebRTCInterface
from .webrtc_signaling import _fingerprint


class NativeWebRTCServiceMixin(NativeWebRTCControlMixin):
    _native_answer_exchange_timeout = 120.0

    def _native_webrtc_host(self):
        from .native_webrtc_host import android_host
        host = getattr(self, "_native_host", None)
        return android_host() if host is None else host

    def webrtc_attach_native(self, session_id: str, *, expected_physical: str | None = None) -> dict[str, Any]:
        with self._dispatch_lock:
            self._require_native_bridge_authority(session_id)
            physical = self._native_resources.require(session_id)
            if expected_physical is not None and physical != expected_physical:
                raise NativeUnavailable("Carrier attachment resource changed")
        journal = getattr(self, "_carrier_journal", None)
        if journal is not None:
            from .native_carrier_checkpoint import checkpoint_carrier
            checkpoint_carrier(self, session_id, journal)
        with self._dispatch_lock:
            self._require_native_bridge_authority(session_id)
            if not self._native_resources.current(session_id, physical):
                raise NativeUnavailable("Carrier attachment resource changed")
            recovered = session_id in getattr(self, "_native_recovered_bindings", {})
        if recovered:
            self._native_webrtc_host().activate(physical)
        with self._dispatch_lock:
            if not self._native_resources.current(session_id, physical):
                raise NativeUnavailable("Carrier attachment resource changed")
            return self._attach_native_bridge(session_id)

    def _require_native_bridge_authority(self, session_id):
        if (getattr(self, "_connection_policy", "legacy") == "shared-native"
                and not self._shared_native_session(session_id)):
            raise ContactNotApproved("Native messaging carrier has not been adopted")
        if not self._native_carrier_authorized(session_id):
            raise ContactNotApproved("Native messaging carrier authority is unavailable")
        if session_id not in self._native_webrtc_live:
            raise NativeUnavailable("Native messaging carrier is retiring")

    def _attach_native_bridge(self, session_id: str) -> dict[str, Any]:
        self._require_native_bridge_authority(session_id)
        if self.network is None:
            raise NetworkUnavailable("Reticulum is not running for a WebRTC bridge")
        existing = self._native_webrtc_sessions.get(session_id)
        if self._native_bridge_attached(session_id):
            return {
                "bridge_id": existing,
                "max_packet": WebRTCInterface.HW_MTU,
                "state": "online",
            }
        if existing is not None:
            self.webrtc_detach_native(session_id)
        bridge_id = str(uuid.uuid4())
        physical = self._native_resources.require(session_id)

        def send(data: bytes) -> None:
            if (session_id not in self._native_webrtc_live
                    or not self._native_resources.current(session_id, physical)
                    or self._native_webrtc_sessions.get(session_id) != bridge_id
                    or not self._native_bridge_attached(session_id)):
                return
            try:
                self._native_webrtc_host().send(physical, data)
            except Exception:
                pass

        interface = WebRTCInterface(
            RNS.Transport,
            send,
            name=f"Mesh Chat native WebRTC {bridge_id[:8]}",
        )
        try:
            self.network.reticulum._add_interface(
                interface, mode=interface.MODE_POINT_TO_POINT
            )
            if interface not in RNS.Transport.interfaces:
                raise RuntimeError("Reticulum did not register the native WebRTC interface")
        except Exception as exc:
            interface.detach()
            raise NetworkUnavailable("Could not attach the native WebRTC interface") from exc
        self._webrtc_bridges[bridge_id] = interface
        self._native_webrtc_sessions[session_id] = bridge_id
        self._deliver_native_startup_packets(session_id, physical, interface)
        try:
            self.network.reannounce()
        except Exception:
            pass
        for delay in (2.0, 6.0):
            threading.Thread(
                target=self._webrtc_announce_later,
                args=(bridge_id, delay),
                daemon=True,
                name="mesh-chat-native-webrtc-announce",
            ).start()
        self._changed()
        return {
            "bridge_id": bridge_id,
            "max_packet": WebRTCInterface.HW_MTU,
            "state": "online",
        }

    def _deliver_native_startup_packets(self, session_id, physical, interface):
        for packet in self._native_startup_packets.take(physical):
            if (session_id not in self._native_webrtc_live
                    or not self._native_resources.current(session_id, physical)
                    or not self._native_bridge_attached(session_id)):
                return
            try:
                interface.process_incoming(packet)
            except Exception:
                # One malformed early packet must not hide the remaining announces.
                continue

    def _retain_native_startup_packet(self, session_id, data):
        with self._native_webrtc_lock:
            if session_id not in self._native_webrtc_live or not self._shared_native_session(session_id):
                return
            physical = self._native_resources.physical(session_id)
            if physical is not None:
                self._native_startup_packets.retain(physical, data)

    def _native_bridge_attached(self, session_id: str) -> bool:
        bridge_id = self._native_webrtc_sessions.get(session_id)
        interface = self._webrtc_bridges.get(bridge_id)
        return bool(session_id in self._native_webrtc_live
                    and getattr(self, "network", None) is not None and interface is not None
                    and interface.online and any(current is interface for current in RNS.Transport.interfaces)
                    and self._native_carrier_authorized(session_id))

    def _native_carrier_authorized(self, session_id: str) -> bool:
        if getattr(self, "_connection_policy", "legacy") != "shared-native":
            return True
        runtime = getattr(self, "_connection_runtime", None)
        if runtime is None:
            return False
        with self._native_webrtc_lock:
            profile_id = next((profile for profile, current in self._native_webrtc_profile_sessions.items()
                               if current == session_id), None)
        from .connection.model import Resource
        physical = self._native_resources.physical(session_id)
        return profile_id is not None and physical is not None and (
            runtime.permits_carrier(profile_id, Resource("native", physical))
            or runtime.permits_carrier(profile_id, Resource("native", session_id)))

    def webrtc_detach_native(self, session_id: str) -> dict[str, Any]:
        bridge_id = self._native_webrtc_sessions.pop(session_id, None)
        if bridge_id is not None:
            self.webrtc_detach(bridge_id)
        return {"state": "closed"}

    def native_webrtc_event(self, event: str, session_id: str, data: str = "") -> None:
        """Queue a WebRTC callback without blocking the WebRTC/JNI thread.

        The callback can run while a Python command still owns the dispatch
        lock and is waiting for the native method to return. Taking that lock
        here would deadlock the command; the worker takes it after the command
        has unwound.
        """
        if not isinstance(event, str) or not isinstance(session_id, str):
            return
        if not isinstance(data, str):
            return
        queue_ref = getattr(self, "_native_webrtc_events", None)
        if queue_ref is None or self._shutdown.is_set():
            return
        try:
            queue_ref.put_nowait((event, session_id, data))
        except Exception:
            pass

    def _native_webrtc_event_loop(self) -> None:
        while not self._shutdown.is_set():
            try:
                with self._dispatch_lock:
                    self._expire_native_answer_exchanges()
                    self._maintain_native_controls()
            except Exception:
                pass
            try:
                item = self._native_webrtc_events.get(timeout=0.5)
            except queue.Empty:
                continue
            if item is None:
                return
            try:
                self._handle_native_webrtc_event(*item)
            except Exception:
                pass

    def _handle_native_webrtc_event(
        self, event: str, session_id: str, data: str = ""
    ) -> None:
        with self._dispatch_lock:
            if event == "overflow":
                runtime = getattr(self, "_connection_runtime", None)
                if runtime is not None:
                    runtime.quarantine()
                for current in tuple(self._native_webrtc_live):
                    if runtime is None or not self._shared_native_session(current):
                        self.native_webrtc_close(current)
                return
            # Resolve at consumption time: a queued event from a released
            # physical peer must not target a later reuse of its public ID.
            session_id = self._native_resources.resolve(session_id)
            if session_id is None or (session_id not in self._native_webrtc_live and event != "closed"):
                return
            managed = self._shared_native_session(session_id)
            if event == "ice" or event in {"open", "closed"}:
                connection_diagnostics.record(self, "transport_state", {
                    "setup_id": session_id, "state": data if event == "ice" else event,
                    "command": "native_webrtc_event", "component": "ice" if event == "ice" else "bridge",
                })
            elif event == "channel" and data.startswith("mesh-reticulum:"):
                connection_diagnostics.record(self, "transport_state", {
                    "setup_id": session_id, "state": data.partition(":")[2],
                    "command": "native_webrtc_event", "component": "data_channel",
                })
            if event == "open":
                if session_id not in self._native_webrtc_live:
                    return
                if getattr(self, "_connection_policy", "legacy") == "shared-native":
                    self._native_webrtc_descriptions.get(session_id, {})["packet_open"] = True
                    pending = getattr(self, "_pending_contact_carriers", {}).get(session_id)
                    if pending is not None: pending.opened()
                    # Pending onboarding uses only its isolated contact-control scope.
                    # The reducer admits messaging after verified discovery or CHECKING.
                    return
                self._native_webrtc_descriptions.get(session_id, {}).pop("answer_wait_until", None)
                try:
                    attached = self.webrtc_attach_native(session_id)
                except Exception:
                    return
                self.emit(
                    {
                        "type": "event",
                        "event": "webrtc_native_open",
                        "session_id": session_id,
                        "bridge_id": attached["bridge_id"],
                    }
                )
            elif event == "message":
                bridge_id = self._native_webrtc_sessions.get(session_id)
                if bridge_id is not None and self._native_bridge_attached(session_id):
                    try:
                        self.webrtc_packet(bridge_id, data)
                    except Exception:
                        pass
                elif managed:
                    self._retain_native_startup_packet(session_id, data)
                else:
                    pending = getattr(self, "_pending_contact_carriers", {}).get(session_id)
                    if pending is not None: pending.receive(data)
            elif event == "control":
                if session_id not in self._native_webrtc_live or len(data) > 90_000:
                    return
                label, _, encoded = data.partition(":")
                if label not in {"mesh-onboarding", "meshchat-reconnect"}:
                    return
                try:
                    text = base64.b64decode(encoded, validate=True).decode("utf-8")
                except Exception:
                    return
                if len(text) <= 65_536:
                    self._native_control_receive(session_id, label, text)
                    if label == "meshchat-reconnect":
                        return
                    self.emit(
                        {
                            "type": "event",
                            "event": "webrtc_control",
                            "session_id": session_id,
                            "label": label,
                            "data": text,
                        }
                    )
            elif event == "closed":
                from .native_onboarding_bootstrap import retire
                retire(self, session_id)
                physical = self._native_resources.physical(session_id)
                self._native_resources.confirm_closed(session_id, physical)
                try:
                    journal = getattr(self, "_carrier_journal", None)
                    if journal is not None and physical is not None:
                        journal.retire(physical)
                    self._release_native_session(session_id)
                finally:
                    self.webrtc_detach_native(session_id)
                self.emit(
                    {
                        "type": "event",
                        "event": "webrtc_native_state",
                        "session_id": session_id,
                        "state": "closed",
                    }
                )
            elif event in {"ice", "channel", "signaling", "gathering"}:
                if not managed and event == "ice" and (data == "closed" or (
                    data == "failed" and not self._native_answer_exchange_pending(session_id)
                )):
                    self.native_webrtc_close(session_id)
                if event == "channel":
                    label, _, state = data.partition(":")
                    if session_id in self._native_webrtc_live and label in {"mesh-onboarding", "meshchat-reconnect"} and state == "open":
                        self._native_webrtc_controls.setdefault(session_id, {})["label"] = label
                        self._native_control_next = 0
                    if not managed and label == "mesh-reticulum" and state in {"closing", "closed"}:
                        self.native_webrtc_close(session_id)
                    if label == "mesh-onboarding" and state == "open":
                        self.emit(
                            {
                                "type": "event",
                                "event": "webrtc_control_open",
                                "session_id": session_id,
                                "label": label,
                            }
                        )
                self.emit(
                    {
                        "type": "event",
                        "event": "webrtc_native_state",
                        "session_id": session_id,
                        "state": event,
                        "detail": data[:160],
                    }
                )

    def _shared_native_session(self, session_id: str) -> bool:
        with self._native_webrtc_lock:
            return (getattr(self, "_connection_policy", "legacy") == "shared-native"
                    and session_id in self._native_webrtc_profile_sessions.values())

    def _native_answer_exchange_pending(self, session_id: str) -> bool:
        with self._native_webrtc_lock:
            deadline = self._native_webrtc_descriptions.get(session_id, {}).get("answer_wait_until", 0)
            return (session_id in self._native_webrtc_live
                    and session_id not in self._native_webrtc_sessions
                    and time.monotonic() < deadline)

    def _expire_native_answer_exchanges(self) -> None:
        # Run in the native event worker, even if the WebView is suspended.
        # Preserving a pending answer must not leave abandoned peers alive.
        now = time.monotonic()
        with self._native_webrtc_lock:
            expired = [session_id for session_id, description in self._native_webrtc_descriptions.items()
                       if session_id in self._native_webrtc_live
                       and session_id not in self._native_webrtc_sessions
                       and description.get("answer_wait_until", float("inf")) <= now]
        for session_id in expired:
            self.native_webrtc_close(session_id)

    def native_reconnect_session(self, profile_id: str) -> str | None:
        with self._native_webrtc_lock:
            current = self._native_webrtc_profile_sessions.get(profile_id)
            if current:
                return current
            # A manually paired native transport remains usable without a
            # mailbox. Reconnect must reuse it after the contact is approved.
            for session_id in self._native_webrtc_peers:
                if (session_id in self._native_webrtc_live
                        and self._native_webrtc_controls.get(session_id, {}).get("profile_id") == profile_id):
                    return session_id
            return None

    def close_native_reconnect_session(self, profile_id: str) -> None:
        session_id = self.native_reconnect_session(profile_id)
        if session_id is not None:
            self.native_webrtc_close(session_id)

    def retire_unmanaged_native_connections(self, profile_ids) -> None:
        """Explicit Stop also covers verified manual peers awaiting transfer."""
        with self._native_webrtc_lock:
            sessions = [session for session, control in self._native_webrtc_controls.items()
                        if control.get("profile_id") in profile_ids
                        and session in self._native_webrtc_peers
                        and session in self._native_webrtc_live
                        and not self._shared_native_session(session)]
        failure = None
        for session in sessions:
            try:
                self.native_webrtc_close(session)
            except Exception as error:
                # Each close removes routing in finally, even when JNI fails.
                failure = error
        if failure is not None:
            raise failure

    def _claim_native_session(self, session_id: str, profile_id: Any, *, background: bool,
                              runtime_owned: bool = False) -> bool:
        relay_only = False
        with self._dispatch_lock:
            if self._shutdown.is_set():
                raise NativeUnavailable("Native WebRTC is shutting down")
            if getattr(self, "_carrier_recovery_pending", False):
                raise NativeUnavailable("Native carrier recovery is pending")
            if profile_id is not None:
                shared = getattr(self, "_connection_policy", "legacy") == "shared-native"
                if shared != runtime_owned:
                    raise NativeUnavailable("Native reconnect is owned by another policy")
                profile = self._reconnect_profile(profile_id)
                public = self._reconnect_profile_public(profile)
                if not public["effective"]["ready"] or not profile.get("active"):
                    raise ContactNotApproved("Reconnect profile is not active and ready")
                relay_only = not profile.get("allow_direct_ip_disclosure")
                in_background = self._workspace_lifecycle_state().get("state") in {
                    "background", "background_available", "suspended",
                }
                if ((not runtime_owned and background != in_background)
                        or (in_background and not self._background_availability_enabled())):
                    raise NativeUnavailable("Native reconnect ownership changed")
            with self._native_webrtc_lock:
                if session_id in self._native_webrtc_live or session_id in self._native_webrtc_creating:
                    raise NativeUnavailable("Native WebRTC session already exists")
                if profile_id is not None:
                    if self.native_reconnect_session(profile_id):
                        raise NativeUnavailable("Native reconnect profile already has a peer")
                self._native_resources.reserve(session_id)
                if profile_id is not None:
                    self._native_webrtc_profile_sessions[profile_id] = session_id
                self._native_webrtc_live.add(session_id)
                self._native_webrtc_creating.add(session_id)
        return relay_only

    def _release_native_session(self, session_id: str) -> None:
        with self._native_webrtc_lock:
            self._native_webrtc_live.discard(session_id)
            self._native_startup_packets.discard(self._native_resources.physical(session_id))
            if session_id in self._native_webrtc_creating or not self._native_resources.closed(session_id):
                return
            self._native_resources.release(session_id, self._native_resources.physical(session_id))
            self._native_webrtc_descriptions.pop(session_id, None)
            self._native_webrtc_peers.pop(session_id, None)
            self._native_webrtc_controls.pop(session_id, None)
            getattr(self, "_native_recovered_bindings", {}).pop(session_id, None)
            for profile_id, current in list(self._native_webrtc_profile_sessions.items()):
                if current == session_id:
                    del self._native_webrtc_profile_sessions[profile_id]

    def _native_sdp_result(self, session_id: str, raw: str) -> dict[str, Any]:
        result = json.loads(raw)
        if not result.get("ok"):
            raise NativeUnavailable(str(result.get("error", "native_webrtc_sdp_failed")))
        if session_id not in self._native_webrtc_live or self._shutdown.is_set():
            raise NativeUnavailable("Native WebRTC creation was cancelled")
        # The signed document must bind the fingerprint in the actual SDP.
        # Normalize here as well as in Kotlin so bridge metadata cannot drift.
        fingerprints = [line[len("a=fingerprint:"):] for line in result.get("sdp", "").splitlines()
                        if line.startswith("a=fingerprint:")]
        if len(fingerprints) != 1:
            raise ValidationError("Native WebRTC SDP fingerprint is invalid")
        result["fingerprint"] = _fingerprint(fingerprints[0])
        self._native_webrtc_descriptions.setdefault(session_id, {})["local"] = result["sdp"]
        return result

    def native_webrtc_offer(
        self, session_id: Any, ice: Any, channels: Any, profile_id: Any = None, *, background: bool = False,
        runtime_owned: bool = False,
    ) -> dict[str, Any]:
        if not isinstance(session_id, str) or not 8 <= len(session_id) <= 128:
            raise ValidationError("Native WebRTC session is invalid")
        if not isinstance(ice, dict) or not isinstance(channels, list):
            raise ValidationError("Native WebRTC configuration is invalid")
        if self._claim_native_session(session_id, profile_id, background=background, runtime_owned=runtime_owned):
            ice = {**ice, "iceTransportPolicy": "relay"}
        self._native_webrtc_descriptions[session_id] = {"ice_policy": ice.get("iceTransportPolicy", "all")}
        try:
            return self._native_sdp_result(session_id, self._native_webrtc_host().createOffer(
                self._native_resources.require(session_id),
                json.dumps(ice, separators=(",", ":")),
                json.dumps(channels, separators=(",", ":")),
            ))
        except Exception:
            self.native_webrtc_close(session_id)
            raise
        finally:
            with self._native_webrtc_lock:
                self._native_webrtc_creating.discard(session_id)
                if session_id not in self._native_webrtc_live:
                    self._release_native_session(session_id)

    def native_webrtc_accept(
        self, session_id: Any, offer_sdp: Any, ice: Any, channels: Any, profile_id: Any = None, *, background: bool = False,
        runtime_owned: bool = False,
    ) -> dict[str, Any]:
        if (not isinstance(session_id, str) or not 8 <= len(session_id) <= 128
                or not isinstance(offer_sdp, str)):
            raise ValidationError("Native WebRTC session is invalid")
        if not isinstance(ice, dict) or not isinstance(channels, list):
            raise ValidationError("Native WebRTC configuration is invalid")
        if self._claim_native_session(session_id, profile_id, background=background, runtime_owned=runtime_owned):
            ice = {**ice, "iceTransportPolicy": "relay"}
        self._native_webrtc_descriptions[session_id] = {
            "remote_offer": offer_sdp, "ice_policy": ice.get("iceTransportPolicy", "all")}
        if profile_id is None and any(
            isinstance(channel, dict) and channel.get("label") == "mesh-onboarding" for channel in channels
        ):
            # The offerer cannot send checks to this peer until the person
            # returns its signed answer. An early ICE failure must not destroy
            # the session before binding/signing or during that manual wait.
            # Match the browser answerer's bounded exchange window; established
            # channels and automatic reconnect retain immediate failure cleanup.
            self._native_webrtc_descriptions[session_id]["answer_wait_until"] = (
                time.monotonic() + self._native_answer_exchange_timeout
            )
        try:
            return self._native_sdp_result(session_id, self._native_webrtc_host().acceptOffer(
                self._native_resources.require(session_id),
                offer_sdp,
                json.dumps(ice, separators=(",", ":")),
                json.dumps(channels, separators=(",", ":")),
            ))
        except Exception:
            self.native_webrtc_close(session_id)
            raise
        finally:
            with self._native_webrtc_lock:
                self._native_webrtc_creating.discard(session_id)
                if session_id not in self._native_webrtc_live:
                    self._release_native_session(session_id)

    def native_webrtc_apply_answer(self, session_id: Any, answer_sdp: Any) -> dict[str, Any]:
        if not isinstance(session_id, str) or not isinstance(answer_sdp, str):
            raise ValidationError("Native WebRTC answer is invalid")
        from .native_webrtc_control import normalized_sdp
        with self._native_webrtc_lock:
            physical = self._native_resources.require(session_id)
            description = self._native_webrtc_descriptions.get(session_id, {})
            bound = description.get("bound_remote_sdp")
            if bound and bound != normalized_sdp(answer_sdp):
                raise IdentityMismatch("Answer does not match the verified native binding")
        result = json.loads(
            self._native_webrtc_host().applyAnswer(physical, answer_sdp)
        )
        if not result.get("ok"):
            raise NativeUnavailable(str(result.get("error", "native_webrtc_apply_failed")))
        with self._native_webrtc_lock:
            if (not self._native_resources.current(session_id, physical)
                    or session_id not in self._native_webrtc_live):
                raise NativeUnavailable("Native answer completed after its resource was retired")
            self._native_webrtc_descriptions.setdefault(session_id, {})["remote_answer"] = answer_sdp
        return result

    def native_webrtc_control(
        self, session_id: Any, label: Any, text: Any
    ) -> dict[str, Any]:
        if (
            not isinstance(session_id, str)
            or label not in {"mesh-onboarding", "meshchat-reconnect"}
            or not isinstance(text, str)
            or not 1 <= len(text) <= 65_536
        ):
            raise ValidationError("Native WebRTC control message is invalid")
        physical = self._native_resources.require(session_id)
        accepted = bool(self._native_webrtc_host().sendControl(physical, label, text))
        accepted = (accepted and session_id in self._native_webrtc_live
                    and self._native_resources.current(session_id, physical))
        return {"accepted": accepted}

    def native_webrtc_close(self, session_id: Any, *, expected_physical: str | None = None) -> dict[str, Any]:
        if not isinstance(session_id, str):
            raise ValidationError("Native WebRTC session is invalid")
        with self._native_webrtc_lock:
            physical = self._native_resources.physical(session_id)
            if expected_physical is not None and physical != expected_physical:
                return {"state": "closed"}
            was_live = session_id in self._native_webrtc_live
            self._native_webrtc_live.discard(session_id)
            self._native_startup_packets.discard(physical)
        from .native_onboarding_bootstrap import retire
        retire(self, session_id)
        if was_live:
            connection_diagnostics.record(self, "transport_state", {
                "setup_id": session_id, "state": "closed", "command": "native_webrtc_close", "component": "bridge",
            })
        checkpoint_retired = physical is None
        try:
            if physical is not None:
                try:
                    journal = getattr(self, "_carrier_journal", None)
                    if journal is not None:
                        journal.retire(physical)
                    checkpoint_retired = True
                finally:
                    self._native_webrtc_host().close(physical)
                    self._native_resources.confirm_closed(session_id, physical)
        finally:
            with self._dispatch_lock, self._native_webrtc_lock:
                if self._native_resources.current(session_id, physical):
                    if checkpoint_retired:
                        self._release_native_session(session_id)
                    self.webrtc_detach_native(session_id)
        return {"state": "closed"}

    def native_webrtc_stats(self, session_id: Any) -> dict[str, Any]:
        if not isinstance(session_id, str):
            raise ValidationError("Native WebRTC session is invalid")
        physical = self._native_resources.require(session_id)
        result = json.loads(self._native_webrtc_host().stats(physical))
        if not self._native_resources.current(session_id, physical):
            raise NativeUnavailable("Native inspection completed after its resource was retired")
        if not result.get("ok"):
            raise NativeUnavailable(str(result.get("error", "native_webrtc_stats_failed")))
        stats = result.get("result", {})
        if isinstance(stats, dict):
            stats["attached"] = (
                self._native_bridge_attached(session_id)
                and stats.get("data_channel_state") == "open"
                and stats.get("ice_connection_state") not in {"failed", "closed"}
            )
            stats["session_id"] = session_id
        return stats

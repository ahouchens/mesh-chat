from __future__ import annotations

import platform
from copy import deepcopy
import secrets
import socket
import time
import uuid
from pathlib import Path
from typing import Any

from .connectivity import (
    DEFAULT_MAPPING_LIFETIME,
    ConnectivityError,
    candidate_connection_result,
    create_port_mapping,
    default_routes,
    diagnostic_step,
    gateway_candidates,
    global_ipv6_addresses,
    inspect_nat_pmp,
    inspect_pcp,
    inspect_upnp,
    map_upnp_ipv6_pinhole,
    public_ipv4_addresses,
    remove_port_mapping,
    renew_port_mapping,
    select_available_port,
)
from .errors import DirectConnectionUnavailable, ValidationError
from .firewall import (
    firewall_diagnostic,
    install_temporary_windows_rule,
    remove_temporary_windows_rule,
)
from .participant import create_access_document, validate_access_document
from .remote import resolve_public_endpoint, validate_endpoint

MAX_ACTIVE_HOST_SESSIONS = 8
HOST_EXPIRY_MARGIN_SECONDS = 60
MANUAL_SETUP_LIFETIME_SECONDS = 30 * 60
RENEWAL_FRACTION = 0.5
MAX_PARTICIPANT_INTENTS = 256


class ParticipantReservationUnavailable(ValidationError):
    """A keyed live resource cannot safely be reconstructed or replayed."""
    code = "resync_required"


class ParticipantReservationCapacity(ValidationError):
    """The bounded intent or live resource capacity is exhausted."""
    code = "resource_exhausted"


class ParticipantAccessServiceMixin:
    """Invitation-scoped participant hosting without a rendezvous or relay."""

    def _participant_hosts(self) -> list[dict[str, Any]]:
        return self.store.list("participant_host")

    def _participant_access_records(self) -> list[dict[str, Any]]:
        return self.store.list("participant_access")

    def _participant_runtime_epoch(self) -> str:
        if not hasattr(self, "_participant_reservation_epoch"):
            self._participant_reservation_epoch = secrets.token_hex(16)
        return self._participant_reservation_epoch

    def _participant_retirements(self) -> dict[str, dict[str, Any]]:
        if not hasattr(self, "_participant_retired_intents"):
            self._participant_retired_intents = {}
        return self._participant_retired_intents

    def _reclaim_participant_intents(self, now: float) -> None:
        """Discard private history only after every possible lease has expired."""
        deletions = []
        reclaimed = []
        for intent in self.store.list("participant_host_intent"):
            operation = intent["id"]
            expiry = float(intent["maximum_expires_at"])
            safe_after = expiry if intent["state"] == "reserved" else expiry + DEFAULT_MAPPING_LIFETIME
            local = self._participant_retirements().get(operation, {})
            if (now <= max(safe_after, float(intent.get("uncertain_lease_until", 0)))
                    or self.store.get("participant_host", intent["host_session_id"]) is not None
                    or intent.get("cleanup") or local.get("cleanup")
                    or intent["host_session_id"] in getattr(self, "_participant_pending_resources", {})):
                continue
            if self.store.operation_result(operation, intent["input_digest"]) != self._participant_intent_receipt(operation):
                continue
            deletions.extend([("participant_host_intent", operation), ("participant_host_completion", operation)])
            reclaimed.append(operation)
        if deletions:
            self.store.put_and_delete([], deletions)
            for operation in reclaimed:
                self._participant_retirements().pop(operation, None)

    def _participant_intent_holds_capacity(self, intent: dict[str, Any], now: float) -> bool:
        if float(intent.get("uncertain_lease_until", 0)) > now:
            return True
        if (intent.get("state") == "allocating"
                and self.store.get("participant_host", intent["host_session_id"]) is None):
            # A crash can interrupt retirement after deleting the host record.
            return float(intent["maximum_expires_at"]) + DEFAULT_MAPPING_LIFETIME > now
        if float(intent.get("maximum_expires_at", 0)) <= now:
            return False
        if intent.get("state") == "reserved":
            return intent.get("runtime_epoch") == self._participant_runtime_epoch()
        return False

    def reserve_participant_host_intent(
        self, operation_id, input_digest, *, purpose, scope_id, maximum_expires_at,
        relationship_scope, peer_destination, generation_id, base_generation,
        access_mode="participant_callback", preferred_external_port=None,
    ):
        """Commit a bounded resource intent before any allocation is admitted."""
        with self._dispatch_lock:
            try:
                if (str(uuid.UUID(operation_id)) != operation_id or not isinstance(input_digest, str)
                        or len(input_digest) != 64 or input_digest != input_digest.lower()
                        or len(bytes.fromhex(input_digest)) != 32):
                    raise ValueError
            except (ValueError, TypeError, AttributeError) as error:
                raise ValidationError("Participant operation is invalid") from error
            if (not isinstance(relationship_scope, dict) or set(relationship_scope) != {"kind", "id"}
                    or purpose not in {"personal", "workspace"}
                    or access_mode not in {"participant_direct", "participant_callback"}
                    or type(base_generation) is not int or base_generation < 0
                    or type(maximum_expires_at) is not int or maximum_expires_at <= time.time()
                    or maximum_expires_at > time.time() + 24 * 60 * 60 + 1
                    or (preferred_external_port is not None and (type(preferred_external_port) is not int
                        or not 1 <= preferred_external_port <= 65535))):
                raise ValidationError("Participant reservation is invalid")
            if self._identity is None or self._shutdown.is_set():
                raise ValidationError("Local profile is unavailable")
            canonical, audience, _, _ = self._route_update_binding(
                relationship_scope["kind"], relationship_scope["id"], peer_destination)
            expected_purpose = "personal" if relationship_scope["kind"] == "contact" else "workspace"
            if (canonical != scope_id or audience.hex() != peer_destination or purpose != expected_purpose
                    or generation_id != f"out:{relationship_scope['kind']}:{canonical}:{peer_destination}"):
                raise ValidationError("Participant reservation scope does not match its peer")
            previous = self.store.get("participant_host_intent", operation_id)
            if previous is not None:
                if previous.get("input_digest") != input_digest:
                    raise ValidationError("Operation ID was already used with different input")
                for key, value in {"purpose": purpose, "scope_id": scope_id,
                        "relationship_scope": relationship_scope, "peer_destination": peer_destination,
                        "generation_id": generation_id, "access_mode": access_mode,
                        "preferred_external_port": preferred_external_port}.items():
                    if previous.get(key) != value:
                        raise ValidationError("Operation ID was already used with different input")
                return deepcopy(self._require_participant_host_intent(operation_id, input_digest))
            if self.store.operation_result(operation_id, input_digest) is not None:
                raise ParticipantReservationUnavailable("Participant operation has no reservation")
            self._reclaim_participant_intents(time.time())
            intents = self.store.list("participant_host_intent")
            if len(intents) >= MAX_PARTICIPANT_INTENTS:
                raise ParticipantReservationCapacity("Too many participant operation intents")
            generation = self.store.get("route_generation", generation_id) or {}
            if int(generation.get("generation", 0)) != base_generation:
                raise ParticipantReservationUnavailable("Route generation changed")
            now = time.time()
            pending = sum(self._participant_intent_holds_capacity(item, now) for item in intents)
            if self._active_host_count() + pending >= MAX_ACTIVE_HOST_SESSIONS:
                raise ParticipantReservationCapacity("Too many participant host reservations")
            intent = {"id": operation_id, "input_digest": input_digest, "state": "reserved",
                "host_session_id": secrets.token_hex(32), "runtime_epoch": self._participant_runtime_epoch(),
                "purpose": purpose, "scope_id": scope_id, "relationship_scope": dict(relationship_scope),
                "peer_destination": peer_destination, "maximum_expires_at": maximum_expires_at,
                "generation_id": generation_id, "base_generation": base_generation, "generation": base_generation + 1,
                "access_mode": access_mode, "preferred_external_port": preferred_external_port,
                "local_destination": self._require_profile()["destination_hash"],
                "created_at": time.time()}
            self.store.commit_operation(operation_id, input_digest,
                self._participant_intent_receipt(operation_id),
                [("participant_host_intent", operation_id, intent)])
            return deepcopy(intent)

    @staticmethod
    def _participant_intent_receipt(operation_id: str) -> dict[str, str]:
        return {"action": "participant_host", "intent_id": operation_id}

    def _require_participant_host_intent(self, operation_id, input_digest):
        intent = self.store.get("participant_host_intent", operation_id)
        if intent is None:
            raise ParticipantReservationUnavailable("Participant reservation is missing")
        if intent.get("input_digest") != input_digest:
            raise ValidationError("Operation ID was already used with different input")
        if operation_id in self._participant_retirements():
            raise ParticipantReservationUnavailable("Participant reservation is retired in this runtime")
        if self._identity is None or self._shutdown.is_set():
            self._retire_participant_intent(intent)
            raise ParticipantReservationUnavailable("Local profile is unavailable")
        try:
            if self.store.operation_result(operation_id, input_digest) != self._participant_intent_receipt(operation_id):
                raise ParticipantReservationUnavailable("Participant operation reservation is missing")
            relationship = intent["relationship_scope"]
            canonical, audience, _, _ = self._route_update_binding(
                relationship["kind"], relationship["id"], intent["peer_destination"])
            current = self.store.get("route_generation", intent["generation_id"]) or {}
            expected = intent["generation"] if intent["state"] == "committed" else intent["base_generation"]
            if (intent["runtime_epoch"] != self._participant_runtime_epoch()
                    or float(intent["maximum_expires_at"]) <= time.time()
                    or intent["state"] == "retired" or canonical != intent["scope_id"]
                    or intent.get("local_destination") != self._require_profile()["destination_hash"]
                    or audience.hex() != intent["peer_destination"]
                    or int(current.get("generation", 0)) != expected
                    or (intent["state"] == "committed"
                        and current.get("host_session_id") != intent["host_session_id"])):
                raise ParticipantReservationUnavailable("Participant reservation needs resynchronization")
        except Exception:
            self._retire_participant_intent(intent)
            raise
        return intent

    def _retire_participant_intent(self, intent):
        session = intent["host_session_id"]
        host = self.store.get("participant_host", session)
        memory = getattr(self, "_participant_pending_resources", {}).get(session)
        local = self._participant_retirements().get(intent["id"])
        resource = local.get("cleanup") if local is not None else memory or host or intent.get("cleanup")
        def matches(item):
            return (item is not None and item.get("reservation_operation_id") == intent["id"]
                    and item.get("reservation_epoch") == intent["runtime_epoch"])
        retired = {**intent, "state": "retired"}
        if intent.get("state") == "allocating" and (resource is None or not resource.get("access")):
            # The router lease can outlive the signed access document. An
            # unknown allocation reply must hold capacity for the whole lease.
            retired["uncertain_lease_until"] = max(
                float(intent.get("uncertain_lease_until", 0)), time.time() + DEFAULT_MAPPING_LIFETIME)
        if matches(resource):
            retired["cleanup"] = deepcopy(resource)
        else:
            retired.pop("cleanup", None)
        # Fence before the first fallible write. Restore and replay must deny
        # this listener even while durable retirement is unavailable.
        self._participant_retirements()[intent["id"]] = retired
        errors = []
        try:
            self.store.put("participant_host_intent", intent["id"], retired)
        except Exception as error:
            errors.append(error)
        if matches(host):
            try:
                self.store.delete("participant_host", session)
            except Exception as error:
                errors.append(error)
        if matches(resource) or matches(host) or local is not None:
            try:
                self._apply_participant_interfaces()
            except Exception as error:
                errors.append(error)
        if matches(resource):
            for key, cleanup in (("mapping", remove_port_mapping), ("pinhole", remove_port_mapping),
                                 ("firewall", remove_temporary_windows_rule)):
                if not isinstance(retired["cleanup"].get(key), dict):
                    continue
                try:
                    cleanup(retired["cleanup"][key])
                    retired["cleanup"].pop(key)
                except Exception as error:
                    errors.append(error)
            getattr(self, "_participant_pending_resources", {}).pop(session, None)
            if not any(isinstance(retired["cleanup"].get(key), dict) for key in ("mapping", "pinhole", "firewall")):
                retired.pop("cleanup", None)
        try:
            self.store.put("participant_host_intent", intent["id"], retired)
        except Exception as error:
            errors.append(error)
        if errors:
            raise errors[0]

    def retire_participant_host_intent(self, operation_id, input_digest):
        with self._dispatch_lock:
            intent = self.store.get("participant_host_intent", operation_id)
            if intent is None:
                return
            if intent.get("input_digest") != input_digest:
                raise ValidationError("Operation ID was already used with different input")
            self._retire_participant_intent(intent)

    def _participant_reserved_access(self, intent):
        record = self.store.get("participant_host", intent["host_session_id"])
        if (record is None or record.get("reservation_operation_id") != intent["id"]
                or record.get("reservation_epoch") != self._participant_runtime_epoch()
                or record.get("state") == "unavailable" or float(record.get("expires_at", 0)) <= time.time()
                or not record.get("access")
                or not self._listener_ready(record["id"], len(record.get("listeners", [])))):
            self._retire_participant_intent(intent)
            raise ParticipantReservationUnavailable("Participant resource is no longer live")
        access = validate_access_document(record["access"])
        return {**access, "host_session_id": record["id"]}

    def materialize_participant_host_intent(self, operation_id, input_digest):
        with self._dispatch_lock:
            intent = self._require_participant_host_intent(operation_id, input_digest)
            if intent["state"] in {"allocating", "allocated", "committed"}:
                return self._participant_reserved_access(intent)
            intent["state"] = "allocating"
            self.store.put("participant_host_intent", operation_id, intent)
            try:
                result = self.create_participant_host_access(
                    purpose=intent["purpose"], scope_id=intent["scope_id"],
                    maximum_expires_at=intent["maximum_expires_at"], access_mode=intent["access_mode"],
                    preferred_external_port=intent["preferred_external_port"], _reservation=intent)
                self._require_participant_host_intent(operation_id, input_digest)
            except Exception:
                self._retire_participant_intent(intent)
                raise
            getattr(self, "_participant_pending_resources", {}).pop(intent["host_session_id"], None)
            intent["state"] = "allocated"
            # A failed reply here still leaves a complete owned host record.
            self.store.put("participant_host_intent", operation_id, intent)
            return result

    def _prepare_participant_host_completion(self, operation_id, input_digest, *, result: dict[str, Any]):
        if not isinstance(result, dict):
            raise ValidationError("Participant completion must be an object")
        intent = self._require_participant_host_intent(operation_id, input_digest)
        self._participant_reserved_access(intent)
        existing = self.store.get("participant_host_completion", operation_id)
        completion = {"id": operation_id, "input_digest": input_digest, "result": deepcopy(result)}
        if existing is not None and existing != completion:
            raise ValidationError("Participant completion cannot change")
        return [("participant_host_intent", operation_id, {**intent, "state": "committed"}),
                ("participant_host_completion", operation_id, completion)]

    def _restore_participant_interfaces(self) -> None:
        now = time.time()
        listeners: list[dict[str, Any]] = []
        clients: list[dict[str, Any]] = []
        for record_id, record in self.store.items("participant_host"):
            if record.get("reservation_operation_id"):
                if record["reservation_operation_id"] in self._participant_retirements():
                    continue
                intent = self.store.get("participant_host_intent", record["reservation_operation_id"])
                if (intent is None or intent.get("state") == "retired"
                        or record.get("reservation_epoch") != self._participant_runtime_epoch()):
                    if intent is not None:
                        self._retire_participant_intent(intent)
                    else:
                        self.stop_participant_host(record_id)
                    continue
            if float(record.get("expires_at", 0)) <= now:
                mapping = record.get("mapping")
                if isinstance(mapping, dict):
                    remove_port_mapping(mapping)
                pinhole = record.get("pinhole")
                if isinstance(pinhole, dict):
                    remove_port_mapping(pinhole)
                firewall = record.get("firewall")
                if isinstance(firewall, dict):
                    remove_temporary_windows_rule(firewall)
                self.store.delete("participant_host", record_id)
                continue
            if record.get("state") != "unavailable":
                listeners.extend(dict(item) for item in record.get("listeners", []))
        for record_id, record in self.store.items("participant_access"):
            access = record.get("access", {})
            if float(access.get("expires_at", 0)) <= now:
                self.store.delete("participant_access", record_id)
                continue
            if record.get("prepared_replacement"):
                scopes = []
                for scope in record.get("scopes", []):
                    if scope not in record.get("prepared_scope_checks", []):
                        scopes.append(scope)
                        continue
                    try:
                        _, audience, _, _ = self._route_update_binding(
                            scope["kind"], scope["id"], access.get("operator_destination"))
                        if audience.hex() == access.get("operator_destination"):
                            scopes.append(scope)
                    except Exception:
                        continue
                if not scopes:
                    self.store.delete("participant_access", record_id)
                    continue
                if scopes != record.get("scopes"):
                    record["scopes"] = scopes
                    self.store.put("participant_access", record_id, record)
            endpoints = record.get("resolved_endpoints")
            if not record.get("resolution_attempted"):
                # Import commits the exact credential and replay state before
                # DNS or sockets. If the process stopped in that intentional
                # gap, finish resolution only after reading the durable record.
                try:
                    endpoints, results = self._resolved_participant_endpoints(access)
                    record["resolved_endpoints"] = endpoints
                    record["candidate_results"] = results
                    record["resolution_attempted"] = True
                    self.store.put("participant_access", record_id, record)
                except Exception:
                    endpoints = []
            for index, endpoint in enumerate(endpoints):
                clients.append({
                    "id": access["id"], "endpoint_index": index,
                    "host": endpoint["host"], "port": endpoint["port"],
                    "network_name": access["network_name"],
                    "passphrase": access["passphrase"],
                    "expires_at": access["expires_at"],
                })
        self.settings.participant_listeners = listeners
        self.settings.participant_clients = clients

    def _apply_participant_interfaces(self) -> None:
        self._restore_participant_interfaces()
        if self.network is not None:
            self.network.apply_participant_interfaces(
                self.settings.participant_listeners,
                self.settings.participant_clients,
            )

    def _active_host_count(self) -> int:
        now = time.time()
        return sum(
            1 for record in self._participant_hosts()
            if float(record.get("expires_at", 0)) > now
            and record.get("state") != "unavailable"
        )

    def _direct_failure(self, error: ConnectivityError) -> DirectConnectionUnavailable:
        self._last_direct_diagnostic = error.diagnostic()
        return DirectConnectionUnavailable(error.reason, details=error.diagnostic())

    def _listener_ready(self, session_id: str, expected: int) -> bool:
        if self.network is None:
            return False
        state_method = getattr(self.network, "participant_host_state", None)
        if not callable(state_method):
            return True
        state = state_method(session_id)
        return int(state.get("listener_count", 0)) >= expected and bool(state.get("online", False))

    def _new_listener_record(
        self,
        *,
        purpose: str,
        expires_at: int,
        ipv6: bool,
        include_ipv4: bool,
        reservation=None,
    ) -> dict[str, Any]:
        session_id = reservation["host_session_id"] if reservation else secrets.token_hex(32)
        network_name = secrets.token_urlsafe(18)
        passphrase = secrets.token_urlsafe(32)
        last_error: Exception | None = None
        for _attempt in range(3):
            bindings_method = (
                getattr(self.network, "participant_listener_bindings", None)
                if self.network is not None else None
            )
            kernel_allocates = callable(bindings_method)
            listeners: list[dict[str, Any]] = []
            if include_ipv4:
                listeners.append({
                    "id": session_id, "listen_ip": "0.0.0.0",
                    "port": 0 if kernel_allocates else select_available_port(),
                    "network_name": network_name,
                    "passphrase": passphrase, "expires_at": expires_at,
                })
            if ipv6:
                listeners.append({
                    "id": session_id, "listen_ip": "::",
                    "port": 0 if kernel_allocates else select_available_port(ipv6=True),
                    "network_name": network_name,
                    "passphrase": passphrase, "expires_at": expires_at,
                })
            record = {
                "id": session_id, "purpose": purpose, "scope_id": "",
                "access": None, "listeners": listeners, "mapping": None,
                "pinhole": None,
                "firewall": None, "created_at": float(time.time()),
                "expires_at": float(expires_at), "state": "preparing",
                "network_name": network_name, "passphrase": passphrase,
            }
            if reservation:
                record.update(reservation_operation_id=reservation["id"], reservation_epoch=reservation["runtime_epoch"],
                    relationship_scope=reservation["relationship_scope"], peer_destination=reservation["peer_destination"],
                    scope_id=reservation["scope_id"])
                if not hasattr(self, "_participant_pending_resources"):
                    self._participant_pending_resources = {}
                self._participant_pending_resources[session_id] = record
            self.store.put("participant_host", session_id, record)
            try:
                self._apply_participant_interfaces()
                if kernel_allocates:
                    bindings = bindings_method(session_id)
                    for listener in listeners:
                        family_is_ipv6 = ":" in str(listener["listen_ip"])
                        binding = next((
                            item for item in bindings
                            if (":" in str(item.get("listen_ip", ""))) == family_is_ipv6
                        ), None)
                        if binding is None:
                            raise OSError("listener port unavailable")
                        listener["port"] = int(binding["port"])
                    self.store.put("participant_host", session_id, record)
                if not self._listener_ready(session_id, len(listeners)):
                    raise OSError("listener unavailable")
                return record
            except Exception as exc:
                last_error = exc
                self.store.delete("participant_host", session_id)
                try:
                    self._apply_participant_interfaces()
                except Exception:
                    pass
        raise self._direct_failure(ConnectivityError(
            "listener", "listener_bind_failed", result="blocked",
            recommended_action="retry_or_check_firewall",
        )) from last_error

    def check_direct_connection(self) -> dict[str, Any]:
        """Return a strictly allowlisted, endpoint-free connection doctor report."""

        checks: list[dict[str, str]] = []
        if self.network is None:
            summary = diagnostic_step(
                "precondition", "unavailable", "listener_bind_failed", "restart_app"
            )
            return {"summary": summary, "checks": [summary]}
        if self._active_host_count() >= MAX_ACTIVE_HOST_SESSIONS:
            summary = diagnostic_step(
                "precondition", "blocked", "session_limit", "stop_an_active_invitation"
            )
            return {"summary": summary, "checks": [summary]}
        routes = default_routes()
        if not routes:
            summary = diagnostic_step(
                "precondition", "unavailable", "no_default_route", "connect_to_internet"
            )
            return {"summary": summary, "checks": [summary, firewall_diagnostic()]}
        checks.append(diagnostic_step(
            "precondition", "available", "ready_to_prepare", "continue"
        ))
        public_v4 = public_ipv4_addresses(routes=routes)
        if public_v4:
            checks.append(diagnostic_step(
                "listener", "available", "direct_public_ipv4", "prepare_direct"
            ))
        ipv6 = global_ipv6_addresses(routes=routes)
        checks.append(diagnostic_step(
            "ipv6", "available" if ipv6 else "unsupported",
            "global_ipv6_available" if ipv6 else "no_global_ipv6",
            "prepare_direct" if ipv6 else "try_router_mapping",
        ))
        for checker, phase, reason in (
            (inspect_pcp, "pcp", "pcp_no_response"),
            (inspect_upnp, "upnp", "upnp_no_discovery"),
            (inspect_nat_pmp, "nat_pmp", "nat_pmp_no_response"),
        ):
            try:
                checks.append(checker(routes=routes))
            except ConnectivityError as exc:
                checks.append(exc.diagnostic())
            except OSError:
                checks.append(diagnostic_step(
                    phase, "unsupported", reason, "try_another_method"
                ))
        checks.append(firewall_diagnostic())
        available = any(item["result"] == "available" for item in checks[1:-1])
        upstream = next((
            item for item in checks
            if item["reason"] in {"upnp_wan_private", "upnp_wan_shared", "upstream_nat_detected"}
        ), None)
        summary = (
            diagnostic_step(
                "precondition", "available", "ready_to_prepare", "prepare_direct"
            ) if available else upstream or diagnostic_step(
                "precondition", "unavailable", "manual_setup_required",
                "set_up_manual_forward_or_choose_explicit_fallback",
            )
        )
        self._last_direct_diagnostic = summary
        return {"summary": summary, "checks": checks}

    def create_participant_host_access(
        self, *, purpose: str, scope_id: str, maximum_expires_at: int,
        access_mode: str = "participant_direct",
        preferred_external_port: int | None = None,
        _reservation=None,
    ) -> dict[str, Any]:
        if purpose not in {"personal", "workspace"} or not isinstance(scope_id, str):
            raise ValidationError("Participant host scope is invalid")
        if access_mode not in {"participant_direct", "participant_callback"}:
            raise ValidationError("Participant access mode is invalid")
        if self._identity is None or self.network is None:
            raise self._direct_failure(ConnectivityError(
                "precondition", "listener_bind_failed", recommended_action="restart_app"
            ))
        self.reconcile_participant_access()
        if self._active_host_count() >= MAX_ACTIVE_HOST_SESSIONS:
            raise self._direct_failure(ConnectivityError(
                "precondition", "session_limit", result="blocked",
                recommended_action="stop_an_active_invitation",
            ))

        routes = default_routes()
        try:
            ipv6_addresses = global_ipv6_addresses(routes=routes)
        except TypeError:
            ipv6_addresses = global_ipv6_addresses()
        public_v4 = public_ipv4_addresses(routes=routes)
        now = int(time.time())
        provisional_expiry = min(int(maximum_expires_at), now + DEFAULT_MAPPING_LIFETIME)
        record = self._new_listener_record(
            purpose=purpose, expires_at=provisional_expiry,
            ipv6=bool(ipv6_addresses), include_ipv4=True,
            reservation=_reservation,
        )
        session_id = record["id"]
        v4_listener = next(item for item in record["listeners"] if item["listen_ip"] == "0.0.0.0")
        endpoints: list[dict[str, Any]] = []
        mapping_record: dict[str, Any] | None = None
        pinhole_record: dict[str, Any] | None = None
        mapping_error: ConnectivityError | None = None
        mapping = None
        pinhole = None
        if public_v4:
            endpoints.extend({
                "host": address, "port": v4_listener["port"], "path": "public_ipv4"
            } for address in public_v4)
        else:
            try:
                mapping = create_port_mapping(
                    v4_listener["port"], lifetime=DEFAULT_MAPPING_LIFETIME, routes=routes,
                    preferred_external_port=(
                        preferred_external_port
                        if isinstance(preferred_external_port, int)
                        and not isinstance(preferred_external_port, bool)
                        and 1 <= preferred_external_port <= 65535
                        else 0
                    ),
                )
                mapping_record = mapping.record()
                if _reservation:
                    record["mapping"] = mapping_record
                    self.store.put("participant_host", session_id, record)
                endpoints.append(mapping.endpoint())
            except TypeError:
                if _reservation:
                    raise
                # Compatibility with deterministic injected mappers.
                try:
                    mapping = create_port_mapping(
                        v4_listener["port"], lifetime=DEFAULT_MAPPING_LIFETIME
                    )
                    mapping_record = mapping.record()
                    endpoints.append(mapping.endpoint())
                except ConnectivityError as exc:
                    mapping_error = exc
                except OSError:
                    mapping_error = ConnectivityError("pcp", "pcp_no_response")
            except ConnectivityError as exc:
                mapping_error = exc
            except OSError:
                mapping_error = ConnectivityError("pcp", "pcp_no_response")
        ipv6_listener = next((
            item for item in record["listeners"] if item["listen_ip"] == "::"
        ), None)
        if ipv6_listener is not None:
            try:
                pinhole = map_upnp_ipv6_pinhole(
                    ipv6_addresses[0], ipv6_listener["port"],
                    lifetime=DEFAULT_MAPPING_LIFETIME, routes=routes,
                )
                pinhole_record = pinhole.record()
                if _reservation:
                    record["pinhole"] = pinhole_record
                    self.store.put("participant_host", session_id, record)
                ipv6_addresses = ipv6_addresses[:1]
            except ConnectivityError as exc:
                # No advertised IPv6 firewall-control service is compatible with
                # routers that pass inbound IPv6 by policy. An explicit denial is
                # authoritative and that candidate must not be advertised.
                if exc.result == "blocked":
                    ipv6_addresses = []
            endpoints.extend({
                "host": address, "port": ipv6_listener["port"], "path": "public_ipv6"
            } for address in ipv6_addresses)
        if not endpoints:
            self.store.delete("participant_host", session_id)
            self._apply_participant_interfaces()
            raise self._direct_failure(mapping_error or ConnectivityError(
                "precondition", "manual_setup_required",
                recommended_action="set_up_manual_forward_or_choose_explicit_fallback",
            ))
        # Do not retain a listener that has no signed endpoint.
        if not public_v4 and mapping_record is None:
            record["listeners"] = [
                item for item in record["listeners"] if item["listen_ip"] != "0.0.0.0"
            ]
        if not ipv6_addresses:
            record["listeners"] = [
                item for item in record["listeners"] if item["listen_ip"] != "::"
            ]
        leases = [
            item.lifetime for item in (mapping, pinhole)
            if item is not None
        ]
        lease_expiry = (
            now + max(60, min(int(item) for item in leases) - HOST_EXPIRY_MARGIN_SECONDS)
            if leases else now + 24 * 60 * 60
        )
        expires_at = min(int(maximum_expires_at), lease_expiry)
        access = create_access_document(
            self._identity, endpoints[:3], network_name=record["network_name"],
            passphrase=record["passphrase"], now=now, expires_at=expires_at,
            mode=access_mode,
        )
        for listener in record["listeners"]:
            listener["expires_at"] = expires_at
        record.update({
            "scope_id": scope_id, "access": access, "mapping": mapping_record,
            "pinhole": pinhole_record,
            "expires_at": float(expires_at), "state": "prepared_unverified",
            "renew_at": (
                float(now + max(30, int(min(leases) * RENEWAL_FRACTION)))
                if leases else None
            ),
            "route_addresses": [
                item["host"] for item in endpoints if item["path"] in {"public_ipv4", "public_ipv6"}
            ],
        })
        self.store.put("participant_host", session_id, record)
        try:
            self._apply_participant_interfaces()
            self.network.reannounce()
        except Exception as exc:
            if _reservation:
                raise
            self.store.delete("participant_host", session_id)
            if mapping_record:
                remove_port_mapping(mapping_record)
            if pinhole_record:
                remove_port_mapping(pinhole_record)
            self._apply_participant_interfaces()
            raise self._direct_failure(ConnectivityError(
                "listener", "listener_bind_failed", result="blocked",
                recommended_action="retry_or_check_firewall",
            )) from exc
        self._last_direct_diagnostic = diagnostic_step(
            "listener", "prepared_unverified", "mapping_prepared", "share_invitation"
        )
        return {**access, "host_session_id": session_id}

    def prepare_manual_participant_host(self, purpose: Any) -> dict[str, Any]:
        if purpose not in {"personal", "workspace"}:
            raise ValidationError("Participant host purpose is invalid")
        if self._identity is None or self.network is None:
            raise self._direct_failure(ConnectivityError(
                "listener", "listener_bind_failed", recommended_action="restart_app"
            ))
        self.reconcile_participant_access()
        if self._active_host_count() >= MAX_ACTIVE_HOST_SESSIONS:
            raise self._direct_failure(ConnectivityError(
                "precondition", "session_limit", result="blocked",
                recommended_action="stop_an_active_invitation",
            ))
        now = int(time.time())
        record = self._new_listener_record(
            purpose=purpose, expires_at=now + MANUAL_SETUP_LIFETIME_SECONDS,
            ipv6=False, include_ipv4=True,
        )
        record["state"] = "manual_setup"
        self.store.put("participant_host", record["id"], record)
        device = " ".join(socket.gethostname().strip().split())[:64] or "This device"
        upstream_warning = None
        routes = default_routes()
        for checker in (inspect_upnp, inspect_nat_pmp):
            try:
                checker(routes=routes, timeout=0.25)
            except ConnectivityError as exc:
                if exc.reason in {
                    "upnp_wan_private", "upnp_wan_shared", "upstream_nat_detected"
                }:
                    upstream_warning = exc.reason
                    break
        return {
            "setup_id": record["id"], "device_label": device,
            "tcp_port": int(record["listeners"][0]["port"]),
            "expires_at": int(record["expires_at"]),
            "warning": "manual_rule_not_removed_automatically",
            "upstream_warning": upstream_warning,
        }

    def finalize_manual_participant_host(
        self, setup_id: Any, *, purpose: str, scope_id: str,
        maximum_expires_at: int, external_host: Any, external_port: Any,
        access_mode: str = "participant_direct",
    ) -> dict[str, Any]:
        if not isinstance(setup_id, str):
            raise ValidationError("Manual participant setup is invalid")
        record = self.store.get("participant_host", setup_id)
        if record is None or record.get("state") != "manual_setup" or record.get("purpose") != purpose:
            raise ValidationError("Manual participant setup is unavailable")
        endpoint = validate_endpoint({"host": external_host, "port": external_port})
        # Resolve now and reject the whole hostname if any answer is not public.
        resolve_public_endpoint(endpoint)
        now = int(time.time())
        expires_at = min(int(maximum_expires_at), now + 24 * 60 * 60)
        access = create_access_document(
            self._identity, [{**endpoint, "path": "manual"}],
            network_name=record["network_name"], passphrase=record["passphrase"],
            now=now, expires_at=expires_at, mode=access_mode,
        )
        for listener in record["listeners"]:
            listener["expires_at"] = expires_at
        record.update({
            "scope_id": scope_id, "access": access, "expires_at": float(expires_at),
            "state": "prepared_unverified", "manual": True, "renew_at": None,
        })
        self.store.put("participant_host", setup_id, record)
        self._apply_participant_interfaces()
        self.network.reannounce()
        return {**access, "host_session_id": setup_id}

    def configure_participant_firewall(self, access_id: Any) -> dict[str, str]:
        if not isinstance(access_id, str):
            raise ValidationError("Participant host ID is invalid")
        record = self.store.get("participant_host", access_id)
        if record is None or record.get("state") == "unavailable":
            raise ValidationError("Participant host is unavailable")
        listener = next((
            item for item in record.get("listeners", []) if item.get("listen_ip") == "0.0.0.0"
        ), None)
        if listener is None:
            return diagnostic_step(
                "firewall", "unsupported", "firewall_check_unsupported", "use_ipv6_firewall_instructions"
            )
        state_dir = Path(self.profile_dir) / "firewall"
        installed = install_temporary_windows_rule(
            access_id, int(listener["port"]), state_dir
        )
        if not installed.get("configured"):
            return diagnostic_step(
                "firewall", "blocked", str(installed.get("reason", "windows_firewall_blocked")),
                "follow_guided_firewall_instructions",
            )
        record["firewall"] = installed
        self.store.put("participant_host", access_id, record)
        return diagnostic_step(
            "firewall", "prepared_unverified", "mapping_prepared", "wait_for_recipient"
        )

    def _resolved_participant_endpoints(
        self, access: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        resolved: list[dict[str, Any]] = []
        results: list[dict[str, Any]] = []
        for index, endpoint in enumerate(access.get("endpoints", [])):
            try:
                addresses = resolve_public_endpoint({
                    "host": endpoint["host"], "port": endpoint["port"]
                })
            except ValidationError:
                results.append({
                    "candidate": index + 1, "path": endpoint["path"],
                    "result": "unresolved",
                })
                continue
            outcomes = [
                candidate_connection_result(address, int(endpoint["port"]))
                for address in addresses
            ]
            outcome = "connected" if "connected" in outcomes else next((
                result for result in ("refused", "no_ipv6_route", "timed_out")
                if result in outcomes
            ), "timed_out")
            results.append({
                "candidate": index + 1, "path": endpoint["path"], "result": outcome
            })
            for address in addresses:
                candidate = {"host": address, "port": endpoint["port"], "path": endpoint["path"]}
                if candidate not in resolved:
                    resolved.append(candidate)
                if len(resolved) >= 6:
                    break
        return resolved, results

    def approve_participant_access(
        self, value: Any, *, scope_kind: str, scope_id: str,
    ) -> dict[str, Any]:
        if scope_kind not in {
            "contact", "workspace", "pending_invitation", "workspace_device"
        } or not isinstance(scope_id, str):
            raise ValidationError("Participant access scope is invalid")
        access = validate_access_document(value)
        existing = self.store.get("participant_access", access["id"])
        if existing is not None and existing.get("access") != access:
            raise ValidationError("Participant access identity changed")
        scopes = list(existing.get("scopes", [])) if existing else []
        scope = {"kind": scope_kind, "id": scope_id}
        if scope not in scopes:
            scopes.append(scope)
        resolved, results = self._resolved_participant_endpoints(access)
        record = {
            "id": access["id"], "access": access, "scopes": scopes,
            "resolved_endpoints": resolved, "candidate_results": results,
            "resolution_attempted": True,
            "consented_at": float(time.time()),
        }
        self.store.put("participant_access", access["id"], record)
        try:
            self._apply_participant_interfaces()
        except Exception:
            pass
        return record

    def release_participant_scope(self, scope_kind: str, scope_id: str) -> None:
        """Remove only the selected relationship's imported route material."""

        changed = False
        scope = {"kind": scope_kind, "id": scope_id}
        for record_id, record in list(self.store.items("participant_access")):
            scopes = [item for item in record.get("scopes", []) if item != scope]
            if scopes == record.get("scopes", []):
                continue
            changed = True
            if scopes:
                record["scopes"] = scopes
                self.store.put("participant_access", record_id, record)
            else:
                self.store.delete("participant_access", record_id)
        if changed:
            try:
                self._apply_participant_interfaces()
            except Exception:
                pass

    def replace_participant_scope_access(
        self, value: Any, *, scope_kind: str, scope_id: str,
        additional_writes: list[tuple[str, str, dict[str, Any]]] | None = None,
    ) -> dict[str, Any]:
        """Persist a verified route before activation and retire older scope routes."""

        record, writes, deletions = self._prepare_participant_scope_replacement(
            value, scope_kind=scope_kind, scope_id=scope_id, additional_writes=additional_writes)
        self.store.put_and_delete(writes, deletions, redact_command_cache=True)
        self.reconcile_prepared_participant_access()
        return self.store.get("participant_access", record["id"]) or record

    def _prepare_participant_scope_replacement(
        self, value, *, scope_kind, scope_id, additional_writes=None,
    ):
        """Return scope replacement writes/deletions without DNS or activation."""

        if scope_kind not in {"contact", "workspace_device"} or not isinstance(scope_id, str):
            raise ValidationError("Participant access scope is invalid")
        access = validate_access_document(value)
        scope = {"kind": scope_kind, "id": scope_id}
        deletions: list[tuple[str, str]] = []
        writes: list[tuple[str, str, dict[str, Any]]] = []
        for record_id, record in self.store.items("participant_access"):
            if record_id == access["id"] or scope not in record.get("scopes", []):
                continue
            scopes = [item for item in record.get("scopes", []) if item != scope]
            if scopes:
                updated = dict(record)
                updated["scopes"] = scopes
                writes.append(("participant_access", record_id, updated))
            else:
                deletions.append(("participant_access", record_id))
        existing = self.store.get("participant_access", access["id"])
        if existing is not None and existing.get("access") != access:
            raise ValidationError("Participant access identity changed")
        scopes = list(existing.get("scopes", [])) if existing else []
        if scope not in scopes:
            scopes.append(scope)
        checked_scopes = list(existing.get("prepared_scope_checks", [])) if existing else []
        if scope not in checked_scopes:
            checked_scopes.append(scope)
        record = {
            "id": access["id"], "access": access, "scopes": scopes,
            "resolved_endpoints": [], "candidate_results": [],
            "resolution_attempted": False,
            "consented_at": float(time.time()),
            "prepared_replacement": True,
            "prepared_scope_checks": checked_scopes,
        }
        writes.append(("participant_access", access["id"], record))
        writes.extend(additional_writes or [])
        writes.append(("participant_reconcile", "current", {"revision": secrets.token_hex(16)}))
        return record, writes, deletions

    def reconcile_prepared_participant_access(self):
        """Apply only the current committed scope set; never replay old writes."""
        with self._dispatch_lock:
            marker = self.store.get("participant_reconcile", "current")
            if marker is None:
                return
            try:
                self._apply_participant_interfaces()
            except Exception:
                return
            if self.network is not None and self.store.get("participant_reconcile", "current") == marker:
                self.store.delete("participant_reconcile", "current")

    def promote_pending_callback(
        self,
        responder_destination: str,
        *,
        scope_kind: str,
        scope_id: str,
        purpose: str | None = None,
    ) -> None:
        """Move a consumed callback route onto the admitted relationship scope."""

        for pending_id, pending in self.store.items("email_invitation"):
            if (
                pending.get("state") != "consumed"
                or pending.get("responder_destination") != responder_destination
                or (purpose is not None and pending.get("purpose") != purpose)
            ):
                continue
            pending_scope = {"kind": "pending_invitation", "id": pending_id}
            durable_scope = {"kind": scope_kind, "id": scope_id}
            for record_id, record in self.store.items("participant_access"):
                scopes = list(record.get("scopes", []))
                if pending_scope not in scopes:
                    continue
                scopes = [item for item in scopes if item != pending_scope]
                if durable_scope not in scopes:
                    scopes.append(durable_scope)
                record["scopes"] = scopes
                self.store.put("participant_access", record_id, record)
            pending["promoted_scope"] = durable_scope
            self.store.put("email_invitation", pending_id, pending)

    def decline_pending_callbacks(
        self,
        responder_destination: str,
        *,
        purpose: str,
        legacy_scope_kind: str | None = None,
        legacy_scope_id: str | None = None,
    ) -> None:
        """Retire an unapproved peer's callback routes without other scopes."""

        pending = [
            (pending_id, record)
            for pending_id, record in self.store.items("email_invitation")
            if record.get("state") == "consumed"
            and record.get("purpose") == purpose
            and record.get("responder_destination") == responder_destination
        ]
        if not pending:
            return
        pending_scopes = [
            {"kind": "pending_invitation", "id": pending_id}
            for pending_id, _record in pending
        ]
        legacy_scope = {
            "kind": legacy_scope_kind,
            "id": legacy_scope_id,
        }
        release_legacy_scope = (
            legacy_scope_kind is not None
            and legacy_scope_id is not None
            and any(
                record.get("promoted_scope") == legacy_scope
                for _pending_id, record in pending
            )
        )
        writes: list[tuple[str, str, dict[str, Any]]] = []
        deletions: list[tuple[str, str]] = []
        changed = False
        for record_id, record in self.store.items("participant_access"):
            removable_scopes = list(pending_scopes)
            if (
                release_legacy_scope
                and record.get("access", {}).get("operator_destination")
                == responder_destination
            ):
                removable_scopes.append(legacy_scope)
            scopes = [
                item
                for item in record.get("scopes", [])
                if item not in removable_scopes
            ]
            if scopes == record.get("scopes", []):
                continue
            changed = True
            if scopes:
                updated = dict(record)
                updated["scopes"] = scopes
                writes.append(("participant_access", record_id, updated))
            else:
                deletions.append(("participant_access", record_id))
        now = time.time()
        for pending_id, record in pending:
            updated = dict(record)
            updated["state"] = "declined"
            updated["declined_at"] = now
            updated.pop("promoted_scope", None)
            writes.append(("email_invitation", pending_id, updated))
        self.store.put_and_delete(writes, deletions, redact_command_cache=True)
        if changed:
            try:
                self._apply_participant_interfaces()
            except Exception:
                pass

    def participant_connection_snapshot(self) -> list[dict[str, Any]]:
        return [{
            "id": record["id"],
            "candidate_results": [dict(item) for item in record.get("candidate_results", [])],
            "all_failed": bool(record.get("candidate_results")) and not any(
                item.get("result") == "connected" for item in record.get("candidate_results", [])
            ),
        } for record in self._participant_access_records()]

    def stop_participant_host(self, access_id: Any) -> dict[str, Any]:
        if not isinstance(access_id, str) or len(access_id) != 64:
            raise ValidationError("Participant host ID is invalid")
        record = self.store.get("participant_host", access_id)
        if record is None:
            return {"id": access_id, "stopped": False}
        self.store.delete("participant_host", access_id)
        try:
            self._apply_participant_interfaces()
        finally:
            if isinstance(record.get("mapping"), dict):
                remove_port_mapping(record["mapping"])
            if isinstance(record.get("pinhole"), dict):
                remove_port_mapping(record["pinhole"])
            if isinstance(record.get("firewall"), dict):
                remove_temporary_windows_rule(record["firewall"])
        return {"id": access_id, "stopped": True}

    def stop_participant_host_for_scope(self, purpose: str, scope_id: str) -> None:
        for record in list(self._participant_hosts()):
            if record.get("purpose") == purpose and record.get("scope_id") == scope_id:
                try:
                    self.stop_participant_host(record["id"])
                except Exception:
                    pass

    def _invalidate_host(self, record: dict[str, Any], reason: str) -> None:
        if isinstance(record.get("mapping"), dict):
            remove_port_mapping(record["mapping"])
        if isinstance(record.get("pinhole"), dict):
            remove_port_mapping(record["pinhole"])
        if isinstance(record.get("firewall"), dict):
            remove_temporary_windows_rule(record["firewall"])
        record.update({
            "state": "unavailable", "reason": reason, "listeners": [],
            "mapping": None, "pinhole": None, "firewall": None,
        })
        self.store.put("participant_host", record["id"], record)

    def reconcile_participant_access(self) -> None:
        self.reconcile_prepared_participant_access()
        now = time.time()
        changed = False
        for record in list(self._participant_hosts()):
            if record.get("reservation_operation_id") in self._participant_retirements():
                intent = self._participant_retirements()[record["reservation_operation_id"]]
                try:
                    self._retire_participant_intent(intent)
                except Exception:
                    pass
                continue
            if float(record.get("expires_at", 0)) <= now:
                self.stop_participant_host(record["id"])
                changed = True
                continue
            if record.get("state") in {"manual_setup", "unavailable"}:
                continue
            renew_at = record.get("renew_at")
            mappings = [
                (key, record.get(key)) for key in ("mapping", "pinhole")
                if isinstance(record.get(key), dict)
            ]
            if mappings and renew_at is not None and float(renew_at) <= now:
                try:
                    renewed = [
                        (key, renew_port_mapping(mapping))
                        for key, mapping in mappings
                    ]
                    for key, result in renewed:
                        record[key] = result.record()
                    record["renew_at"] = now + max(
                        30, int(min(result.lifetime for _key, result in renewed) * RENEWAL_FRACTION)
                    )
                    self.store.put("participant_host", record["id"], record)
                except ConnectivityError:
                    self._invalidate_host(record, "router_state_changed")
                    changed = True
                    continue
            expected = set(record.get("route_addresses", []))
            if expected:
                current = set(public_ipv4_addresses()) | set(global_ipv6_addresses())
                if not expected.issubset(current):
                    self._invalidate_host(record, "router_state_changed")
                    changed = True
        for record_id, record in self.store.items("participant_access"):
            if float(record.get("access", {}).get("expires_at", 0)) <= now:
                self.store.delete("participant_access", record_id)
                changed = True
        if changed:
            try:
                self._apply_participant_interfaces()
            except Exception:
                pass

    def participant_hosting_snapshot(self) -> list[dict[str, Any]]:
        now = time.time()
        snapshots: list[dict[str, Any]] = []
        for record in self._participant_hosts():
            state = str(record.get("state", "prepared_unverified"))
            if float(record.get("expires_at", 0)) <= now:
                state = "expired"
            elif state == "prepared_unverified" and self.network is not None:
                method = getattr(self.network, "participant_host_state", None)
                if callable(method):
                    try:
                        live = method(record["id"])
                        if int(live.get("client_count", 0)) > 0:
                            state = "recipient_connected"
                            record["state"] = state
                            record["verified_at"] = float(now)
                            self.store.put("participant_host", record["id"], record)
                    except Exception:
                        pass
            access = record.get("access") or {}
            snapshots.append({
                "id": record["id"], "purpose": record["purpose"],
                "scope_id": record.get("scope_id", ""),
                "endpoint_count": len(access.get("endpoints", [])),
                "methods": sorted({
                    endpoint.get("path") for endpoint in access.get("endpoints", [])
                    if isinstance(endpoint.get("path"), str)
                }),
                "expires_at": int(record["expires_at"]), "state": state,
                "reason": record.get("reason"),
                "firewall_configured": bool(record.get("firewall", {}).get("configured"))
                    if isinstance(record.get("firewall"), dict) else False,
            })
        return snapshots

    def close_participant_hosts(self) -> None:
        for record in list(self._participant_hosts()):
            try:
                self.stop_participant_host(record["id"])
            except Exception:
                self.store.delete("participant_host", record["id"])
        self._apply_participant_interfaces()

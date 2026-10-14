from __future__ import annotations

import platform
import secrets
import socket
import time
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


class ParticipantAccessServiceMixin:
    """Invitation-scoped participant hosting without a rendezvous or relay."""

    def _participant_hosts(self) -> list[dict[str, Any]]:
        return self.store.list("participant_host")

    def _participant_access_records(self) -> list[dict[str, Any]]:
        return self.store.list("participant_access")

    def _restore_participant_interfaces(self) -> None:
        now = time.time()
        listeners: list[dict[str, Any]] = []
        clients: list[dict[str, Any]] = []
        for record_id, record in self.store.items("participant_host"):
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
            endpoints = record.get("resolved_endpoints", access.get("endpoints", []))
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
    ) -> dict[str, Any]:
        session_id = secrets.token_hex(32)
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
    ) -> dict[str, Any]:
        if purpose not in {"personal", "workspace"} or not isinstance(scope_id, str):
            raise ValidationError("Participant host scope is invalid")
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
                    v4_listener["port"], lifetime=DEFAULT_MAPPING_LIFETIME, routes=routes
                )
                mapping_record = mapping.record()
                endpoints.append(mapping.endpoint())
            except TypeError:
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
            now=now, expires_at=expires_at,
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
        if scope_kind not in {"contact", "workspace"} or not isinstance(scope_id, str):
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
            "consented_at": float(time.time()),
        }
        self.store.put("participant_access", access["id"], record)
        try:
            self._apply_participant_interfaces()
        except Exception:
            pass
        return record

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
        now = time.time()
        changed = False
        for record in list(self._participant_hosts()):
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

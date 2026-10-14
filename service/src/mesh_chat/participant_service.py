from __future__ import annotations

import secrets
import time
from typing import Any

from .connectivity import (
    DEFAULT_MAPPING_LIFETIME,
    create_port_mapping,
    global_ipv6_addresses,
    remove_port_mapping,
    select_available_port,
)
from .errors import DirectConnectionUnavailable, ValidationError
from .participant import create_access_document, validate_access_document

MAX_ACTIVE_HOST_SESSIONS = 8
HOST_EXPIRY_MARGIN_SECONDS = 60


class ParticipantAccessServiceMixin:
    """Participant-operated Internet access with no third-party rendezvous.

    Host sessions and imported credentials live only in the encrypted vault.
    Renderer snapshots expose status summaries, never endpoint addresses or
    interface credentials.
    """

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
                self.store.delete("participant_host", record_id)
                continue
            listeners.extend(dict(item) for item in record.get("listeners", []))
        for record_id, record in self.store.items("participant_access"):
            access = record.get("access", {})
            if float(access.get("expires_at", 0)) <= now:
                self.store.delete("participant_access", record_id)
                continue
            for index, endpoint in enumerate(access.get("endpoints", [])):
                clients.append(
                    {
                        "id": access["id"],
                        "endpoint_index": index,
                        "host": endpoint["host"],
                        "port": endpoint["port"],
                        "network_name": access["network_name"],
                        "passphrase": access["passphrase"],
                        "expires_at": access["expires_at"],
                    }
                )
        self.settings.participant_listeners = listeners
        self.settings.participant_clients = clients

    def _apply_participant_interfaces(self) -> None:
        self._restore_participant_interfaces()
        if self.network is not None:
            self.network.apply_participant_interfaces(
                self.settings.participant_listeners,
                self.settings.participant_clients,
            )

    def create_participant_host_access(
        self,
        *,
        purpose: str,
        scope_id: str,
        maximum_expires_at: int,
    ) -> dict[str, Any]:
        if purpose not in {"personal", "workspace"} or not isinstance(scope_id, str):
            raise ValidationError("Participant host scope is invalid")
        identity = self._identity
        if identity is None or self.network is None:
            raise DirectConnectionUnavailable("Participant hosting is unavailable")
        self.reconcile_participant_access()
        if len(self._participant_hosts()) >= MAX_ACTIVE_HOST_SESSIONS:
            raise DirectConnectionUnavailable("Too many participant invitations are active")

        network_name = secrets.token_urlsafe(18)
        passphrase = secrets.token_urlsafe(32)
        listeners: list[dict[str, Any]] = []
        endpoints: list[dict[str, Any]] = []
        mapping_record: dict[str, Any] | None = None

        # IPv4 home-router mapping covers the common desktop-Wi-Fi to cellular
        # case. No external IP-discovery service is contacted: the local router
        # returns its own public mapping through UPnP, NAT-PMP, or PCP.
        ipv4_port = select_available_port()
        try:
            mapping = create_port_mapping(
                ipv4_port, lifetime=DEFAULT_MAPPING_LIFETIME
            )
            mapping_record = mapping.record()
            endpoints.append(mapping.endpoint())
            listeners.append(
                {
                    "listen_ip": "0.0.0.0",
                    "port": ipv4_port,
                    "network_name": network_name,
                    "passphrase": passphrase,
                }
            )
        except OSError:
            mapping = None

        # Globally routed IPv6 needs no NAT mapping. It remains best effort
        # because operating-system and router firewalls may still reject an
        # inbound connection; the recipient is the first independent verifier.
        ipv6_addresses = global_ipv6_addresses()
        if ipv6_addresses:
            try:
                ipv6_port = select_available_port(ipv6=True)
                endpoints.extend(
                    {
                        "host": address,
                        "port": ipv6_port,
                        "path": "public_ipv6",
                    }
                    for address in ipv6_addresses
                )
                listeners.append(
                    {
                        "listen_ip": "::",
                        "port": ipv6_port,
                        "network_name": network_name,
                        "passphrase": passphrase,
                    }
                )
            except OSError:
                pass

        if not endpoints:
            raise DirectConnectionUnavailable(
                "No public IPv6 or automatic router mapping is available"
            )
        now = int(time.time())
        lease_expiry = (
            now + max(60, int(mapping.lifetime) - HOST_EXPIRY_MARGIN_SECONDS)
            if mapping is not None
            else now + 24 * 60 * 60
        )
        expires_at = min(int(maximum_expires_at), lease_expiry)
        access = create_access_document(
            identity,
            endpoints,
            network_name=network_name,
            passphrase=passphrase,
            now=now,
            expires_at=expires_at,
        )
        for listener in listeners:
            listener.update({"id": access["id"], "expires_at": expires_at})
        record = {
            "id": access["id"],
            "purpose": purpose,
            "scope_id": scope_id,
            "access": access,
            "listeners": listeners,
            "mapping": mapping_record,
            "created_at": float(now),
            "expires_at": float(expires_at),
        }
        self.store.put("participant_host", access["id"], record)
        try:
            self._apply_participant_interfaces()
            self.network.reannounce()
        except Exception as exc:
            self.store.delete("participant_host", access["id"])
            if mapping_record is not None:
                remove_port_mapping(mapping_record)
            self._apply_participant_interfaces()
            raise DirectConnectionUnavailable(
                "Participant listener could not start"
            ) from exc
        return access

    def approve_participant_access(
        self,
        value: Any,
        *,
        scope_kind: str,
        scope_id: str,
    ) -> dict[str, Any]:
        if scope_kind not in {"contact", "workspace"} or not isinstance(scope_id, str):
            raise ValidationError("Participant access scope is invalid")
        access = validate_access_document(value)
        existing = self.store.get("participant_access", access["id"])
        if existing is not None and existing.get("access") != access:
            raise ValidationError("Participant access identity changed")
        scopes = list(existing.get("scopes", [])) if existing is not None else []
        scope = {"kind": scope_kind, "id": scope_id}
        if scope not in scopes:
            scopes.append(scope)
        record = {
            "id": access["id"],
            "access": access,
            "scopes": scopes,
            "consented_at": float(time.time()),
        }
        # Commit the signed credential before starting any outbound socket.
        self.store.put("participant_access", access["id"], record)
        try:
            self._apply_participant_interfaces()
        except Exception:
            # The route remains durable and is retried during reconciliation.
            pass
        return record

    def stop_participant_host(self, access_id: Any) -> dict[str, Any]:
        if not isinstance(access_id, str) or len(access_id) != 64:
            raise ValidationError("Participant host ID is invalid")
        record = self.store.get("participant_host", access_id)
        if record is None:
            return {"id": access_id, "stopped": False}
        self.store.delete("participant_host", access_id)
        mapping = record.get("mapping")
        try:
            self._apply_participant_interfaces()
        finally:
            # Never leave a router lease behind merely because a Reticulum
            # interface detach/config refresh raised during shutdown.
            if isinstance(mapping, dict):
                remove_port_mapping(mapping)
        return {"id": access_id, "stopped": True}

    def stop_participant_host_for_scope(self, purpose: str, scope_id: str) -> None:
        for record in list(self._participant_hosts()):
            if record.get("purpose") == purpose and record.get("scope_id") == scope_id:
                try:
                    self.stop_participant_host(record["id"])
                except Exception:
                    # The durable record and router mapping are removed before
                    # an interface-refresh error can escape. Lifecycle callers
                    # may already have committed an approval or revocation and
                    # must not report that operation as failed afterward.
                    pass

    def reconcile_participant_access(self) -> None:
        now = time.time()
        expired_hosts = [
            record
            for record in self._participant_hosts()
            if float(record.get("expires_at", 0)) <= now
        ]
        changed = bool(expired_hosts)
        for record in expired_hosts:
            self.store.delete("participant_host", record["id"])
            mapping = record.get("mapping")
            if isinstance(mapping, dict):
                remove_port_mapping(mapping)
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
        return [
            {
                "id": record["id"],
                "purpose": record["purpose"],
                "scope_id": record["scope_id"],
                "endpoint_count": len(record.get("access", {}).get("endpoints", [])),
                "methods": sorted(
                    {
                        endpoint.get("path")
                        for endpoint in record.get("access", {}).get("endpoints", [])
                        if isinstance(endpoint.get("path"), str)
                    }
                ),
                "expires_at": int(record["expires_at"]),
                "state": "ready" if float(record["expires_at"]) > now else "expired",
            }
            for record in self._participant_hosts()
        ]

    def close_participant_hosts(self) -> None:
        for record in self._participant_hosts():
            mapping = record.get("mapping")
            if isinstance(mapping, dict):
                remove_port_mapping(mapping, timeout=0.2)
            self.store.delete("participant_host", record["id"])
        # Rewrite the app-owned RNS config as well as the vault. Otherwise an
        # expired listener credential could remain on disk until next launch.
        self._apply_participant_interfaces()

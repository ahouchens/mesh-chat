from __future__ import annotations

import time
from typing import Any

from .errors import ValidationError
from .remote import (
    MAX_REMOTE_PROFILES,
    add_profile_scope,
    create_profile_document,
    new_profile_record,
    remove_profile_scope,
    resolve_public_endpoint,
    retry_delay,
    sanitized_profile,
    validate_profile_document,
)


class RemoteProfileServiceMixin:
    """Protected-vault lifecycle for consented remote connection profiles."""

    def _remote_profiles(self) -> list[dict[str, Any]]:
        return self.store.list("remote_profile")

    def _require_remote_profile(self, profile_id: Any) -> dict[str, Any]:
        if not isinstance(profile_id, str) or len(profile_id) != 64:
            raise ValidationError("Remote profile ID is invalid")
        record = self.store.get("remote_profile", profile_id)
        if record is None:
            raise ValidationError("Remote profile does not exist")
        return record

    def list_remote_profiles(self) -> dict[str, Any]:
        self._refresh_remote_profile_states()
        return {"profiles": [sanitized_profile(item) for item in self._remote_profiles()]}

    def preview_remote_profile(self, value: Any, allow_private: bool = False) -> dict[str, Any]:
        if not isinstance(allow_private, bool):
            raise ValidationError("Private endpoint choice is invalid")
        checked = validate_profile_document(value, allow_private=allow_private)
        propagation = checked.get("propagation_node")
        return {
            "id": checked["id"],
            "label": checked["label"],
            "endpoint_count": len(checked["endpoints"]),
            "expires_at": checked["expires_at"],
            "capabilities": checked["capabilities"],
            "private_endpoint_warning": allow_private,
            "propagation_identifier": (
                f"{propagation[:8]}…{propagation[-4:]}" if propagation else None
            ),
            "privacy_disclosure": (
                "The access-point operator can observe IP addresses, timing, packet sizes, "
                "connection duration, and Reticulum routing identifiers. It cannot decrypt "
                "or forge valid MeshChat content."
            ),
        }

    def create_manual_remote_profile(
        self,
        label: Any,
        endpoints: Any,
        propagation_node: Any = None,
        allow_private: Any = False,
    ) -> dict[str, Any]:
        if not isinstance(endpoints, list) or not isinstance(allow_private, bool):
            raise ValidationError("Remote profile input is invalid")
        profile = create_profile_document(
            label,
            endpoints,
            propagation_node=propagation_node,
            allow_private=allow_private,
        )
        record = self._approve_remote_document(
            profile,
            origin="manual",
            scope_kind="manual",
            scope_id=profile["id"],
            allow_private=allow_private,
        )
        return sanitized_profile(record)

    def approve_remote_profile(
        self,
        value: Any,
        *,
        origin: str,
        scope_kind: str,
        scope_id: str,
        allow_private: bool = False,
    ) -> dict[str, Any]:
        record = self._approve_remote_document(
            value,
            origin=origin,
            scope_kind=scope_kind,
            scope_id=scope_id,
            allow_private=allow_private,
        )
        return sanitized_profile(record)

    def _approve_remote_document(
        self,
        value: Any,
        *,
        origin: str,
        scope_kind: str,
        scope_id: str,
        allow_private: bool = False,
    ) -> dict[str, Any]:
        checked = validate_profile_document(value, allow_private=allow_private)
        existing = self.store.get("remote_profile", checked["id"])
        if existing is None:
            active_profiles = sum(
                1
                for item in self._remote_profiles()
                if float(item.get("profile", {}).get("expires_at", 0)) > time.time()
            )
            if active_profiles >= MAX_REMOTE_PROFILES:
                raise ValidationError("At most four remote connection profiles are supported")
            record = new_profile_record(
                checked,
                origin=origin,
                scope_kind=scope_kind,
                scope_id=scope_id,
                allow_private=allow_private,
            )
        else:
            if existing.get("profile") != checked:
                raise ValidationError("Remote profile ID collision")
            record = add_profile_scope(dict(existing), scope_kind, scope_id)
        # Consent and scope are durable before any DNS lookup, socket, or
        # Reticulum interface is created. A failed activation remains safely
        # retryable after restart.
        self.store.put("remote_profile", record["id"], record)
        record = self._activate_remote_profile(record)
        self._changed()
        return record

    def _runtime_remote_endpoints(self) -> list[dict[str, Any]]:
        endpoints: list[dict[str, Any]] = []
        now = time.time()
        for record in self._remote_profiles():
            if float(record.get("profile", {}).get("expires_at", 0)) < now:
                continue
            for endpoint in record.get("resolved_endpoints", []):
                if not isinstance(endpoint, dict):
                    continue
                endpoints.append(
                    {
                        "profile_id": record["id"],
                        "endpoint_index": int(endpoint["endpoint_index"]),
                        "host": endpoint["host"],
                        "port": int(endpoint["port"]),
                    }
                )
        return endpoints[: MAX_REMOTE_PROFILES * 2]

    def _apply_remote_runtime(self) -> None:
        network = getattr(self, "network", None)
        if network is not None:
            network.apply_remote_profiles(self._runtime_remote_endpoints())

    def _activate_remote_profile(self, record: dict[str, Any]) -> dict[str, Any]:
        record = dict(record)
        now = time.time()
        had_attempt = record.get("last_attempt_at") is not None
        if had_attempt:
            record["retry_count"] = min(
                12, int(record.get("retry_count", 0)) + 1
            )
        record["last_attempt_at"] = now
        record["updated_at"] = now
        resolved: list[dict[str, Any]] = []
        try:
            for index, endpoint in enumerate(record["profile"]["endpoints"]):
                answers = resolve_public_endpoint(
                    endpoint, allow_private=bool(record.get("allow_private", False))
                )
                # Rotate among multiple public answers across retries without
                # ever handing the hostname itself to Reticulum.
                selected = answers[int(record.get("retry_count", 0)) % len(answers)]
                resolved.append(
                    {
                        "endpoint_index": index,
                        "host": selected,
                        "port": endpoint["port"],
                    }
                )
            record["resolved_endpoints"] = resolved
            record["state"] = "connecting"
            record["last_error"] = None
            # RNS TCP clients retry their sockets asynchronously. This timer
            # bounds profile-level DNS revalidation/interface replacement and
            # grows independently until a real online interface resets it.
            record["next_retry_at"] = now + retry_delay(
                int(record.get("retry_count", 0)) + 4
            )
            self.store.put("remote_profile", record["id"], record)
            self._apply_remote_runtime()
        except Exception:
            # Do not persist upstream text: resolver and socket errors can
            # contain raw hostnames and addresses.
            record["resolved_endpoints"] = []
            record["connected_endpoints"] = 0
            record["state"] = "access_point_unavailable"
            record["last_error"] = "connection_validation_failed"
            if not had_attempt:
                record["retry_count"] = 1
            record["next_retry_at"] = now + retry_delay(
                int(record["retry_count"]) + 4
            )
            self.store.put("remote_profile", record["id"], record)
            try:
                self._apply_remote_runtime()
            except Exception:
                pass
        return record

    def _refresh_remote_profile_states(self) -> None:
        network = getattr(self, "network", None)
        if network is None:
            return
        for record in self._remote_profiles():
            previous = int(record.get("connected_endpoints", 0))
            state = network.remote_profile_state(
                record["id"], len(record.get("profile", {}).get("endpoints", []))
            )
            connected = int(state["connected_endpoint_count"])
            destinations = self._remote_scope_destinations(record)
            path_available = any(
                network.path_known(bytes.fromhex(destination))
                for destination in destinations
            )
            ratchet_ready = any(
                network.recipient_ready(bytes.fromhex(destination))
                for destination in destinations
            )
            propagation = record.get("profile", {}).get("propagation_node")
            try:
                propagation_available = bool(
                    propagation
                    and record.get("propagation_approved_at")
                    and network.propagation_available(propagation)
                )
            except Exception:
                propagation_available = False
            changed = (
                connected != previous
                or path_available != bool(record.get("path_available", False))
                or ratchet_ready != bool(record.get("ratchet_ready", False))
                or propagation_available
                != bool(record.get("propagation_available", False))
            )
            record["path_available"] = path_available
            record["ratchet_ready"] = ratchet_ready
            record["propagation_available"] = propagation_available
            if connected:
                record["connected_endpoints"] = connected
                record["state"] = "connected"
                record["last_connected_at"] = time.time()
                record["last_error"] = None
                record["retry_count"] = 0
                record["next_retry_at"] = time.time() + 5 * 60
                if previous == 0:
                    network.reannounce()
                    self._request_remote_scope_paths(record)
            elif record.get("resolved_endpoints"):
                record["connected_endpoints"] = 0
                record["state"] = "connecting"
            if changed:
                record["updated_at"] = time.time()
                self.store.put("remote_profile", record["id"], record)

    def _remote_scope_destinations(self, record: dict[str, Any]) -> set[str]:
        destinations: set[str] = set()
        for scope in record.get("scopes", []):
            if scope.get("kind") == "contact":
                contact = self.store.get("contact", scope.get("id", ""))
                if contact is not None:
                    destinations.add(contact["destination_hash"])
            elif scope.get("kind") == "workspace":
                workspace = self.store.get("workspace", scope.get("id", ""))
                if workspace is None:
                    # Workspace records use a keyed record ID; find by public ID.
                    workspace = next(
                        (item for item in self.store.list("workspace") if item.get("id") == scope.get("id")),
                        None,
                    )
                if workspace is not None:
                    for member in workspace.get("members", []):
                        for device in member.get("devices", [member.get("device", {})]):
                            destination = device.get("destination_hash") if isinstance(device, dict) else None
                            if isinstance(destination, str):
                                destinations.add(destination)
        return destinations

    def _request_remote_scope_paths(self, record: dict[str, Any]) -> None:
        network = getattr(self, "network", None)
        if network is None:
            return
        destinations = self._remote_scope_destinations(record)
        for destination in destinations:
            try:
                network.request_path(bytes.fromhex(destination))
            except (TypeError, ValueError):
                continue

    def reconcile_remote_profiles(self, *, force_dns: bool = False) -> None:
        now = time.time()
        changed_runtime = False
        for record in self._remote_profiles():
            expires = float(record.get("profile", {}).get("expires_at", 0))
            if expires <= now:
                if record.get("state") != "expired":
                    record["state"] = "expired"
                    record["resolved_endpoints"] = []
                    record["connected_endpoints"] = 0
                    record["updated_at"] = now
                    self.store.put("remote_profile", record["id"], record)
                    changed_runtime = True
                continue
            if force_dns or float(record.get("next_retry_at", 0)) <= now:
                self._activate_remote_profile(record)
        if changed_runtime:
            try:
                self._apply_remote_runtime()
            except Exception:
                pass
        self._refresh_remote_profile_states()

    def retry_remote_profile(self, profile_id: Any) -> dict[str, Any]:
        record = self._require_remote_profile(profile_id)
        if float(record["profile"]["expires_at"]) <= time.time():
            raise ValidationError("Remote profile has expired")
        record["next_retry_at"] = time.time()
        self.store.put("remote_profile", record["id"], record)
        record = self._activate_remote_profile(record)
        self._refresh_remote_profile_states()
        return sanitized_profile(self._require_remote_profile(record["id"]))

    def test_remote_profile(self, profile_id: Any) -> dict[str, Any]:
        return self.retry_remote_profile(profile_id)

    def release_remote_scope(self, kind: str, scope_id: str) -> None:
        for record in self._remote_profiles():
            if {"kind": kind, "id": scope_id} not in record.get("scopes", []):
                continue
            removable = remove_profile_scope(record, kind, scope_id)
            if removable:
                self.store.delete("remote_profile", record["id"])
            else:
                self.store.put("remote_profile", record["id"], record)
        try:
            self._apply_remote_runtime()
        except Exception:
            pass

    def remove_remote_profile(self, profile_id: Any) -> dict[str, Any]:
        record = self._require_remote_profile(profile_id)
        if record.get("propagation_approved_at") is not None:
            raise ValidationError(
                "Remove offline delivery approval before removing this profile"
            )
        # Explicit removal detaches transport for every scope but does not alter
        # contact trust, workspace membership, identities, or durable outboxes.
        self.store.delete("remote_profile", record["id"])
        try:
            self._apply_remote_runtime()
        except Exception:
            # The durable consent is gone. A stale runtime interface will be
            # detached by the next reconciliation or service restart.
            pass
        self._changed()
        return {"id": record["id"], "removed": True}

    def approve_remote_propagation(self, profile_id: Any) -> dict[str, Any]:
        record = self._require_remote_profile(profile_id)
        if float(record.get("profile", {}).get("expires_at", 0)) <= time.time():
            raise ValidationError("Remote profile has expired")
        node = record["profile"].get("propagation_node")
        if node is None:
            raise ValidationError("Remote profile does not recommend offline delivery")
        record["propagation_approved_at"] = int(time.time())
        record["updated_at"] = time.time()
        nodes = list(self.settings.approved_propagation_nodes)
        if node not in nodes:
            if len(nodes) >= 16:
                raise ValidationError("Propagation-node allowlist is full")
            nodes.append(node)
        self.settings.approved_propagation_nodes = nodes
        # Persist both approvals before asking LXMF to contact the node.
        self.store.put_many(
            [
                ("remote_profile", record["id"], record),
                ("settings", "network", self.settings.to_dict()),
            ]
        )
        network = getattr(self, "network", None)
        if network is not None:
            try:
                network.apply_propagation_nodes(nodes)
            except Exception:
                record["propagation_available"] = False
                self.store.put("remote_profile", record["id"], record)
        self._changed()
        return sanitized_profile(record)

    def remove_remote_propagation(self, profile_id: Any) -> dict[str, Any]:
        record = self._require_remote_profile(profile_id)
        node = record["profile"].get("propagation_node")
        record["propagation_approved_at"] = None
        record["updated_at"] = time.time()
        still_used = any(
            item["id"] != record["id"]
            and item.get("profile", {}).get("propagation_node") == node
            and item.get("propagation_approved_at") is not None
            for item in self._remote_profiles()
        )
        nodes = list(self.settings.approved_propagation_nodes)
        if node in nodes and not still_used:
            nodes.remove(node)
        self.settings.approved_propagation_nodes = nodes
        self.store.put_many(
            [
                ("remote_profile", record["id"], record),
                ("settings", "network", self.settings.to_dict()),
            ]
        )
        network = getattr(self, "network", None)
        if network is not None:
            try:
                network.apply_propagation_nodes(nodes)
            except Exception:
                pass
        self._changed()
        return sanitized_profile(record)

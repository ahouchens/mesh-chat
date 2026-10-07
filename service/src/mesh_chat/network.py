from __future__ import annotations

import hashlib
import ipaddress
import socket
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable

import LXMF
import RNS

from .app_protocol import build_fields, parse_payload
from .errors import NetworkUnavailable, RecipientKeysUnavailable, ValidationError
from .invitations import verify_invitation
from .models import DeliveryState, MessageKind
from .reticulum_config import NetworkSettings, write_config
from .workspace_protocol import verify_workspace_join
from .workspace_wire import is_workspace_payload, parse_workspace_payload

InboundCallback = Callable[[LXMF.LXMessage], None]
StatusCallback = Callable[[str, DeliveryState, str | None], None]

LAN_FALLBACK_INTERFACE = "Mesh Chat LAN fallback"
LAN_FALLBACK_MAX_CLIENTS = 4
LAN_FALLBACK_ATTEMPTS_PER_MINUTE = 10
LAN_FALLBACK_PORT_MIN = 42000
LAN_FALLBACK_PORT_SPAN = 7000
CALLBACK_QUEUE_MAX_ITEMS = 256
CALLBACK_SHUTDOWN_TIMEOUT = 0.5
CALLBACK_CANCEL_TIMEOUT = 0.1


class EmbeddedRuntimeTermination(RuntimeError):
    """A process-level RNS exit converted into an embedded-runtime failure."""


def _local_ipv4_entries(rns_module: Any = RNS) -> list[tuple[str, int]]:
    """Return concrete on-link IPv4 addresses without exposing them to logs."""

    entries: list[tuple[str, int]] = []
    seen: set[str] = set()
    try:
        netinfo = rns_module.Interfaces.netinfo
        for interface_name in netinfo.interfaces():
            addresses = netinfo.ifaddresses(interface_name)
            for value in addresses.get(netinfo.AF_INET, []):
                raw_address = value.get("addr")
                prefix = value.get("prefix", 32)
                try:
                    address = ipaddress.ip_address(raw_address)
                    prefix_value = int(prefix)
                except (TypeError, ValueError):
                    continue
                if (
                    not isinstance(address, ipaddress.IPv4Address)
                    or address.is_loopback
                    or address.is_unspecified
                    or address.is_multicast
                    or address.is_reserved
                    or raw_address in seen
                    or not 0 <= prefix_value <= 32
                ):
                    continue
                # Invitations are intentionally limited to local/on-link routes.
                if not (
                    address.is_private
                    or address.is_link_local
                    or address in ipaddress.ip_network("100.64.0.0/10")
                ):
                    continue
                seen.add(raw_address)
                entries.append((raw_address, prefix_value))
    except Exception:
        return []
    return entries


def lan_ipv4_addresses(rns_module: Any = RNS, *, limit: int = 3) -> list[str]:
    """Return a small, preferred-first list of LAN addresses for signed hints."""

    entries = _local_ipv4_entries(rns_module)
    preferred: str | None = None
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            # UDP connect selects a route but sends no packet.
            probe.connect(("192.0.2.1", 9))
            candidate = str(probe.getsockname()[0])
            if any(address == candidate for address, _prefix in entries):
                preferred = candidate
    except OSError:
        pass
    # Windows and mobile hosts can expose several disconnected or virtual
    # adapters with self-assigned 169.254/16 addresses. Keep a route-selected
    # address first, then prefer generally useful private/CGNAT addresses so
    # those stale adapters cannot consume the bounded invitation hint slots.
    regular = [
        address
        for address, _prefix in entries
        if address != preferred and not ipaddress.ip_address(address).is_link_local
    ]
    link_local = [
        address
        for address, _prefix in entries
        if address != preferred and ipaddress.ip_address(address).is_link_local
    ]
    ordered = ([preferred] if preferred else []) + regular + link_local
    return ordered[: max(0, limit)]


def _source_is_on_lan(source: str, rns_module: Any = RNS) -> bool:
    try:
        address = ipaddress.ip_address(source)
    except ValueError:
        return False
    if not isinstance(address, ipaddress.IPv4Address):
        return False
    for local_address, prefix in _local_ipv4_entries(rns_module):
        network = ipaddress.ip_network(f"{local_address}/{prefix}", strict=False)
        if address in network:
            return True
    return False


def select_lan_listener_port(identity_hash: bytes, preferred: int | None = None) -> int:
    """Select a stable available port before Reticulum starts its listener."""

    candidates: list[int] = []
    if preferred is not None:
        candidates.append(preferred)
    seed = int.from_bytes(identity_hash[:2], "big") if identity_hash else 0
    start = LAN_FALLBACK_PORT_MIN + seed % LAN_FALLBACK_PORT_SPAN
    candidates.extend(
        LAN_FALLBACK_PORT_MIN
        + ((start - LAN_FALLBACK_PORT_MIN + offset) % LAN_FALLBACK_PORT_SPAN)
        for offset in range(64)
    )
    for port in dict.fromkeys(candidates):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.bind(("0.0.0.0", port))
            return port
        except OSError:
            continue
    raise NetworkUnavailable("No local TCP listener port is available")


def install_lan_listener_guard(rns_module: Any = RNS) -> None:
    """Bound the app-owned wildcard TCP listener before RNS handles a client."""

    try:
        server_class = rns_module.Interfaces.TCPInterface.TCPServerInterface
    except (AttributeError, ImportError):
        return
    if getattr(server_class, "_mesh_chat_lan_guard", False):
        return
    original_incoming = server_class.incoming_connection

    def reject(handler: Any) -> None:
        try:
            handler.request.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        try:
            handler.request.close()
        except Exception:
            pass

    def guarded_incoming(interface: Any, handler: Any) -> Any:
        if getattr(interface, "name", None) != LAN_FALLBACK_INTERFACE:
            return original_incoming(interface, handler)
        lock = getattr(interface, "_mesh_chat_guard_lock", None)
        if lock is None:
            lock = threading.Lock()
            interface._mesh_chat_guard_lock = lock
        source = str(handler.client_address[0])
        now = time.monotonic()
        with lock:
            attempts = getattr(interface, "_mesh_chat_attempts", {})
            history = attempts.setdefault(source, deque())
            while history and history[0] < now - 60:
                history.popleft()
            active = int(getattr(interface, "_mesh_chat_active", 0))
            if (
                not _source_is_on_lan(source, rns_module)
                or active >= LAN_FALLBACK_MAX_CLIENTS
                or len(history) >= LAN_FALLBACK_ATTEMPTS_PER_MINUTE
            ):
                reject(handler)
                return None
            history.append(now)
            interface._mesh_chat_attempts = attempts
            interface._mesh_chat_active = active + 1
        try:
            return original_incoming(interface, handler)
        finally:
            with lock:
                interface._mesh_chat_active = max(
                    0, int(getattr(interface, "_mesh_chat_active", 1)) - 1
                )

    server_class.incoming_connection = guarded_incoming
    server_class._mesh_chat_lan_guard = True


def install_embedded_runtime_guards(rns_module: Any = RNS) -> None:
    """Keep upstream process exits from terminating an Android/iOS host app.

    RNS is normally the owner of its Python process and intentionally uses
    ``os._exit`` for unrecoverable configuration/interface failures. Mobile
    embeds Python inside the UI process, so that behavior would also kill the
    entire app. A failed interface is isolated and marked unavailable; other
    fatal exits become catchable startup errors.
    """

    # Upstream TCP clients synchronously wait for their first connection by
    # default. Invitations can contain several signed return routes, so adding
    # or reprioritising those routes on an approval command could otherwise
    # consume five seconds per unreachable address and outlive the desktop IPC
    # deadline. Upstream already provides an asynchronous initial-connect path;
    # select it before Reticulum constructs configured or dynamically attached
    # clients. Assignment is intentionally repeated so this remains true even
    # when the rest of the guards were installed by an earlier bridge call.
    try:
        rns_module.Interfaces.TCPInterface.TCPClientInterface.SYNCHRONOUS_START = False
    except (AttributeError, ImportError):
        pass

    reticulum_class = rns_module.Reticulum
    if getattr(reticulum_class, "_mesh_chat_embedded_guards", False):
        return

    original_synthesize = reticulum_class._synthesize_interface

    def blocked_panic() -> None:
        raise EmbeddedRuntimeTermination("reticulum_panic_blocked")

    def blocked_exit(_code: int = 0) -> None:
        raise EmbeddedRuntimeTermination("reticulum_exit_blocked")

    def guarded_synthesize(instance: Any, *args: Any, **kwargs: Any) -> Any:
        transport = getattr(rns_module, "Transport", None)
        interfaces_before = {
            id(interface) for interface in list(getattr(transport, "interfaces", []))
        }
        try:
            return original_synthesize(instance, *args, **kwargs)
        except EmbeddedRuntimeTermination:
            # Upstream adds an interface before final_init(), and its error path
            # calls panic without removing that partially constructed object.
            # Detach only interfaces added by this synthesis attempt so failed
            # sockets and threads cannot poison the embedded process.
            for interface in list(getattr(transport, "interfaces", [])):
                if id(interface) in interfaces_before:
                    continue
                try:
                    interface.detach()
                except Exception:
                    pass
                try:
                    transport.remove_interface(interface)
                except Exception:
                    pass
            instance._mesh_chat_interface_start_failed = True
            return None

    rns_module.panic = blocked_panic
    rns_module.exit = blocked_exit
    reticulum_class._synthesize_interface = guarded_synthesize
    reticulum_class._mesh_chat_embedded_guards = True
    install_lan_listener_guard(rns_module)


def map_native_delivery_state(method: int, state: int) -> DeliveryState:
    """Map transport evidence without overstating durable recipient delivery."""
    if method == LXMF.LXMessage.PROPAGATED and state == LXMF.LXMessage.SENT:
        return DeliveryState.STORED_FOR_DELIVERY
    if method == LXMF.LXMessage.DIRECT and state == LXMF.LXMessage.DELIVERED:
        return DeliveryState.RECEIVED_BY_ENDPOINT
    return DeliveryState.SENDING


def validate_unknown_source_signature(message: LXMF.LXMessage, public_key: bytes) -> bool:
    """Validate an inbound LXMF signature using a signed invitation identity.

    LXMF cannot validate the first message from an unknown source because its
    identity is not in the local recall table yet. The contact request carries
    that public identity in a separately signed, destination-bound invitation.
    Reconstruct the native LXMF signed bytes before remembering the identity.
    """

    packed = getattr(message, "packed", None)
    destination_length = LXMF.LXMessage.DESTINATION_LENGTH
    signature_length = LXMF.LXMessage.SIGNATURE_LENGTH
    header_length = 2 * destination_length + signature_length
    if not isinstance(packed, bytes) or len(packed) <= header_length:
        return False
    destination_hash = packed[:destination_length]
    source_hash = packed[destination_length : 2 * destination_length]
    signature = packed[2 * destination_length : header_length]
    packed_payload = packed[header_length:]
    if (
        destination_hash != getattr(message, "destination_hash", None)
        or source_hash != getattr(message, "source_hash", None)
    ):
        return False
    identity = RNS.Identity(create_keys=False)
    if not identity.load_public_key(public_key):
        return False
    if RNS.Destination.hash(identity, "lxmf", "delivery") != source_hash:
        return False
    hashed_part = destination_hash + source_hash + packed_payload
    message_hash = RNS.Identity.full_hash(hashed_part)
    if getattr(message, "hash", message_hash) != message_hash:
        return False
    return bool(identity.validate(signature, hashed_part + message_hash))


class ReticulumNetwork:
    """Narrow adapter over the pinned RNS and LXMF reference APIs."""

    def __init__(
        self,
        profile_dir: Path,
        identity: RNS.Identity,
        display_name: str,
        settings: NetworkSettings,
        inbound_callback: InboundCallback,
        status_callback: StatusCallback,
    ):
        self.profile_dir = profile_dir
        self.identity = identity
        self.settings = settings
        self._inbound_callback = inbound_callback
        self._status_callback = status_callback
        self._send_lock = threading.RLock()
        # Keep correlation bookkeeping independent from outbound/router
        # serialization. LXMF can invoke callbacks while one of its own locks
        # is held; those callbacks must never wait for a sender which may in
        # turn be waiting for that router lock.
        self._message_lock = threading.RLock()
        # One durable logical delivery can briefly have more than one native
        # attempt (for example an older build may have retried a group leg
        # before its failure callback). Keep every plaintext-bearing object so
        # local conversation deletion can cancel and release all of them.
        self._messages: dict[str, list[LXMF.LXMessage]] = {}
        # LXMF invokes delivery, failure and inbound handlers while some of its
        # own router locks are held. Calling back into MeshChatService from
        # those frames can invert the lock order with an outbound retry (service
        # lock -> LXMF lock versus LXMF lock -> service lock) and freeze every
        # later renderer command. A bounded dispatcher preserves inbound FIFO
        # and status ordering while letting the LXMF-owned thread return
        # without waiting for the service lock or queue capacity.
        self._callback_capacity = CALLBACK_QUEUE_MAX_ITEMS
        self._callback_items: deque[
            tuple[str, Callable[..., None], tuple[Any, ...]]
        ] = deque()
        self._callback_condition = threading.Condition()
        self._callback_accepting = True
        self._callback_cancelled = False
        # Content-free counters are intentionally kept private. They make the
        # overload policy testable without logging identities or messages.
        self._callback_dropped_inbound = 0
        self._callback_dropped_status = 0
        self._callback_thread = threading.Thread(
            target=self._dispatch_callbacks,
            name="mesh-chat-network-callbacks",
            daemon=True,
        )

        # RNS normally owns its entire process and exits on any interface
        # construction error. Mesh Chat owns the service lifecycle on desktop
        # and mobile, so isolate a failed optional interface on both runtimes.
        install_embedded_runtime_guards()
        self.rns_dir = profile_dir / "reticulum"
        write_config(self.rns_dir, settings)
        # A callback prevents RNS from writing to stdout, which is reserved for
        # framed IPC. It also keeps destination IDs and message details out of logs.
        self.reticulum = RNS.Reticulum(
            configdir=str(self.rns_dir), loglevel=RNS.LOG_ERROR, logdest=lambda _line: None
        )
        self.interface_start_failed = bool(
            getattr(self.reticulum, "_mesh_chat_interface_start_failed", False)
        ) or not self.interface_available
        static_peers = [bytes.fromhex(value) for value in settings.approved_propagation_nodes]
        self.router = LXMF.LXMRouter(
            identity=identity,
            storagepath=str(profile_dir / "network-state"),
            autopeer=False,
            static_peers=static_peers,
            from_static_only=True,
            propagation_limit=256,
            delivery_limit=64,
            sync_limit=1024,
            enforce_ratchets=True,
            enforce_stamps=False,
            max_peers=max(4, len(static_peers)),
            max_inbound_syncs=2,
        )
        self.delivery_destination = self.router.register_delivery_identity(
            identity, display_name=display_name
        )
        if self.delivery_destination is None:
            raise NetworkUnavailable("Could not register LXMF delivery identity")
        self.delivery_destination.set_retained_ratchets(RNS.Destination.RATCHET_COUNT)
        self.router.register_delivery_callback(self._on_inbound)

        if settings.approved_propagation_nodes:
            self.router.set_outbound_propagation_node(static_peers[0])
        if settings.store_for_offline:
            self.router.set_message_storage_limit(megabytes=100)
            self.router.enable_propagation()

        self.router.announce(self.delivery_destination.hash)
        if settings.approved_propagation_nodes:
            self.router.request_messages_from_propagation_node(identity)
        # Start only after every fallible constructor step. Inbound callbacks
        # registered above can safely queue during this short interval; if
        # startup fails, no orphan dispatcher thread is left behind.
        self._callback_thread.start()

    @property
    def destination_hash(self) -> bytes:
        return self.delivery_destination.hash

    @property
    def interface_available(self) -> bool:
        """Whether at least one configured Reticulum interface can receive traffic."""
        return any(
            bool(getattr(interface, "online", False))
            and bool(getattr(interface, "receives", False))
            for interface in list(RNS.Transport.interfaces)
        )

    def remember_contact(self, public_key: bytes, destination_hash: bytes) -> None:
        identity = RNS.Identity(create_keys=False)
        if not identity.load_public_key(public_key):
            raise ValidationError("Contact public identity is invalid")
        derived = RNS.Destination.hash(identity, "lxmf", "delivery")
        if derived != destination_hash:
            raise ValidationError("Contact destination binding is invalid")
        synthetic_announce = hashlib.sha256(
            b"mesh-chat:verified-invitation:" + destination_hash + public_key
        ).digest()
        RNS.Identity.remember(synthetic_announce, destination_hash, public_key)
        RNS.Transport.request_path(destination_hash)

    def recipient_ready(self, destination_hash: bytes) -> bool:
        return (
            RNS.Identity.recall(destination_hash) is not None
            and RNS.Identity.get_ratchet(destination_hash) is not None
        )

    def path_known(self, destination_hash: bytes) -> bool:
        return bool(RNS.Transport.has_path(destination_hash))

    def request_path(self, destination_hash: bytes) -> None:
        RNS.Transport.request_path(destination_hash)

    def prefer_signed_route(
        self,
        destination_hash: bytes,
        connection_hints: list[dict[str, Any]],
        *,
        timeout: float = 0.75,
    ) -> bool:
        """Briefly prefer a TCP client imported from this contact's invitation.

        Reticulum deliberately keeps the first equal-hop route for a repeated
        announce. On Android, nearby discovery can therefore remain selected
        even after the TCP client from a signed invitation connects
        asynchronously. Wait a bounded time for that exact client, ask for the
        destination only on it, and let its minimally higher configured gravity
        replace the nearby path before handing chat to LXMF. The path response
        is still identity-signed and ratcheted; the TCP socket itself is not
        treated as peer authentication.

        The destination hash is never broadcast to unrelated configured peers
        or the wildcard LAN listener. ``True`` means the signed route became
        selected. ``False`` means it did not respond within the small bound;
        callers must permit normal Reticulum routing as a fallback instead of
        pinning the durable outbox indefinitely.
        """

        endpoints: set[tuple[str, int]] = set()
        for hint in connection_hints:
            try:
                if hint.get("type") == "tcp":
                    endpoints.add((str(hint["host"]), int(hint["port"])))
            except (AttributeError, KeyError, TypeError, ValueError):
                # Contact hints are validated before persistence, but this
                # preference remains best effort for upgraded/legacy vaults.
                continue
        if not endpoints:
            return False

        deadline = time.monotonic() + max(0.0, timeout)
        requested: set[int] = set()
        while True:
            preferred: list[Any] = []
            for interface in list(RNS.Transport.interfaces):
                if not str(getattr(interface, "name", "")).startswith(
                    "Private TCP peer "
                ) or not bool(getattr(interface, "online", False)):
                    continue
                try:
                    endpoint = (
                        str(getattr(interface, "target_ip", "")),
                        int(getattr(interface, "target_port", -1)),
                    )
                except (TypeError, ValueError):
                    continue
                if endpoint in endpoints:
                    preferred.append(interface)

            try:
                current = RNS.Transport.next_hop_interface(destination_hash)
            except Exception:
                current = None
            if current in preferred:
                return True
            for interface in preferred:
                marker = id(interface)
                if marker not in requested:
                    try:
                        RNS.Transport.request_path(
                            destination_hash, on_interface=interface
                        )
                    except Exception:
                        # A malformed/stale TCP client must not turn this
                        # best-effort preference into a permanent outbox pin.
                        # Normal Reticulum routing remains the fallback below.
                        pass
                    requested.add(marker)

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(0.025, remaining))

    def apply_connection_settings(self, settings: NetworkSettings) -> None:
        """Attach newly approved TCP hints without restarting onboarding."""
        self.settings = settings
        write_config(self.rns_dir, settings)
        desired: dict[str, dict[str, Any]] = {
            f"Private TCP peer {index + 1}": hint
            for index, hint in enumerate(settings.tcp_clients)
        }
        for interface in list(RNS.Transport.interfaces):
            name = str(getattr(interface, "name", ""))
            if not name.startswith("Private TCP peer "):
                continue
            hint = desired.get(name)
            endpoint_matches = hint is not None and (
                str(getattr(interface, "target_ip", "")) == hint["host"]
                and int(getattr(interface, "target_port", -1)) == hint["port"]
            )
            if not endpoint_matches:
                self.reticulum.detach_interface(name)
        existing = {str(interface.name) for interface in RNS.Transport.interfaces}
        for name in desired:
            if name not in existing:
                self.reticulum.attach_interface(name)

    def invitation_hints(self) -> list[dict[str, Any]]:
        """Return only live, concrete listener addresses for a signed invitation."""

        hints: list[dict[str, Any]] = []
        if self.settings.lan_fallback and self.settings.lan_listener_port is not None:
            listener_online = any(
                str(getattr(interface, "name", "")) == LAN_FALLBACK_INTERFACE
                and bool(getattr(interface, "online", False))
                and bool(getattr(interface, "receives", False))
                for interface in list(RNS.Transport.interfaces)
            )
            if listener_online:
                hints.extend(
                    {
                        "type": "tcp",
                        "host": address,
                        "port": self.settings.lan_listener_port,
                    }
                    for address in lan_ipv4_addresses()
                )
        listener = self.settings.tcp_listener
        if listener and listener["host"] not in {"0.0.0.0", "::", "127.0.0.1", "::1"}:
            hints.append({"type": "tcp", **listener})
        deduplicated: list[dict[str, Any]] = []
        for hint in hints:
            if hint not in deduplicated:
                deduplicated.append(hint)
        return deduplicated[:8]

    def send(
        self,
        *,
        logical_id: str,
        conversation_id: str,
        recipient_public_key: bytes,
        recipient_destination: bytes,
        kind: MessageKind,
        text: str,
        expires_at: int,
        receipt_for: str | None = None,
        invitation: str | None = None,
        propagated: bool = False,
        reaction_for: str | None = None,
        reaction_emoji: str | None = None,
        reaction_active: bool | None = None,
        reaction_revision: int | None = None,
    ) -> str:
        fields = build_fields(
            kind=kind,
            logical_id=logical_id,
            conversation=conversation_id,
            expires_at=expires_at,
            receipt_for=receipt_for,
            invitation=invitation,
            reaction_for=reaction_for,
            reaction_emoji=reaction_emoji,
            reaction_active=reaction_active,
            reaction_revision=reaction_revision,
        )
        return self.send_with_fields(
            logical_id=logical_id,
            recipient_public_key=recipient_public_key,
            recipient_destination=recipient_destination,
            text=text,
            fields=fields,
            propagated=propagated,
        )

    def send_with_fields(
        self,
        *,
        logical_id: str,
        recipient_public_key: bytes,
        recipient_destination: bytes,
        text: str,
        fields: dict[int, Any],
        propagated: bool = False,
    ) -> str:
        """Send an application payload over the same guarded LXMF path.

        Direct messages and group-delivery legs use different authenticated
        metadata schemas, but both must retain the exact same recipient
        identity binding, ratchet requirement, and delivery evidence mapping.
        The service constructs the fields; renderer input is never passed
        through here as an arbitrary LXMF field map.
        """

        if not isinstance(fields, dict):
            raise ValidationError("Application fields are invalid")
        with self._send_lock:
            if not self.recipient_ready(recipient_destination):
                self.request_path(recipient_destination)
                raise RecipientKeysUnavailable("Recipient ratchet is not available")
            recipient_identity = RNS.Identity.recall(recipient_destination)
            if recipient_identity is None or recipient_identity.get_public_key() != recipient_public_key:
                raise ValidationError("Recalled identity does not match the approved contact")
            target = RNS.Destination(
                recipient_identity,
                RNS.Destination.OUT,
                RNS.Destination.SINGLE,
                "lxmf",
                "delivery",
            )
            if target.hash != recipient_destination:
                raise ValidationError("Outbound destination binding changed")
            method = LXMF.LXMessage.PROPAGATED if propagated else LXMF.LXMessage.DIRECT
            if propagated and not self.settings.approved_propagation_nodes:
                raise NetworkUnavailable("No approved propagation node is configured")
            message = LXMF.LXMessage(
                target,
                self.delivery_destination,
                content=text,
                fields=fields,
                desired_method=method,
            )
            message.register_delivery_callback(
                lambda delivered: self._on_native_delivery(logical_id, delivered)
            )
            message.register_failed_callback(
                lambda failed: self._on_native_failure(logical_id, failed)
            )
            # Packing before durable handoff gives us the native correlation ID.
            # For propagated delivery, recipient ratchet presence was required
            # before this call, preventing LXMF's base-key fallback.
            message.pack()
            if propagated and message.ratchet_id is None:
                raise RecipientKeysUnavailable("Propagated message did not use a recipient ratchet")
            native_id = message.hash.hex()
            with self._message_lock:
                self._messages.setdefault(logical_id, []).append(message)
            self._status_callback(logical_id, DeliveryState.SENDING, native_id)
            try:
                self.router.handle_outbound(message)
            except Exception:
                self._forget_native_attempt(logical_id, message)
                raise
            return native_id

    def _forget_native_attempt(
        self, logical_id: str, message: LXMF.LXMessage
    ) -> None:
        with self._message_lock:
            attempts = self._messages.get(logical_id)
            if attempts is None:
                return
            # Match object identity, not only the packed hash. Two native
            # attempts can legitimately carry the same logical payload and
            # correlation ID; each plaintext-bearing object must be released.
            attempts[:] = [candidate for candidate in attempts if candidate is not message]
            if not attempts:
                self._messages.pop(logical_id, None)

    def cancel_outbound(self, logical_ids: set[str] | list[str]) -> int:
        """Cancel selected native LXMF handoffs without touching controls.

        Callers provide application logical IDs which they have already
        classified as chat payloads. LXMF cancellation uses the packed native
        ``message_id``; retaining that translation here keeps the service away
        from router internals and serializes cancellation with send().
        """

        cancelled = 0
        with self._send_lock:
            requested = set(logical_ids)
            # Detach references while holding only the bookkeeping lock, and
            # release it before touching LXMF. Delivery/failure callbacks can
            # therefore complete even if cancellation enters the router.
            with self._message_lock:
                attempts_by_id = {
                    logical_id: list(self._messages.pop(logical_id, []))
                    for logical_id in requested
                }
            for logical_id in requested:
                attempts = attempts_by_id[logical_id]
                # Include router-restored or legacy duplicate attempts which
                # predate the in-memory mapping. LXMF's public cancellation API
                # performs the actual synchronized state transition.
                for pending in list(getattr(self.router, "pending_outbound", [])):
                    try:
                        if parse_payload(pending).logical_id == logical_id:
                            attempts.append(pending)
                    except Exception:
                        continue
                seen_objects: set[int] = set()
                for message in attempts:
                    message_id = getattr(message, "message_id", None)
                    object_id = id(message)
                    if message_id is None or object_id in seen_objects:
                        continue
                    seen_objects.add(object_id)
                    try:
                        self.router.cancel_outbound(message_id)
                    except Exception:
                        # Deleting the durable application record remains safe
                        # even if an upstream packet is already unwinding.
                        pass
                    cancelled += 1
        return cancelled

    def _on_native_delivery(self, logical_id: str, message: LXMF.LXMessage) -> None:
        state = map_native_delivery_state(message.method, message.state)
        # LXMF invokes this callback once the native handoff has concluded.
        # Direct delivery maps to endpoint evidence and propagation delivery to
        # stored evidence, not the app-level DELIVERED state, but neither needs
        # Mesh Chat to retain the plaintext LXMessage object afterward.
        self._forget_native_attempt(logical_id, message)
        self._defer_callback(
            self._status_callback,
            logical_id,
            state,
            message.hash.hex() if message.hash else None,
            kind="status",
        )

    def _on_native_failure(self, logical_id: str, message: LXMF.LXMessage) -> None:
        # Native exhaustion is treated as a transient route failure until the
        # application delivery window expires; the durable outbox remains intact.
        self._forget_native_attempt(logical_id, message)
        self._defer_callback(
            self._status_callback,
            logical_id,
            DeliveryState.QUEUED,
            message.hash.hex() if message.hash else None,
            kind="status",
        )

    def _on_inbound(self, message: LXMF.LXMessage) -> None:
        # LXMRouter intentionally exposes invalid/unknown signatures to clients;
        # private chat must reject them here before any application mutation.
        # The sole bootstrap exception is a contact request whose invitation
        # and native LXMF signature independently bind the same unknown source.
        if message.destination_hash != self.delivery_destination.hash:
            return
        if not message.signature_validated:
            try:
                if is_workspace_payload(message):
                    wire = parse_workspace_payload(message)
                    if wire.kind != "workspace_join":
                        return
                    join = verify_workspace_join(wire.document)
                    if (
                        join.workspace_id != wire.workspace_id
                        or join.device.destination_hash != message.source_hash
                    ):
                        return
                    if not validate_unknown_source_signature(
                        message, join.device.public_identity
                    ):
                        return
                else:
                    app = parse_payload(message)
                    if app.kind != MessageKind.CONTACT_REQUEST or app.invitation is None:
                        return
                    invitation = verify_invitation(app.invitation)
                    if invitation.destination_hash != message.source_hash:
                        return
                    if not validate_unknown_source_signature(
                        message, invitation.public_identity
                    ):
                        return
                    self.remember_contact(
                        invitation.public_identity, invitation.destination_hash
                    )
                message.signature_validated = True
            except Exception:
                return
        self._defer_callback(self._inbound_callback, message, kind="inbound")

    def _defer_callback(
        self,
        callback: Callable[..., None],
        *args: Any,
        kind: str = "status",
    ) -> bool:
        """Queue an upstream callback without waiting for service execution.

        The queue is deliberately bounded because each inbound callback owns
        an LXMF message object. Inbound messages have admission and dispatch
        priority over transport status. Status transitions are kept in order
        until the hard capacity is reached, because replacing a delivery with
        a later failure would erase stronger evidence before the service can
        apply its monotonic-state rules. If an overload consists entirely of
        inbound messages, the newest arrival is rejected rather than evicting
        an older accepted message and breaking FIFO order.
        """

        callback_condition = getattr(self, "_callback_condition", None)
        callback_items = getattr(self, "_callback_items", None)
        if callback_condition is None or callback_items is None:
            # Some narrow unit probes construct the adapter with ``__new__``.
            # Production instances always initialise the dispatcher above.
            callback(*args)
            return True
        if kind not in {"inbound", "status"}:
            raise ValueError("Unknown network callback kind")

        item = (kind, callback, args)
        with callback_condition:
            if not self._callback_accepting:
                if kind == "inbound":
                    self._callback_dropped_inbound += 1
                else:
                    self._callback_dropped_status += 1
                return False

            if len(callback_items) >= self._callback_capacity:
                # An inbound payload may displace status bookkeeping, which is
                # recoverable from the durable outbox. Status may displace the
                # oldest other status so current handoffs remain observable.
                status_index = next(
                    (
                        index
                        for index, queued in enumerate(callback_items)
                        if queued[0] == "status"
                    ),
                    None,
                )
                if status_index is None:
                    if kind == "inbound":
                        self._callback_dropped_inbound += 1
                    else:
                        self._callback_dropped_status += 1
                    return False
                del callback_items[status_index]
                self._callback_dropped_status += 1

            callback_items.append(item)
            callback_condition.notify()
            return True

    def _dispatch_callbacks(self) -> None:
        while True:
            with self._callback_condition:
                while (
                    not self._callback_items
                    and self._callback_accepting
                    and not self._callback_cancelled
                ):
                    self._callback_condition.wait()
                if self._callback_cancelled:
                    return
                if not self._callback_items:
                    # The producer has closed and the accepted queue drained.
                    return
                # Preserve FIFO within each class while ensuring status churn
                # cannot delay an accepted inbound application payload.
                inbound_index = next(
                    (
                        index
                        for index, queued in enumerate(self._callback_items)
                        if queued[0] == "inbound"
                    ),
                    None,
                )
                if inbound_index is None:
                    _kind, callback, args = self._callback_items.popleft()
                else:
                    _kind, callback, args = self._callback_items[inbound_index]
                    del self._callback_items[inbound_index]
            try:
                callback(*args)
            except Exception:
                # Native callback failures are already non-fatal in LXMF.
                # Keep this boundary equally isolated and content-free.
                pass

    def _stop_callback_dispatcher(self) -> bool:
        """Drain accepted callbacks, then cancel safely if the drain stalls.

        ``False`` means a callback was already executing and did not return in
        the bounded interval. Callers must keep callback-owned state (notably
        the vault) open in that exceptional case.
        """

        callback_condition = getattr(self, "_callback_condition", None)
        callback_thread = getattr(self, "_callback_thread", None)
        if callback_condition is None or callback_thread is None:
            return True
        with callback_condition:
            self._callback_accepting = False
            callback_condition.notify_all()
        if callback_thread is threading.current_thread():
            return False
        callback_thread.join(timeout=CALLBACK_SHUTDOWN_TIMEOUT)
        if callback_thread.is_alive():
            with callback_condition:
                self._callback_cancelled = True
                for kind, _callback, _args in self._callback_items:
                    if kind == "inbound":
                        self._callback_dropped_inbound += 1
                    else:
                        self._callback_dropped_status += 1
                self._callback_items.clear()
                callback_condition.notify_all()
            callback_thread.join(timeout=CALLBACK_CANCEL_TIMEOUT)
        return not callback_thread.is_alive()

    def wait_for_callback_shutdown(self) -> None:
        """Wait for a previously cancelled active callback to unwind."""

        callback_thread = getattr(self, "_callback_thread", None)
        if callback_thread is not None and callback_thread is not threading.current_thread():
            callback_thread.join()

    def snapshot(self) -> dict[str, Any]:
        interfaces = []
        for interface in list(RNS.Transport.interfaces):
            item = {
                "name": str(interface.name),
                "online": bool(interface.online),
                "receives": bool(getattr(interface, "receives", False)),
                "type": type(interface).__name__,
            }
            if type(interface).__name__ == "AutoInterface":
                item.update(
                    {
                        "adopted_interface_count": len(
                            getattr(interface, "adopted_interfaces", {})
                        ),
                        "self_echo_seen": bool(getattr(interface, "initial_echoes", {})),
                        "carrier_timed_out": any(
                            getattr(interface, "timed_out_interfaces", {}).values()
                        ),
                        "peer_count": len(getattr(interface, "peers", {})),
                    }
                )
            elif str(interface.name) == LAN_FALLBACK_INTERFACE:
                item["client_count"] = int(getattr(interface, "clients", 0))
            interfaces.append(item)
        return {
            "transport_enabled": bool(RNS.Reticulum.transport_enabled()),
            "propagation_enabled": bool(self.router.propagation_node),
            "interface_available": self.interface_available,
            "interfaces": interfaces,
            "outbound_propagation_node": (
                self.router.outbound_propagation_node.hex()
                if self.router.outbound_propagation_node
                else None
            ),
        }

    def shutdown(self) -> bool:
        callbacks_stopped = True
        try:
            self.router.exit_handler()
        finally:
            try:
                RNS.Reticulum.exit_handler()
            finally:
                callbacks_stopped = self._stop_callback_dispatcher()
        return callbacks_stopped

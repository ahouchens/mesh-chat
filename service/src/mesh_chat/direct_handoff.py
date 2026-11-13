"""Fresh admitted credentials exchanged over the isolated bootstrap LXMF path."""
import threading
import time
import uuid

from . import direct_admission
from .direct_admitted_carrier import AdmittedCarrier
from .direct_binding import BindingAuthority, create_binding
from .direct_candidates import prepare_candidates
from .direct_path import native_parameters
from .errors import ValidationError
from .invitations import canonical_bytes
from .workspace_protocol import _destination_for, _identity_from_public_key
from .workspace_wire import build_workspace_fields


class AdmissionHandoff:
    def __init__(self, service, authority, promoted):
        self.service, self.authority, self.promoted = service, authority, promoted
        self._lock = threading.Lock()
        self._remote = None
        self.carrier = None

    def receive(self, document):
        try:
            direct_admission.decode(document)
            with self._lock:
                if self._remote is not None and self._remote != document:
                    raise ValidationError("Conflicting admission credentials")
                self._remote = document
        except Exception:
            if self.carrier is not None:
                self.carrier.close()

    def start(self, carrier):
        self.carrier = carrier
        self._thread = threading.Thread(target=self._run, name="mesh-direct-handoff", daemon=True)
        self._thread.start()

    def _prepare(self):
        service = self.service
        with service._dispatch_lock:
            expected = self.authority.admitted_authority()
            peer = _destination_for(_identity_from_public_key(expected.issuer_public_identity))
            scope = {**expected.scope, "issuer_device_id":expected.scope["audience_device_id"],
                     "audience_device_id":expected.scope["issuer_device_id"]}
            own = BindingAuthority(service._identity.get_public_key(), peer, scope,
                                   expected.expires_at, expected.challenge)
            key = service.store.opaque_id("direct-outgoing", canonical_bytes(scope).decode())
            previous = service.store.get("direct_outgoing", key)
            generation = (previous or {}).get("generation",0)+1
        prepared = prepare_candidates(service._direct_native, generation=generation,
            expires_at=min(int(time.time())+240,expected.expires_at), family=self.carrier.prepared.family, multiple=True)
        try:
            with service._dispatch_lock:
                self.authority.admitted_authority()
                if self.carrier._stop.is_set() or service.store.get("direct_outgoing",key) != previous:
                    raise ValidationError("Admission preparation was retired")
                fields = prepared.document_fields()
                binding = create_binding(service._identity, own, fields["certificate"],
                    session_id=fields["session_id"], generation=generation, challenge=own.challenge,
                    candidates=fields["candidates"], issued_at=int(time.time()),
                    expires_at=fields["expires_at"], version=2)
                document = direct_admission.encode(binding, fields["certificate"])
                service.store.put("direct_outgoing",key,{"generation":generation,"binding":binding,
                    "certificate":fields["certificate"].hex()})
                prepared.document_fields()
                return prepared, fields, document
        except BaseException:
            prepared.close()
            raise

    def _await_main_ready(self, admitted, *, deadline, announce_interval=1):
        """Confirm main RNS keys and selected admitted path within handoff time."""
        next_announce = time.monotonic() + announce_interval
        while not admitted._stop.is_set():
            if time.monotonic() >= deadline:
                return False
            if admitted.main_rns_ready():
                return time.monotonic() < deadline and not admitted._stop.is_set()
            now = time.monotonic()
            if now >= deadline:
                return False
            if now >= next_announce:
                self.service.network.router.announce(self.service.network.destination_hash)
                admitted.refresh_path()
                next_announce = now + announce_interval
            admitted._stop.wait(.05)
        return False

    def _run(self):
        prepared = None
        promoted = False
        activated = False
        expected = peer_binding = peer_certificate = None
        document = fields = None
        logical_id = str(uuid.uuid4())
        next_send = 0
        try:
            while not self.carrier._stop.is_set():
                self.authority.check()
                if self.authority.stage == "admission_handoff":
                    if prepared is None:
                        prepared, fields, document = self._prepare()
                    if self.carrier.ready and time.monotonic() >= next_send:
                        wire = build_workspace_fields(kind="workspace_direct_binding", logical_id=logical_id,
                            workspace_id=self.authority.workspace_id, expires_at=fields["expires_at"], document=document)
                        self.carrier.send(logical_id=logical_id, recipient_public_key=self.authority.peer_identity,
                            recipient_destination=self.carrier.peer, text="", fields=wire)
                        next_send = time.monotonic()+2
                    with self._lock:
                        remote = self._remote
                    if remote is not None and not activated:
                        peer_binding, peer_certificate = direct_admission.decode(remote)
                        with self.service._dispatch_lock:
                            expected = self.authority.admitted_authority()
                            accepted = self.service._accept_direct_workspace_binding(peer_binding, expected, peer_certificate)
                        prepared.document_fields()
                        self.service._direct_native.request("arm", id=prepared.handle, session=fields["session_id"],
                            generation=fields["generation"], digest=accepted.digest)
                        parameters = native_parameters(self.service._identity, fields["candidates"], peer_binding, peer_certificate, allow_multiple_families=True)
                        parameters["remaining_ms"] = min(parameters["remaining_ms"], 30_000,
                            int((fields["expires_at"]-time.time())*1000))
                        self.service._direct_native.request("activate", id=prepared.handle, **parameters)
                        activated = True
                    if activated:
                        polled = self.service._direct_native.request("poll", id=prepared.handle)
                        state = polled["state"]
                        if state == 2:
                            raise ValidationError("Admitted path failed")
                        if state == 1:
                            # Parent installs the separately leased main-context
                            # adapter before retiring this isolated control path.
                            admitted = AdmittedCarrier(self.service, prepared, peer_binding, expected,
                                peer_certificate, self.authority,
                                lambda state: self.promoted(admitted, state), initial_packets=polled["packets"])
                            try:
                                self.promoted(admitted, "admitted_path")
                                admitted.start()
                                promoted = True
                            except BaseException:
                                admitted.close()
                                raise
                            # Native authentication alone does not prove the
                            # other service has installed its admitted adapter.
                            # Observe its signed RNS announce before retiring
                            # the bootstrap control carrier. Repeat standard
                            # announces to tolerate unreliable DATAGRAM loss.
                            end = min(time.monotonic()+10, self.authority.transition_deadline)
                            # A signature-only native sighting does not install
                            # the main interpreter's recipient ratchet or route.
                            if not self._await_main_ready(admitted, deadline=end):
                                admitted.close()
                                raise ValidationError("Admitted path retired before confirmation")
                            from .direct_relationship import record_success
                            with self.service._dispatch_lock:
                                self.service._check_direct_runtime_available()
                                record_success(self.service.store, expected, accepted,
                                    load_authority=lambda: self.service._direct_workspace_binding_authority(expected),
                                    clock=lambda: int(time.time()))
                                self.service._direct_recovery.adopt(expected,admitted)
                            self.carrier.close()
                            return
                self.carrier._stop.wait(.1)
        except Exception:
            if promoted:
                admitted.close()
            self.carrier.close()
        finally:
            if prepared is not None and not promoted:
                prepared.close()

"""Authority for a narrow, expiring pending-to-admitted control handoff.

This is never an admitted packet lease. After admission it permits only the
admission root and fresh credential controls on the isolated bootstrap engine.
"""
import hashlib
import time

from .direct_binding import BindingAuthority, _parse
from .errors import IdentityMismatch, ValidationError
from .workspace_protocol import find_device, _destination_for


class BootstrapAuthority:
    def __init__(self, service, checked, *, owner, clock=time.monotonic):
        self.service, self.checked, self.owner, self.clock = service, checked, owner, clock
        self.workspace_id = checked.invitation.workspace_id
        self.invitation_id = service._workspace_invitation_record_id(checked.invitation.nonce)
        self.record_id = self.invitation_id if owner else service._workspace_record_id(self.workspace_id)
        self.collection = "direct_pending" if owner else "direct_join_exchange"
        self.saved = service.store.get(self.collection, self.record_id)
        if self.saved is None or not checked.ready:
            raise ValidationError("Bootstrap requires the saved Ready chain")
        if any(self.saved.get(field) != getattr(checked, field) for field in ("offer", "answer", "ready")):
            raise IdentityMismatch("Bootstrap chain changed")
        self.peer_identity = (checked.answer_authority.issuer_public_identity if owner
                              else checked.offer_authority.issuer_public_identity)
        self.challenge = hashlib.sha256(b"mesh-direct-admission-v2:" + checked.ready.encode()).digest()
        self.expires_at = min(_parse(checked.offer)["expires_at"], *(
            _parse(getattr(checked, field))["binding"]["expires_at"] for field in ("answer", "ready")))
        self.transition_deadline = None
        self.stage = "pending"
        self.check()

    def check(self):
        service = self.service
        with service._dispatch_lock:
            service._check_direct_runtime_available()
            if service.store.get(self.collection, self.record_id) != self.saved:
                raise ValidationError("Bootstrap chain changed")
            if time.time() >= self.expires_at:
                raise ValidationError("Bootstrap details expired")
            workspace = service._require_workspace(self.workspace_id)
            if workspace["state"] == "joining" and not self.owner:
                if self.transition_deadline is not None:
                    raise ValidationError("Admission cannot revert to pending")
                expected = BindingAuthority(self.peer_identity, _destination_for(service._identity),
                    self.checked.offer_authority.scope, self.checked.offer_authority.expires_at,
                    self.checked.offer_authority.challenge)
                service._direct_join_binding_authority(self.workspace_id, expected)
                return
            manifest = service._workspace_current_manifest(workspace)
            local = find_device(manifest, workspace["local_device_id"])
            authority = find_device(manifest, manifest.authority_device_id)
            if (workspace["state"] != "active" or manifest.status != "active" or local is None
                    or local[0].status != "active" or local[0].member_id != workspace["local_member_id"]
                    or service._identity is None or local[1].public_identity != service._identity.get_public_key()
                    or authority is None or authority[0].status != "active"
                    or authority[1].public_identity != self.checked.offer_authority.issuer_public_identity):
                raise IdentityMismatch("Bootstrap workspace authority changed")
            peer = next(((member, device) for member in manifest.members for device in member.devices
                         if device.public_identity == self.peer_identity), None)
            if peer is None and self.owner and self.transition_deadline is None:
                service._direct_owner_invitation(self.invitation_id)
                return
            if peer is None or peer[0].status != "active":
                raise IdentityMismatch("Bootstrap peer is not admitted")
            if self.owner:
                invite = service.store.get("workspace_invitation", self.invitation_id)
                if (invite is None or invite.get("state") != "consumed"
                        or invite.get("consumed_by_member_id") != peer[0].member_id):
                    raise ValidationError("Bootstrap invitation was not consumed by this peer")
            if self.transition_deadline is None:
                self.transition_deadline = self.clock()+30
            if self.clock() >= self.transition_deadline:
                raise ValidationError("Bootstrap admission handoff expired")
            self.stage = "admission_handoff"

    def admitted_authority(self):
        with self.service._dispatch_lock:
            return self._admitted_authority()

    def _admitted_authority(self):
        self.check()
        if self.stage != "admission_handoff":
            raise ValidationError("Bootstrap peer is not admitted")
        service = self.service
        workspace = service._require_workspace(self.workspace_id)
        manifest = service._workspace_current_manifest(workspace)
        peer = next(device for member in manifest.members for device in member.devices
                    if device.public_identity == self.peer_identity)
        expected = BindingAuthority(self.peer_identity, _destination_for(service._identity),
            {"kind":"workspace", "workspace_id":self.workspace_id,
             "issuer_device_id":peer.device_id, "audience_device_id":workspace["local_device_id"]},
            self.expires_at, self.challenge)
        return service._direct_workspace_binding_authority(expected)

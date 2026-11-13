"""Limited contact handshake scope; no chat, receipts, or workspace payloads."""
from .app_protocol import build_fields, conversation_id, parse_payload
from .errors import ValidationError
from .invitations import verify_invitation
from .isolated_bootstrap import IsolatedBootstrapEngine
from .models import MessageKind


class ContactBootstrapScope:
    KINDS = frozenset({"contact_request", "contact_accept", "contact_decline"})

    def accepts(self, message, local, peer):
        if message.source_hash != peer or message.destination_hash != local:
            return False
        try:
            payload = parse_payload(message)
            return (payload.kind.value in self.KINDS
                    and payload.conversation_id == conversation_id(local, peer))
        except ValidationError:
            return False

    def fields(self, kind, logical_id, document, expires_at, local, peer):
        if kind not in self.KINDS:
            raise ValidationError("Contact bootstrap payload is not permitted")
        if kind == "contact_request":
            if verify_invitation(document).destination_hash != local:
                raise ValidationError("Contact request identity does not match the local signer")
        elif document != "":
            raise ValidationError("Contact decision cannot carry another payload")
        return build_fields(kind=MessageKind(kind), logical_id=logical_id,
            conversation=conversation_id(local, peer), expires_at=expires_at,
            invitation=document if kind == "contact_request" else None)


class ContactBootstrapEngine(IsolatedBootstrapEngine):
    def __init__(self, private_identity, peer_identity, expires_at, *, directory=None):
        super().__init__(private_identity, peer_identity, expires_at,
                         ContactBootstrapScope(), directory=directory)

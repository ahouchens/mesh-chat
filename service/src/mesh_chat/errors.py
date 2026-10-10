class MeshChatError(Exception):
    """Base class for errors safe to map to a redacted UI code."""

    code = "internal_error"


class ValidationError(MeshChatError):
    code = "invalid_request"


class StaleCursor(ValidationError):
    """A sealed cursor belongs to an older authorization or retention view."""

    code = "stale_cursor"


class HistoryPruned(ValidationError):
    """The requested retained-history object is no longer available locally."""

    code = "history_pruned"


class StorageUnavailable(MeshChatError):
    code = "protected_storage_unavailable"


class ProfileInUse(MeshChatError):
    code = "profile_in_use"


class IdentityMismatch(MeshChatError):
    code = "identity_mismatch"


class InvitationInvalid(MeshChatError):
    code = "invitation_invalid"


class InvitationExpired(MeshChatError):
    code = "invitation_expired"


class ContactNotApproved(MeshChatError):
    code = "contact_not_approved"


class ContactInUse(MeshChatError):
    code = "contact_in_use"


class RecipientKeysUnavailable(MeshChatError):
    code = "recipient_keys_unavailable"


class NetworkUnavailable(MeshChatError):
    code = "network_unavailable"

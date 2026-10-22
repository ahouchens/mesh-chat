class MeshChatError(Exception):
    """Base class for errors safe to map to a redacted UI code."""

    code = "internal_error"


class ValidationError(MeshChatError):
    code = "invalid_request"


class WorkspaceAlreadyKnown(ValidationError):
    code = "workspace_already_known"

    def __init__(self, message: str, *, reason: str = "saved_request_invalid"):
        super().__init__(message)
        self.reason = reason


# Allowlisted over the service boundary: these describe why a saved workspace
# join request cannot be reused. Never include documents, identities or paths.
WORKSPACE_ALREADY_KNOWN_REASONS = frozenset({
    "invitation_mismatch",
    "request_stopped",
    "request_expired",
    "identity_mismatch",
    "saved_request_invalid",
    "workspace_active",
    "workspace_not_pending",
})


class WorkspaceLimitReached(ValidationError):
    code = "workspace_limit_reached"


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


class MailboxUnauthorized(MeshChatError):
    """The signaling capability token was missing, wrong, or rotated."""

    code = "mailbox_unauthorized"


class MailboxRateLimited(MeshChatError):
    """The signaling mailbox per-token or per-IP budget is exhausted."""

    code = "mailbox_rate_limited"


class ReconnectReplayed(MeshChatError):
    """A reconnect document was already accepted by this device."""

    code = "reconnect_replayed"


class NativeUnavailable(ValidationError):
    """The private native channel closed or stopped answering.

    Native ownership is reset before this is raised. Reopening the app is the
    supported recovery; the saved request and identity remain intact.
    """

    code = "native_unavailable"


class DirectConnectionUnavailable(NetworkUnavailable):
    code = "direct_connection_unavailable"

    def __init__(self, message: str = "direct_connection_unavailable", *, details=None):
        super().__init__(message)
        self.details = details

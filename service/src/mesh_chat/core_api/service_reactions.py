"""Private reaction adapter over the existing caller-scoped message index."""

from ..errors import ContactNotApproved, ValidationError
from .errors import ApiFailure
from .reactions import ReactionObservation
from .service_messages import storage_errors


class ServiceReactions:
    def __init__(self, service):
        self._service = service
        self._store = service.store

    def _message(self, scope, handle):
        index = self._store.get("api_message", handle)
        if index is None or (index.get("caller"), index.get("profile")) != (scope.caller, scope.profile):
            raise ApiFailure("forbidden")
        message = self._store.get("message", index.get("message_id"))
        if message is None:
            raise ApiFailure("not_found")
        return message

    def set(self, scope, handle, emoji, active):
        if not isinstance(emoji, str) or not emoji or type(active) is not bool:
            raise ApiFailure("invalid_request")
        with storage_errors():
            message = self._message(scope, handle)
            kind = "group" if message.get("group_id") else "direct"
            try:
                result = self._service.set_message_reaction(
                    kind, message["id"], emoji, active)
            except (ValidationError, ContactNotApproved) as error:
                raise ApiFailure("invalid_request") from error
            if (not isinstance(result, dict) or result.get("kind") not in {"direct", "group"}
                    or result.get("emoji") != emoji or result.get("active") is not active):
                raise ApiFailure("internal")
            return ReactionObservation(result["kind"], result["emoji"], result["active"])

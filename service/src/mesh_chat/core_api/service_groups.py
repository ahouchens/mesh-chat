"""Private adapter for first-class group summaries."""

from .errors import ApiFailure
from .groups import GroupMessageObservation, GroupObservation
from .service_messages import storage_errors


class ServiceGroups:
    def __init__(self, service):
        self._service = service

    def list(self, profile):
        if profile != "local":
            raise ApiFailure("forbidden")
        if self._service._identity is None:
            raise ApiFailure("locked")
        with storage_errors():
            snapshot = self._service.group_snapshot()
            return [self._observation(group) for group in snapshot.get("groups", [])]

    @staticmethod
    def _observation(group):
        group_id = group.get("id")
        name = group.get("title")
        policy = group.get("posting_policy")
        if (not isinstance(group_id, str) or not isinstance(name, str)
                or not isinstance(policy, str)):
            raise ApiFailure("internal")
        return GroupObservation(group_id, name, policy)

    def create(self, profile, title, member_ids, posting_policy):
        from ..errors import ValidationError

        if profile != "local":
            raise ApiFailure("forbidden")
        if self._service._identity is None:
            raise ApiFailure("locked")
        if not isinstance(title, str) or not title.strip():
            raise ApiFailure("invalid_request")
        with storage_errors():
            try:
                group = self._service.create_group(title, member_ids, posting_policy)
            except ValidationError as error:
                raise ApiFailure("invalid_request") from error
            return self._observation(group)
    def send(self, profile, group_id, text):
        from ..errors import ValidationError

        if profile != "local":
            raise ApiFailure("forbidden")
        if self._service._identity is None:
            raise ApiFailure("locked")
        if not isinstance(text, str) or not text.strip():
            raise ApiFailure("invalid_request")
        with storage_errors():
            try:
                self._service.send_group_message(group_id, text)
            except ValidationError as error:
                raise ApiFailure("invalid_request") from error
            return GroupMessageObservation(text)

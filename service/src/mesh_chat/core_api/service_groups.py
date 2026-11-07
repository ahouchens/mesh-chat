"""Private adapter for first-class group operations."""

from ..errors import ValidationError
from .errors import ApiFailure
from .groups import (GroupInvitationObservation, GroupMembershipObservation,
                     GroupMessageObservation, GroupObservation)
from .service_messages import storage_errors


class ServiceGroups:
    def __init__(self, service):
        self._service = service
        self._store = service.store

    def _require_local(self, profile):
        if profile != "local":
            raise ApiFailure("forbidden")
        if self._service._identity is None:
            raise ApiFailure("locked")

    def list(self, profile):
        self._require_local(profile)
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
        self._require_local(profile)
        if not isinstance(title, str) or not title.strip():
            raise ApiFailure("invalid_request")
        with storage_errors():
            try:
                group = self._service.create_group(title, member_ids, posting_policy)
            except ValidationError as error:
                raise ApiFailure("invalid_request") from error
            return self._observation(group)

    def send(self, profile, group_id, text):
        self._require_local(profile)
        if not isinstance(text, str) or not text.strip():
            raise ApiFailure("invalid_request")
        with storage_errors():
            try:
                self._service.send_group_message(group_id, text)
            except ValidationError as error:
                raise ApiFailure("invalid_request") from error
            return GroupMessageObservation(text)

    def leave(self, profile, group_id):
        self._require_local(profile)
        with storage_errors():
            try:
                self._service.leave_group(group_id)
            except ValidationError as error:
                raise ApiFailure("invalid_request") from error
            return GroupMembershipObservation("left")

    def close(self, profile, group_id):
        self._require_local(profile)
        with storage_errors():
            try:
                self._service.close_group(group_id)
            except ValidationError as error:
                raise ApiFailure("invalid_request") from error
            return GroupMembershipObservation("closed")

    def remove(self, profile, group_id, contact_id):
        self._require_local(profile)
        with storage_errors():
            contact = self._store.get("contact", contact_id)
            if contact is None or not isinstance(contact.get("destination_hash"), str):
                raise ApiFailure("forbidden")
            try:
                self._service.remove_group_member(group_id, contact["destination_hash"])
            except ValidationError as error:
                raise ApiFailure("invalid_request") from error
            return GroupMembershipObservation("removed")


    def retry_invitation(self, profile, group_id, contact_id):
        self._require_local(profile)
        with storage_errors():
            contact = self._store.get("contact", contact_id)
            if contact is None or not isinstance(contact.get("destination_hash"), str):
                raise ApiFailure("forbidden")
            try:
                self._service.retry_group_invitation(group_id, contact["destination_hash"])
            except ValidationError as error:
                raise ApiFailure("invalid_request") from error
            return GroupMembershipObservation("retrying")

    def invitations(self, profile):
        self._require_local(profile)
        with storage_errors():
            snapshot = self._service.group_snapshot()
            return [GroupInvitationObservation(item["id"], item["group_id"], item["title"])
                    for item in snapshot.get("invitations", [])
                    if isinstance(item, dict) and isinstance(item.get("id"), str)
                    and isinstance(item.get("group_id"), str)
                    and isinstance(item.get("title"), str)]

    def accept_invitation(self, profile, invitation_id):
        self._require_local(profile)
        with storage_errors():
            try:
                self._service.accept_group_invitation(invitation_id)
            except ValidationError as error:
                raise ApiFailure("invalid_request") from error
            return GroupMembershipObservation("accepted")

    def decline_invitation(self, profile, invitation_id):
        self._require_local(profile)
        with storage_errors():
            try:
                self._service.decline_group_invitation(invitation_id)
            except ValidationError as error:
                raise ApiFailure("invalid_request") from error
            return GroupMembershipObservation("declined")

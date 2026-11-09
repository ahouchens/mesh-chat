"""Private adapter for first-class group operations."""

from ..errors import ValidationError
from ..group_service import GroupMutationCapacityExceeded
from .errors import ApiFailure
from .groups import (GroupInvitationObservation, GroupMembershipObservation,
                     GroupMessageObservation, GroupObservation)
from .service_messages import storage_errors
from .optional_mutations import OptionalMutationJournal


class ServiceGroups:
    def __init__(self, service):
        self._service = service
        self._store = service.store
        self._optional = OptionalMutationJournal(self._store)
        transactional = all(callable(getattr(self._store, name, None)) for name in (
            "read_snapshot", "opaque_id", "operation_result", "conditional_put_and_delete", "record_count"))
        self.optional_keyed_operations = tuple(operation for operation, methods in (
            ("group.create", ("prepare_group_create", "validate_group_create", "wake_group_outbox")),
            ("group.message_enqueue", ("prepare_group_send", "validate_group_send", "wake_group_outbox")))
            if transactional and all(callable(getattr(service, method, None)) for method in methods))

    def _reconcile_optional(self, outcome):
        self._service.wake_group_outbox(outcome["delivery_ids"])
        self._service._changed()

    def create_keyed(self, scope, title, member_ids, posting_policy, operation_id):
        self._require_local(scope.profile)
        if "group.create" not in self.optional_keyed_operations:
            raise ApiFailure("unsupported_operation")
        def project(outcome, receipt):
            group = self._store.get("group", outcome["group_id"])
            if group is None:
                raise ApiFailure("idempotency_expired")
            if group.get("owner_destination") != self._service._require_profile()["destination_hash"]:
                raise ApiFailure("forbidden")
            return self._observation(group)
        def prepare():
            try:
                return self._service.prepare_group_create(title, list(member_ids), posting_policy, operation_id)
            except GroupMutationCapacityExceeded as error:
                raise ApiFailure("resource_exhausted") from error
        return self._optional.apply(scope, "group.create", operation_id,
            {"title": title, "members": list(member_ids), "posting_policy": posting_policy},
            validate=lambda: self._service.validate_group_create(title, list(member_ids), posting_policy),
            prepare=prepare,
            select_outcome=lambda plan: {**plan.result, "delivery_ids": list(plan.delivery_ids)}, project=project,
            reconcile=self._reconcile_optional)

    def send_keyed(self, scope, group_id, text, operation_id):
        self._require_local(scope.profile)
        if "group.message_enqueue" not in self.optional_keyed_operations:
            raise ApiFailure("unsupported_operation")
        def project(outcome, receipt):
            message = self._store.get("group_message", outcome["message_id"])
            if message is None or message.get("group_id") != group_id:
                raise ApiFailure("idempotency_expired")
            return GroupMessageObservation(message["text"], message["id"], receipt["accepted_at"], receipt["expires_at"])
        return self._optional.apply(scope, "group.message_enqueue", operation_id, {"group": group_id, "text": text},
            validate=lambda: self._service.validate_group_send(group_id, text),
            prepare=lambda: self._service.prepare_group_send(group_id, text, operation_id),
            select_outcome=lambda plan: {**plan.result, "delivery_ids": list(plan.delivery_ids)}, project=project,
            reconcile=self._reconcile_optional)

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


    def save_draft(self, profile, group_id, text):
        self._require_local(profile)
        with storage_errors():
            try:
                self._service.save_group_draft(group_id, text)
            except ValidationError as error:
                raise ApiFailure("invalid_request") from error
            return "saved"

"""Private adapter for typed call settings through the existing domain rules."""
import re
from .._qualification_failure_observer import note

from ..errors import MailboxRateLimited, MailboxUnauthorized, NetworkUnavailable, ValidationError
from ..call_manager import CallOutcomeRequiresResync, CallOperationCapacityExceeded
from .calls import CallIceObservation, CallMediaObservation, CallSettingsObservation
from .errors import ApiFailure
from .service_messages import storage_errors
from .call_operations import CallOperationJournal, CALL_RECOVERY_OPERATIONS


class ServiceCallSettings:
    def __init__(self, service, retirement=None):
        self._service = service
        owner = getattr(retirement, "owner_incarnation", None)
        if retirement is not None and (not callable(getattr(retirement, "request_retirement", None))
                or not isinstance(owner, str) or re.fullmatch(r"[A-Za-z0-9_-]{16,128}", owner) is None):
            raise ValueError("Call retirement requires a trusted bound media owner")
        self._operations = (CallOperationJournal(service, retirement)
                            if all(callable(getattr(service.store, name, None)) for name in
                                   ("conditional_put_and_delete", "items", "read_snapshot"))
                            and hasattr(service, "calls") and retirement is not None else None)
        self.recovery_operations = CALL_RECOVERY_OPERATIONS if self._operations is not None else ()

    def operation_rows(self, scope):
        self._require_local(scope.profile)
        return self._operations.rows(scope)

    def operation_query(self, scope, operation_id):
        self._require_local(scope.profile)
        return self._operations.observe(scope, operation_id)

    def operation_abandon(self, scope, target_id, operation_id):
        self._require_local(scope.profile)
        return self._operations.abandon(scope, target_id, operation_id)

    def control_scoped(self, scope, action, params, operation_id):
        self._require_local(scope.profile)
        if self._operations is None:
            # Once a vault has accepted protected media ownership, losing the
            # host port cannot reopen the legacy mutation route around its fence.
            with storage_errors():
                if callable(getattr(self._service.store, "record_count", None)) and self._service.store.record_count("api_call_operation"):
                    raise ApiFailure("resync_required")
            return self.control(scope.profile, action, params, operation_id)
        if action not in {"start", "answer", "restart", "answer_restart", "end", "candidate"}:
            return self.control(scope.profile, action, params, operation_id)
        with storage_errors():
            try:
                return self._operations.control(scope, action, params, operation_id)
            except CallOutcomeRequiresResync as error:
                raise ApiFailure("resync_required") from error
            except ValidationError as error:
                raise ApiFailure("invalid_request") from error

    def _require_local(self, profile):
        if profile != "local":
            raise ApiFailure("forbidden")
        if self._service._identity is None:
            raise ApiFailure("locked")

    def get(self, profile):
        self._require_local(profile)
        with storage_errors():
            return CallSettingsObservation(dict(self._service.call_settings()))

    def update(self, profile, settings):
        self._require_local(profile)
        if not isinstance(settings, dict):
            raise ApiFailure("invalid_request")
        with storage_errors():
            try:
                updated = self._service.update_call_settings(settings)
            except ValidationError as error:
                raise ApiFailure("invalid_request") from error
            if not isinstance(updated, dict):
                raise ApiFailure("internal")
            return CallSettingsObservation(dict(updated))


    def ice(self, profile):
        self._require_local(profile)
        with storage_errors():
            try:
                value = self._service.call_ice_servers()
            except ValidationError as error:
                note("caught", error, "ice_service")
                raise ApiFailure("invalid_request") from error
            except Exception as error:
                note("caught", error, "ice_service")
                raise
            if not isinstance(value, dict):
                error = ApiFailure("internal")
                note("caught", error, "ice_return", "invalid_observation")
                raise error
            try:
                return CallIceObservation(dict(value))
            except Exception as error:
                note("caught", error, "ice_return")
                raise


    def call_ids(self, profile):
        self._require_local(profile)
        with storage_errors():
            return tuple(item["id"] for item in self._service.store.list("call")
                         if isinstance(item.get("id"), str))

    def media(self, profile, call_id):
        self._require_local(profile)
        with storage_errors():
            try:
                value = self._service.call_media(call_id)
            except ValidationError as error:
                raise ApiFailure("invalid_request") from error
            if not isinstance(value, dict):
                raise ApiFailure("internal")
            return CallMediaObservation(dict(value))


    def control(self, profile, action, params, operation_id):
        self._require_local(profile)
        with storage_errors():
            try:
                if action in {"start", "answer", "restart", "answer_restart", "end", "candidate"}:
                    value = self._service.keyed_call_control(action, params, operation_id)
                elif action == "signal_publish":
                    role = {"caller": "offer", "callee": "answer"}.get(params["role"], params["role"])
                    value = self._service.keyed_signal_publish(params["document"], role, operation_id,
                                                               params.get("session_id"),
                                                               params.get("mailbox_token"))
                elif action == "signal_fetch":
                    role = {"caller": "offer", "callee": "answer"}.get(params["role"], params["role"])
                    value = self._service.signal_fetch(params["session"], role,
                                                      params.get("mailbox_token"))
                else:
                    raise ApiFailure("invalid_request")
            except CallOutcomeRequiresResync as error:
                raise ApiFailure("resync_required") from error
            except CallOperationCapacityExceeded as error:
                raise ApiFailure("resource_exhausted") from error
            except MailboxRateLimited as error:
                raise ApiFailure("rate_limited") from error
            except MailboxUnauthorized as error:
                raise ApiFailure("forbidden") from error
            except NetworkUnavailable as error:
                raise ApiFailure("unavailable") from error
            except ValidationError as error:
                raise ApiFailure("invalid_request") from error
            if not isinstance(value, dict):
                raise ApiFailure("internal")
            return dict(value)

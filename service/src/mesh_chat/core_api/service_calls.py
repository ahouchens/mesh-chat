"""Private adapter for typed call settings through the existing domain rules."""

from ..errors import MailboxRateLimited, MailboxUnauthorized, NetworkUnavailable, ValidationError
from ..call_manager import CallOutcomeRequiresResync, CallOperationCapacityExceeded
from .calls import CallIceObservation, CallMediaObservation, CallSettingsObservation
from .errors import ApiFailure
from .service_messages import storage_errors


class ServiceCallSettings:
    def __init__(self, service):
        self._service = service

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
                raise ApiFailure("invalid_request") from error
            if not isinstance(value, dict):
                raise ApiFailure("internal")
            return CallIceObservation(dict(value))


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

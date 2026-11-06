"""Private adapter for typed call settings through the existing domain rules."""

from ..errors import ValidationError
from .calls import CallIceObservation, CallSettingsObservation
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

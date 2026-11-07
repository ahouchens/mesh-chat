"""Private adapter for typed network settings through the existing rules."""

from uuid import uuid4

from .errors import ApiFailure
from .service_messages import storage_errors
from .settings import NetworkSettingsObservation


class ServiceNetworkSettings:
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
            return NetworkSettingsObservation(dict(self._service._public_network_settings()))

    def update(self, profile, settings):
        self._require_local(profile)
        if not isinstance(settings, dict):
            raise ApiFailure("invalid_request")
        with storage_errors():
            response, should_stop = self._service.dispatch({
                "v": 1, "id": uuid4().hex, "command": "update_settings",
                "payload": {"settings": settings},
            })
            if should_stop or response.get("ok") is not True:
                raise ApiFailure("invalid_request")
            updated = response.get("result")
            if not isinstance(updated, dict):
                raise ApiFailure("internal")
            return NetworkSettingsObservation(dict(updated))

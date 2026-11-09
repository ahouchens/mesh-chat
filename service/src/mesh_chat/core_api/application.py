"""Owner-scoped application read projection over the protected service."""

from uuid import uuid4

from .application_commands import APPLICATION_COMMANDS
from .session import ApiFailure


class ServiceApplication:
    def __init__(self, service):
        self._service = service

    def create_profile(self, display_name):
        try:
            return self._service.create_profile(display_name)
        except Exception as error:
            raise ApiFailure("invalid_request") from error

    def snapshot(self):
        try:
            return self._service.snapshot()
        except Exception as error:
            raise ApiFailure("internal") from error


    def command(self, command, payload):
        if command not in APPLICATION_COMMANDS:
            raise ApiFailure("forbidden")
        if not isinstance(payload, dict):
            raise ApiFailure("invalid_request")
        response, should_stop = self._service.dispatch({
            "v": 1,
            "id": uuid4().hex,
            "command": command,
            "payload": payload,
        })
        if should_stop:
            raise ApiFailure("forbidden")
        if response.get("ok") is not True:
            code = response.get("error", {}).get("code", "internal")
            raise ApiFailure(code if code in {
                "invalid_request", "forbidden", "unavailable", "conflict",
                "resource_exhausted", "internal",
            } else "internal")
        return response.get("result")

"""Owner-scoped application read projection over the protected service."""

from .errors import ApiFailure


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

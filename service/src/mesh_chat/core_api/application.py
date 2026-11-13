"""Owner-scoped application read projection over the protected service."""

from .errors import ApiFailure


class ServiceApplication:
    def __init__(self, service):
        self._service = service

    def snapshot(self):
        try:
            return self._service.snapshot()
        except Exception as error:
            raise ApiFailure("internal") from error

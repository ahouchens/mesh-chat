"""Private profile bootstrap port, separate from public owner administration."""

from .service_messages import storage_errors


class ServiceProfileBootstrap:
    def __init__(self, service):
        self._service = service

    def create(self, display_name, operation_id):
        with storage_errors():
            return self._service.create_profile(display_name, operation_id=operation_id)

"""Private adapter for current policy diagnostics, excluding global history."""

import time

from .diagnostics import DiagnosticObservation
from .service_messages import storage_errors


class ServiceDiagnostics:
    def __init__(self, service, messages):
        self._service = service
        self._messages = messages

    def query(self, profile):
        with storage_errors():
            self._messages._profile(profile)
            runtime = self._service._connection_runtime
            if runtime is None:
                return DiagnosticObservation(time.time(), False, None, {})
            return DiagnosticObservation(time.time(), True, runtime._failure, runtime.snapshots())

"""Private adapter: request shutdown through the service's own event.

The adapter does not call close() while the facade holds the dispatch lock. It
sets the same event close() sets first, so workers stop accepting work, and the
owning host completes resource cleanup after the reply is written.
"""

from .lifecycle import StopObservation


class ServiceLifecycle:
    def __init__(self, service):
        self._service = service

    def stop(self):
        already = self._service._shutdown.is_set()
        if not already:
            self._service._shutdown.set()
        return StopObservation(True, already)

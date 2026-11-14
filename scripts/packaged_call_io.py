"""Bound one owned child-stdin write without making close wait on its lock."""

import threading
import time


class WriteRetirementUnconfirmed(RuntimeError):
    pass


class BoundedWriter:
    def __init__(self, stream, terminate):
        self.stream, self.terminate = stream, terminate
        self.lock = threading.Lock()
        self.worker = None
        self.faulted = False
        self.retired = True

    def write(self, data: bytes, deadline: float):
        if self.faulted or type(data) is not bytes or not data or not self.lock.acquire(blocking=False):
            raise ValueError("owned_write_invalid")
        done = threading.Event()
        errors = []

        def worker():
            try:
                self.stream.write(data)
                self.stream.flush()
            except Exception as error:
                errors.append(error)
            finally:
                done.set()

        try:
            self.retired = False
            self.worker = threading.Thread(target=worker, daemon=True)
            self.worker.start()
            remaining = max(0, deadline - time.monotonic())
            if not done.wait(remaining):
                self.faulted = True
                # Terminate the exact owned child (or its job) before joining
                # the blocked WriteFile. close() never takes this writer lock.
                terminated = False
                try: terminated = self.terminate() is True
                except Exception: pass
                self.worker.join(timeout=5)
                self.retired = not self.worker.is_alive()
                if not self.retired:
                    raise WriteRetirementUnconfirmed("owned_write_retirement_unconfirmed")
                if not terminated:
                    raise WriteRetirementUnconfirmed("owned_child_retirement_unconfirmed")
                raise TimeoutError("owned_write_deadline")
            self.worker.join(timeout=1)
            self.retired = not self.worker.is_alive()
            if not self.retired:
                self.faulted = True
                raise WriteRetirementUnconfirmed("owned_write_retirement_unconfirmed")
            if errors:
                self.faulted = True
                raise ValueError("owned_write_failed") from None
        finally:
            self.lock.release()

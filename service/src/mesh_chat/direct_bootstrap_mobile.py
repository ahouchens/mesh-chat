"""Protected Python to non-exported Android bootstrap process bridge."""
import json

from .direct_bootstrap_worker import MAX_BYTES
from .errors import ValidationError


class AndroidBootstrapProcess:
    def __init__(self):
        from java import jclass
        self._client = jclass("com.meshchat.runtime.BootstrapClient").open()
        self._closed = False

    def request(self, operation, **payload):
        try:
            if self._closed:
                raise ValidationError("Bootstrap process is closed")
            raw = json.dumps({"operation":operation,"payload":payload}, separators=(",", ":"))
            if len(raw.encode("utf-8")) > MAX_BYTES:
                raise ValidationError("Bootstrap request is too large")
            raw = str(self._client.call(raw))
            if len(raw.encode("utf-8")) > MAX_BYTES:
                raise ValidationError("Bootstrap response is too large")
            response = json.loads(raw)
            if not isinstance(response, dict) or set(response) != {"ok", "result"} or response["ok"] is not True:
                raise ValidationError("Bootstrap process failed")
            return response["result"]
        except Exception as exc:
            self.close()
            raise ValidationError("Bootstrap process failed") from exc

    def close(self):
        if not self._closed:
            self._closed = True
            self._client.close()

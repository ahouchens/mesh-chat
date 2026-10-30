"""Private cursor encoding and validation, shared by reads and acknowledgments."""

import math
import re
import time

from ..errors import StorageUnavailable, ValidationError
from ..message_journal import RETENTION_SECONDS
from .errors import ApiFailure


class ServiceCursors:
    def __init__(self, store, journal, identifier):
        self._store = store
        self._journal = journal
        self._identifier = identifier

    def _scope_key(self, scope):
        return self._identifier("core-api-recovery:v1", scope.caller, scope.profile)

    def create(self, scope, authority, purpose, head, position=""):
        return self._store.seal_private_cursor(self._scope_key(scope), {
            "v": 1, "g": self._journal.generation, "a": authority, "p": purpose,
            "h": head, "k": position, "x": time.time() + RETENTION_SECONDS,
        })

    def decode(self, scope, authority, token, purpose):
        try:
            value = self._store.open_private_cursor(self._scope_key(scope), token)
        except ValidationError as error:
            raise ApiFailure("invalid_request") from error
        except StorageUnavailable as error:
            raise ApiFailure("forbidden") from error
        self.validate(value, authority, purpose)
        return value

    def validate(self, value, authority, purpose):
        if (set(value) != {"v", "g", "a", "p", "h", "k", "x"}
                or type(value["v"]) is not int or value["v"] != 1
                or value["g"] != self._journal.generation or value["a"] != authority):
            raise ApiFailure("resync_required")
        if value["p"] != purpose:
            raise ApiFailure("invalid_request")
        expiry = value["x"]
        if (type(expiry) not in {int, float} or not math.isfinite(expiry) or expiry < 0
                or type(value["h"]) is not int or not 0 <= value["h"] <= self._journal.head()
                or not isinstance(value["k"], str)
                or (value["k"] != "" and (purpose != "snapshot" or re.fullmatch(r"[a-f0-9]{64}", value["k"]) is None))):
            raise ApiFailure("resync_required")

    @staticmethod
    def require_live(value):
        if value["x"] <= time.time():
            raise ApiFailure("resync_required")

    def open(self, scope, authority, token, purpose):
        value = self.decode(scope, authority, token, purpose)
        self.require_live(value)
        return value

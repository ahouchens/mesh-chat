"""Stable failures at the application boundary, without private exception text."""

from ..errors import ValidationError


class ApiFailure(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def failure_code(error):
    # Existing domain transactions use this precise validation failure for
    # replay collisions. Translate it without exposing domain exception text.
    cause = error if isinstance(error, ValidationError) else error.__cause__
    if (isinstance(cause, ValidationError)
            and str(cause) == "Operation ID was already used with different input"):
        return "idempotency_conflict"
    return error.code if isinstance(error, ApiFailure) else "invalid_request"

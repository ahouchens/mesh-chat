"""Public protocol and transport failures; no runtime imports."""

class CoreClientError(Exception):
    """A typed failure from the facade or from the frame contract."""

    def __init__(self, code, request_id=None, retry_after_ms=None):
        super().__init__(code)
        self.code = code
        self.request_id = request_id
        self.retry_after_ms = retry_after_ms



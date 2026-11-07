"""Stable failures at the application boundary, without private exception text."""


class ApiFailure(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code

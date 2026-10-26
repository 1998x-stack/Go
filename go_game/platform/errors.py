"""Stable protocol error codes used by SDK, HTTP handlers and tests."""


class PlatformError(Exception):
    def __init__(self, code, message, status=400, **details):
        self.code = code
        self.message = message
        self.status = status
        self.details = details
        super().__init__(message)

    def to_dict(self):
        return {"error": {"code": self.code, "message": self.message,
                          "details": self.details}}

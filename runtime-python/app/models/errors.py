from enum import Enum

class ModelErrorType(str, Enum):
    AUTH = "auth"
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    UNAVAILABLE = "unavailable"
    BAD_REQUEST = "bad_request"
    UNKNOWN = "unknown"

class ModelError(RuntimeError):
    def __init__(self, error_type: ModelErrorType, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.retryable = retryable

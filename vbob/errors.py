from __future__ import annotations


class VBobError(Exception):
    """Base error mapped to the API error envelope."""

    status = 400
    code = "bad_request"

    def __init__(self, message: str, *, code: str | None = None, status: int | None = None):
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if status is not None:
            self.status = status


class NotFoundError(VBobError):
    status = 404
    code = "not_found"


class ConflictError(VBobError):
    status = 409
    code = "conflict"


class InvalidError(VBobError):
    status = 422
    code = "invalid_request"


class PlaybackError(ConflictError):
    code = "playback_unavailable"


class JobCanceled(Exception):
    """Raised inside a job worker when the user requests cancellation."""

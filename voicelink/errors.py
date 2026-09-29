"""Exception hierarchy for the VoiceLink SDK.

Every failure the SDK raises is a subclass of :class:`VoiceLinkError`, so callers can
catch that one type to handle anything, or catch a specific subclass to react to a
particular kind of failure.

    from voicelink.errors import VoiceLinkError, NotFoundError

    try:
        client.websocket_bots.update(999, status=Status.ACTIVE)
    except NotFoundError:
        ...          # that bot id does not exist
    except VoiceLinkError as exc:
        ...          # anything else the SDK could raise
"""

from __future__ import annotations

from typing import Any


class VoiceLinkError(Exception):
    """Base class for every error raised by the SDK."""


class VoiceLinkConnectionError(VoiceLinkError):
    """The request never produced an HTTP response.

    Raised for network failures, DNS problems, and timeouts — i.e. we could not reach
    VoiceLink at all, as opposed to VoiceLink replying with an error.
    """


class VoiceLinkAPIError(VoiceLinkError):
    """VoiceLink returned an error response.

    Attributes:
        message: Human-readable message (from the API's ``message`` field when present).
        status_code: HTTP status code, if there was an HTTP response.
        payload: The parsed response body, when available — useful for debugging.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        payload: Any | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.payload = payload

    def __str__(self) -> str:
        if self.status_code is not None:
            return f"[{self.status_code}] {self.message}"
        return self.message


class AuthenticationError(VoiceLinkAPIError):
    """The API token is missing, invalid, or expired (HTTP 401)."""


class PermissionDeniedError(VoiceLinkAPIError):
    """The account is authenticated but not allowed to perform this action (HTTP 403)."""


class NotFoundError(VoiceLinkAPIError):
    """The requested resource or route does not exist (HTTP 404)."""


class ValidationError(VoiceLinkAPIError):
    """The request was rejected as invalid (HTTP 422).

    Attributes:
        errors: Per-field validation messages, when the API supplies them.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        payload: Any | None = None,
        errors: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, status_code=status_code, payload=payload)
        self.errors = errors or {}


class RateLimitError(VoiceLinkAPIError):
    """Too many requests in a short window (HTTP 429)."""


class ServerError(VoiceLinkAPIError):
    """VoiceLink hit an internal error (HTTP 5xx)."""


def error_from_status(
    status_code: int,
    message: str,
    *,
    payload: Any | None = None,
) -> VoiceLinkAPIError:
    """Map an HTTP status code to the most specific error class."""
    mapping: dict[int, type[VoiceLinkAPIError]] = {
        401: AuthenticationError,
        403: PermissionDeniedError,
        404: NotFoundError,
        422: ValidationError,
        429: RateLimitError,
    }
    if status_code in mapping:
        cls = mapping[status_code]
    elif status_code >= 500:
        cls = ServerError
    else:
        cls = VoiceLinkAPIError

    if cls is ValidationError:
        errors = None
        if isinstance(payload, dict):
            # Laravel-style validators return {"errors": {...}} or {"data": {...}}.
            errors = payload.get("errors") or payload.get("data")
            if not isinstance(errors, dict):
                errors = None
        return ValidationError(message, status_code=status_code, payload=payload, errors=errors)

    return cls(message, status_code=status_code, payload=payload)

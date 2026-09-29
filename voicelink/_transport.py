"""The single HTTP engine shared by every resource.

Responsibilities that live here, and nowhere else:

* attach the bearer token to every request,
* speak JSON,
* unwrap VoiceLink's standard ``{"status", "message", "data"}`` envelope,
* turn HTTP/API failures into typed :mod:`voicelink.errors` exceptions,
* retry transient network / server errors with a short backoff.

Resources call :meth:`Transport.request` and get back the already-unwrapped ``data`` —
they never see headers, status codes, or the envelope.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from .errors import (
    VoiceLinkAPIError,
    VoiceLinkConnectionError,
    error_from_status,
)

# Status codes worth retrying: gateway/availability blips and rate limiting.
_RETRYABLE_STATUS = frozenset({429, 502, 503, 504})


class Transport:
    """Thin wrapper over :class:`httpx.Client` that returns unwrapped API data."""

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout: float = 30.0,
        max_retries: int = 2,
        client: httpx.Client | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._max_retries = max(0, max_retries)
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=self._base_url,
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )

    # -- lifecycle ---------------------------------------------------------------

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> Transport:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # -- the one method resources use --------------------------------------------

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        """Send a request and return the unwrapped ``data`` payload.

        Raises a :class:`~voicelink.errors.VoiceLinkAPIError` subclass on API failure, or
        :class:`~voicelink.errors.VoiceLinkConnectionError` if VoiceLink was unreachable.
        """
        clean_params = (
            None if params is None else {k: v for k, v in params.items() if v is not None}
        )
        response = self._send_with_retry(method, path, params=clean_params, json=json)
        return self._unwrap(response)

    # -- internals ---------------------------------------------------------------

    def _send_with_retry(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None,
        json: dict[str, Any] | None,
    ) -> httpx.Response:
        attempt = 0
        while True:
            try:
                response = self._client.request(method, path, params=params, json=json)
            except httpx.TimeoutException as exc:
                if attempt < self._max_retries:
                    self._backoff(attempt)
                    attempt += 1
                    continue
                raise VoiceLinkConnectionError(f"Request to {path} timed out") from exc
            except httpx.TransportError as exc:
                if attempt < self._max_retries:
                    self._backoff(attempt)
                    attempt += 1
                    continue
                raise VoiceLinkConnectionError(f"Could not reach VoiceLink: {exc}") from exc

            if response.status_code in _RETRYABLE_STATUS and attempt < self._max_retries:
                self._backoff(attempt)
                attempt += 1
                continue
            return response

    @staticmethod
    def _backoff(attempt: int) -> None:
        # 0.5s, 1s, 2s, ... — brief, capped, deterministic.
        time.sleep(min(0.5 * (2**attempt), 5.0))

    @staticmethod
    def _unwrap(response: httpx.Response) -> Any:
        """Validate the response and return its ``data`` field."""
        payload: Any = None
        if response.content:
            try:
                payload = response.json()
            except ValueError:
                payload = None

        if response.status_code >= 400:
            message = _extract_message(payload) or f"HTTP {response.status_code}"
            raise error_from_status(response.status_code, message, payload=payload)

        # 2xx, but the envelope can still report a logical failure.
        if isinstance(payload, dict) and payload.get("status") is False:
            message = _extract_message(payload) or "Request failed"
            raise VoiceLinkAPIError(message, status_code=response.status_code, payload=payload)

        if isinstance(payload, dict) and "data" in payload:
            return payload["data"]
        return payload


def _extract_message(payload: Any) -> str | None:
    if isinstance(payload, dict):
        msg = payload.get("message")
        if isinstance(msg, str) and msg:
            return msg
    return None

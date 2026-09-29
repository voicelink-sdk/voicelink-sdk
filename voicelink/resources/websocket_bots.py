"""WebSocket Bots — the endpoints that receive live call audio.

A WebSocket bot points VoiceLink at your ``wss://`` server. When a call is routed to the
bot, VoiceLink opens a WebSocket to that URL and streams the audio. This resource creates
and manages those bot registrations.

Note: the API has no delete endpoint for bots. To retire one, set it inactive with
:meth:`update` (``status=Status.INACTIVE``); removal is portal-only.
"""

from __future__ import annotations

from ..enums import AudioFormat, NoiseCancel, Status
from ..models import Page, WebSocketBot
from .base import Resource


class WebSocketBotsResource(Resource):
    def create(
        self,
        *,
        bot_name: str,
        websocket_url: str,
        client_id: int | None = None,
        webhook_url: str | None = None,
        audio_format: AudioFormat | str = AudioFormat.L16_16K,
        status: Status | int = Status.ACTIVE,
        noise_cancel: NoiseCancel | int = NoiseCancel.OFF,
    ) -> WebSocketBot:
        """Register a new WebSocket bot.

        ``audio_format`` defaults to ``L16_16K`` (16 kHz linear PCM) — the best choice for
        AI speech, since it needs no transcoding before speech-to-text.

        ``client_id`` is required for reseller accounts; it falls back to the client's
        default if one was set.
        """
        body = self._clean(
            {
                "bot_name": bot_name,
                "websocket_url": websocket_url,
                "webhook_url": webhook_url,
                "audio_format": _fmt(audio_format),
                "status": int(status),
                "noise_cancel": int(noise_cancel),
                "client_id": self._resolve_client_id(client_id),
            }
        )
        data = self._transport.request("POST", "/v1/websocket-bot/create", json=body)
        return WebSocketBot.from_dict(data or {})

    def list(
        self,
        *,
        page: int = 1,
        per_page: int = 10,
        status: Status | int | None = None,
        client_id: int | None = None,
    ) -> Page[WebSocketBot]:
        """List WebSocket bots visible to the account."""
        params = {
            "page": page,
            "per_page": per_page,
            "status": None if status is None else int(status),
            "client_id": self._resolve_client_id(client_id),
        }
        data = self._transport.request("GET", "/v1/websocket-bot/list", params=params)
        return Page.from_payload(data, WebSocketBot.from_dict)

    def update(
        self,
        bot_id: int,
        *,
        bot_name: str | None = None,
        websocket_url: str | None = None,
        webhook_url: str | None = None,
        audio_format: AudioFormat | str | None = None,
        status: Status | int | None = None,
        noise_cancel: NoiseCancel | int | None = None,
        client_id: int | None = None,
    ) -> WebSocketBot:
        """Update an existing bot.

        Despite the name this is not a partial update: the API rejects the request with
        422 unless ``bot_name`` and ``status`` are present, even when neither is changing.
        Resend the bot's own values for those two.

        Note also that ``status`` matters beyond this endpoint — call routing refuses a
        bot it considers inactive, while :meth:`list` has been observed reporting
        ``status=0`` for bots that stream audio normally.
        """
        body = self._clean(
            {
                "bot_name": bot_name,
                "websocket_url": websocket_url,
                "webhook_url": webhook_url,
                "audio_format": None if audio_format is None else _fmt(audio_format),
                "status": None if status is None else int(status),
                "noise_cancel": None if noise_cancel is None else int(noise_cancel),
                "client_id": self._resolve_client_id(client_id),
            }
        )
        data = self._transport.request("POST", f"/v1/websocket-bot/update/{bot_id}", json=body)
        return WebSocketBot.from_dict(data or {})


def _fmt(value: AudioFormat | str) -> str:
    return value.value if isinstance(value, AudioFormat) else str(value)

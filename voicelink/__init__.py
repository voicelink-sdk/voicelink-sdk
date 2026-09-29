"""VoiceLink SDK — Python client for VoiceLink telephony and voice-AI integrations.

Quick start::

    from voicelink import VoiceLinkClient
    from voicelink.enums import InboundRoute, OutboundRoute

    client = VoiceLinkClient(api_token="…", client_id=560)
    bot = client.websocket_bots.create(
        bot_name="Support",
        websocket_url="wss://my-agent.example.com/ws",
    )

Framework integrations live under ``voicelink.integrations`` and are installed as extras
(``pip install voicelink[pipecat]`` / ``voicelink[livekit]``). The core never imports
them, so they stay optional.
"""

from __future__ import annotations

from .client import DEFAULT_BASE_URL, UAT_BASE_URL, VoiceLinkClient
from .enums import (
    AudioFormat,
    CallDirection,
    CallEvent,
    InboundRoute,
    NoiseCancel,
    OutboundRoute,
    SipCodec,
    Status,
    TransportType,
)
from .errors import (
    AuthenticationError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    ServerError,
    ValidationError,
    VoiceLinkAPIError,
    VoiceLinkConnectionError,
    VoiceLinkError,
)
from .webhooks import WebhookEvent, parse_webhook

__version__ = "0.1.0"

__all__ = [
    "__version__",
    # client
    "VoiceLinkClient",
    "DEFAULT_BASE_URL",
    "UAT_BASE_URL",
    # enums
    "Status",
    "NoiseCancel",
    "AudioFormat",
    "SipCodec",
    "TransportType",
    "InboundRoute",
    "OutboundRoute",
    "CallDirection",
    "CallEvent",
    # webhooks
    "parse_webhook",
    "WebhookEvent",
    # errors
    "VoiceLinkError",
    "VoiceLinkConnectionError",
    "VoiceLinkAPIError",
    "AuthenticationError",
    "PermissionDeniedError",
    "NotFoundError",
    "ValidationError",
    "RateLimitError",
    "ServerError",
]

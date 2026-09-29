"""Typed names for VoiceLink's API integers and string codes.

The VoiceLink API speaks in bare numbers — ``status: 1``, ``for_inbound_call: 3`` — and
the same number is sometimes labelled inconsistently across endpoints. This module gives
each one a readable name so callers never memorize magic values.

All integer enums subclass :class:`int`, and all string enums subclass :class:`str`, so
you can pass an enum member anywhere the raw API value is expected and it will serialize
correctly.

    from voicelink.enums import Status, InboundRoute, AudioFormat

    Status.ACTIVE            # -> 1
    InboundRoute.WEBSOCKET_BOT   # -> 3
    AudioFormat.L16_16K      # -> "l16_16k"
"""

from __future__ import annotations

from enum import Enum, IntEnum


class Status(IntEnum):
    """Active/inactive flag used across bots, trunks, routing, etc."""

    INACTIVE = 0
    ACTIVE = 1


class NoiseCancel(IntEnum):
    """WebSocket-bot noise cancellation toggle."""

    OFF = 0
    ON = 1


class AudioFormat(str, Enum):
    """Audio encoding negotiated for a WebSocket bot's media stream.

    ``L16_16K`` (16 kHz linear PCM) is the recommended default for AI voice agents: it is
    uncompressed and already at the sample rate most speech-to-text engines expect, so no
    transcoding is needed on the real-time path.
    """

    ALAW = "alaw"          # G.711 A-law, 8 kHz (companded, lossy)
    ULAW = "ulaw"          # G.711 mu-law, 8 kHz (companded, lossy)
    L16 = "l16"            # linear PCM, 8 kHz
    L16_16K = "l16_16k"    # linear PCM, 16 kHz  (recommended)


class SipCodec(str, Enum):
    """Codecs selectable on a custom SIP trunk (stored comma-separated by the API)."""

    ALAW = "alaw"          # G.711 A-law / PCMA
    ULAW = "ulaw"          # G.711 mu-law / PCMU
    G722 = "g722"
    G729 = "g729"


class TransportType(IntEnum):
    """SIP transport protocol for a trunk.

    NOTE: The API accepts 1/2/3 but does not label them in the spec. This mapping is
    inferred from the common UDP/TCP/TLS ordering and should be confirmed with VoiceLink.
    """

    UDP = 1
    TCP = 2
    TLS = 3


class InboundRoute(IntEnum):
    """Where inbound calls to a DID are sent (``for_inbound_call``)."""

    MOBILE = 1
    SIP_TRUNK = 2
    WEBSOCKET_BOT = 3


class OutboundRoute(IntEnum):
    """How outbound calls from a DID are handled (``for_outbound_call``).

    Note there is no ``MOBILE`` option for outbound, and ``ONLY_ANSWER`` (4) has no
    inbound equivalent — the two enums deliberately do not share all members.
    """

    SIP_TRUNK = 2
    WEBSOCKET_BOT = 3
    ONLY_ANSWER = 4


class CallDirection(str, Enum):
    """Direction of a call, as reported in webhooks and call logs."""

    INBOUND = "inbound"
    OUTBOUND = "outbound"


class CallEvent(str, Enum):
    """Lifecycle events VoiceLink delivers to a configured webhook URL.

    ``RINGING`` and ``FAILED`` are emitted by the platform but are absent from the public
    documentation. ``COMPLETED`` fires even for failed calls (with a failed status).
    """

    INITIATED = "call.initiated"
    RINGING = "call.ringing"
    ANSWERED = "call.answered"
    ENDED = "call.ended"
    FAILED = "call.failed"
    COMPLETED = "call.completed"

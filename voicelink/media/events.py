"""VoiceLink WebSocket media protocol — event models and message builders.

When a call is routed to a WebSocket bot, VoiceLink opens a WebSocket to your server and
exchanges JSON messages. This module models that protocol in a framework-free way so the
Pipecat and Dograh adapters can both build on it.

Inbound (VoiceLink → your server):

    connected   handshake established
    start       call metadata + negotiated media format
    media       a chunk of caller audio (base64)
    mark        a synchronization checkpoint echoed back
    stop        stream ended

Outbound (your server → VoiceLink):

    media       a chunk of bot audio to play to the caller
    mark        a checkpoint to be echoed when playback reaches it
    clear       discard audio queued but not yet played (barge-in)
    transfer    hand the call off to another number

Parse inbound frames with :func:`parse_message`; build outbound frames with the
``build_*`` helpers.

Two behaviors are marked ``UNVERIFIED`` below: they could not be confirmed on a live call
(the UAT carrier was down during testing) and are isolated here so they are easy to
adjust once a real call is captured.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .audio import decode_payload


class MediaEventType(str, Enum):
    """The ``event`` discriminator on every protocol message."""

    CONNECTED = "connected"
    START = "start"
    MEDIA = "media"
    MARK = "mark"
    STOP = "stop"
    TRANSFER = "transfer"
    CLEAR = "clear"


# --------------------------------------------------------------------------- #
# Inbound event models
# --------------------------------------------------------------------------- #


@dataclass
class ConnectedEvent:
    type: MediaEventType = MediaEventType.CONNECTED
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class StartEvent:
    """Call metadata delivered once, right after ``connected``."""

    stream_sid: str | None = None
    call_sid: str | None = None
    account_sid: str | None = None
    from_number: str | None = None
    to_number: str | None = None
    custom_parameters: dict[str, Any] = field(default_factory=dict)
    encoding: str | None = None          # e.g. "audio/alaw", "audio/l16"
    sample_rate: int | None = None
    type: MediaEventType = MediaEventType.START
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class MediaEvent:
    """A chunk of caller audio."""

    payload: str = ""                    # base64-encoded audio
    track: str | None = None
    chunk: int | None = None
    timestamp: int | None = None
    type: MediaEventType = MediaEventType.MEDIA
    raw: dict[str, Any] = field(default_factory=dict)

    def decode(self) -> bytes:
        """Return the raw audio bytes for this chunk."""
        return decode_payload(self.payload) if self.payload else b""


@dataclass
class MarkEvent:
    name: str | None = None
    type: MediaEventType = MediaEventType.MARK
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class StopEvent:
    call_sid: str | None = None
    type: MediaEventType = MediaEventType.STOP
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class UnknownEvent:
    event: str | None = None
    type: MediaEventType | None = None
    raw: dict[str, Any] = field(default_factory=dict)


InboundEvent = (
    ConnectedEvent | StartEvent | MediaEvent | MarkEvent | StopEvent | UnknownEvent
)


def parse_message(raw: str | bytes | dict[str, Any]) -> InboundEvent:
    """Parse one inbound protocol frame into a typed event object.

    Accepts a JSON string/bytes or an already-decoded dict. Unknown event types are
    returned as :class:`UnknownEvent` rather than raising, so a new server-side event
    never crashes a running call.
    """
    if isinstance(raw, (str, bytes)):
        try:
            msg = json.loads(raw)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Media frame is not valid JSON: {exc}") from exc
    else:
        msg = raw

    if not isinstance(msg, dict):
        raise ValueError("Media frame must be a JSON object")

    event = msg.get("event")

    if event == MediaEventType.CONNECTED.value:
        return ConnectedEvent(raw=msg)

    if event == MediaEventType.START.value:
        start = msg.get("start") if isinstance(msg.get("start"), dict) else {}
        fmt = start.get("media_format")
        media_format = fmt if isinstance(fmt, dict) else {}
        return StartEvent(
            # `start` nests the ids; the top level sometimes carries stream_sid too.
            stream_sid=_first(
                msg.get("stream_sid"), start.get("stream_sid"), start.get("streamSid")
            ),
            call_sid=_first(start.get("call_sid"), start.get("callSid")),
            account_sid=_as_str(start.get("account_sid")),
            from_number=_as_str(start.get("from")),
            to_number=_as_str(start.get("to")),
            custom_parameters=start.get("custom_parameters") or {},
            encoding=media_format.get("encoding"),
            sample_rate=_as_int(media_format.get("sample_rate")),
            raw=msg,
        )

    if event == MediaEventType.MEDIA.value:
        media = msg.get("media") if isinstance(msg.get("media"), dict) else {}
        return MediaEvent(
            payload=media.get("payload") or "",
            track=media.get("track"),
            chunk=_as_int(media.get("chunk")),
            timestamp=_as_int(media.get("timestamp")),
            raw=msg,
        )

    if event == MediaEventType.MARK.value:
        mark = msg.get("mark") if isinstance(msg.get("mark"), dict) else {}
        return MarkEvent(name=mark.get("name"), raw=msg)

    if event == MediaEventType.STOP.value:
        stop = msg.get("stop") if isinstance(msg.get("stop"), dict) else {}
        # `stop` uses camelCase `callSid` (the `start` event uses snake_case call_sid).
        return StopEvent(call_sid=_first(stop.get("callSid"), stop.get("call_sid")), raw=msg)

    return UnknownEvent(event=event, raw=msg)


# --------------------------------------------------------------------------- #
# Outbound message builders (your server → VoiceLink)
# --------------------------------------------------------------------------- #


def build_media(payload: str, stream_sid: str | None = None) -> dict[str, Any]:
    """Build a media message carrying bot audio to play to the caller.

    ``payload`` is base64-encoded audio in the negotiated format.

    UNVERIFIED: whether outbound media frames require a top-level ``stream_sid``. The
    documented example omits it; ``clear`` includes one. This builder includes it when
    provided so callers can match whichever the live platform requires.
    """
    msg: dict[str, Any] = {"event": "media", "media": {"payload": payload}}
    if stream_sid is not None:
        msg["stream_sid"] = stream_sid
    return msg


def build_mark(name: str, stream_sid: str | None = None) -> dict[str, Any]:
    """Build a mark checkpoint that VoiceLink echoes back when playback reaches it."""
    msg: dict[str, Any] = {"event": "mark", "mark": {"name": name}}
    if stream_sid is not None:
        msg["stream_sid"] = stream_sid
    return msg


def build_clear(stream_sid: str | None = None) -> dict[str, Any]:
    """Build a clear message to discard queued-but-unplayed audio (barge-in)."""
    msg: dict[str, Any] = {"event": "clear"}
    if stream_sid is not None:
        msg["stream_sid"] = stream_sid
    return msg


def build_transfer(target: str) -> dict[str, Any]:
    """Build a transfer message handing the call to another number.

    ``target`` is kept as a string to preserve leading ``+``/``0`` digits. (The raw API
    example shows an unquoted integer, which would corrupt such numbers.)

    UNVERIFIED: the transfer direction and exact field encoding on a live call.
    """
    return {"event": "transfer", "target": target}


def to_json(message: dict[str, Any]) -> str:
    """Serialize an outbound message dict to a JSON string for sending."""
    return json.dumps(message)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _first(*values: Any) -> Any:
    for v in values:
        if v is not None:
            return _as_str(v)
    return None


def _as_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

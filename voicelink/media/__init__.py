"""Framework-free building blocks for VoiceLink's real-time media stream.

These models and helpers describe the WebSocket audio protocol without depending on any
voice-AI framework. The Pipecat and Dograh adapters build on top of them.
"""

from .audio import AudioSpec, decode_payload, encode_payload, resolve_spec, spec_for
from .events import (
    ConnectedEvent,
    InboundEvent,
    MarkEvent,
    MediaEvent,
    MediaEventType,
    StartEvent,
    StopEvent,
    UnknownEvent,
    build_clear,
    build_mark,
    build_media,
    build_transfer,
    parse_message,
    to_json,
)

__all__ = [
    # audio
    "AudioSpec",
    "spec_for",
    "resolve_spec",
    "encode_payload",
    "decode_payload",
    # event models
    "MediaEventType",
    "ConnectedEvent",
    "StartEvent",
    "MediaEvent",
    "MarkEvent",
    "StopEvent",
    "UnknownEvent",
    "InboundEvent",
    # parsing / building
    "parse_message",
    "build_media",
    "build_mark",
    "build_clear",
    "build_transfer",
    "to_json",
]

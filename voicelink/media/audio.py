"""Audio format facts for VoiceLink's WebSocket media stream.

This module is deliberately small and dependency-free. It describes each audio format
(sample rate, sample width, whether it's linear PCM) and offers a couple of framing
helpers. It does **not** transcode between codecs — G.711 (a-law/mu-law) conversion is
done in the framework adapter using that framework's optimized resampler, and the linear
``l16`` / ``l16_16k`` formats need no conversion at all (which is exactly why they are
preferred for AI speech).

    from voicelink.media.audio import spec_for
    from voicelink.enums import AudioFormat

    spec = spec_for(AudioFormat.L16_16K)
    spec.sample_rate          # 16000
    spec.bytes_per_ms(20)     # bytes in a 20 ms frame
"""

from __future__ import annotations

import base64
from dataclasses import dataclass

from ..enums import AudioFormat


@dataclass(frozen=True)
class AudioSpec:
    """The physical shape of one audio format on the wire."""

    format: AudioFormat
    sample_rate: int          # samples per second (Hz)
    sample_width: int         # bytes per sample
    is_linear: bool           # True for uncompressed PCM; False for companded G.711
    channels: int = 1

    def bytes_per_ms(self, ms: float) -> int:
        """Number of audio bytes in a frame of ``ms`` milliseconds."""
        return int(self.sample_rate * self.sample_width * self.channels * ms / 1000)

    def duration_ms(self, num_bytes: int) -> float:
        """Duration in milliseconds represented by ``num_bytes`` of audio."""
        per_second = self.sample_rate * self.sample_width * self.channels
        return (num_bytes / per_second) * 1000 if per_second else 0.0


_SPECS: dict[AudioFormat, AudioSpec] = {
    # G.711 companded: 8-bit samples at 8 kHz.
    AudioFormat.ALAW: AudioSpec(AudioFormat.ALAW, 8000, 1, is_linear=False),
    AudioFormat.ULAW: AudioSpec(AudioFormat.ULAW, 8000, 1, is_linear=False),
    # Linear PCM: 16-bit samples.
    AudioFormat.L16: AudioSpec(AudioFormat.L16, 8000, 2, is_linear=True),
    AudioFormat.L16_16K: AudioSpec(AudioFormat.L16_16K, 16000, 2, is_linear=True),
}


def spec_for(fmt: AudioFormat | str) -> AudioSpec:
    """Return the :class:`AudioSpec` for an audio format.

    Accepts an :class:`~voicelink.enums.AudioFormat` or its string value.
    """
    if isinstance(fmt, str) and not isinstance(fmt, AudioFormat):
        fmt = AudioFormat(fmt)
    try:
        return _SPECS[fmt]
    except KeyError:  # pragma: no cover - guarded by the enum
        raise ValueError(f"Unknown audio format: {fmt!r}") from None


# The ``start`` frame names encodings differently from the bot configuration: the wire
# carries a MIME-ish "audio/alaw" where the config says "alaw". Observed on a real call::
#
#     "media_format": {"encoding": "audio/alaw", "sample_rate": "8000"}
#
# Sample rate is part of the key because linear PCM is the same encoding at two rates -
# "audio/l16" alone cannot tell l16 (8 kHz) from l16_16k (16 kHz).
_WIRE_FORMATS: dict[tuple[str, int], AudioFormat] = {
    ("alaw", 8000): AudioFormat.ALAW,
    ("pcma", 8000): AudioFormat.ALAW,
    ("ulaw", 8000): AudioFormat.ULAW,
    ("mulaw", 8000): AudioFormat.ULAW,
    ("pcmu", 8000): AudioFormat.ULAW,
    ("l16", 8000): AudioFormat.L16,
    ("l16", 16000): AudioFormat.L16_16K,
    ("pcm", 8000): AudioFormat.L16,
    ("pcm", 16000): AudioFormat.L16_16K,
}


def resolve_spec(encoding: str, sample_rate: int | str) -> AudioSpec:
    """Return the :class:`AudioSpec` for a ``start`` frame's ``media_format``.

    The bot's *configured* audio format cannot be trusted: VoiceLink has been observed
    streaming ``audio/alaw`` at 8 kHz for a bot configured as ``l16_16k``. The ``start``
    frame is the only reliable description of a stream, so resolve from it at runtime
    rather than from configuration.

    Args:
        encoding: wire encoding from ``media_format``, e.g. ``"audio/alaw"``. The
            ``audio/`` prefix and letter case are both optional.
        sample_rate: samples per second; VoiceLink sends this as a string.

    Returns:
        The spec describing what will actually arrive on this stream.

    Raises:
        ValueError: if the encoding or rate is not one VoiceLink is known to send. This
            is deliberately fatal - guessing would feed corrupted audio to a speech
            recogniser, which fails silently and convincingly.
    """
    name = encoding.strip().lower().removeprefix("audio/")
    try:
        rate = int(sample_rate)
    except (TypeError, ValueError):
        raise ValueError(f"Unusable sample_rate in media_format: {sample_rate!r}") from None
    try:
        return _SPECS[_WIRE_FORMATS[(name, rate)]]
    except KeyError:
        raise ValueError(
            f"Unsupported media_format: encoding={encoding!r} sample_rate={sample_rate!r}"
        ) from None


def encode_payload(pcm: bytes) -> str:
    """Base64-encode raw audio bytes for a media message payload."""
    return base64.b64encode(pcm).decode("ascii")


def decode_payload(payload: str) -> bytes:
    """Decode a base64 media payload back to raw audio bytes."""
    return base64.b64decode(payload)

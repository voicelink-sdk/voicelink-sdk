"""Translate between VoiceLink's WebSocket media protocol and Pipecat frames.

Unlike LiveKit — which terminates SIP itself and never routes audio through this SDK —
Pipecat has no telephony of its own. It expects a transport to hand it raw PCM. VoiceLink
speaks JSON with base64 G.711 inside. This serializer is the translator between the two,
and it is the whole of the Pipecat media integration.

Everything here is written against frames captured from real VoiceLink calls rather than
from documentation, which is wrong in several places. Notably:

* No ``connected`` event is ever sent — ``start`` arrives first.
* The bot's configured audio format is ignored by the platform. A bot configured for
  ``l16_16k`` streamed ``audio/alaw`` at 8 kHz. The ``start`` frame is the only truth, so
  the stream's format is resolved at runtime from it.
* Key casing is inconsistent: ``start`` carries ``stream_sid`` while ``media`` and
  ``stop`` carry ``streamSid``.

Usage — note that nothing needs to be passed in::

    from voicelink.integrations.pipecat import VoiceLinkFrameSerializer

    serializer = VoiceLinkFrameSerializer()

Twilio's and Exotel's serializers require ``stream_sid`` up front because their apps learn
it from a webhook before the socket opens. VoiceLink puts it in the ``start`` frame, so we
read it there and the caller passes nothing.
"""

from __future__ import annotations

from binascii import Error as BinasciiError
from typing import Any

from loguru import logger
from pipecat.audio.utils import (
    alaw_to_pcm,
    create_stream_resampler,
    pcm_to_alaw,
    pcm_to_ulaw,
    ulaw_to_pcm,
)
from pipecat.frames.frames import (
    AudioRawFrame,
    EndFrame,
    Frame,
    InputAudioRawFrame,
    InterruptionFrame,
    OutputTransportMessageFrame,
    OutputTransportMessageUrgentFrame,
    StartFrame,
)
from pipecat.serializers.base_serializer import FrameSerializer

from ...enums import AudioFormat
from ...media.audio import AudioSpec, decode_payload, encode_payload, resolve_spec
from ...media.events import (
    MediaEvent,
    StartEvent,
    StopEvent,
    build_clear,
    build_media,
    parse_message,
    to_json,
)


class VoiceLinkFrameSerializer(FrameSerializer):
    """Convert VoiceLink media-stream messages to and from Pipecat frames.

    The stream's audio format is not known until the ``start`` frame arrives, so no
    conversion is attempted before then. This also means an idle connection — VoiceLink
    probes reachability by opening a socket and closing it without sending anything —
    costs nothing: no resampling, no frames, no pipeline activity.
    """

    class InputParams(FrameSerializer.InputParams):
        """Configuration for :class:`VoiceLinkFrameSerializer`.

        Parameters:
            sample_rate: Override for the pipeline's input sample rate. Defaults to
                whatever the pipeline negotiates in its ``StartFrame``.
            fallback_encoding: Encoding assumed if a ``start`` frame omits
                ``media_format`` entirely. Every observed call included it; this exists so
                a malformed frame degrades instead of dropping the call.
            fallback_sample_rate: Sample rate paired with ``fallback_encoding``.
            send_stream_sid_alias: Also include a camelCase ``streamSid`` on outbound
                messages. VoiceLink is inconsistent about casing and its own docs omit the
                field on outbound media, so both spellings are sent until a live call
                proves which one it reads. Costs ~20 bytes per frame.
        """

        sample_rate: int | None = None
        fallback_encoding: str = "audio/alaw"
        fallback_sample_rate: int = 8000
        send_stream_sid_alias: bool = True

    def __init__(self, params: InputParams | None = None, **kwargs: Any) -> None:
        """Initialize the serializer.

        Args:
            params: Optional configuration. The defaults suit every VoiceLink deployment
                observed so far.
            **kwargs: Passed through to Pipecat's
                :class:`~pipecat.serializers.base_serializer.FrameSerializer`.
        """
        params = params or VoiceLinkFrameSerializer.InputParams()
        super().__init__(params, **kwargs)
        self._params: VoiceLinkFrameSerializer.InputParams = params

        # Learned from the start frame, not from configuration.
        self._stream_sid: str | None = None
        self._call_sid: str | None = None
        self._spec: AudioSpec | None = None

        self._sample_rate: int = 0  # pipeline rate, set in setup()

        # Resamplers are stateful, so each direction needs its own.
        self._input_resampler = create_stream_resampler(
            clear_after_secs=self._params.resampler_clear_after_secs
        )
        self._output_resampler = create_stream_resampler(
            clear_after_secs=self._params.resampler_clear_after_secs
        )

    # ----------------------------------------------------------------- properties

    @property
    def stream_sid(self) -> str | None:
        """Stream id from the ``start`` frame, or ``None`` before the call begins."""
        return self._stream_sid

    @property
    def call_sid(self) -> str | None:
        """Call id from the ``start`` frame, or ``None`` before the call begins."""
        return self._call_sid

    @property
    def audio_spec(self) -> AudioSpec | None:
        """Format actually being streamed, or ``None`` before the ``start`` frame."""
        return self._spec

    # --------------------------------------------------------------------- setup

    async def setup(self, frame: StartFrame) -> None:
        """Adopt the pipeline's negotiated input sample rate.

        Args:
            frame: The pipeline's ``StartFrame``.
        """
        self._sample_rate = self._params.sample_rate or frame.audio_in_sample_rate

    # --------------------------------------------------------------- deserialize

    async def deserialize(self, data: str | bytes) -> Frame | None:
        """Convert one VoiceLink message into a Pipecat frame.

        Args:
            data: Raw WebSocket message from VoiceLink.

        A malformed message is logged and skipped rather than raised. Pipecat's transport
        calls this inside a ``try`` that catches only ``ConnectionClosed``, so any other
        exception escapes the read loop and ends the call - one stray frame would hang up
        on a real customer. Skipping costs 20 ms of audio instead.

        The single deliberate exception is an unrecognised audio format on the ``start``
        frame: that is a stream we cannot decode at all, and continuing would feed noise
        to the transcriber for the whole call. See :meth:`_on_start`.

        Args:
            data: Raw WebSocket message from VoiceLink.

        Returns:
            The corresponding frame, or ``None`` for messages that carry no audio
            (``start``, ``mark``, malformed input, and anything unrecognised).
        """
        try:
            event = parse_message(data)
        except ValueError as exc:
            logger.warning(f"Skipping unparseable VoiceLink message: {exc}")
            return None

        if isinstance(event, StartEvent):
            self._on_start(event)
            return None

        if isinstance(event, MediaEvent):
            try:
                return await self._on_media(event)
            except (ValueError, BinasciiError) as exc:
                # A corrupt payload loses one 20 ms frame; raising would lose the call.
                logger.warning(f"Skipping undecodable VoiceLink media frame: {exc}")
                return None

        if isinstance(event, StopEvent):
            logger.debug(f"VoiceLink stopped stream {self._stream_sid}")
            return EndFrame()

        return None

    def _on_start(self, event: StartEvent) -> None:
        """Record stream identity and resolve the format actually being sent.

        Safe to call more than once. A second ``start`` replaces the stream's identity and
        format, and resets both resamplers - they carry a few samples of history, and
        reusing that across a format change produces audible artefacts.
        """
        if self._spec is not None:
            logger.info(
                f"VoiceLink sent a second start frame; re-reading the format "
                f"(was {self._spec.format.value} @ {self._spec.sample_rate} Hz)"
            )
            self._input_resampler = create_stream_resampler(
                clear_after_secs=self._params.resampler_clear_after_secs
            )
            self._output_resampler = create_stream_resampler(
                clear_after_secs=self._params.resampler_clear_after_secs
            )

        self._stream_sid = event.stream_sid
        self._call_sid = event.call_sid

        encoding = event.encoding or self._params.fallback_encoding
        sample_rate = event.sample_rate or self._params.fallback_sample_rate
        if not event.encoding:
            logger.warning(
                f"VoiceLink start frame had no media_format; assuming "
                f"{encoding} @ {sample_rate} Hz"
            )
        elif event.sample_rate is None:
            # events.py yields None when sample_rate is not a number. Falling back would
            # silently play a 16 kHz stream at half speed, so say what happened.
            logger.warning(
                f"VoiceLink start frame had an unreadable sample_rate; assuming "
                f"{sample_rate} Hz for {encoding}"
            )

        # Deliberately not caught: an unknown format must fail loudly. Guessing would feed
        # corrupted audio to the transcriber, which produces confident nonsense instead of
        # an error.
        self._spec = resolve_spec(encoding, sample_rate)
        logger.info(
            f"VoiceLink call {self._call_sid} streaming {self._spec.format.value} "
            f"@ {self._spec.sample_rate} Hz -> pipeline @ {self._sample_rate} Hz"
        )

    async def _on_media(self, event: MediaEvent) -> Frame | None:
        """Turn one inbound media message into PCM Pipecat can consume."""
        if self._spec is None:
            logger.warning("Dropping VoiceLink media received before a start frame")
            return None
        # VoiceLink labels caller audio "inbound"; ignore any echo of our own output.
        if event.track is not None and event.track != "inbound":
            return None

        pcm = await self._to_pcm(decode_payload(event.payload))
        if not pcm:
            return None
        return InputAudioRawFrame(audio=pcm, num_channels=1, sample_rate=self._sample_rate)

    # ----------------------------------------------------------------- serialize

    async def serialize(self, frame: Frame) -> str | bytes | None:
        """Convert a Pipecat frame into a VoiceLink message.

        Args:
            frame: The frame produced by the pipeline.

        Returns:
            A JSON string to send over the WebSocket, or ``None`` if this frame has no
            VoiceLink equivalent.
        """
        if isinstance(frame, InterruptionFrame):
            # Barge-in: drop audio already queued for playback.
            return to_json(self._stamped(build_clear(self._stream_sid)))

        if isinstance(frame, AudioRawFrame):
            if self._spec is None:
                # Bot audio before the call started — nowhere to send it.
                return None
            wire = await self._from_pcm(frame.audio, frame.sample_rate)
            if not wire:
                return None
            message = build_media(encode_payload(wire), self._stream_sid)
            return to_json(self._stamped(message))

        if isinstance(frame, (OutputTransportMessageFrame, OutputTransportMessageUrgentFrame)):
            if self.should_ignore_frame(frame):
                return None
            return to_json(frame.message)

        return None

    def _stamped(self, message: dict[str, Any]) -> dict[str, Any]:
        """Add the camelCase ``streamSid`` alias when configured to do so."""
        if self._params.send_stream_sid_alias and self._stream_sid is not None:
            message["streamSid"] = self._stream_sid
        return message

    # ------------------------------------------------------------- audio codecs

    async def _to_pcm(self, audio: bytes) -> bytes:
        """Decode wire audio to linear PCM at the pipeline's sample rate."""
        spec = self._spec
        assert spec is not None  # guarded by callers
        wire, out, rs = spec.sample_rate, self._sample_rate, self._input_resampler
        if spec.format is AudioFormat.ALAW:
            return await alaw_to_pcm(audio, wire, out, rs)
        if spec.format is AudioFormat.ULAW:
            return await ulaw_to_pcm(audio, wire, out, rs)
        # Already linear PCM — only the rate may differ.
        return await self._input_resampler.resample(audio, spec.sample_rate, self._sample_rate)

    async def _from_pcm(self, pcm: bytes, in_rate: int) -> bytes:
        """Encode pipeline PCM back into the format VoiceLink is streaming."""
        spec = self._spec
        assert spec is not None  # guarded by callers
        if spec.format is AudioFormat.ALAW:
            return await pcm_to_alaw(pcm, in_rate, spec.sample_rate, self._output_resampler)
        if spec.format is AudioFormat.ULAW:
            return await pcm_to_ulaw(pcm, in_rate, spec.sample_rate, self._output_resampler)
        return await self._output_resampler.resample(pcm, in_rate, spec.sample_rate)

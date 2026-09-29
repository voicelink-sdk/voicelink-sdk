"""Connect a Pipecat voice agent to VoiceLink, inbound and outbound.

Pipecat has no telephony of its own: it expects a transport to hand it raw PCM over a
WebSocket. VoiceLink speaks its own JSON dialect with base64 G.711 inside. So a Pipecat
deployment needs two things from this SDK, and nothing else:

    PipecatProvisioner(...).setup_inbound(...)   # once, before any call
    serializer = VoiceLinkFrameSerializer()      # in your bot, during every call

This is the mirror image of the LiveKit integration, which terminates SIP itself and
therefore needs configuration only.

Environment:

    # VoiceLink account
    VOICELINK_USER          portal username           (or VOICELINK_TOKEN)
    VOICELINK_PASS          portal password
    VOICELINK_CLIENT_ID     sub-account id, e.g. 123
    VOICELINK_BASE_URL      defaults to the UAT host
    VOICELINK_DID           the number callers dial, e.g. 919484950416

    # Your Pipecat bot
    VOICELINK_BOT_NAME      any name you choose, e.g. pipecat-agent
    VOICELINK_WS_URL        public wss:// address of your bot server
    VOICELINK_WEBHOOK_URL   optional https:// endpoint for call-lifecycle events

    # Outbound smoke test only
    CALL_TO                 national number to dial, WITHOUT country code, e.g. 9876543210
    CALL_COUNTRY_CODE       country code on its own, defaults to 91

    # Speech and language services - only for the `repeat` and `bot` modes.
    # No provider is hardcoded: the name selects any Pipecat provider, and each needs
    # its own <PROVIDER>_API_KEY. See _ai_service().
    STT_PROVIDER            e.g. sarvam, deepgram, azure    (`repeat` and `bot`)
    TTS_PROVIDER            e.g. sarvam, elevenlabs, rime   (`repeat` and `bot`)
    LLM_PROVIDER            e.g. openai, google, anthropic  (`bot` only)
    <PROVIDER>_API_KEY      the key for each provider named above
    STT_MODEL / TTS_MODEL / LLM_MODEL      optional; the provider's default otherwise
    TTS_VOICE               optional
    STT_LANGUAGE / TTS_LANGUAGE            optional, e.g. en-IN

Run:
    python examples/pipecat_quickstart.py show           # what does the DID point at? (read-only)
    python examples/pipecat_quickstart.py inbound        # PSTN -> VoiceLink -> your bot
    python examples/pipecat_quickstart.py outbound       # your bot -> VoiceLink -> PSTN
    python examples/pipecat_quickstart.py echo           # plays the caller's audio back
    python examples/pipecat_quickstart.py repeat         # STT + TTS, no LLM
    python examples/pipecat_quickstart.py bot            # a real speaking agent
    python examples/pipecat_quickstart.py restore 213    # give the DID back to a SIP trunk

``inbound`` prints the exact ``restore`` command when it takes a DID away from a SIP
trunk, so sharing a number with a LiveKit deployment needs nothing written down.

``echo`` needs no LLM, no speech-to-text and no API keys. It is the fastest way to prove
audio flows both directions before spending anything on AI services. ``repeat`` adds
speech recognition and synthesis; ``bot`` adds an LLM on top of those.

Install the SDK, then whichever providers you named in ``.env``::

    pip install -e ".[pipecat]"
    pip install "pipecat-ai[sarvam]"          # or deepgram, elevenlabs, openai, ...

``repeat`` and ``bot`` serve many calls at once: every connection gets its own transport,
its own serializer and its own pipeline. Pipecat's ``WebsocketServerTransport`` cannot do
this - it accepts one client and closes every other with code 1013, which on a phone call
is heard as an answered but completely silent line - so these modes run a FastAPI
WebSocket endpoint instead. It is mounted at ``/``, so ``VOICELINK_WS_URL`` needs no path.

WARNING: ``outbound`` dials a real number and consumes account balance. ``inbound`` and
``echo`` only change configuration.
"""

import asyncio
import importlib
import inspect
import itertools
import logging
import os
import sys
from pathlib import Path

from voicelink import UAT_BASE_URL, VoiceLinkClient
from voicelink.integrations.pipecat import PipecatProvisioner, VoiceLinkFrameSerializer

PORT = 8080
PIPELINE_RATE = 16000
#: Numbers the concurrent calls in the log, so two callers can be told apart.
_CALL_IDS = itertools.count(1)

logger = logging.getLogger("pipecat_quickstart")


def _load_dotenv() -> None:
    """Read a sibling ``.env`` if present. Real environment variables always win."""
    path = Path(__file__).resolve().parent.parent / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def _client() -> VoiceLinkClient:
    base = os.environ.get("VOICELINK_BASE_URL", UAT_BASE_URL)
    client_id = os.environ.get("VOICELINK_CLIENT_ID")
    client_id = int(client_id) if client_id else None
    token = os.environ.get("VOICELINK_TOKEN")
    if token:
        return VoiceLinkClient(token, base_url=base, client_id=client_id)
    return VoiceLinkClient.login(
        os.environ["VOICELINK_USER"],
        os.environ["VOICELINK_PASS"],
        base_url=base,
        client_id=client_id,
    )


def _report(result) -> None:
    print(f"  bot     : id={result.bot.id} -> {os.environ['VOICELINK_WS_URL']}")
    print(f"            {'created' if result.bot_created else 'updated existing'}")
    print(f"  routing : id={result.routing.id} "
          f"{'created' if result.routing_created else 'updated existing'}")
    previous = result.previous_routing
    if result.replaced_inbound is not None and previous is not None:
        trunk = previous.inbound_sip_trunk_id
        print(f"\n  NOTE    : this DID was answering on {result.replaced_inbound.name} "
              f"(trunk {trunk}). To hand it back when you are done:")
        print(f"            python examples/pipecat_quickstart.py restore {trunk}")


def setup_inbound() -> None:
    """PSTN -> VoiceLink -> your Pipecat bot.

    Registers the bot and points the DID's inbound calls at it. The outbound half of the
    routing rule is left untouched, so a number already dialling out through LiveKit keeps
    working.
    """
    prov = PipecatProvisioner(_client())
    result = prov.setup_inbound(
        bot_name=os.environ["VOICELINK_BOT_NAME"],
        websocket_url=os.environ["VOICELINK_WS_URL"],
        did=os.environ["VOICELINK_DID"],
        webhook_url=os.environ.get("VOICELINK_WEBHOOK_URL"),
    )
    print("[VoiceLink] inbound configured")
    _report(result)
    print(f"\n  Dial {os.environ['VOICELINK_DID']} to reach the bot.")


def setup_outbound() -> None:
    """Your Pipecat bot -> VoiceLink -> PSTN.

    Pipecat cannot originate a call - it has no SIP stack - so VoiceLink dials on its
    behalf. That requires the DID's *outbound* half to point at an active WebSocket bot.
    """
    did = os.environ["VOICELINK_DID"]
    to_number = os.environ.get("CALL_TO")

    prov = PipecatProvisioner(_client())
    result = prov.setup_outbound(
        bot_name=os.environ["VOICELINK_BOT_NAME"],
        websocket_url=os.environ["VOICELINK_WS_URL"],
        did=did,
        webhook_url=os.environ.get("VOICELINK_WEBHOOK_URL"),
    )
    print("[VoiceLink] outbound configured")
    _report(result)

    if not to_number:
        print("\n  Set CALL_TO to place a test call. Nothing was dialled.")
        return

    # VoiceLink needs the national number and the country code as separate fields.
    # Passing "919000000001" with no country_code fails with 38 - Network out of order.
    country = os.environ.get("CALL_COUNTRY_CODE", "91")
    print(f"\n  placing a call to +{country} {to_number} (this spends balance) ...")
    lead = prov.place_call(
        did=did,
        customer_number=to_number,
        country_code=country,
        # Arrives back in the media start frame, so the agent knows who it called.
        custom_parameters={"source": "pipecat_quickstart"},
    )
    print(f"  queued: {lead}")


def restore(trunk_id: str | None) -> None:
    """Hand a DID back to the SIP trunk it used before.

    Useful when a number is shared with a SIP-based integration such as LiveKit: point it
    at a Pipecat bot to test, then give it straight back. The bot registration is left in
    place, so switching again is one command.

    Args:
        trunk_id: The SIP trunk to restore to. ``inbound`` prints this number when it
            takes the DID over, and ``show`` reports it for a DID still on its trunk.
    """
    if not trunk_id:
        print("Usage: pipecat_quickstart.py restore <sip_trunk_id>")
        print("Run `show` first to see which trunk this DID answers on.")
        sys.exit(1)

    prov = PipecatProvisioner(_client())
    did = os.environ["VOICELINK_DID"]
    # Both directions: restoring only inbound would leave outbound calls still routed
    # through the bot, which is easy to miss on a shared number.
    routing = prov.restore_sip_trunk(did=did, sip_trunk_id=int(trunk_id))
    print(f"[VoiceLink] DID {did} restored to SIP trunk {trunk_id}")
    print(f"  inbound  : {routing.for_inbound_call}  trunk={routing.inbound_sip_trunk_id} "
          f"bot={routing.inbound_websocket_bot_id}")
    print(f"  outbound : {routing.for_outbound_call}  trunk={routing.outbound_sip_trunk_id} "
          f"bot={routing.outbound_websocket_bot_id}")


def show() -> None:
    """Print what a DID currently points at. Changes nothing."""
    prov = PipecatProvisioner(_client())
    did = os.environ["VOICELINK_DID"]
    routing = prov.find_routing(did)
    if routing is None:
        print(f"DID {did} has no routing rule.")
        return
    print(f"DID {did}")
    print(f"  routing id : {routing.id}")
    print(f"  inbound    : {routing.for_inbound_call}  "
          f"(sip_trunk={routing.inbound_sip_trunk_id}, "
          f"bot={routing.inbound_websocket_bot_id})")
    print(f"  outbound   : {routing.for_outbound_call}  "
          f"(sip_trunk={routing.outbound_sip_trunk_id}, "
          f"bot={routing.outbound_websocket_bot_id})")


async def _echo(websocket) -> None:
    """A bot with no brain: hand the caller's audio straight back."""
    from pipecat.frames.frames import InputAudioRawFrame, StartFrame, TTSAudioRawFrame

    serializer = VoiceLinkFrameSerializer()
    await serializer.setup(
        StartFrame(audio_in_sample_rate=PIPELINE_RATE, audio_out_sample_rate=PIPELINE_RATE)
    )
    print("  call connected")

    async for message in websocket:
        frame = await serializer.deserialize(message)
        if not isinstance(frame, InputAudioRawFrame):
            continue
        reply = await serializer.serialize(
            TTSAudioRawFrame(audio=frame.audio, sample_rate=frame.sample_rate, num_channels=1)
        )
        if reply is not None:
            await websocket.send(reply)

    spec = serializer.audio_spec
    print(f"  call ended (wire format was {spec.format.value if spec else 'unknown'})")


async def _serve() -> None:
    import websockets

    print(f"[bot] echo server on 0.0.0.0:{PORT}")
    print("      expose it publicly and set VOICELINK_WS_URL to that wss:// address,")
    print("      then run:  python examples/pipecat_quickstart.py inbound\n")
    async with websockets.serve(_echo, "0.0.0.0", PORT, max_size=None):
        await asyncio.Future()


SYSTEM_PROMPT = """You are a friendly voice assistant answering a phone call.

Your replies are converted to speech, so keep them short and natural - one or two
sentences. Never use bullet points, markdown, emoji, or symbols; write numbers as words.
If you did not understand the caller, say so plainly and ask them to repeat."""


def _fresh_serializer() -> VoiceLinkFrameSerializer:
    """Build a serializer for exactly one call.

    A serializer learns ``stream_sid``, ``call_sid`` and the wire audio format from that
    call's ``start`` frame. One instance shared between two callers would stamp the second
    caller's audio with the first caller's stream id, so every connection builds its own.
    """
    return VoiceLinkFrameSerializer(
        params=VoiceLinkFrameSerializer.InputParams(
            # Outbound messages carry both stream_sid and streamSid because VoiceLink's
            # expectation is unverified. Set VOICELINK_SID_ALIAS=0 to send snake_case
            # only; if audio still plays, that is the one it reads.
            send_stream_sid_alias=os.environ.get("VOICELINK_SID_ALIAS", "1") != "0",
        )
    )


def _call_transport(websocket):
    """One Pipecat transport bound to one already-accepted WebSocket."""
    from pipecat.transports.websocket.fastapi import (
        FastAPIWebsocketParams,
        FastAPIWebsocketTransport,
    )

    return FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=False,
            serializer=_fresh_serializer(),
        ),
    )


def _vad():
    """Speech detection for one call, so the caller can interrupt the bot.

    In Pipecat 1.7 this is a pipeline step. Passing ``vad_analyzer`` to the transport
    params, as older examples do, is silently discarded by pydantic - no error, no
    warning, and no detection runs at all, which leaves the bot impossible to interrupt.
    Our serializer turns a detected interruption into VoiceLink's ``clear`` message.
    """
    from pipecat.audio.vad.silero import SileroVADAnalyzer
    from pipecat.processors.audio.vad_processor import VADProcessor

    return VADProcessor(vad_analyzer=SileroVADAnalyzer())


def _ai_service(kind: str):
    """Build an AI service from the environment, without naming any provider here.

    Pipecat ships every provider under the same shape - ``pipecat.services.<provider>.
    <kind>`` holding a class called ``<Provider><KIND>Service`` - so the provider is a
    configuration value, not a code change. Any of Pipecat's providers works, and
    switching costs one line in ``.env``:

        STT_PROVIDER=sarvam       TTS_PROVIDER=elevenlabs      LLM_PROVIDER=openai
        SARVAM_API_KEY=...        ELEVENLABS_API_KEY=...       OPENAI_API_KEY=...

    Which speech provider you pick matters more than it looks. Each call builds its own
    pipeline, so each call pays that provider's connection setup before the caller
    hears anything. Measured from India: Deepgram (US-hosted) takes about 1.4 s to
    open a WebSocket, Sarvam (India-hosted) about 0.25 s.

    No provider is privileged and none is a default: which one answers the phone is the
    deployment's decision, not this SDK's.

    Args:
        kind: ``"stt"``, ``"tts"`` or ``"llm"``.

    Returns:
        The configured service, or ``None`` if ``<KIND>_PROVIDER`` is unset, leaving the
        caller to decide whether that kind is required.
    """
    provider = os.environ.get(f"{kind.upper()}_PROVIDER", "").strip().lower()
    if not provider:
        return None
    module = importlib.import_module(f"pipecat.services.{provider}.{kind}")

    suffix = f"{kind.upper()}Service"
    candidates = [
        obj
        for name, obj in vars(module).items()
        if name.endswith(suffix) and isinstance(obj, type)
    ]
    if not candidates:
        raise RuntimeError(f"pipecat.services.{provider}.{kind} defines no {suffix}")
    # A module may hold variants (Sarvam ships a WebSocket and an HTTP TTS). Prefer the
    # one named exactly after the provider; otherwise take the plainest name.
    wanted = f"{provider}{suffix}".lower()
    service = next(
        (c for c in candidates if c.__name__.lower() == wanted),
        min(candidates, key=lambda c: len(c.__name__)),
    )

    options = {"model": os.environ.get(f"{kind.upper()}_MODEL")}
    if kind == "tts":
        options["voice"] = os.environ.get("TTS_VOICE")
    if kind in ("stt", "tts"):
        options["language"] = os.environ.get(f"{kind.upper()}_LANGUAGE")
    options = {k: v for k, v in options.items() if v}

    kwargs = {"api_key": os.environ[f"{provider.upper()}_API_KEY"]}
    if options:
        # Modern Pipecat services take these through a per-service ``Settings`` object
        # and deprecate the flat keywords, so use Settings when the service has one and
        # pass only the fields it actually declares.
        settings_cls = getattr(service, "Settings", None)
        if settings_cls is not None:
            accepted = inspect.signature(settings_cls).parameters
            kwargs["settings"] = settings_cls(
                **{k: v for k, v in options.items() if k in accepted}
            )
        else:
            kwargs.update(options)

    logger.info(f"{kind.upper()}: {service.__name__} ({provider})")
    return service(**kwargs)


def _call_worker(pipeline):
    """Wrap one call's pipeline in a worker.

    ``idle_timeout_secs`` defaults to 300, which cancels the pipeline after five minutes
    with no speech frames. On a phone call that is a legitimate state - hold music, or a
    caller who simply stops talking - and the WebSocket closing is the real end of the
    call, so the timeout is switched off rather than left to hang up on someone.
    """
    from pipecat.pipeline.task import PipelineParams, PipelineWorker

    return PipelineWorker(
        pipeline,
        params=PipelineParams(
            audio_in_sample_rate=PIPELINE_RATE,
            audio_out_sample_rate=PIPELINE_RATE,
        ),
        idle_timeout_secs=None,
    )


def build_app(handler):
    """A FastAPI app that runs ``handler(websocket, call_id)`` once per connection.

    Pipecat's ``WebsocketServerTransport`` holds a single client and closes every other
    with code 1013. VoiceLink still answers those calls, so the caller hears an open,
    silent line. A FastAPI endpoint instead hands each connection its own transport,
    serializer and pipeline. Mounted at ``/`` so ``VOICELINK_WS_URL`` needs no path.

    Separate from :func:`_serve_calls` so a test can drive the endpoint with two
    simultaneous connections without binding a port.
    """
    from fastapi import FastAPI, WebSocket

    app = FastAPI()
    live: set[int] = set()

    @app.websocket("/")
    async def _endpoint(websocket: WebSocket) -> None:
        # The transport requires an already-connected socket, so accept here first.
        await websocket.accept()
        call_id = next(_CALL_IDS)
        live.add(call_id)
        print(f"[call {call_id}] connected  ({len(live)} live)")
        try:
            await handler(websocket, call_id)
        finally:
            live.discard(call_id)
            print(f"[call {call_id}] ended      ({len(live)} live)")

    return app


async def _serve_calls(handler, banner: str, needs_speech: bool = True) -> None:
    """Serve many concurrent VoiceLink calls on :data:`PORT`.

    The speech services are built once here and thrown away, purely to check the
    configuration. Constructing them opens no connection, but it does resolve the
    provider and read its API key - so a misspelled ``STT_PROVIDER`` or a missing key
    stops the server now, with a readable message, instead of killing every call
    silently once the phone is already ringing.
    """
    import uvicorn

    if needs_speech:
        try:
            for kind in ("stt", "tts"):
                if _ai_service(kind) is None:
                    sys.exit(
                        f"[bot] {kind.upper()}_PROVIDER is not set in .env - cannot start.\n"
                        "      Name any Pipecat provider and give it a key, e.g.\n"
                        f"      {kind.upper()}_PROVIDER=deepgram  and  DEEPGRAM_API_KEY=..."
                    )
        except KeyError as exc:
            sys.exit(f"[bot] {exc.args[0]} is not set in .env - cannot start.")
        except ModuleNotFoundError as exc:
            sys.exit(
                f"[bot] provider not installed: {exc}\n"
                '      pip install "pipecat-ai[<provider>]"'
            )

    print(f"[bot] {banner} on 0.0.0.0:{PORT}")
    print("      many calls at once; set VOICELINK_WS_URL to this wss:// address,")
    print("      then run:  python examples/pipecat_quickstart.py inbound\n")
    await uvicorn.Server(
        uvicorn.Config(build_app(handler), host="0.0.0.0", port=PORT, log_level="warning")
    ).serve()


async def _agent_call(websocket, call_id: int) -> None:
    """One call's agent: speech in -> LLM -> speech out.

    Our serializer is the transport's translator, so VoiceLink's A-law frames become PCM
    on the way in and back to A-law on the way out. Nothing in the pipeline below knows
    that VoiceLink exists.

    Every service here is chosen in ``.env``. The LLM in particular is nobody's default:
    which model answers the phone is the deployment's decision, so ``LLM_PROVIDER`` must
    be set to run this mode. ``repeat`` needs no LLM at all.
    """
    from pipecat.frames.frames import LLMRunFrame
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.runner import WorkerRunner
    from pipecat.processors.aggregators.llm_context import LLMContext
    from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair

    transport = _call_transport(websocket)

    stt = _ai_service("stt")
    tts = _ai_service("tts")
    llm = _ai_service("llm")
    if llm is None:
        raise RuntimeError(
            "bot mode needs an LLM: set LLM_PROVIDER (and that provider's API key) in "
            ".env, or run `repeat`, which uses no LLM."
        )

    # Per call: two simultaneous callers must not share a conversation history.
    context = LLMContext([{"role": "system", "content": SYSTEM_PROMPT}])
    aggregators = LLMContextAggregatorPair(context)

    pipeline = Pipeline(
        [
            transport.input(),        # VoiceLink audio  -> PCM   (our serializer)
            _vad(),                   # detect speech, so the caller can interrupt
            stt,                      # PCM              -> text
            aggregators.user(),       # text             -> conversation history
            llm,                      # history          -> reply
            tts,                      # reply            -> PCM
            transport.output(),       # PCM              -> VoiceLink  (our serializer)
            aggregators.assistant(),  # remember what the bot said
        ]
    )

    worker = _call_worker(pipeline)

    @transport.event_handler("on_client_connected")
    async def _greet(_transport, _client):
        print(f"  [call {call_id}] greeting")
        context.add_message({"role": "user", "content": "Greet the caller in one sentence."})
        await worker.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def _bye(_transport, _client):
        print(f"  [call {call_id}] caller hung up")
        await worker.cancel()

    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)   # a coroutine; forgetting the await runs no audio
    await runner.run()


async def _repeat_call(websocket, call_id: int) -> None:
    """One call, speech-to-text and text-to-speech only - no LLM in the pipeline.

    An LLM is the slowest and most rate-limited part of a voice agent, and on a free tier
    it dominates everything else: Gemini's free quota is 5 requests per minute, and a
    normal conversation exceeds that within one minute, after which every turn waits.

    Removing it leaves the parts this SDK actually touches - VoiceLink's audio in, our
    serializer, speech recognition, speech synthesis, audio back out - so response time
    reflects the integration rather than someone's billing tier. The bot simply repeats
    what it heard, which also makes recognition errors audible immediately.
    """
    from pipecat.frames.frames import Frame, TranscriptionFrame, TTSSpeakFrame
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.runner import WorkerRunner
    from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

    class RepeatBack(FrameProcessor):
        """Turn each final transcript into something for the TTS to say."""

        async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
            await super().process_frame(frame, direction)
            if isinstance(frame, TranscriptionFrame) and frame.text.strip():
                print(f"  [call {call_id}] heard: {frame.text!r}")
                await self.push_frame(TTSSpeakFrame(f"You said: {frame.text}"), direction)
            else:
                await self.push_frame(frame, direction)

    transport = _call_transport(websocket)
    stt = _ai_service("stt")
    tts = _ai_service("tts")

    worker = _call_worker(
        Pipeline([transport.input(), _vad(), stt, RepeatBack(), tts, transport.output()])
    )

    @transport.event_handler("on_client_connected")
    async def _greet(_transport, _client):
        print(f"  [call {call_id}] greeting")
        # A fixed line, since there is no LLM to compose one.
        await worker.queue_frames([TTSSpeakFrame("Hello. Say something and I will repeat it.")])

    @transport.event_handler("on_client_disconnected")
    async def _bye(_transport, _client):
        print(f"  [call {call_id}] caller hung up")
        await worker.cancel()

    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)   # a coroutine; forgetting the await runs no audio
    await runner.run()


def main() -> None:
    _load_dotenv()
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "inbound":
        setup_inbound()
    elif mode == "outbound":
        setup_outbound()
    elif mode == "echo":
        asyncio.run(_serve())
    elif mode == "bot":
        asyncio.run(_serve_calls(_agent_call, "speech + LLM agent"))
    elif mode == "repeat":
        asyncio.run(_serve_calls(_repeat_call, "speech only, no LLM"))
    elif mode == "restore":
        restore(sys.argv[2] if len(sys.argv) > 2 else None)
    elif mode == "show":
        show()
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()

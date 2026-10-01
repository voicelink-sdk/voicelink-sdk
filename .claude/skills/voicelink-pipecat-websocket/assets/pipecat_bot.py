"""Pipecat bot server for VoiceLink calls - many concurrent calls, one pipeline each.

    pip install -e ".[pipecat]"                 # from the voicelink-sdk repo root
    pip install "pipecat-ai[silero]"            # voice activity detection (repeat, bot)
    pip install "pipecat-ai[sarvam]"            # or whichever STT/TTS/LLM providers you use
    python pipecat_bot.py echo                  # plays the caller back; no AI keys needed
    python pipecat_bot.py repeat                # STT + TTS, no LLM
    python pipecat_bot.py bot                   # a real speaking agent: STT + LLM + TTS

Settings come from a `.env` file in the current directory (see env.example); real
environment variables win over it.

Listens on 0.0.0.0:8080 (PORT in .env to change) at path "/". Expose it (e.g.
`ngrok http 8080`) and register the public wss:// host - with no path - as
VOICELINK_WS_URL, then run `python provision.py inbound`.

Why FastAPI and not Pipecat's WebsocketServerTransport: that transport serves one client and
closes every other with code 1013, which a caller hears as an answered, silent line. Here each
connection gets its own transport, serializer and pipeline.

Providers are chosen in .env, never hardcoded: STT_PROVIDER / TTS_PROVIDER / LLM_PROVIDER
plus <PROVIDER>_API_KEY.
"""

import importlib
import inspect
import itertools
import os
import sys
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from voicelink.integrations.pipecat import VoiceLinkFrameSerializer
from voicelink.media.events import StartEvent, parse_message

PIPELINE_RATE = 16000
_CALL_IDS = itertools.count(1)

SYSTEM_PROMPT = (
    "You are the VoiceLink voice assistant, speaking on a live phone call. "
    "VoiceLink, by Elisiontec, is a cloud telephony platform from India. It provides virtual "
    "phone numbers (DIDs), SIP trunks, inbound and outbound calling, call routing, call logs, "
    "call event webhooks and a prepaid wallet. Businesses can route a number to a mobile phone, "
    "a SIP trunk, or a WebSocket bot - which is how AI voice agents like you answer calls. "
    "VoiceLink works with AI voice frameworks such as Pipecat, LiveKit and Dograh through the "
    "VoiceLink Python SDK, and resellers can manage their own client accounts. "
    "Answer questions about VoiceLink using only these facts. If you do not know something, "
    "such as pricing or account details, say so and suggest contacting the VoiceLink team. "
    "Your replies are spoken aloud: keep them to one or two short sentences, with no markdown, "
    "lists, emoji or symbols, and write numbers as words. If you did not catch what the caller "
    "said, ask them politely to repeat."
)


def load_dotenv(path: str = ".env") -> None:
    """Read KEY=VALUE lines from `path` if it exists. Real environment variables win."""
    file = Path(path)
    if not file.is_file():
        return
    for line in file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.split(" #", 1)[0].strip().strip("\"'")  # drop inline comments
        os.environ.setdefault(key.strip(), value)


# --------------------------------------------------------------------- per-call parts


def fresh_serializer() -> VoiceLinkFrameSerializer:
    """One serializer per call: it learns stream_sid and the wire format from `start`.

    Outbound messages carry both `stream_sid` and `streamSid` because VoiceLink's casing is
    inconsistent. VOICELINK_SID_ALIAS=0 sends snake_case only (a debugging switch).
    """
    return VoiceLinkFrameSerializer(
        params=VoiceLinkFrameSerializer.InputParams(
            send_stream_sid_alias=os.environ.get("VOICELINK_SID_ALIAS", "1").strip() != "0",
        )
    )


async def read_start(websocket: WebSocket):
    """Read the call's first frame and prime a serializer with it.

    Returns (serializer, custom_parameters), or None for an idle probe - VoiceLink opens and
    closes sockets without sending anything to check reachability. The first frame is
    replayed into the serializer so it still learns stream_sid and the audio format;
    reading it without replaying would leave every later audio frame undecodable.
    """
    try:
        first = await websocket.receive_text()
    except WebSocketDisconnect:
        return None
    serializer = fresh_serializer()
    await serializer.deserialize(first)
    try:
        event = parse_message(first)
    except ValueError:
        event = None
    params = event.custom_parameters if isinstance(event, StartEvent) else {}
    return serializer, (params if isinstance(params, dict) else {})


def call_transport(websocket: WebSocket, serializer: VoiceLinkFrameSerializer):
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
            serializer=serializer,
        ),
    )


def vad():
    """Speech detection as a pipeline step (Pipecat 1.7+). Enables barge-in -> `clear`.

    Passing vad_analyzer= to the transport params is silently ignored in 1.7+.
    """
    from pipecat.audio.vad.silero import SileroVADAnalyzer
    from pipecat.processors.audio.vad_processor import VADProcessor

    return VADProcessor(vad_analyzer=SileroVADAnalyzer())


def call_worker(pipeline):
    """Idle timeout off: a silent caller or hold music must not end the call."""
    from pipecat.pipeline.task import PipelineParams, PipelineWorker

    return PipelineWorker(
        pipeline,
        params=PipelineParams(
            audio_in_sample_rate=PIPELINE_RATE, audio_out_sample_rate=PIPELINE_RATE
        ),
        idle_timeout_secs=None,
    )


def ai_service(kind: str):
    """Build the STT/TTS/LLM service named by <KIND>_PROVIDER, or None if unset.

    Pipecat exposes every provider as pipecat.services.<provider>.<kind> with a class
    ending in <KIND>Service, so the provider is configuration, not code.
    """
    provider = os.environ.get(f"{kind.upper()}_PROVIDER", "").strip().lower()
    if not provider:
        return None
    module = importlib.import_module(f"pipecat.services.{provider}.{kind}")
    suffix = f"{kind.upper()}Service"
    candidates = [
        obj for name, obj in vars(module).items() if name.endswith(suffix) and isinstance(obj, type)
    ]
    if not candidates:
        raise RuntimeError(f"pipecat.services.{provider}.{kind} defines no {suffix}")
    wanted = f"{provider}{suffix}".lower()
    service = next(
        (c for c in candidates if c.__name__.lower() == wanted),
        min(candidates, key=lambda c: len(c.__name__)),
    )

    options = {"model": os.environ.get(f"{kind.upper()}_MODEL", "").strip()}
    if kind == "tts":
        options["voice"] = os.environ.get("TTS_VOICE", "").strip()
    if kind in ("stt", "tts"):
        options["language"] = os.environ.get(f"{kind.upper()}_LANGUAGE", "").strip()
    options = {k: v for k, v in options.items() if v}

    key_name = f"{provider.upper()}_API_KEY"
    api_key = os.environ.get(key_name, "").strip()
    if not api_key:
        raise KeyError(key_name)
    kwargs = {"api_key": api_key}
    if options:
        # Modern services take these through a per-service Settings object.
        settings_cls = getattr(service, "Settings", None)
        if settings_cls is not None:
            accepted = inspect.signature(settings_cls).parameters
            kwargs["settings"] = settings_cls(**{k: v for k, v in options.items() if k in accepted})
        else:
            kwargs.update(options)
    return service(**kwargs)


async def run_worker(transport, worker, greeting_frames) -> None:
    """Greet on connect, cancel on hang-up, run until the call ends."""
    from pipecat.pipeline.runner import WorkerRunner

    @transport.event_handler("on_client_connected")
    async def _greet(_transport, _client):
        await worker.queue_frames(greeting_frames())

    @transport.event_handler("on_client_disconnected")
    async def _bye(_transport, _client):
        await worker.cancel()

    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)  # a coroutine: without the await no audio runs
    await runner.run()


# ------------------------------------------------------------------------- handlers


async def echo_call(websocket: WebSocket, call_id: int) -> None:
    """No pipeline, no AI: decode the caller's audio and send it straight back."""
    from pipecat.frames.frames import InputAudioRawFrame, StartFrame, TTSAudioRawFrame

    serializer = fresh_serializer()
    await serializer.setup(
        StartFrame(audio_in_sample_rate=PIPELINE_RATE, audio_out_sample_rate=PIPELINE_RATE)
    )
    try:
        async for message in websocket.iter_text():
            frame = await serializer.deserialize(message)
            if not isinstance(frame, InputAudioRawFrame):
                continue
            reply = await serializer.serialize(
                TTSAudioRawFrame(audio=frame.audio, sample_rate=frame.sample_rate, num_channels=1)
            )
            if reply is not None:
                await websocket.send_text(reply)
    except WebSocketDisconnect:
        pass
    spec = serializer.audio_spec
    print(f"[call {call_id}] wire format was {spec.format.value if spec else 'never sent'}")


async def repeat_call(websocket: WebSocket, call_id: int) -> None:
    """STT + TTS only: the bot repeats what it heard. Proves speech without an LLM."""
    from pipecat.frames.frames import Frame, TranscriptionFrame, TTSSpeakFrame
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

    started = await read_start(websocket)
    if started is None:
        return
    serializer, _params = started

    class RepeatBack(FrameProcessor):
        async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
            await super().process_frame(frame, direction)
            if isinstance(frame, TranscriptionFrame) and frame.text.strip():
                print(f"[call {call_id}] heard: {frame.text!r}")
                await self.push_frame(TTSSpeakFrame(f"You said: {frame.text}"), direction)
            else:
                await self.push_frame(frame, direction)

    transport = call_transport(websocket, serializer)
    worker = call_worker(
        Pipeline([
            transport.input(), vad(), ai_service("stt"), RepeatBack(),
            ai_service("tts"), transport.output(),
        ])
    )
    await run_worker(
        transport, worker, lambda: [TTSSpeakFrame("Hello. Say something and I will repeat it.")]
    )


def build_prompt(params: dict) -> str:
    """The system prompt, plus whatever place_call(custom_parameters=...) sent for this call."""
    if not params:
        return SYSTEM_PROMPT
    details = "; ".join(f"{k}: {v}" for k, v in params.items() if k != "outboundQueueId")
    return f"{SYSTEM_PROMPT} Call details: {details}." if details else SYSTEM_PROMPT


async def agent_call(websocket: WebSocket, call_id: int) -> None:
    """A speaking agent: speech in -> LLM -> speech out, with its own history per call."""
    from pipecat.frames.frames import LLMRunFrame
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.processors.aggregators.llm_context import LLMContext
    from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair

    started = await read_start(websocket)
    if started is None:
        return
    serializer, params = started
    if params:
        print(f"[call {call_id}] custom parameters: {params}")

    transport = call_transport(websocket, serializer)
    context = LLMContext([{"role": "system", "content": build_prompt(params)}])
    aggregators = LLMContextAggregatorPair(context)
    worker = call_worker(
        Pipeline([
            transport.input(),        # VoiceLink audio -> PCM (serializer)
            vad(),                    # caller can interrupt the bot
            ai_service("stt"),
            aggregators.user(),
            ai_service("llm"),
            ai_service("tts"),
            transport.output(),       # PCM -> VoiceLink audio (serializer)
            aggregators.assistant(),
        ])
    )

    def greeting():
        context.add_message({"role": "user", "content": "Greet the caller in one sentence: say you are VoiceLink's AI voice assistant and ask how you can help."})
        return [LLMRunFrame()]

    await run_worker(transport, worker, greeting)


# ------------------------------------------------------------------------------ app


def build_app(handler) -> FastAPI:
    """Run handler(websocket, call_id) once per connection, at path "/"."""
    app = FastAPI()

    @app.websocket("/")
    async def _endpoint(websocket: WebSocket) -> None:
        await websocket.accept()  # the transport needs an already-accepted socket
        call_id = next(_CALL_IDS)
        print(f"[call {call_id}] connected")
        try:
            await handler(websocket, call_id)
        except Exception as exc:  # one broken call must not take the server down
            print(f"[call {call_id}] error: {exc!r}")
        finally:
            print(f"[call {call_id}] ended")

    return app


HANDLERS = {"echo": echo_call, "repeat": repeat_call, "bot": agent_call}


def check_config(mode: str) -> None:
    """Fail at startup, not on the first ringing call, if a provider is misconfigured."""
    kinds = {"echo": (), "repeat": ("stt", "tts"), "bot": ("stt", "tts", "llm")}[mode]
    try:
        if kinds:
            vad()  # also proves the silero extra is installed
        for kind in kinds:
            if ai_service(kind) is None:
                sys.exit(f"{kind.upper()}_PROVIDER is not set - add it to .env to run {mode} mode.")
    except KeyError as exc:
        sys.exit(f"{exc.args[0]} is not set - add it to .env.")
    except ImportError as exc:
        # Pipecat raises a plain ImportError when a provider exists but its package is
        # missing, and ModuleNotFoundError when the provider name itself is unknown.
        sys.exit(f"Not installed: {exc}\n"
                 '  pip install "pipecat-ai[<provider>]" for each provider named in .env, and\n'
                 '  pip install "pipecat-ai[silero]" for voice detection.\n'
                 "  Check the provider names in .env are spelled as Pipecat names them.")


def port() -> int:
    text = os.environ.get("PORT", "").strip() or "8080"
    if not text.isdigit():
        sys.exit(f"PORT must be a number, got {text!r}.")
    return int(text)


if __name__ == "__main__":
    import uvicorn

    # Print each call-log line immediately, even when output goes to a pipe or log file
    # (Docker, systemd, nohup); otherwise buffering hides "connected"/"ended" lines.
    sys.stdout.reconfigure(line_buffering=True)
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode not in HANDLERS:
        sys.exit(__doc__)
    load_dotenv()
    check_config(mode)
    listen = port()
    print(f"[bot] {mode} mode on 0.0.0.0:{listen} - register its public wss:// host, no path")
    uvicorn.run(build_app(HANDLERS[mode]), host="0.0.0.0", port=listen, log_level="warning")

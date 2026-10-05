"""LiveKit agent worker for VoiceLink calls.

    pip install "livekit-agents[deepgram,openai,silero]" python-dotenv
    pip install livekit-plugins-groq livekit-plugins-sarvam    # only if you choose them
    python livekit_agent.py dev

LIVEKIT_AGENT_NAME must equal the dispatch rule's agent_name (inbound) and the name passed
to dispatch_agent (outbound), or calls land in an empty room.

Speech and language services are chosen in .env (defaults shown); each reads its own key:

    STT_PROVIDER = deepgram | sarvam | openai       (default deepgram)
    LLM_PROVIDER = openai | groq                    (default openai)
    TTS_PROVIDER = openai | sarvam | deepgram       (default openai)
    keys: DEEPGRAM_API_KEY, OPENAI_API_KEY, GROQ_API_KEY, SARVAM_API_KEY
    optional: STT_MODEL, LLM_MODEL, TTS_MODEL, TTS_VOICE, STT_LANGUAGE, TTS_LANGUAGE
"""

import importlib
import os
import sys

from dotenv import load_dotenv

load_dotenv()
AGENT_NAME = os.environ.get("LIVEKIT_AGENT_NAME", "").strip() or "voice-assistant"

INSTRUCTIONS = (
    "You are a friendly phone assistant. Replies are spoken, so keep them to one or two short "
    "sentences with no markdown or symbols."
)
GREETING = "Greet the caller in one sentence."

# provider -> (plugin module, pip package, API key variable)
PLUGINS = {
    "deepgram": ("livekit.plugins.deepgram", "livekit-agents[deepgram]", "DEEPGRAM_API_KEY"),
    "openai": ("livekit.plugins.openai", "livekit-agents[openai]", "OPENAI_API_KEY"),
    "groq": ("livekit.plugins.groq", "livekit-plugins-groq", "GROQ_API_KEY"),
    "sarvam": ("livekit.plugins.sarvam", "livekit-plugins-sarvam", "SARVAM_API_KEY"),
}
ALLOWED = {
    "stt": ("deepgram", "sarvam", "openai"),
    "llm": ("openai", "groq"),
    "tts": ("openai", "sarvam", "deepgram"),
}
DEFAULTS = {"stt": "deepgram", "llm": "openai", "tts": "openai"}


def _env(name: str) -> str | None:
    return os.environ.get(name, "").strip() or None


def provider(kind: str) -> str:
    name = (_env(f"{kind.upper()}_PROVIDER") or DEFAULTS[kind]).lower()
    if name not in ALLOWED[kind]:
        sys.exit(f"{kind.upper()}_PROVIDER={name!r} is not supported here. "
                 f"Choose one of: {', '.join(ALLOWED[kind])}.")
    return name


def service(kind: str):
    """Build the STT, LLM or TTS for the chosen provider, passing only options that are set."""
    name = provider(kind)
    module_name, package, key = PLUGINS[name]
    if not _env(key):
        sys.exit(f"{key} is not set - add it to .env (needed for {kind.upper()}_PROVIDER={name}).")
    try:
        plugin = importlib.import_module(module_name)
    except ImportError as exc:
        hint = ""
        if "Application Control" in str(exc) or "DLL load failed" in str(exc):
            hint = ("\n  Windows blocked one of LiveKit's native libraries. Allow it in Windows "
                    "Security (Smart App Control / App & browser control), or run this on Linux/WSL.")
        sys.exit(f"Cannot load {module_name}: {exc}\n  pip install \"{package}\"{hint}")
    cls = getattr(plugin, kind.upper())
    model, lang = _env(f"{kind.upper()}_MODEL"), _env(f"{kind.upper()}_LANGUAGE")
    opts: dict = {"model": model}
    if name == "sarvam" and kind == "tts":
        opts = {"model": model, "target_language_code": lang or "en-IN", "speaker": _env("TTS_VOICE")}
    elif name == "sarvam" and kind == "stt":
        opts = {"model": model, "language": lang or "en-IN"}
    elif kind == "stt":
        opts["language"] = lang
    elif kind == "tts" and name == "openai":
        opts["voice"] = _env("TTS_VOICE")
    return cls(**{k: v for k, v in opts.items() if v})


def check_config() -> None:
    """Fail at startup, not when the first call rings, if a provider is misconfigured."""
    for kind in ("stt", "llm", "tts"):
        service(kind)
    print(f"[agent] {AGENT_NAME}: STT={provider('stt')} LLM={provider('llm')} TTS={provider('tts')}")


def validate_settings() -> None:
    """Settings checks that need no libraries: run first, so the message is about .env."""
    for name in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"):
        if not _env(name):
            sys.exit(f"{name} is not set - add it to .env.")
    chosen = {kind: provider(kind) for kind in ("stt", "llm", "tts")}  # names first, then keys
    for kind in chosen:
        key = PLUGINS[chosen[kind]][2]
        if not _env(key):
            sys.exit(f"{key} is not set - add it to .env "
                     f"(needed for {kind.upper()}_PROVIDER={provider(kind)}).")


def main() -> None:
    validate_settings()
    try:
        from livekit import agents
        from livekit.agents import Agent, AgentSession
        from livekit.plugins import silero
    except ImportError as exc:
        hint = ""
        if "Application Control" in str(exc) or "DLL load failed" in str(exc):
            hint = ("\n  Windows blocked one of LiveKit's native libraries. Allow it in Windows "
                    "Security (Smart App Control / App & browser control), or run this on Linux/WSL.")
        sys.exit(f"LiveKit Agents not installed or blocked: {exc}\n"
                 '  pip install "livekit-agents[deepgram,openai,silero]" python-dotenv' + hint)

    class Assistant(Agent):
        def __init__(self) -> None:
            super().__init__(instructions=INSTRUCTIONS)

    async def entrypoint(ctx: agents.JobContext) -> None:
        await ctx.connect()
        session = AgentSession(
            stt=service("stt"), llm=service("llm"), tts=service("tts"), vad=silero.VAD.load(),
        )
        await session.start(agent=Assistant(), room=ctx.room)
        await session.generate_reply(instructions=GREETING)

    check_config()
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint, agent_name=AGENT_NAME))


if __name__ == "__main__":
    main()

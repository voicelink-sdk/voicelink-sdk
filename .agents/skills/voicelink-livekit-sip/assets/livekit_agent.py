"""Minimal LiveKit agent worker for VoiceLink calls.

    pip install "livekit-agents[deepgram,openai,silero]" python-dotenv
    python livekit_agent.py dev

AGENT_NAME must equal the dispatch rule's agent_name (inbound) and the name passed to
prov.dispatch_agent(...) (outbound), or calls land in an empty room.
"""

import os

from dotenv import load_dotenv
from livekit import agents
from livekit.agents import Agent, AgentSession
from livekit.plugins import deepgram, openai, silero

load_dotenv()
AGENT_NAME = os.environ.get("LIVEKIT_AGENT_NAME", "voice-assistant")


class Assistant(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions=(
                "You are a friendly phone assistant. Replies are spoken, so keep them to one "
                "or two short sentences with no markdown or symbols."
            )
        )


async def entrypoint(ctx: agents.JobContext) -> None:
    await ctx.connect()
    session = AgentSession(
        stt=deepgram.STT(),
        llm=openai.LLM(model="gpt-4o-mini"),
        tts=openai.TTS(),
        vad=silero.VAD.load(),
    )
    await session.start(agent=Assistant(), room=ctx.room)
    await session.generate_reply(instructions="Greet the caller in one sentence.")


if __name__ == "__main__":
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint, agent_name=AGENT_NAME))

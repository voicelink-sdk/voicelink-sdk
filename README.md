# VoiceLink SDK

Python SDK for [VoiceLink](https://app.voicelink.co.in) telephony, with integrations for
the leading open-source voice-AI frameworks — **LiveKit**, **Pipecat**, and **Dograh**.

The SDK gives you one clean interface to VoiceLink's control plane (numbers, bots, SIP
trunks, routing, outbound calls, webhooks) and the real-time media layer that streams
live call audio to an AI agent.

> The full control plane, webhook parsing, and the **LiveKit** and **Pipecat** integrations
> are implemented and tested. A Dograh provider is planned.

## Install

```bash
pip install voicelink                 # core
pip install voicelink[pipecat]        # + Pipecat adapter
pip install voicelink[livekit]        # + LiveKit provisioning helpers
```

## Quick start

```python
from voicelink import VoiceLinkClient
from voicelink.enums import InboundRoute, OutboundRoute

client = VoiceLinkClient(api_token="…", client_id=123)

# Register an AI bot endpoint that receives live call audio.
bot = client.websocket_bots.create(
    bot_name="Support",
    websocket_url="wss://my-agent.example.com/ws",
)

# Point a phone number at it, inbound and outbound.
client.routing.create(
    did_number="919484950416",
    inbound=InboundRoute.WEBSOCKET_BOT,
    inbound_websocket_bot_id=bot.id,
    outbound=OutboundRoute.WEBSOCKET_BOT,
    outbound_websocket_bot_id=bot.id,
)

# Trigger an outbound call.
result = client.calls.create(
    did_number="919484950416",
    customer_number="919812345678",
    custom_parameters={"campaign": "fall"},
)
print(result.outbound_queue_id)
```

### Handling webhooks

```python
from voicelink.webhooks import parse_webhook
from voicelink.enums import CallEvent

event = parse_webhook(request_body)   # dict, JSON string, or bytes
if event.event is CallEvent.COMPLETED:
    print(event.call.id, event.call.status, event.call.duration_sec)
# respond 200 to VoiceLink
```

## AI coding assistant skills (Claude Code and Codex)

This repo ships two skills that let Claude Code or Codex set up a working AI phone agent for
you - you describe what you want in plain English and the assistant does the provisioning,
starts the agent and places test calls.

| Skill | What it sets up |
|---|---|
| `voicelink-livekit-sip` | VoiceLink number -> SIP bridge (Asterisk) -> LiveKit Cloud -> LiveKit agent, inbound and outbound |
| `voicelink-pipecat-websocket` | VoiceLink number -> VoiceLink WebSocket bot -> your Pipecat server, inbound and outbound |

### Install

**Claude Code** - install once as a plugin; the skills then work in any project:

```
/plugin marketplace add voicelink-sdk/voicelink-sdk
/plugin install voicelink@voicelink
```

**Codex** - ask Codex's built-in skill installer to install the skills from this repo:

```
$skill-installer install the skills in https://github.com/voicelink-sdk/voicelink-sdk/tree/master/.agents/skills
```

Working inside a clone of this repo needs no install: Claude Code reads `.claude/skills/`
and Codex reads `.agents/skills/` automatically.

### Prerequisites (both skills)

- Python 3.10+ and this SDK with the right extra: `pip install -e ".[livekit]"` or
  `pip install -e ".[pipecat]"` from a clone of this repo.
- A VoiceLink account: login (or API token), the **client id that owns the number**
  (reseller accounts), and the number (DID).
- Keys for the agent's speech and language services, chosen in `.env` (e.g. Sarvam for speech
  and Groq for the LLM, or Deepgram and OpenAI).
- A `.env` in your project folder, copied from the skill's `assets/env.example`. Never commit it.

### Extra prerequisites for LiveKit

- A LiveKit Cloud project: URL, API key and secret, and its SIP URI (Telephony -> SIP trunks).
- A running SIP bridge (Asterisk) with a **public IPv4** and an open SIP port - VoiceLink
  speaks plain UDP SIP and LiveKit Cloud only accepts TLS, so they cannot connect directly.
  The bridge must forward inbound calls to your LiveKit SIP URI, send outbound calls to
  VoiceLink's termination server with the trunk's credentials, and pin `transport=` on every
  endpoint. See the skill's `references/asterisk-bridge.md`.
- `pip install "livekit-agents[deepgram,openai,silero]" python-dotenv` (plus
  `livekit-plugins-groq` / `livekit-plugins-sarvam` if you choose them).

### Extra prerequisites for Pipecat

- A public `wss://` address for your bot server - a real host, or a tunnel such as ngrok
  while developing.
- `pip install "pipecat-ai[silero]"` plus the provider extras you choose
  (e.g. `pip install "pipecat-ai[sarvam]"`).

### Use

Open Claude Code or Codex in your project folder and ask, for example:

```
Connect my VoiceLink number to my LiveKit voice agent.
Set up my VoiceLink number with a Pipecat bot.
Now set up outbound calling and call me.
```

The skill checks your setup first and tells you exactly what is missing.

### Things the skills handle for you - and why

- **One step in the VoiceLink portal (LiveKit):** after the SIP trunk is created, switch its
  **Peer Monitoring** on (the skill prints a direct link). VoiceLink's API cannot set it, and
  without it the trunk is treated as unreachable.
- **Outbound routing is set to "Only answer" (LiveKit):** the bridge already places the call;
  routing the number's outbound calls to the SIP trunk makes VoiceLink send every answered
  call back as a second call that drops.
- **Run one agent worker per agent name (LiveKit):** LiveKit hands each call to any worker with
  that name, so a forgotten copy elsewhere silently takes calls.
- **WebSocket API toggle off (Pipecat):** with the bot's "WebSocket API" toggle on in the
  portal, VoiceLink hangs up immediately.

## Development

```bash
python -m venv .venv
.venv/Scripts/activate        # Windows
pip install -e ".[dev]"
pytest
```

## License

MIT

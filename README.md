# VoiceLink SDK

Python SDK for [VoiceLink](https://app.voicelink.co.in) telephony, with integrations for
the leading open-source voice-AI frameworks - **LiveKit**, **Pipecat**, and **Dograh**.

The SDK gives you one clean interface to VoiceLink's control plane (numbers, bots, SIP
trunks, routing, outbound calls, webhooks) and the real-time media layer that streams
live call audio to an AI agent.

It also ships **skills for Claude Code and Codex**: describe what you want in plain English
and the assistant provisions VoiceLink and your voice-agent platform, starts the agent and
places test calls for you.

> The control plane, webhook parsing, and the **LiveKit** and **Pipecat** integrations are
> implemented and tested on live calls. A Dograh provider is planned.

## Contents

1. [Install the SDK](#1-install-the-sdk)
2. [Prerequisites](#2-prerequisites)
3. [Install the skills (Claude Code / Codex)](#3-install-the-skills-claude-code--codex)
4. [Use the skills](#4-use-the-skills)
5. [What the skills handle for you - and why](#5-what-the-skills-handle-for-you---and-why)
6. [Use the SDK directly](#6-use-the-sdk-directly)
7. [Development](#7-development)

## 1. Install the SDK

```bash
pip install voicelink                 # core (control plane + webhooks)
pip install "voicelink[pipecat]"      # + Pipecat media adapter
pip install "voicelink[livekit]"      # + LiveKit provisioning helpers
```

Python 3.10 or newer. Working from a clone of this repo: `pip install -e ".[livekit]"` or
`pip install -e ".[pipecat]"`.

## 2. Prerequisites

### 2.1 For everything

| You need | Notes |
|---|---|
| A VoiceLink account | Login (or API token), the **client id that owns the number** (reseller accounts), and the number (DID). Production API: `https://app.voicelink.co.in/api` |
| Speech and language keys for the agent | Chosen in `.env`, e.g. Sarvam for speech + Groq for the LLM, or Deepgram + OpenAI |
| A `.env` file in your project folder | Copy the skill's `assets/env.example` and fill it in. **Never commit it.** |

### 2.2 For LiveKit

How a call flows: `caller -> VoiceLink -> SIP bridge (Asterisk) -> LiveKit Cloud -> your agent`.
VoiceLink speaks plain UDP SIP and LiveKit Cloud only accepts TLS, so a small bridge sits
between them.

| You need | Notes |
|---|---|
| A LiveKit Cloud project | URL, API key, API secret, and its SIP URI (Telephony -> SIP trunks) |
| A running SIP bridge (Asterisk) | Public **IPv4** and an open SIP port. Must forward inbound calls to your LiveKit SIP URI, send outbound calls to VoiceLink's termination server with the trunk's credentials, and pin `transport=` on every endpoint. Setup guide: `.claude/skills/voicelink-livekit-sip/references/asterisk-bridge.md` |
| Agent packages | `pip install "livekit-agents[deepgram,openai,silero]" python-dotenv` (plus `livekit-plugins-groq` / `livekit-plugins-sarvam` if you choose them) |

On Windows, if LiveKit fails with `DLL load failed ... Application Control`, allow it in
Windows Security (Smart App Control) or run the agent on Linux/WSL.

### 2.3 For Pipecat

How a call flows: `caller -> VoiceLink -> WebSocket bot -> your Pipecat server`. No SIP, no bridge.

| You need | Notes |
|---|---|
| A public `wss://` address for your bot server | A real host, or a tunnel such as ngrok while developing |
| Pipecat packages | `pip install "pipecat-ai[silero]"` plus the provider extras you choose, e.g. `pip install "pipecat-ai[sarvam]"` |

## 3. Install the skills (Claude Code / Codex)

| Skill | What it sets up |
|---|---|
| `voicelink-livekit-sip` | VoiceLink number -> SIP bridge -> LiveKit Cloud -> LiveKit agent, inbound and outbound |
| `voicelink-pipecat-websocket` | VoiceLink number -> VoiceLink WebSocket bot -> your Pipecat server, inbound and outbound |

### Claude Code

Install once as a plugin; the skills then work in any project folder:

```
/plugin marketplace add voicelink-sdk/voicelink-sdk
/plugin install voicelink@voicelink
```

Restart Claude Code, then type `/voicelink` to see both skills.

### Codex

Ask Codex's built-in skill installer:

```
$skill-installer install the skills in https://github.com/voicelink-sdk/voicelink-sdk/tree/master/.agents/skills
```

If Codex blocks the install (its permission mode does not allow shell commands), run this in
PowerShell instead, then restart Codex:

```powershell
$skills = Invoke-RestMethod 'https://api.github.com/repos/voicelink-sdk/voicelink-sdk/contents/.agents/skills?ref=master'
$paths = @($skills | Where-Object type -eq 'dir' | ForEach-Object path)
python "$HOME\.codex\skills\.system\skill-installer\scripts\install-skill-from-github.py" --repo voicelink-sdk/voicelink-sdk --ref master --path $paths
```

Type `/skills` to see both skills.

### From a clone of this repo

No install needed: Claude Code reads `.claude/skills/` and Codex reads `.agents/skills/`
automatically when started inside the repo.

## 4. Use the skills

Open Claude Code or Codex **in your project folder** (the one with your `.env`) and ask:

```
Connect my VoiceLink number to my LiveKit voice agent.
Set up my VoiceLink number with a Pipecat bot.
Now set up outbound calling and call me.
```

The skill checks your setup first and tells you exactly what is missing. It asks before
placing any outbound test call, because that dials a real number and spends balance.

## 5. What the skills handle for you - and why

| Rule | Why |
|---|---|
| **Peer Monitoring ON** (LiveKit) - after the SIP trunk is created, switch it on in the VoiceLink portal; the skill prints a direct link | VoiceLink's API cannot set it. With it off, VoiceLink treats the trunk as unreachable and callers hear "out of network coverage" |
| **Outbound route = "Only answer"** (LiveKit) - set by the skill, do not change it | The bridge already places the call. Routing outbound to the SIP trunk makes VoiceLink send every answered call back as a second call, which drops after ~45 s |
| **One agent worker per agent name** (LiveKit) | LiveKit hands each call to any worker with that name, so a forgotten copy elsewhere silently takes calls |
| **Fixed trunk credentials** (LiveKit) - `VOICELINK_TRUNK_USERNAME/PASSWORD` in `.env`, matching the bridge | Otherwise VoiceLink generates new credentials per trunk and the bridge's outbound auth stops matching |
| **"WebSocket API" toggle OFF** (Pipecat) - check it in the portal on the bot | With it on, VoiceLink answers and hangs up immediately |
| **Re-runs are safe** (both) | Every setup script finds existing trunks, rules and bots and reuses or corrects them instead of creating duplicates |

## 6. Use the SDK directly

```python
from voicelink import VoiceLinkClient
from voicelink.enums import InboundRoute, OutboundRoute

client = VoiceLinkClient(api_token="...", client_id=123)

# Register an AI bot endpoint that receives live call audio.
bot = client.websocket_bots.create(
    bot_name="Support",
    websocket_url="wss://my-agent.example.com/ws",
)

# Point a phone number at it, inbound and outbound.
client.routing.create(
    did_number="91XXXXXXXXXX",
    inbound=InboundRoute.WEBSOCKET_BOT,
    inbound_websocket_bot_id=bot.id,
    outbound=OutboundRoute.WEBSOCKET_BOT,
    outbound_websocket_bot_id=bot.id,
)

# Trigger an outbound call.
result = client.calls.create(
    did_number="91XXXXXXXXXX",
    customer_number="9XXXXXXXXX",      # national number
    country_code="91",
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

Runnable examples: `examples/livekit_quickstart.py` and `examples/pipecat_quickstart.py`.

## 7. Development

```bash
python -m venv .venv
.venv/Scripts/activate        # Windows
pip install -e ".[dev]"
pytest
```

## License

MIT

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

## Development

```bash
python -m venv .venv
.venv/Scripts/activate        # Windows
pip install -e ".[dev]"
pytest
```

## License

MIT

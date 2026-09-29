# Outbound: VoiceLink dials → WebSocket bot → Pipecat

Pipecat has no telephony and cannot originate a call. VoiceLink dials the customer and, on
answer, opens the same kind of WebSocket to your server as an inbound call. Your server code
does not change between directions.

Runnable form of steps 1-2: `python provision.py outbound` (routing only), then
`python provision.py outbound --call` (dials `CALL_TO` with `CALL_COUNTRY_CODE`). Step 3 is
built into `pipecat_bot.py`: `bot` mode reads each call's `custom_parameters` and adds them
to the agent's prompt.

## 1. Route the DID's outbound half to the bot

VoiceLink refuses to dial unless the DID has an **active outbound WebSocket bot**.

```python
result = prov.setup_outbound(
    bot_name="pipecat-agent",
    websocket_url="wss://abc.ngrok-free.dev",
    did="91XXXXXXXXXX",
)
```

Only the outbound half changes; a DID still answering inbound on LiveKit keeps doing so.

## 2. Place the call

This dials a real number and spends balance — confirm with the user before running it.

```python
lead = prov.place_call(
    did="91XXXXXXXXXX",
    customer_number="9XXXXXXXXX",      # national number
    country_code="91",                 # always pass it separately
    custom_parameters={"customer_id": "c-42", "campaign": "renewals"},
)
print(lead)                            # carries the outbound_queue_id webhooks refer to
```

- **Number format:** VoiceLink needs the national number and `country_code` apart.
  `919XXXXXXXXX` with no country code fails with `38 - Network out of order`, which looks like
  a dead carrier. `place_call` strips a duplicated prefix, so `"919XXXXXXXXX"`, `"9XXXXXXXXX"`
  and `"+91 9XXXX-XXXXX"` all work **when `country_code="91"` is passed**.
- **`custom_parameters`** is a dict; the SDK JSON-encodes it (the API stores malformed JSON as
  `null`). It comes back on the media `start` frame (`start.custom_parameters`) so the agent
  knows who it called, and on webhooks. VoiceLink adds an `outboundQueueId` for correlation.
- **`websocket_url=`** overrides the bot's registered address for this one call, so one bot
  registration can serve several agents.
- `vl.calls.create_bulk(...)` enqueues a campaign; `call_limit` caps the campaign, it is not a
  concurrency setting.

## 3. Read the agent's context from the start frame

The serializer consumes `start` inside the transport, so the agent never sees it. To use
`custom_parameters` (e.g. in the system prompt), read the first message yourself in the
endpoint, **then replay it into the serializer** so it still learns `stream_sid` and the
audio format:

```python
from voicelink.media.events import StartEvent, parse_message

first = await websocket.receive_text()      # raises WebSocketDisconnect on an idle probe
event = parse_message(first)
params = event.custom_parameters if isinstance(event, StartEvent) else {}

serializer = VoiceLinkFrameSerializer()
await serializer.deserialize(first)         # replay: without this, no audio is decoded
transport = FastAPIWebsocketTransport(
    websocket=websocket,
    params=FastAPIWebsocketParams(
        audio_in_enabled=True, audio_out_enabled=True, add_wav_header=False,
        serializer=serializer,
    ),
)
prompt = f"You are calling customer {params.get('customer_id', 'unknown')}."
```

Wrap the `receive_text` in `try/except WebSocketDisconnect` and return quietly: VoiceLink
opens and closes idle sockets to check reachability.

## 4. Call outcome webhooks (optional)

Set `webhook_url` on the bot (or per call) to receive lifecycle events. Parse them with the SDK:

```python
from voicelink.enums import CallEvent
from voicelink.webhooks import parse_webhook

event = parse_webhook(request_body)                 # dict, str or bytes
if event.event is CallEvent.COMPLETED:
    call = event.call
    print(call.status, call.call_status, call.duration_sec, call.outbound_queue_id)
```

Events: `call.initiated`, `call.ringing`, `call.answered`, `call.ended`, `call.failed`,
`call.completed`. `COMPLETED` fires for failed calls too. `status` is coarse (`"failed"`);
`call_status` carries the reason (`"NO ANSWER"`, `"ANSWERED"`). A no-answer call never opens
the WebSocket, so the webhook is the only place you learn about it.

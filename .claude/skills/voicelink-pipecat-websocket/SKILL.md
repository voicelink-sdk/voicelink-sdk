---
name: voicelink-pipecat-websocket
description: Connect a VoiceLink phone number (DID) to a Pipecat AI voice agent over VoiceLink's WebSocket media stream using the VoiceLink Python SDK — inbound (caller → VoiceLink → WebSocket bot → your Pipecat server) and outbound (VoiceLink dials → WebSocket bot → your Pipecat server). Covers PipecatProvisioner, VoiceLinkFrameSerializer, the per-call FastAPI server, taking a DID over from a SIP trunk and handing it back, and debugging silent calls, instant hang-ups, "38 - Network out of order" and a bot that cannot be interrupted. Use this whenever someone wants to wire VoiceLink to Pipecat, run a Pipecat bot on a VoiceLink number, place outbound calls through a Pipecat agent, write or fix the VoiceLink serializer or bot server, or debug why VoiceLink calls don't reach their Pipecat bot — even if they only say "make my number talk to my Pipecat bot".
---

# VoiceLink ⇄ Pipecat over WebSocket

Connect a VoiceLink DID to a Pipecat voice agent using the `voicelink` SDK. There is **no SIP
and no bridge**: VoiceLink opens a WebSocket to your server and streams the call as JSON with
base64 G.711 inside. The SDK supplies both halves:

- `PipecatProvisioner` — configuration, done once: register the WebSocket bot, route the DID.
- `VoiceLinkFrameSerializer` — media, used on every call: VoiceLink JSON ⇄ Pipecat PCM frames.

```
Inbound : PSTN → VoiceLink ─wss→ your Pipecat server (serializer → VAD → STT → LLM → TTS)
Outbound: prov.place_call() → VoiceLink dials PSTN ─wss→ the same server
```

This is the mirror image of the LiveKit integration: LiveKit terminates SIP and needs
configuration only; Pipecat never sees SIP and needs the serializer.

## The facts that shape everything

These were established on live calls, and several contradict VoiceLink's own documentation:

- **`start` is the first frame.** No `connected` event is ever sent.
- **The bot's configured `audio_format` is ignored.** A bot configured `l16_16k` streamed
  `audio/alaw` at 8 kHz. Only the `start` frame's `media_format` is true, so the serializer
  resolves the format per call at runtime. Never hardcode a codec.
- **Key casing is inconsistent**: `start` carries `stream_sid`; `media` and `stop` carry
  `streamSid`. The serializer handles both and sends both on outbound messages.
- **The portal's "WebSocket API" toggle must stay OFF.** With it on, VoiceLink answers and hangs
  up within a second without ever opening the socket. The REST API cannot set it — check it
  in the portal first whenever a bot gets no audio.
- **VoiceLink probes with idle sockets**: it opens a connection and closes it without sending
  anything. Harmless — the serializer does no work until `start` arrives.
- **One connection = one call**, and calls arrive concurrently. Every connection needs its own
  transport, serializer and pipeline (see "Rules").

## Workflow

Both scripts in `assets/` read a `.env` in the current directory, so copy them and
`assets/env.example` into the user's project and run everything from there.

1. **Install** from the voicelink-sdk repo root (the SDK is not assumed to be on PyPI):
   ```bash
   pip install -e ".[pipecat]"
   pip install "pipecat-ai[silero]"          # voice detection, for repeat/bot modes
   pip install "pipecat-ai[sarvam]"          # the STT/TTS/LLM providers named in .env
   ```
2. **Fill `.env`** from `assets/env.example`: VoiceLink login (user/pass or token),
   `VOICELINK_CLIENT_ID` (reseller accounts require it), the DID, a bot name, and the
   providers + keys. Never ask the user to paste secrets into chat - they edit `.env`.
3. **Check the current state** (read-only): `python provision.py show`. Note any SIP trunk the
   DID uses today, so it can be handed back later.
4. **Start the bot server and expose it:** `python pipecat_bot.py echo` and, while developing,
   `ngrok http 8080`. Put the tunnel's `wss://` host, **no path**, in `VOICELINK_WS_URL`.
5. **Route inbound calls:** `python provision.py inbound`. Remind the user to check the bot's
   **WebSocket API** toggle is OFF in the portal - no API can set it.
6. **Prove audio:** the user calls the DID and hears themselves (echo). Then restart the
   server in `repeat` (STT + TTS) and finally `bot` (adds the LLM).
7. **Outbound**, if wanted: `python provision.py outbound`, then - only after the user
   confirms, because it dials a real number and spends balance - `python provision.py
   outbound --call`. The bot receives `custom_parameters` and uses them in its prompt.
8. **Hand the number back** when done: `python provision.py restore <sip_trunk_id>`
   (both directions; `--inbound-only` / `--outbound-only` to limit it).
9. **If anything fails**, go to `references/troubleshooting.md` and diagnose from evidence
   (bot server log, `show`, VoiceLink CDR) rather than guessing.

## SDK essentials

```python
from voicelink import DEFAULT_BASE_URL, UAT_BASE_URL, VoiceLinkClient
from voicelink.enums import AudioFormat, InboundRoute, OutboundRoute, Status
from voicelink.integrations.pipecat import (      # pip install -e ".[pipecat]"
    PipecatProvisioner, Provisioned, VoiceLinkFrameSerializer,
)

vl = VoiceLinkClient.login(USER, PASS, base_url=UAT_BASE_URL, client_id=CLIENT_ID)
# or: VoiceLinkClient(token, base_url=DEFAULT_BASE_URL, client_id=CLIENT_ID)
prov = PipecatProvisioner(vl)                     # sync; no async context manager
```

`DEFAULT_BASE_URL` is production (`https://app.voicelink.co.in/api`), `UAT_BASE_URL` is
staging. There is no `BASE_URL` export.

| Call | Purpose |
|---|---|
| `prov.setup_inbound(bot_name=, websocket_url=, did=, webhook_url=None)` | Create/update the bot and route the DID's inbound calls to it. Returns `Provisioned` |
| `prov.setup_outbound(bot_name=, websocket_url=, did=, webhook_url=None)` | Same for the outbound half — required before `place_call` |
| `prov.place_call(did=, customer_number=, country_code=, custom_parameters=None, websocket_url=None)` | Ask VoiceLink to dial (spends balance). Returns `LeadResult` |
| `prov.find_routing(did)` / `prov.find_bot(name)` | Read-only lookups |
| `prov.restore_previous(provisioned)` | Put the DID back exactly as it was before `setup_inbound` |
| `prov.restore_sip_trunk(did=, sip_trunk_id=, inbound=True, outbound=True)` | Hand the DID back to a SIP trunk (e.g. LiveKit) |
| `prov.ensure_bot(...)`, `prov.route_inbound_to_bot(...)`, `prov.route_outbound_to_bot(...)` | The individual steps `setup_*` combines |
| `VoiceLinkFrameSerializer()` | The transport's serializer — pass nothing; it learns everything from `start` |

`Provisioned` has `.bot`, `.routing`, `.bot_created`, `.routing_created`,
`.previous_routing` and `.replaced_inbound` (the `InboundRoute` it took over, e.g. `SIP_TRUNK`).

Enums: `InboundRoute.WEBSOCKET_BOT=3`, `OutboundRoute.WEBSOCKET_BOT=3`,
`OutboundRoute.ONLY_ANSWER=4`, `Status.ACTIVE=1`, `AudioFormat.ALAW|ULAW|L16|L16_16K`.

## Rules that prevent the known failures

- **One transport, one serializer, one pipeline per connection.** Pipecat's
  `WebsocketServerTransport` accepts a single client and closes every other with code 1013 —
  on a phone line that is an answered, completely silent call. Serve with FastAPI and build
  everything inside the endpoint (`assets/pipecat_bot.py`). A shared serializer would also
  stamp caller B's audio with caller A's `stream_sid`.
- **VAD is a pipeline step in Pipecat 1.7.** Put `VADProcessor(vad_analyzer=SileroVADAnalyzer())`
  in the pipeline after `transport.input()`. Passing `vad_analyzer=` to the transport params is
  silently discarded, and the bot can never be interrupted. The serializer turns an
  interruption into VoiceLink's `clear` message.
- **Turn the idle timeout off**: `PipelineWorker(..., idle_timeout_secs=None)`. The default
  (300 s) hangs up on a caller who is on hold or silent. The socket closing is the real end.
- **Cancel the worker on `on_client_disconnected`**, and `await runner.add_workers(worker)` —
  it is a coroutine; forgetting the `await` runs no audio.
- **Outbound numbers: national number + `country_code` separately.** `919XXXXXXXXX` with no
  country code fails with `38 - Network out of order`. `place_call` strips a duplicated
  country code for you, so pass `country_code` every time.
- **The DID's outbound half must point at an active WebSocket bot** before `place_call`, or
  VoiceLink refuses to dial. `setup_outbound` does this.
- **A DID has exactly one routing rule for both directions.** The provisioner only changes the
  half you ask for and echoes the other back; don't hand-roll `vl.routing.update` without
  resending both halves, or a working SIP trunk on the other direction is silently dropped.
- **Keep the `Provisioned` result** (or the trunk id `replaced_inbound` reports) when taking a
  DID over from LiveKit/SIP, so you can hand it back with `restore_previous` /
  `restore_sip_trunk`. Restore both directions unless you mean otherwise.
- **Bots are always sent `status=ACTIVE` on update.** The list endpoint reports `status=0` for
  bots in use, and routing refuses inactive bots — never echo that value back.
- **Pick speech providers near the callers.** Each call opens its own STT/TTS connections before
  the caller hears anything; from India, Deepgram (US) took ~1.4 s to connect, Sarvam ~0.25 s.
- **Never commit** `.env`, VoiceLink passwords/tokens or provider API keys.

## Reference files

- `references/inbound.md` — step-by-step inbound provisioning, what each step does, verifying.
- `references/outbound.md` — outbound routing, `place_call`, custom parameters, webhooks.
- `references/media-protocol.md` — the wire protocol and exactly what the serializer does.
- `references/troubleshooting.md` — symptom → evidence → fix table and a pre-demo checklist.
- `assets/env.example` — every setting, copied to `.env`.
- `assets/provision.py` — VoiceLink setup: `show`, `inbound`, `outbound [--call]`, `restore`.
- `assets/pipecat_bot.py` — multi-call Pipecat server: `echo`, `repeat`, `bot` modes; uses each
  outbound call's `custom_parameters` in the agent's prompt.

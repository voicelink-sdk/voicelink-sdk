# VoiceLink WebSocket media protocol and the serializer

`VoiceLinkFrameSerializer` is the whole media integration. You normally never touch the wire
format; read this when writing a custom handler, debugging audio, or porting to another
framework (`voicelink.media` is framework-free for exactly that).

## Inbound messages (VoiceLink → your server)

```json
{"event": "start", "stream_sid": "...",
 "start": {"stream_sid": "...", "call_sid": "...", "account_sid": "123",
           "from": "91...", "to": "91...", "custom_parameters": {...},
           "media_format": {"encoding": "audio/alaw", "sample_rate": "8000"}}}
{"event": "media", "streamSid": "...", "media": {"payload": "<base64>", "track": "inbound", "chunk": 1, "timestamp": 20}}
{"event": "mark",  "mark": {"name": "..."}}
{"event": "stop",  "streamSid": "...", "stop": {"callSid": "..."}}
```

- `start` is first; no `connected` frame arrives in practice (the parser still accepts one).
- `sample_rate` arrives as a **string**. `account_sid` is the VoiceLink client id.
- Parse with `voicelink.media.events.parse_message(raw)` → `StartEvent`, `MediaEvent`,
  `MarkEvent`, `StopEvent`, `ConnectedEvent` or `UnknownEvent`. Unknown events never raise.

## Outbound messages (your server → VoiceLink)

```json
{"event": "media", "media": {"payload": "<base64>"}, "stream_sid": "...", "streamSid": "..."}
{"event": "clear", "stream_sid": "...", "streamSid": "..."}
```

Build with `build_media`, `build_clear`, `build_mark` and `to_json`. Whether VoiceLink reads
`stream_sid` or `streamSid` on outbound messages is unverified, so both are sent
(`InputParams.send_stream_sid_alias=True`, ~20 bytes/frame). `build_transfer` exists but the
transfer message is unverified on a live call — don't promise transfers.

## Audio formats

`voicelink.media.audio.resolve_spec(encoding, sample_rate)` maps the `start` frame to a spec:

| Wire encoding | Rate | Format |
|---|---|---|
| `alaw` / `pcma` | 8000 | `AudioFormat.ALAW` (what live calls actually send) |
| `ulaw` / `mulaw` / `pcmu` | 8000 | `AudioFormat.ULAW` |
| `l16` / `pcm` | 8000 | `AudioFormat.L16` |
| `l16` / `pcm` | 16000 | `AudioFormat.L16_16K` |

Anything else raises `ValueError` on purpose: guessing would feed noise to the speech
recogniser, which fails silently and convincingly.

## What the serializer does

| Situation | Behaviour |
|---|---|
| `setup(StartFrame)` | Adopts the pipeline's input sample rate (use 16000) |
| `start` frame | Records `stream_sid`, `call_sid`; resolves the format; returns no frame |
| Second `start` | Re-reads the format and resets both resamplers |
| `start` with no `media_format` | Assumes `audio/alaw` @ 8000 and logs a warning |
| `media` before `start` | Dropped with a warning |
| `media` with a track other than `inbound` | Ignored (echo of our own audio) |
| `media` | base64 → G.711/PCM → resampled PCM → `InputAudioRawFrame` |
| Corrupt JSON or payload | Logged and skipped (loses 20 ms, not the call) |
| First ~5 `media` frames | No frame yet: the stream resampler buffers ~100 ms before emitting; the first reply follows ~200 ms in. Normal - real calls send 50 frames/s |
| `stop` | `EndFrame` |
| `AudioRawFrame` out | PCM → the call's wire format and rate → base64 `media` message |
| `InterruptionFrame` | `clear` message — VoiceLink drops queued audio (barge-in) |
| Output transport message frames | Sent as JSON unless `should_ignore_frame` says otherwise |

Properties after `start`: `serializer.stream_sid`, `.call_sid`, `.audio_spec`.

Why it never raises on bad frames: Pipecat's transport catches only `ConnectionClosed` around
`deserialize`, so any other exception ends the call on a real customer.

## Using it without Pipecat's pipeline

The echo handler in `assets/pipecat_bot.py` drives the serializer by hand — `setup`, then
`deserialize` each message and `serialize` a reply. That is the smallest proof that audio flows
both ways, and a template for non-Pipecat frameworks.

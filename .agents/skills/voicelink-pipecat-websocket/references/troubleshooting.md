# Troubleshooting VoiceLink ⇄ Pipecat

From the caller's side most failures sound alike: silence, an instant hang-up, or a bot that
talks over them. Collect evidence before changing anything.

## Evidence sources

**1. The bot server log.** Every connection prints `connected` / `ended`; the serializer logs
the resolved format on `start`:
`VoiceLink call <call_sid> streaming alaw @ 8000 Hz -> pipeline @ 16000 Hz`.
No `connected` line means VoiceLink never reached the server.

**2. What the DID points at** (read-only):
```python
r = prov.find_routing(DID)
print(r.for_inbound_call, r.inbound_websocket_bot_id, r.for_outbound_call, r.outbound_websocket_bot_id)
b = prov.find_bot(BOT_NAME)
print(b.id, b.websocket_url, b.status)
```

**3. VoiceLink's record of the call** (call id from the portal CDR):
```python
d = vl.call_logs.details(CALL_ID)
print(d.get("call_status"), d.get("hangup_reason"))
```

**4. The tunnel.** ngrok's inspector (`http://127.0.0.1:4040`) shows whether the WebSocket
upgrade reached it and what status your server returned.

## Symptom → cause → fix

| Symptom | Evidence | Cause | Fix |
|---|---|---|---|
| Call answered then hangs up within ~1 s | No `connected` in the server log | Bot's **WebSocket API** toggle is on | Turn it off in the portal (the API can't) |
| Silence, no connection at all | Nothing in the server or ngrok log | Wrong/stale URL (ngrok restarted), server down, or a path on the URL | Restart server + tunnel, re-run `setup_inbound` with the new `wss://` host, no path |
| First caller fine, second caller hears silence | Second socket closed with code 1013 | Pipecat `WebsocketServerTransport` accepts one client | Serve with FastAPI, one transport per connection (`assets/pipecat_bot.py`) |
| Garbled or double-speed audio | Format line shows an unexpected rate, or none | Codec hardcoded, or a shared serializer across calls | Let the serializer read `start`; one serializer per call |
| Call ends immediately on connect with `ValueError` | `Unsupported media_format` in the log | VoiceLink sent a format not in the table | Capture the `start` frame and add the mapping in `media/audio.py` |
| Bot can't be interrupted | No `clear` messages sent | `vad_analyzer` passed to transport params (silently ignored in Pipecat 1.7) | Add `VADProcessor(vad_analyzer=SileroVADAnalyzer())` to the pipeline |
| Bot hangs up on a silent caller after 5 minutes | Worker cancelled on idle | Default `idle_timeout_secs=300` | `PipelineWorker(..., idle_timeout_secs=None)` |
| Connected, never speaks, no errors | Pipeline never started | `runner.add_workers(worker)` not awaited, or greeting not queued | `await runner.add_workers(worker)`; queue the greeting in `on_client_connected` |
| Long pause before the bot's first word | Slow STT/TTS connection per call | Provider far from callers | Use a nearby provider (Sarvam ~0.25 s vs Deepgram ~1.4 s from India) |
| Server exits at start | `…_PROVIDER is not set` / `…_API_KEY` / provider not installed | Missing config | Set the provider + key in `.env`; `pip install "pipecat-ai[<provider>]"` |
| Outbound `38 - Network out of order` | CDR hangup cause 38 | Country code inside the number and not passed separately | `customer_number` national + `country_code="91"` |
| Outbound refused by the API | Error mentions the WebSocket bot | DID's outbound half not on an active bot | Run `setup_outbound` first |
| Routing rejects the bot ("not valid, not active") | 4xx on routing | Bot inactive | Update the bot with `status=Status.ACTIVE` (the provisioner does) |
| After a Pipecat test, LiveKit outbound stops working | Routing shows outbound still on the bot | Only inbound was restored | `restore_sip_trunk(..., inbound=True, outbound=True)` or `restore_previous` |
| Outbound customer never picks up; bot never sees it | No WebSocket opened | No-answer calls never connect | Watch the webhook: `call.completed` with `call_status="NO ANSWER"` |

## Checklist before a demo

1. Bot server running (`repeat` or `bot` mode) and the tunnel/host reachable over `wss://`.
2. `find_bot(BOT_NAME)` shows the current URL; WebSocket API toggle off in the portal.
3. `find_routing(DID)` shows inbound `3` → that bot (and outbound `3` if dialling out).
4. STT/TTS (and LLM for `bot`) providers set with keys; the server started without exiting.
5. One `echo` call proves audio both ways; one real call through the agent beforehand.
6. If the DID was borrowed from LiveKit, the restore command/`Provisioned` result is saved.

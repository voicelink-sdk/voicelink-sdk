# Inbound: PSTN → VoiceLink → WebSocket bot → Pipecat

Two VoiceLink objects plus your server. `setup_inbound` creates both in one idempotent call;
the steps are shown separately so you know what each one is for.

## 0. The bot server must be up first

VoiceLink connects to the URL the moment a call arrives, so start the server and its public
tunnel before routing a number to it:

```bash
python pipecat_bot.py echo        # terminal 1 - listens on 0.0.0.0:8080
ngrok http 8080                   # terminal 2 - gives https://abc.ngrok-free.dev
```

The WebSocket URL is the tunnel host with the `wss://` scheme and **no path**
(`wss://abc.ngrok-free.dev`) — the endpoint is mounted at `/`. An ngrok address changes on
every restart; re-run provisioning with the new one (it updates the bot in place).

## 1. WebSocket bot — the address-book entry

A VoiceLink "WebSocket bot" is not a bot. It is saved configuration naming your server.

```python
bot, created = prov.ensure_bot(
    bot_name="pipecat-agent",                 # also the key used to find it again
    websocket_url="wss://abc.ngrok-free.dev",
    webhook_url=None,                         # optional https:// call-event endpoint
)
```

- Found by name (case-insensitive), so re-running updates the URL instead of duplicating.
- The update endpoint is a full replace: it needs `bot_name` and `status` every time. The
  provisioner sends both, and always `status=ACTIVE` (see SKILL.md rules).
- `audio_format` is advisory only; the real format comes from each call's `start` frame.
- In the portal, check the bot's **WebSocket API** toggle is **off**. The API cannot set it.

## 2. Routing rule — bind the DID's inbound half to the bot

```python
routing, created, previous = prov.route_inbound_to_bot(did="91XXXXXXXXXX", bot_id=bot.id)
```

- A DID has one rule for both directions. Only the inbound half is changed; the outbound half
  is echoed back untouched. A brand-new rule gets `OutboundRoute.ONLY_ANSWER`.
- `previous` is the rule as it was — keep it to undo the change.

## The one-liner (what you normally run)

```python
result = prov.setup_inbound(
    bot_name="pipecat-agent",
    websocket_url="wss://abc.ngrok-free.dev",
    did="91XXXXXXXXXX",
)
print(result.bot.id, result.bot_created, result.routing.id, result.routing_created)
if result.replaced_inbound is not None:            # e.g. InboundRoute.SIP_TRUNK (LiveKit)
    print("was on trunk", result.previous_routing.inbound_sip_trunk_id)
```

Safe to re-run. `python provision.py inbound` wraps this and prints the restore command.

## Handing the number back

```python
prov.restore_previous(result)                          # exact previous rule, both halves
# or, knowing only the trunk id:
prov.restore_sip_trunk(did="91XXXXXXXXXX", sip_trunk_id=42)   # both directions by default
```

`restore_previous` raises `ValueError` if the DID had no rule before. The bot record stays
registered either way, so switching back to Pipecat later is one call.

## Verify

```python
r = prov.find_routing("91XXXXXXXXXX")
print(r.for_inbound_call, r.inbound_websocket_bot_id)     # expect 3 and the bot id
```

Then dial the DID. Expected bot-server log for one call:
`connected` → `VoiceLink call <call_sid> streaming alaw @ 8000 Hz -> pipeline @ 16000 Hz` →
audio both ways → `ended`. Run `echo` mode first: if you hear yourself, the whole
VoiceLink ⇄ serializer path works and only the AI services remain.

# Outbound: agent → LiveKit → bridge → VoiceLink → PSTN

LiveKit cannot originate directly to VoiceLink (declined `603`), so its outbound trunk targets the
**bridge**. The bridge re-originates to VoiceLink's **termination server** with SIP digest auth.

Runnable form: `python provision_outbound.py` creates or corrects the LiveKit outbound trunk
and routes the DID's outbound half to the bridge trunk; `--call` then dispatches the agent
and dials `CALL_COUNTRY_CODE` + `CALL_TO`. Safe to re-run.

## Why outbound needs auth when inbound didn't

Inbound is IP-authenticated: VoiceLink sends *to you*, low risk. Outbound spends money on
VoiceLink's carrier, so their termination server demands the trunk's username/password —
this is the direction toll-fraud targets. Keep those credentials only in the bridge config.

VoiceLink usually has two hosts: a signalling host (answers locally, never reaches PSTN) and a
termination host (needs auth, rings real phones). Pointing the bridge at the signalling host
looks like "call answered instantly, nothing rings" — use the termination host.

## VoiceLink routing for outbound: ONLY_ANSWER, never the SIP trunk

The bridge places the call itself, over the trunk. Set the DID's outbound route to
`OutboundRoute.ONLY_ANSWER`. With it set to `SIP_TRUNK`, VoiceLink sends the *answered* call
back to the bridge as a new inbound call: LiveKit shows two calls, the real one fails with
`media-timeout`, and the callee is dropped after ~45 s while talking to the wrong agent.
Verified on a live call; `provision_outbound.py` sets ONLY_ANSWER.

## 1. LiveKit outbound trunk → bridge

```python
trunk = await prov.create_outbound_trunk(
    name="voicelink-outbound",
    address=f"{BRIDGE_HOST}:{BRIDGE_PORT}",   # no "sip:" prefix
    numbers=[DID],                            # caller ID presented
    transport=TransportType.UDP,
    codecs=[SipCodec.ALAW],
)
```

The bridge must accept LiveKit's source IPs (identify/allowlist) — see `asterisk-bridge.md`.

## 2. Dispatch the agent, then place the call

Outbound has no dispatch rule, so put the agent in the room *first* so it is there on answer.

```python
room = "outbound-1"
await prov.dispatch_agent(room_name=room, agent_name=AGENT_NAME)
part = await prov.place_call(
    sip_trunk_id=trunk.sip_trunk_id,
    call_to="91XXXXXXXXXX",          # include country code; bridge adds the tech prefix
    room_name=room,
    participant_identity="pstn-callee",
    wait_until_answered=True,
)
print(part.sip_call_id)
```

This dials a real number and spends balance — confirm with the user before running it.

## Bridge side (summary)

LiveKit → `[livekit-in]` endpoint (identified by LiveKit IP ranges) → context `from-livekit` →
`Dial(PJSIP/${EXTEN}@voicelink-out)` → `[voicelink-out]` AOR = termination host:port with
`outbound_auth`. If VoiceLink expects its tech prefix on the dialed number, add it in this
dialplan, not in the SDK call.

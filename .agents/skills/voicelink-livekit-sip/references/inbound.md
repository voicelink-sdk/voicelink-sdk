# Inbound: PSTN → VoiceLink → bridge → LiveKit → agent

Four provisioning steps plus the agent. Run them in this order.

Runnable form: `python provision_inbound.py` does steps 1-4 and is safe to re-run - it
reuses or corrects existing objects instead of duplicating them. `python check_setup.py`
verifies the result. The snippets below show what each step does.

## 1. LiveKit inbound trunk — the guest list

LiveKit's SIP endpoint is public and accepts nothing by default. The inbound trunk declares which
numbers are yours and which source IPs may send calls. Without it the bridge's INVITE is rejected.

```python
trunk = await prov.create_inbound_trunk(
    name="voicelink-inbound",
    numbers=[DID],                               # e.g. "91XXXXXXXXXX"
    allowed_addresses=[f"{BRIDGE_HOST}/32"],     # only the bridge may call in
)
# trunk.sip_trunk_id  -> "ST_..."
```

Optional: `auth_username=` / `auth_password=` (digest) — independent of the IP allowlist.
`codecs=[SipCodec.ALAW]` restricts media to PCMA.

## 2. LiveKit dispatch rule — what to do with an accepted call

Accepting a call does nothing on its own. The dispatch rule creates a fresh room per caller and
dispatches the agent into it.

```python
rule = await prov.create_dispatch_rule(
    trunk_ids=[trunk.sip_trunk_id],
    room_prefix="call-",          # rooms named call-xxxx
    agent_name=AGENT_NAME,        # MUST match the worker's agent_name
)
```

`randomize=True` (default) appends a random suffix; the SDK hides LiveKit's inverted
`no_randomness` flag.

## 3. VoiceLink SIP trunk — the next hop (points at the bridge)

VoiceLink needs to know where to deliver the call. It points at the **bridge**, not LiveKit,
because VoiceLink can only send plain UDP SIP.

```python
vl_trunk = prov.create_voicelink_trunk(       # == vl.sip_trunks.create_custom(...)
    trunk_name="livekit-bridge",
    sip_server_host=BRIDGE_HOST,
    sip_server_port=BRIDGE_PORT,              # required; must match the bridge + router forward
    transport_type=TransportType.UDP,
    audio_format=[SipCodec.ALAW],
)
```

Username/password are auto-generated when omitted (you need them later for outbound — they are
on the returned `SipTrunk` as `username` / `registration_password`).

Repointing an existing trunk instead (e.g. fixing a port):

```python
vl.sip_trunks.update(TRUNK_ID, trunk_name="livekit-bridge", status=Status.ACTIVE,
                     sip_server_host=BRIDGE_HOST, sip_server_port=BRIDGE_PORT,
                     transport_type=TransportType.UDP, audio_format=[SipCodec.ALAW])
```

The update response body may come back sparse — re-read with `vl.sip_trunks.list()` to confirm.

## 4. VoiceLink routing — bind the DID to the trunk

This is the decision VoiceLink makes when a call arrives: "this DID, inbound → this trunk".
Each DID has exactly one rule.

```python
vl.routing.create(
    did_number=DID,
    inbound=InboundRoute.SIP_TRUNK,  inbound_sip_trunk_id=vl_trunk.id,
    outbound=OutboundRoute.ONLY_ANSWER,   # NOT SIP_TRUNK - see outbound.md
)
```

If the DID already has a rule, `create` fails — find it with `vl.routing.list()` and use
`vl.routing.update(routing_id, inbound=..., outbound=..., status=Status.ACTIVE, inbound_sip_trunk_id=...)`.

## 5. Agent worker

Run `assets/livekit_agent.py` (`python livekit_agent.py dev`). It registers under `agent_name`
and LiveKit dispatches it into every `call-*` room.

## Verify

```python
for t in vl.sip_trunks.list():
    print(t.id, t.trunk_name, t.sip_server_host, t.sip_server_port, t.transport_label)
for r in vl.routing.list():
    print(r.did_number, r.for_inbound_call, r.inbound_sip_trunk_id)
print(await prov.list_inbound_trunks())
```

Then dial the DID. Expected bridge trace:
`INVITE from VoiceLink → dialplan strips prefix → Dial(...@livekit-cloud) → 180 → 200 OK`.

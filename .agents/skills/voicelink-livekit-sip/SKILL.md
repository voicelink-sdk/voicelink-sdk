---
name: voicelink-livekit-sip
description: Connect VoiceLink phone numbers to LiveKit voice agents over SIP using the VoiceLink Python SDK. Use for inbound or outbound calling, SIP trunk and dispatch provisioning, Asterisk bridge setup, and diagnosing calls that fail to reach the agent.
---

# VoiceLink ⇄ LiveKit over SIP

Connect a VoiceLink DID to a LiveKit voice agent using the `voicelink` SDK. Everything on the
VoiceLink and LiveKit side is **configuration** — no media code. The only running programs are
a small Asterisk SIP bridge and the LiveKit agent worker.

## The one fact that shapes everything

VoiceLink speaks **plain UDP SIP**. LiveKit Cloud's SIP endpoint is **TLS-only**. They cannot
talk directly:

- A VoiceLink trunk pointed straight at `*.sip.livekit.cloud` fails inbound with `CHANUNAVAIL`.
- A LiveKit outbound trunk pointed straight at VoiceLink is declined with SIP `603`.

So both directions go through a **SIP bridge** (Asterisk) that terminates UDP on one side and
TLS on the other, and strips VoiceLink's numeric tech prefix. Point VoiceLink at the bridge,
point LiveKit at the bridge — never at each other.

```
Inbound : PSTN → VoiceLink ─UDP→ [bridge] ─TLS 5061→ LiveKit (inbound trunk + dispatch rule) → agent
Outbound: agent → LiveKit ─UDP→ [bridge] ─UDP + digest auth→ VoiceLink termination → PSTN
```

If the user has no bridge yet, build it first — read `references/asterisk-bridge.md`.

## Workflow

1. **Confirm inputs.** You need: VoiceLink login (user/pass or token) + `client_id` (reseller
   accounts require it), the DID, LiveKit URL/key/secret, the bridge's public host + SIP port,
   and the agent name. Template: `assets/env.example`.
2. **Make sure the bridge exists and is reachable** (`references/asterisk-bridge.md`).
3. **Provision inbound** with the SDK — `references/inbound.md`.
4. **Run the agent worker** — `assets/livekit_agent.py`. Its `agent_name` must equal the
   dispatch rule's `agent_name`, or calls land in an empty room.
5. **Provision outbound** if needed — `references/outbound.md`.
6. **Verify** with a real call and the SDK read-backs; if it fails, go to
   `references/troubleshooting.md`. Diagnose from evidence (bridge SIP trace, VoiceLink CDR)
   rather than guessing — the failure modes look alike from the caller's side.

## SDK essentials

```python
from voicelink import BASE_URL, VoiceLinkClient
from voicelink.enums import InboundRoute, OutboundRoute, SipCodec, Status, TransportType
from voicelink.integrations.livekit import LiveKitProvisioner   # pip install "voicelink[livekit]"

vl = VoiceLinkClient.login(USER, PASS, base_url=BASE_URL, client_id=CLIENT_ID)  # sync
# or: VoiceLinkClient(token, base_url=BASE_URL, client_id=CLIENT_ID)

async with LiveKitProvisioner(livekit_url=URL, api_key=KEY, api_secret=SECRET,
                              voicelink=vl) as prov:          # async
    ...
```

Two clients because two platforms: `vl` owns the number and its routing; `prov` owns LiveKit
trunks, dispatch rules and calls. Passing `voicelink=vl` lets `prov.create_voicelink_trunk(...)`
create the VoiceLink trunk too (it forwards to `vl.sip_trunks.create_custom`).

| Call | Purpose |
|---|---|
| `await prov.create_inbound_trunk(name, numbers, allowed_addresses=, auth_username=, auth_password=, codecs=)` | LiveKit accepts the DID |
| `await prov.create_dispatch_rule(trunk_ids, room_prefix="call-", agent_name=, randomize=True)` | Call → fresh room → agent |
| `prov.create_voicelink_trunk(trunk_name, sip_server_host, sip_server_port, transport_type, audio_format)` | VoiceLink trunk → bridge |
| `vl.sip_trunks.update(id, trunk_name=, status=, sip_server_host=, sip_server_port=, ...)` | Repoint a trunk (name+status required every time) |
| `vl.routing.create(did_number=, inbound=, inbound_sip_trunk_id=, outbound=, outbound_sip_trunk_id=)` | Bind DID → trunk |
| `vl.routing.update(routing_id, inbound=, outbound=, status=, ...)` | Change an existing rule (DID is fixed) |
| `await prov.create_outbound_trunk(name, address, numbers, transport=, codecs=)` | LiveKit → bridge |
| `await prov.dispatch_agent(room_name, agent_name)` | Put agent in room before an outbound call |
| `await prov.place_call(sip_trunk_id, call_to, room_name, participant_identity, wait_until_answered=)` | Dial out |
| `await prov.list_inbound_trunks()` / `list_outbound_trunks()` / `delete_trunk(id)` | Inspect / clean up LiveKit |
| `vl.sip_trunks.list()`, `vl.routing.list()`, `vl.call_logs.details(call_id)` | Verify / diagnose |

Enums: `InboundRoute.SIP_TRUNK=2`, `OutboundRoute.SIP_TRUNK=2`, `TransportType.UDP=1/TCP=2/TLS=3`,
`SipCodec.ALAW|ULAW|G722|G729` (ALAW→PCMA on LiveKit), `Status.ACTIVE=1/INACTIVE=0`.

## Rules that prevent the known failures

- **Always set `allowed_addresses=[f"{bridge_ip}/32"]` on the LiveKit inbound trunk.** An open
  trunk (`0.0.0.0/0`, no auth) gets found by SIP scanners within hours; every junk call spins
  up a room and an agent and costs money. This happened on a real deployment.
- **Always pass `sip_server_port`** on the VoiceLink trunk. Omitting it produces a dead trunk.
  Use the port the bridge actually receives on — behind consumer NAT, 5060 is often ISP-blocked,
  so a high port such as 35060 is common. The VoiceLink trunk port, the bridge's bind port and
  the router forward must all agree.
- **Outbound goes to VoiceLink's termination server with digest auth**, not to the signalling
  host that answers inbound. The signalling host answers but never reaches the PSTN; the
  termination host needs the trunk's username/password. Ask VoiceLink which is which.
- **Dial with the country code** on outbound (e.g. `91XXXXXXXXXX`); the bridge adds VoiceLink's
  tech prefix itself.
- **Order matters:** LiveKit trunk before dispatch rule; VoiceLink trunk before routing.
- **No delete endpoints** for VoiceLink trunks or routing — deactivate via `update(status=Status.INACTIVE)`.
- **Don't trust VoiceLink `*_label` fields** — derive meaning from the enum integers.
- **Never commit** trunk passwords, LiveKit secrets, or the bridge's public IP into shared repos.

## Reference files

- `references/inbound.md` — step-by-step inbound provisioning with code and why each step exists.
- `references/outbound.md` — outbound trunk, agent dispatch, placing a call.
- `references/asterisk-bridge.md` — building the bridge (pjsip.conf, extensions.conf, rtp.conf, Docker, NAT).
- `references/troubleshooting.md` — symptom → evidence → fix table and diagnostic commands.
- `assets/env.example` — environment variables.
- `assets/livekit_agent.py` — minimal LiveKit agent worker.
- `assets/provision_inbound.py` — runnable end-to-end inbound provisioning script.

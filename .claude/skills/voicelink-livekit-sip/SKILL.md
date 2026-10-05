---
name: voicelink-livekit-sip
description: Connect a VoiceLink phone number (DID) to a LiveKit AI voice agent over SIP using the VoiceLink Python SDK — inbound (caller → VoiceLink → SIP bridge → LiveKit → agent) and outbound (agent → LiveKit → bridge → VoiceLink → PSTN). Covers LiveKitProvisioner, VoiceLink SIP trunks and call routing, the Asterisk SIP bridge, the LiveKit agent worker, and debugging CHANUNAVAIL / 603 / "out of network coverage" failures. Use this whenever someone wants to wire VoiceLink to LiveKit, set up inbound or outbound calling with a LiveKit agent, provision SIP trunks or dispatch rules through the voicelink SDK, build or fix the Asterisk bridge, or debug why VoiceLink calls don't reach their LiveKit agent — even if they only say "make my number talk to my LiveKit bot".
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

Copy every file in `assets/` (the scripts import `_common.py`) plus a filled `.env` into one
folder and run from there. Inside the voicelink-sdk repo itself, use a `livekit-demo/` folder
listed in `.git/info/exclude` so copies, `.env` and logs never reach source control. Never ask
the user to paste secrets into chat - they edit `.env`.

1. **Install** from the voicelink-sdk repo root: `pip install -e ".[livekit]"`, then
   `pip install "livekit-agents[deepgram,openai,silero]" python-dotenv` (plus
   `livekit-plugins-groq` / `livekit-plugins-sarvam` if `.env` chooses them).
2. **Fill `.env`** from `assets/env.example`: VoiceLink login + `VOICELINK_CLIENT_ID` (reseller
   accounts: the client that owns the DID), the DID, LiveKit URL/key/secret, the bridge's
   **public IPv4** + SIP port, the agent name, and the agent's STT/LLM/TTS providers + keys.
3. **Make sure the bridge exists and is reachable** (`references/asterisk-bridge.md`). It must
   forward inbound calls to this LiveKit project's SIP URI.
4. **Check current state (read-only):** `python check_setup.py`.
5. **Provision inbound:** `python provision_inbound.py` - LiveKit inbound trunk, dispatch rule,
   VoiceLink trunk and inbound routing. Safe to re-run; it reuses or corrects what exists.
6. **Run the agent worker:** `python livekit_agent.py dev`. Its `LIVEKIT_AGENT_NAME` must
   equal the dispatch rule's agent, or calls land in an empty room. Then the user calls the DID.
7. **Outbound**, if wanted: `python provision_outbound.py` (LiveKit outbound trunk + outbound
   routing), then - only after the user confirms, because it dials a real number and spends
   balance - `python provision_outbound.py --call`.
8. **If anything fails**, run `check_setup.py` again and go to `references/troubleshooting.md`.
   Diagnose from evidence (bridge SIP trace, VoiceLink CDR) rather than guessing - the failure
   modes look alike from the caller's side.

## SDK essentials

```python
from voicelink import DEFAULT_BASE_URL, UAT_BASE_URL, VoiceLinkClient   # production / UAT
from voicelink.enums import InboundRoute, OutboundRoute, SipCodec, Status, TransportType
from voicelink.integrations.livekit import LiveKitProvisioner   # pip install "voicelink[livekit]"

vl = VoiceLinkClient.login(USER, PASS, base_url=DEFAULT_BASE_URL, client_id=CLIENT_ID)  # sync
# or: VoiceLinkClient(token, base_url=UAT_BASE_URL, client_id=CLIENT_ID)

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
- **Turn the VoiceLink trunk's Peer Monitoring ON** in the portal (SIP Trunk Management ->
  edit trunk) after it is created. The API cannot set it; with it off, VoiceLink marks the
  trunk unreachable and inbound calls fail with "out of network coverage" (`CHANUNAVAIL`).
  Remind the user every time `provision_inbound.py` creates a trunk.
- **Always pass `sip_server_port`** on the VoiceLink trunk. Omitting it produces a dead trunk.
  Use the port the bridge actually receives on — behind consumer NAT, 5060 is often ISP-blocked,
  so a high port such as 35060 is common. The VoiceLink trunk port, the bridge's bind port and
  the router forward must all agree.
- **Outbound goes to VoiceLink's termination server with digest auth**, not to the signalling
  host that answers inbound. The signalling host answers but never reaches the PSTN; the
  termination host needs the trunk's username/password. Ask VoiceLink which is which.
- **Dial with the country code** on outbound (e.g. `91XXXXXXXXXX`); the bridge adds VoiceLink's
  tech prefix itself.
- **Outbound route = `ONLY_ANSWER`, never `SIP_TRUNK`.** The bridge originates over the trunk;
  a `SIP_TRUNK` outbound route bounces every answered call back to the bridge as a second call
  that drops after ~45 s. Inbound stays `SIP_TRUNK`.
- **Run one agent worker per `LIVEKIT_AGENT_NAME`.** LiveKit hands each call to any worker with
  that name, so a forgotten copy elsewhere silently takes calls.
- **Order matters:** LiveKit trunk before dispatch rule; VoiceLink trunk before routing.
- **No delete endpoints** for VoiceLink trunks or routing — deactivate via `update(status=Status.INACTIVE)`.
- **Don't trust VoiceLink `*_label` fields** — derive meaning from the enum integers.
- **Never commit** trunk passwords, LiveKit secrets, or the bridge's public IP into shared repos.

## Reference files

- `references/inbound.md` — step-by-step inbound provisioning with code and why each step exists.
- `references/outbound.md` — outbound trunk, agent dispatch, placing a call.
- `references/asterisk-bridge.md` — building the bridge (pjsip.conf, extensions.conf, rtp.conf, Docker, NAT).
- `references/troubleshooting.md` — symptom → evidence → fix table and diagnostic commands.
- `assets/env.example` — every setting, copied to `.env`.
- `assets/check_setup.py` — read-only check of both platforms; flags known misconfigurations.
- `assets/provision_inbound.py` — inbound: LiveKit inbound trunk + dispatch rule, VoiceLink
  trunk + inbound routing. Re-runnable.
- `assets/provision_outbound.py` — outbound: LiveKit outbound trunk + outbound routing;
  `--call` places a test call. Re-runnable.
- `assets/livekit_agent.py` — agent worker; STT/LLM/TTS providers chosen in `.env`.
- `assets/_common.py` — shared helpers the scripts import; keep it next to them.

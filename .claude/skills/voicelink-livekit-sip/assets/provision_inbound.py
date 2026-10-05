"""Provision the inbound path: PSTN -> VoiceLink -> SIP bridge -> LiveKit -> agent.

    pip install -e ".[livekit]"          # from the voicelink-sdk repo root
    python provision_inbound.py

Reads `.env` in the current directory (see env.example). Safe to re-run: every object is
looked up first and reused or corrected, never duplicated:

    1. LiveKit inbound trunk  - accepts the DID, only from the bridge's IP
    2. LiveKit dispatch rule  - each call gets a fresh room with the agent in it
    3. VoiceLink SIP trunk    - VoiceLink's next hop: the bridge (reused if one exists)
    4. VoiceLink routing      - the DID's inbound calls go to that trunk

The outbound half of the DID's routing is left as it is; run provision_outbound.py for it.
"""

from __future__ import annotations

from _common import (
    INBOUND_TRUNK_NAME, agent_name, bridge, did, ensure_voicelink_trunk,
    livekit_provisioner, require_livekit_settings, trunk_credentials, route_to_trunk, run, voicelink_client,
)
from voicelink.enums import SipCodec


async def ensure_inbound_trunk(prov, number: str, allow: str):
    from livekit import api as lk

    for trunk in await prov.list_inbound_trunks():
        if trunk.name == INBOUND_TRUNK_NAME:
            missing_number = number not in trunk.numbers
            missing_ip = allow not in trunk.allowed_addresses
            if missing_number or missing_ip:
                await prov._api.sip.update_inbound_trunk_fields(
                    trunk.sip_trunk_id,
                    numbers=lk.ListUpdate(add=[number]) if missing_number else None,
                    allowed_addresses=lk.ListUpdate(add=[allow]) if missing_ip else None,
                )
                print(f"LiveKit inbound  : updated {trunk.sip_trunk_id} (added "
                      f"{'DID ' if missing_number else ''}{'bridge IP' if missing_ip else ''})")
            else:
                print(f"LiveKit inbound  : reusing {trunk.sip_trunk_id}")
            return trunk.sip_trunk_id
    trunk = await prov.create_inbound_trunk(
        name=INBOUND_TRUNK_NAME,
        numbers=[number],
        allowed_addresses=[allow],  # only the bridge may call in - never 0.0.0.0/0
        codecs=[SipCodec.ALAW],
    )
    print(f"LiveKit inbound  : created {trunk.sip_trunk_id}")
    return trunk.sip_trunk_id


async def ensure_dispatch_rule(prov, trunk_id: str, agent: str) -> None:
    from livekit import api as lk

    rules = await prov._api.sip.list_dispatch_rule(lk.ListSIPDispatchRuleRequest())
    for rule in rules.items:
        if trunk_id in rule.trunk_ids:
            agents = [a.agent_name for a in rule.room_config.agents]
            if agent in agents:
                print(f"LiveKit dispatch : reusing {rule.sip_dispatch_rule_id} -> agent {agent!r}")
            else:
                print(f"LiveKit dispatch : WARNING rule {rule.sip_dispatch_rule_id} dispatches "
                      f"{agents or 'no agent'}, not {agent!r}. Calls will reach the wrong agent "
                      "or an empty room - fix LIVEKIT_AGENT_NAME or edit the rule in the dashboard.")
            return
    rule = await prov.create_dispatch_rule(trunk_ids=[trunk_id], room_prefix="call-", agent_name=agent)
    print(f"LiveKit dispatch : created {rule.sip_dispatch_rule_id} -> agent {agent!r}")


async def main() -> None:
    number, (host, port), agent = did(), bridge(), agent_name()
    require_livekit_settings()
    trunk_credentials()  # validate before any network call
    vl = voicelink_client()
    try:
        async with livekit_provisioner(vl) as prov:
            trunk_id = await ensure_inbound_trunk(prov, number, f"{host}/32")
            await ensure_dispatch_rule(prov, trunk_id, agent)
            vl_trunk = ensure_voicelink_trunk(vl, host, port)
            route_to_trunk(vl, number, vl_trunk.id, inbound=True, outbound=False)
    finally:
        vl.close()
    print(f"\nDone. Start the agent worker (python livekit_agent.py dev), then call {number}.")
    print("The bridge must forward the call to your LiveKit SIP URI - see references/asterisk-bridge.md.")


if __name__ == "__main__":
    run(main)

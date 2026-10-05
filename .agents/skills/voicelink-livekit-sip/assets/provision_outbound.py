"""Provision the outbound path and optionally place one test call.

    python provision_outbound.py          # configure only - dials nobody
    python provision_outbound.py --call   # ...then dial CALL_TO (spends balance)

Outbound: agent -> LiveKit -> SIP bridge -> VoiceLink termination -> PSTN. Safe to re-run:

    1. LiveKit outbound trunk - LiveKit sends calls to the bridge (reused or corrected)
    2. VoiceLink SIP trunk    - the same bridge trunk inbound uses (reused if one exists)
    3. VoiceLink routing      - the DID's outbound half set to ONLY_ANSWER (not the trunk:
                                that bounces answered calls back as a second call)

The bridge itself must hold VoiceLink's termination host and the trunk's digest
credentials - see references/outbound.md and references/asterisk-bridge.md.
"""

from __future__ import annotations

import os
import sys
import time

from _common import (
    OUTBOUND_TRUNK_NAME, agent_name, bridge, did, digits, ensure_voicelink_trunk,
    livekit_provisioner, require_livekit_settings, trunk_credentials, need, route_to_trunk, run, voicelink_client,
)
from voicelink.enums import SipCodec, TransportType


async def ensure_outbound_trunk(prov, number: str, address: str) -> str:
    from voicelink.integrations.livekit.provisioning import map_transport

    for trunk in await prov.list_outbound_trunks():
        if trunk.name == OUTBOUND_TRUNK_NAME:
            if trunk.address != address or number not in trunk.numbers:
                await prov._api.sip.update_outbound_trunk_fields(
                    trunk.sip_trunk_id, address=address,
                    transport=map_transport(TransportType.UDP), numbers=[number],
                )
                print(f"LiveKit outbound : updated {trunk.sip_trunk_id} -> {address}")
            else:
                print(f"LiveKit outbound : reusing {trunk.sip_trunk_id} -> {address}")
            return trunk.sip_trunk_id
    trunk = await prov.create_outbound_trunk(
        name=OUTBOUND_TRUNK_NAME, address=address, numbers=[number],
        transport=TransportType.UDP, codecs=[SipCodec.ALAW],
    )
    print(f"LiveKit outbound : created {trunk.sip_trunk_id} -> {address}")
    return trunk.sip_trunk_id


def dial_string() -> str:
    """Country code + national number; the bridge adds VoiceLink's tech prefix itself."""
    national = digits(need("CALL_TO"))
    country = digits(os.environ.get("CALL_COUNTRY_CODE", "") or "91")
    if national.startswith(country) and len(national) > 10:
        national = national[len(country):]
    if len(national) < 6:
        sys.exit(f"CALL_TO looks too short: {national!r}. Use the national number, e.g. 9XXXXXXXXX.")
    return country + national


async def main() -> None:
    place = "--call" in sys.argv[1:]
    number, (host, port), agent = did(), bridge(), agent_name()
    require_livekit_settings()
    trunk_credentials()  # validate before any network call
    to = dial_string() if place else None  # validate before changing anything
    vl = voicelink_client()
    try:
        async with livekit_provisioner(vl) as prov:
            trunk_id = await ensure_outbound_trunk(prov, number, f"{host}:{port}")
            vl_trunk = ensure_voicelink_trunk(vl, host, port)
            route_to_trunk(vl, number, vl_trunk.id, inbound=False, outbound=True)
            if not place:
                print("\nOutbound configured. Nothing was dialled; add --call to place a test call.")
                return
            room = f"outbound-{int(time.time())}"
            # Outbound has no dispatch rule: put the agent in the room before dialling.
            await prov.dispatch_agent(room_name=room, agent_name=agent)
            print(f"\nAgent {agent!r} dispatched to room {room}. Dialling {to} (spends balance) ...")
            part = await prov.place_call(
                sip_trunk_id=trunk_id, call_to=to, room_name=room,
                participant_identity="pstn-callee", wait_until_answered=True,
            )
            print(f"Answered - SIP call id {part.sip_call_id}. The agent worker must be running.")
    finally:
        vl.close()


if __name__ == "__main__":
    run(main)

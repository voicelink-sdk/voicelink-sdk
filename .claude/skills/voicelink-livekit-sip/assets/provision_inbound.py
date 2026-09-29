"""Provision the full inbound path: PSTN -> VoiceLink -> SIP bridge -> LiveKit -> agent.

    pip install "voicelink[livekit]"
    python provision_inbound.py

Reads the variables in env.example from the environment. Creates new objects each run —
if the DID already has a routing rule, update it with vl.routing.update(...) instead.
"""

import asyncio
import os

from voicelink import BASE_URL, VoiceLinkClient
from voicelink.enums import InboundRoute, OutboundRoute, SipCodec, TransportType
from voicelink.integrations.livekit import LiveKitProvisioner


def voicelink_client() -> VoiceLinkClient:
    base = os.environ.get("VOICELINK_BASE_URL", BASE_URL)
    cid = os.environ.get("VOICELINK_CLIENT_ID")
    cid = int(cid) if cid else None
    if token := os.environ.get("VOICELINK_TOKEN"):
        return VoiceLinkClient(token, base_url=base, client_id=cid)
    return VoiceLinkClient.login(
        os.environ["VOICELINK_USER"], os.environ["VOICELINK_PASS"], base_url=base, client_id=cid
    )


async def main() -> None:
    did = os.environ["VOICELINK_DID"]
    agent = os.environ.get("LIVEKIT_AGENT_NAME", "voice-assistant")
    bridge_host = os.environ["VOICELINK_BRIDGE_HOST"]
    bridge_port = int(os.environ.get("VOICELINK_BRIDGE_PORT", "5060"))

    vl = voicelink_client()
    try:
        async with LiveKitProvisioner(
            livekit_url=os.environ["LIVEKIT_URL"],
            api_key=os.environ["LIVEKIT_API_KEY"],
            api_secret=os.environ["LIVEKIT_API_SECRET"],
            voicelink=vl,
        ) as prov:
            trunk = await prov.create_inbound_trunk(
                name="voicelink-inbound",
                numbers=[did],
                allowed_addresses=[f"{bridge_host}/32"],  # never 0.0.0.0/0
            )
            print("LiveKit inbound trunk:", trunk.sip_trunk_id)

            rule = await prov.create_dispatch_rule(
                trunk_ids=[trunk.sip_trunk_id], room_prefix="call-", agent_name=agent
            )
            print("LiveKit dispatch rule:", rule.sip_dispatch_rule_id)

            vl_trunk = prov.create_voicelink_trunk(
                trunk_name="livekit-bridge",
                sip_server_host=bridge_host,
                sip_server_port=bridge_port,
                transport_type=TransportType.UDP,
                audio_format=[SipCodec.ALAW],
            )
            print("VoiceLink trunk:", vl_trunk.id)

            vl.routing.create(
                did_number=did,
                inbound=InboundRoute.SIP_TRUNK,
                inbound_sip_trunk_id=vl_trunk.id,
                outbound=OutboundRoute.SIP_TRUNK,
                outbound_sip_trunk_id=vl_trunk.id,
            )
            print(f"Routing: {did} -> trunk {vl_trunk.id}")
    finally:
        vl.close()
    print(f"\nDone. Start the agent worker, then call {did}.")


if __name__ == "__main__":
    asyncio.run(main())

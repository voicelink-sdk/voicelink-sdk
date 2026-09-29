"""Connect a VoiceLink number to a LiveKit voice agent — end to end.

This is the full recipe, both directions, through the VoiceLink SDK. It mirrors the
manual steps other providers document, but as a few SDK calls instead of hand-written
LiveKit requests.

It runs REAL provisioning when credentials are supplied, so treat it as a live setup /
smoke-test script. Set these environment variables first:

    # VoiceLink
    VOICELINK_TOKEN         a VoiceLink API token   (or use VOICELINK_USER/PASS)
    VOICELINK_CLIENT_ID     client id for reseller accounts
    VOICELINK_DID           the phone number, e.g. 919484950416

    # LiveKit
    LIVEKIT_URL             wss://<your>.livekit.cloud
    LIVEKIT_API_KEY
    LIVEKIT_API_SECRET
    LIVEKIT_SIP_URI         your project SIP URI, e.g. abc123.sip.livekit.cloud  (no "sip:")
    LIVEKIT_AGENT_NAME      the agent to dispatch, e.g. voice-assistant

    # SIP bridge (Asterisk) that terminates plain SIP and re-originates to LiveKit/VoiceLink.
    # Used by BOTH directions: VoiceLink dials it inbound; LiveKit dials it outbound.
    VOICELINK_BRIDGE_HOST   your bridge IP/host, e.g. sip-bridge.example.com
    VOICELINK_BRIDGE_PORT   bridge SIP port, e.g. 35060

    # Real number to ring for the outbound smoke-test (optional; E.164/local digits)
    CALL_TO                 e.g. 9198xxxxxxxx

Run:
    python examples/livekit_quickstart.py inbound     # PSTN -> VoiceLink -> LiveKit agent
    python examples/livekit_quickstart.py outbound    # LiveKit agent -> VoiceLink -> PSTN
"""

import asyncio
import os
import sys

from voicelink import UAT_BASE_URL, VoiceLinkClient
from voicelink.enums import InboundRoute, OutboundRoute, SipCodec, TransportType
from voicelink.integrations.livekit import LiveKitProvisioner


def _voicelink_client() -> VoiceLinkClient:
    token = os.environ.get("VOICELINK_TOKEN")
    client_id = os.environ.get("VOICELINK_CLIENT_ID")
    client_id = int(client_id) if client_id else None
    base = os.environ.get("VOICELINK_BASE_URL", UAT_BASE_URL)
    if token:
        return VoiceLinkClient(token, base_url=base, client_id=client_id)
    user = os.environ["VOICELINK_USER"]
    pwd = os.environ["VOICELINK_PASS"]
    return VoiceLinkClient.login(user, pwd, base_url=base, client_id=client_id)


def _provisioner(voicelink: VoiceLinkClient) -> LiveKitProvisioner:
    return LiveKitProvisioner(
        livekit_url=os.environ["LIVEKIT_URL"],
        api_key=os.environ["LIVEKIT_API_KEY"],
        api_secret=os.environ["LIVEKIT_API_SECRET"],
        voicelink=voicelink,
    )


async def setup_inbound() -> None:
    """PSTN -> VoiceLink -> LiveKit agent.

    1. Create a LiveKit inbound trunk that accepts the DID.
    2. Create a dispatch rule that puts each call in a room and dispatches the agent.
    3. On VoiceLink: create a SIP trunk pointing at your SIP BRIDGE and route the DID
       inbound to it.

    IMPORTANT: VoiceLink speaks PLAIN SIP and cannot reach LiveKit Cloud's TLS-only SIP
    endpoint directly (a direct trunk fails with hangup cause CHANUNAVAIL). Point the
    VoiceLink trunk at a SIP bridge (e.g. Asterisk) that terminates VoiceLink's plain SIP
    and re-originates to LiveKit Cloud over TLS. Provide the bridge address via
    VOICELINK_BRIDGE_HOST / VOICELINK_BRIDGE_PORT. (If/when VoiceLink supports outbound
    TLS SIP, you can instead point straight at LIVEKIT_SIP_URI over TLS.)
    """
    did = os.environ["VOICELINK_DID"]
    agent = os.environ.get("LIVEKIT_AGENT_NAME", "voice-assistant")
    bridge_host = os.environ["VOICELINK_BRIDGE_HOST"]   # your SIP bridge (Asterisk) IP/host
    bridge_port = int(os.environ.get("VOICELINK_BRIDGE_PORT", "5060"))

    voicelink = _voicelink_client()
    async with _provisioner(voicelink) as prov:
        print("[LiveKit] creating inbound trunk ...")
        trunk = await prov.create_inbound_trunk(
            name="voicelink-inbound",
            numbers=[did],
            # SECURITY — restrict to YOUR bridge's IP. NEVER use 0.0.0.0/0: an open,
            # auth-less trunk is a SIP-fraud magnet. Scanners find LiveKit's public SIP
            # endpoint and flood the trunk with junk calls, each spinning up a room + an
            # agent that costs you money. Locking to the bridge /32 rejects all of them.
            allowed_addresses=[f"{bridge_host}/32"],
        )
        print("  trunk id:", trunk.sip_trunk_id)

        print("[LiveKit] creating dispatch rule ...")
        rule = await prov.create_dispatch_rule(
            trunk_ids=[trunk.sip_trunk_id],
            room_prefix="call-",
            agent_name=agent,
        )
        print("  rule id:", rule.sip_dispatch_rule_id)

        print("[VoiceLink] creating SIP trunk -> bridge ...")
        vl_trunk = prov.create_voicelink_trunk(
            trunk_name="livekit-inbound",
            sip_server_host=bridge_host,
            sip_server_port=bridge_port,          # must be set — omitting it yields a dead trunk
            transport_type=TransportType.UDP,     # plain SIP to the bridge (not TLS)
            audio_format=[SipCodec.ALAW],
        )
        print("  voicelink trunk id:", vl_trunk.id)

        print("[VoiceLink] routing DID inbound -> that trunk ...")
        voicelink.routing.create(
            did_number=did,
            inbound=InboundRoute.SIP_TRUNK,
            inbound_sip_trunk_id=vl_trunk.id,
            outbound=OutboundRoute.SIP_TRUNK,
            outbound_sip_trunk_id=vl_trunk.id,
        )
    voicelink.close()
    print("\nInbound setup complete. Call the DID to reach the agent.")


async def setup_outbound() -> None:
    """LiveKit agent -> VoiceLink -> PSTN, then place a test call.

    Same bridge topology as inbound, reversed: LiveKit originates to the SIP BRIDGE, which
    re-originates to VoiceLink from its whitelisted IP; VoiceLink terminates to the PSTN.
    LiveKit Cloud cannot originate straight to VoiceLink (a direct trunk is declined with
    SIP 603) — so the outbound trunk's address is the BRIDGE, not app.voicelink.co.in.

    VoiceLink applies its tech prefix per trunk; the bridge dialplan adds it before
    forwarding, so nothing here needs to.
    """
    did = os.environ["VOICELINK_DID"]
    agent = os.environ.get("LIVEKIT_AGENT_NAME", "voice-assistant")
    bridge_host = os.environ["VOICELINK_BRIDGE_HOST"]   # your SIP bridge (Asterisk) IP/host
    bridge_port = int(os.environ.get("VOICELINK_BRIDGE_PORT", "5060"))
    to_number = os.environ.get("CALL_TO")

    voicelink = _voicelink_client()
    async with _provisioner(voicelink) as prov:
        print("[LiveKit] creating outbound trunk -> bridge ...")
        trunk = await prov.create_outbound_trunk(
            name="voicelink-outbound",
            address=f"{bridge_host}:{bridge_port}",
            numbers=[did],                       # caller ID presented to VoiceLink
            transport=TransportType.UDP,         # plain SIP to the bridge (not TLS)
            codecs=[SipCodec.ALAW],
        )
        print("  trunk id:", trunk.sip_trunk_id)

        if to_number:
            room = "outbound-test"
            print(f"[LiveKit] dispatching agent {agent!r} into {room!r} ...")
            await prov.dispatch_agent(room_name=room, agent_name=agent)

            print(f"[LiveKit] placing test call to {to_number} ...")
            part = await prov.place_call(
                sip_trunk_id=trunk.sip_trunk_id,
                call_to=to_number,
                room_name=room,
                participant_identity="pstn-callee",
                wait_until_answered=True,
            )
            print("  participant:", part.participant_identity, "| sip_call_id:", part.sip_call_id)
    voicelink.close()
    print("\nOutbound setup complete.")


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "inbound"
    if mode == "inbound":
        asyncio.run(setup_inbound())
    elif mode == "outbound":
        asyncio.run(setup_outbound())
    else:
        print("usage: python examples/livekit_quickstart.py [inbound|outbound]")
        sys.exit(1)


if __name__ == "__main__":
    main()

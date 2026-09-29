"""LiveKit provisioning builders — verified against the real livekit.api proto types.

Skipped entirely if the optional ``livekit`` extra is not installed.
"""

import pytest

pytest.importorskip("livekit.api")

from voicelink.enums import SipCodec, TransportType  # noqa: E402
from voicelink.integrations.livekit import (  # noqa: E402
    build_agent_dispatch_request,
    build_dispatch_rule_request,
    build_inbound_trunk_request,
    build_outbound_trunk_request,
    build_sip_participant_request,
    map_codec,
    map_transport,
)


def test_codec_mapping():
    assert map_codec(SipCodec.ALAW).name == "PCMA"
    assert map_codec(SipCodec.ULAW).name == "PCMU"
    assert map_codec("g722").name == "G722"
    assert map_codec(SipCodec.ALAW).rate == 8000


def test_transport_mapping():
    from livekit import api as lk

    assert map_transport(TransportType.UDP) == lk.SIPTransport.SIP_TRANSPORT_UDP
    assert map_transport(TransportType.TLS) == lk.SIPTransport.SIP_TRANSPORT_TLS
    assert map_transport(2) == lk.SIPTransport.SIP_TRANSPORT_TCP


def test_inbound_trunk_request_fields():
    req = build_inbound_trunk_request(
        name="voicelink-in",
        numbers=["919484950416"],
        allowed_addresses=["1.2.3.4/32"],
        auth_username="u",
        auth_password="p",
        codecs=[SipCodec.ALAW],
        krisp_enabled=True,
    )
    trunk = req.trunk
    assert trunk.name == "voicelink-in"
    assert list(trunk.numbers) == ["919484950416"]
    assert list(trunk.allowed_addresses) == ["1.2.3.4/32"]
    assert trunk.auth_username == "u"
    assert trunk.auth_password == "p"
    assert trunk.krisp_enabled is True
    assert trunk.media.only_listed_codecs is True
    assert [c.name for c in trunk.media.codecs] == ["PCMA"]


def test_inbound_trunk_without_media_when_no_codecs():
    req = build_inbound_trunk_request(name="in", numbers=["1"])
    # No codecs -> media left at default (no listed codecs pinned).
    assert req.trunk.media.only_listed_codecs is False


def test_outbound_trunk_request_fields():
    req = build_outbound_trunk_request(
        name="voicelink-out",
        address="app.voicelink.co.in:3300",
        transport=TransportType.TCP,
        numbers=["919484950416"],
        auth_username="u",
        auth_password="p",
        codecs=[SipCodec.ALAW, SipCodec.ULAW],
    )
    from livekit import api as lk

    trunk = req.trunk
    assert trunk.address == "app.voicelink.co.in:3300"
    assert trunk.transport == lk.SIPTransport.SIP_TRANSPORT_TCP
    assert [c.name for c in trunk.media.codecs] == ["PCMA", "PCMU"]


def test_outbound_trunk_transport_defaults_to_auto():
    # Omitting transport must yield AUTO, not error (matches real-world usage).
    from livekit import api as lk

    req = build_outbound_trunk_request(
        name="out", address="app.voicelink.co.in:3300", numbers=["919484950416"]
    )
    assert req.trunk.transport == lk.SIPTransport.SIP_TRANSPORT_AUTO


def test_dispatch_rule_normalizes_randomize():
    # randomize=True must map to no_randomness=False (LiveKit's inverted flag).
    req = build_dispatch_rule_request(trunk_ids=["ST_1"], randomize=True, room_prefix="call-")
    assert req.dispatch_rule.rule.dispatch_rule_individual.no_randomness is False
    assert req.dispatch_rule.rule.dispatch_rule_individual.room_prefix == "call-"

    req2 = build_dispatch_rule_request(trunk_ids=["ST_1"], randomize=False)
    assert req2.dispatch_rule.rule.dispatch_rule_individual.no_randomness is True


def test_dispatch_rule_attaches_agent():
    req = build_dispatch_rule_request(trunk_ids=["ST_1"], agent_name="support")
    agents = req.dispatch_rule.room_config.agents
    assert len(agents) == 1
    assert agents[0].agent_name == "support"


def test_dispatch_rule_trunk_ids():
    req = build_dispatch_rule_request(trunk_ids=["ST_1", "ST_2"])
    assert list(req.dispatch_rule.trunk_ids) == ["ST_1", "ST_2"]


def test_agent_dispatch_request_fields():
    req = build_agent_dispatch_request(
        room_name="outbound-test", agent_name="voice-assistant", metadata='{"k":1}'
    )
    assert req.room == "outbound-test"
    assert req.agent_name == "voice-assistant"
    assert req.metadata == '{"k":1}'


def test_agent_dispatch_request_omits_metadata_when_none():
    req = build_agent_dispatch_request(room_name="r", agent_name="a")
    assert req.metadata == ""  # proto default when not set


def test_sip_participant_request_fields():
    req = build_sip_participant_request(
        sip_trunk_id="ST_out",
        call_to="919812345678",
        room_name="room-1",
        participant_identity="caller",
        participant_name="Caller",
        wait_until_answered=True,
    )
    assert req.sip_trunk_id == "ST_out"
    assert req.sip_call_to == "919812345678"
    assert req.room_name == "room-1"
    assert req.participant_identity == "caller"
    assert req.participant_name == "Caller"
    assert req.wait_until_answered is True


# --- LiveKitProvisioner (mocked — no network) -------------------------------


def _fake_api():
    """A stand-in LiveKitAPI whose .sip methods are awaitable mocks."""
    import unittest.mock as m

    api = m.MagicMock()
    api.sip.create_inbound_trunk = m.AsyncMock(return_value="INBOUND_INFO")
    api.sip.create_outbound_trunk = m.AsyncMock(return_value="OUTBOUND_INFO")
    api.sip.create_dispatch_rule = m.AsyncMock(return_value="RULE_INFO")
    api.sip.create_sip_participant = m.AsyncMock(return_value="PARTICIPANT_INFO")
    api.agent_dispatch.create_dispatch = m.AsyncMock(return_value="DISPATCH_INFO")
    api.sip.delete_trunk = m.AsyncMock(return_value="DELETED")
    inbound_resp = m.MagicMock()
    inbound_resp.items = ["TRUNK_A", "TRUNK_B"]
    api.sip.list_inbound_trunk = m.AsyncMock(return_value=inbound_resp)
    api.aclose = m.AsyncMock()
    return api


def test_provisioner_create_inbound_trunk_builds_and_calls():
    import asyncio
    import unittest.mock as m

    from livekit import api as lk

    from voicelink.integrations.livekit import LiveKitProvisioner

    fake = _fake_api()
    with m.patch(
        "voicelink.integrations.livekit.provisioning.lk.LiveKitAPI", return_value=fake
    ):
        async def run():
            prov = LiveKitProvisioner(livekit_url="wss://x", api_key="k", api_secret="s")
            result = await prov.create_inbound_trunk(name="in", numbers=["919484950416"])
            await prov.aclose()
            return result

        result = asyncio.run(run())

    assert result == "INBOUND_INFO"
    fake.sip.create_inbound_trunk.assert_awaited_once()
    sent = fake.sip.create_inbound_trunk.await_args.args[0]
    assert isinstance(sent, lk.CreateSIPInboundTrunkRequest)
    assert list(sent.trunk.numbers) == ["919484950416"]
    fake.aclose.assert_awaited_once()


def test_provisioner_place_call_builds_participant_request():
    import asyncio
    import unittest.mock as m

    from livekit import api as lk

    from voicelink.integrations.livekit import LiveKitProvisioner

    fake = _fake_api()
    with m.patch(
        "voicelink.integrations.livekit.provisioning.lk.LiveKitAPI", return_value=fake
    ):
        async def run():
            prov = LiveKitProvisioner(livekit_url="wss://x", api_key="k", api_secret="s")
            return await prov.place_call(
                sip_trunk_id="ST_1",
                call_to="919812345678",
                room_name="room-1",
                participant_identity="caller",
            )

        result = asyncio.run(run())

    assert result == "PARTICIPANT_INFO"
    sent = fake.sip.create_sip_participant.await_args.args[0]
    assert isinstance(sent, lk.CreateSIPParticipantRequest)
    assert sent.sip_call_to == "919812345678"


def test_provisioner_dispatch_agent_builds_request():
    import asyncio
    import unittest.mock as m

    from livekit import api as lk

    from voicelink.integrations.livekit import LiveKitProvisioner

    fake = _fake_api()
    with m.patch(
        "voicelink.integrations.livekit.provisioning.lk.LiveKitAPI", return_value=fake
    ):
        async def run():
            prov = LiveKitProvisioner(livekit_url="wss://x", api_key="k", api_secret="s")
            return await prov.dispatch_agent(
                room_name="outbound-test", agent_name="voice-assistant"
            )

        result = asyncio.run(run())

    assert result == "DISPATCH_INFO"
    sent = fake.agent_dispatch.create_dispatch.await_args.args[0]
    assert isinstance(sent, lk.CreateAgentDispatchRequest)
    assert sent.room == "outbound-test"
    assert sent.agent_name == "voice-assistant"


def test_provisioner_list_and_delete():
    import asyncio
    import unittest.mock as m

    from livekit import api as lk

    from voicelink.integrations.livekit import LiveKitProvisioner

    fake = _fake_api()
    with m.patch(
        "voicelink.integrations.livekit.provisioning.lk.LiveKitAPI", return_value=fake
    ):
        async def run():
            prov = LiveKitProvisioner(livekit_url="wss://x", api_key="k", api_secret="s")
            trunks = await prov.list_inbound_trunks()
            deleted = await prov.delete_trunk("ST_1")
            return trunks, deleted

        trunks, deleted = asyncio.run(run())

    assert trunks == ["TRUNK_A", "TRUNK_B"]
    assert deleted == "DELETED"
    sent = fake.sip.delete_trunk.await_args.args[0]
    assert isinstance(sent, lk.DeleteSIPTrunkRequest)
    assert sent.sip_trunk_id == "ST_1"


def test_provisioner_voicelink_trunk_requires_client():
    import unittest.mock as m

    from voicelink.integrations.livekit import LiveKitProvisioner

    with m.patch(
        "voicelink.integrations.livekit.provisioning.lk.LiveKitAPI", return_value=_fake_api()
    ):
        prov = LiveKitProvisioner(livekit_url="wss://x", api_key="k", api_secret="s")
        with pytest.raises(ValueError):
            prov.create_voicelink_trunk(trunk_name="t")

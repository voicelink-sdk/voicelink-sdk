"""Resource behavior: correct request bodies, enum encoding, and response parsing."""

import json

import httpx
import pytest
import respx

from voicelink import VoiceLinkClient
from voicelink.enums import (
    AudioFormat,
    InboundRoute,
    OutboundRoute,
    SipCodec,
    Status,
    TransportType,
)

BASE = "https://api.test/api"


def _client() -> VoiceLinkClient:
    return VoiceLinkClient("tok", base_url=BASE, client_id=123, max_retries=0)


def test_client_requires_token():
    with pytest.raises(ValueError):
        VoiceLinkClient("")


@respx.mock
def test_create_bot_defaults_to_l16_16k_and_wraps_result():
    route = respx.post(f"{BASE}/v1/websocket-bot/create").mock(
        return_value=httpx.Response(201, json={"status": True, "data": {"id": 34}})
    )
    with _client() as client:
        bot = client.websocket_bots.create(
            bot_name="Support", websocket_url="wss://x/ws"
        )
    body = json.loads(route.calls.last.request.content)
    assert body["audio_format"] == "l16_16k"       # default we recommend
    assert body["status"] == 1                       # Status.ACTIVE
    assert body["client_id"] == 123                  # from client default
    assert bot.id == 34


@respx.mock
def test_create_bot_explicit_format_and_client_override():
    route = respx.post(f"{BASE}/v1/websocket-bot/create").mock(
        return_value=httpx.Response(201, json={"status": True, "data": {"id": 1}})
    )
    with _client() as client:
        client.websocket_bots.create(
            bot_name="B",
            websocket_url="wss://x",
            audio_format=AudioFormat.ALAW,
            status=Status.INACTIVE,
            client_id=999,
        )
    body = json.loads(route.calls.last.request.content)
    assert body["audio_format"] == "alaw"
    assert body["status"] == 0
    assert body["client_id"] == 999


@respx.mock
def test_routing_encodes_enums():
    route = respx.post(f"{BASE}/v1/call-routing/create").mock(
        return_value=httpx.Response(201, json={"status": True, "data": {"id": 140}})
    )
    with _client() as client:
        routing = client.routing.create(
            did_number="919484950416",
            inbound=InboundRoute.WEBSOCKET_BOT,
            inbound_websocket_bot_id=34,
            outbound=OutboundRoute.WEBSOCKET_BOT,
            outbound_websocket_bot_id=34,
        )
    body = json.loads(route.calls.last.request.content)
    assert body["for_inbound_call"] == 3
    assert body["for_outbound_call"] == 3
    assert body["inbound_websocket_bot_id"] == 34
    assert routing.id == 140


def test_routing_requires_a_did():
    with _client() as client:
        with pytest.raises(ValueError):
            client.routing.create(
                inbound=InboundRoute.WEBSOCKET_BOT,
                outbound=OutboundRoute.WEBSOCKET_BOT,
            )


@respx.mock
def test_calls_create_encodes_custom_parameters_as_json_string():
    route = respx.post(f"{BASE}/v1/add_lead").mock(
        return_value=httpx.Response(
            201,
            json={"status": True, "data": {"outbound_queue_id": 300735, "bot_id": 34}},
        )
    )
    with _client() as client:
        result = client.calls.create(
            did_number="919484950416",
            customer_number="919812345678",
            custom_parameters={"campaign": "fall"},
        )
    body = json.loads(route.calls.last.request.content)
    # custom_parameters must be a JSON *string*, not a nested object.
    assert isinstance(body["custom_parameters"], str)
    assert json.loads(body["custom_parameters"]) == {"campaign": "fall"}
    assert result.outbound_queue_id == 300735


@respx.mock
def test_sip_trunk_update_can_repoint_host_port_transport():
    # Regression: update() must be able to change host/port/transport/codecs, not just name/status.
    route = respx.post(f"{BASE}/v1/sip-trunk/update/205").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": True,
                "data": {
                    "id": 205,
                    "trunk_name": "bridge",
                    "sip_server_host": "1.2.3.4",
                    "sip_server_port": 35060,
                    "transport_type": 1,
                    "transport_label": "UDP",
                    "audio_format": ["alaw"],
                    "status": 1,
                },
            },
        )
    )
    with _client() as client:
        trunk = client.sip_trunks.update(
            205,
            trunk_name="bridge",
            status=Status.ACTIVE,
            sip_server_host="1.2.3.4",
            sip_server_port=35060,
            transport_type=TransportType.UDP,
            audio_format=[SipCodec.ALAW],
        )
    body = json.loads(route.calls.last.request.content)
    assert body["sip_server_host"] == "1.2.3.4"
    assert body["sip_server_port"] == 35060
    assert body["transport_type"] == 1        # UDP
    assert body["audio_format"] == ["alaw"]
    # And the returned model now exposes these (previously only in .raw)
    assert trunk.sip_server_host == "1.2.3.4"
    assert trunk.sip_server_port == 35060
    assert trunk.transport_label == "UDP"
    assert trunk.audio_format == ["alaw"]


@respx.mock
def test_sip_trunk_create_custom_surfaces_credentials():
    # The bridge authenticates outbound to VoiceLink with the trunk's username/password,
    # so create_custom must send them and the returned model must expose them.
    route = respx.post(f"{BASE}/v1/sip-trunk/create").mock(
        return_value=httpx.Response(
            201,
            json={
                "status": True,
                "data": {
                    "id": 213,
                    "trunk_name": "asterisk-bridge",
                    "sip_server_host": "sip-bridge.example.com",
                    "sip_server_port": 35060,
                    "transport_type": 1,
                    "audio_format": ["alaw"],
                    "username": "trunk_example",
                    "registration_password": "test-trunk-secret",
                    "status": 1,
                },
            },
        )
    )
    with _client() as client:
        trunk = client.sip_trunks.create_custom(
            trunk_name="asterisk-bridge",
            sip_server_host="sip-bridge.example.com",
            sip_server_port=35060,
            transport_type=TransportType.UDP,
            audio_format=[SipCodec.ALAW],
            username="trunk_example",
            registration_password="test-trunk-secret",
        )
    body = json.loads(route.calls.last.request.content)
    assert body["username"] == "trunk_example"
    assert body["registration_password"] == "test-trunk-secret"
    # The model now exposes the credentials the bridge needs for outbound auth.
    assert trunk.username == "trunk_example"
    assert trunk.registration_password == "test-trunk-secret"


@respx.mock
def test_bot_list_parses_paginator():
    respx.get(f"{BASE}/v1/websocket-bot/list").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": True,
                "data": {
                    "data": [{"id": 1, "bot_name": "A"}, {"id": 2, "bot_name": "B"}],
                    "current_page": 1,
                    "per_page": 10,
                    "total": 2,
                    "last_page": 1,
                },
            },
        )
    )
    with _client() as client:
        page = client.websocket_bots.list()
    assert len(page) == 2
    assert [b.id for b in page] == [1, 2]
    assert page.total == 2
    assert page.has_next is False

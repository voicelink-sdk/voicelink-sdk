"""Enums must serialize to the exact integers/strings the API expects."""

from voicelink.enums import (
    AudioFormat,
    CallEvent,
    InboundRoute,
    OutboundRoute,
    SipCodec,
    Status,
    TransportType,
)


def test_status_values():
    assert int(Status.INACTIVE) == 0
    assert int(Status.ACTIVE) == 1


def test_route_values_match_api():
    assert int(InboundRoute.MOBILE) == 1
    assert int(InboundRoute.SIP_TRUNK) == 2
    assert int(InboundRoute.WEBSOCKET_BOT) == 3
    assert int(OutboundRoute.SIP_TRUNK) == 2
    assert int(OutboundRoute.WEBSOCKET_BOT) == 3
    assert int(OutboundRoute.ONLY_ANSWER) == 4


def test_outbound_has_no_mobile():
    assert not hasattr(OutboundRoute, "MOBILE")


def test_audio_and_codec_strings():
    assert AudioFormat.L16_16K.value == "l16_16k"
    assert SipCodec.ALAW.value == "alaw"
    assert TransportType.UDP == 1


def test_call_event_strings():
    assert CallEvent.COMPLETED.value == "call.completed"
    assert CallEvent("call.ringing") is CallEvent.RINGING

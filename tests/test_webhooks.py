"""Webhook parsing, checked against a real payload captured from the live platform."""

import json

from voicelink.enums import CallEvent
from voicelink.webhooks import parse_webhook

# Verbatim body VoiceLink delivered for a completed (failed) outbound call.
REAL_COMPLETED = {
    "event": "call.completed",
    "timestamp": "2026-07-23T01:56:39.000+05:30",
    "call": {
        "id": "0de3a0e3-5f8e-4f33-ba9f-f53e1a5711a3",
        "direction": "outbound",
        "callType": "agent",
        "from": "919484950416",
        "to": "919812345678",
        "status": "failed",
        "hangupCause": "38 - Network out of order",
        "startedAt": "2026-07-23T01:56:20.000+05:30",
        "ringingAt": "2026-07-23T01:56:20.000+05:30",
        "answeredAt": None,
        "endedAt": "2026-07-23T01:56:39.000+05:30",
        "ringDurationSec": None,
        "durationSec": None,
        "callStatus": "NO ANSWER",
        "hangupReason": "38 - Network out of order",
        "customParameters": {
            "src": "sdk-design",
            "probe": "outbound_1",
            "outboundQueueId": 300735,
        },
    },
    "legs": [
        {
            "legType": "A",
            "channelId": "ca6339d4-0b52-465e-87db-0df522916b8e",
            "sipStatus": "503",
            "hangupReason": "Network out of order",
        }
    ],
}


def test_parses_nested_call_and_event():
    event = parse_webhook(REAL_COMPLETED)
    assert event.event is CallEvent.COMPLETED
    assert event.call.id == "0de3a0e3-5f8e-4f33-ba9f-f53e1a5711a3"
    assert event.call.direction == "outbound"
    assert event.call.from_number == "919484950416"
    assert event.call.to_number == "919812345678"
    assert event.call.status == "failed"


def test_parses_legs():
    event = parse_webhook(REAL_COMPLETED)
    assert len(event.call.legs) == 1
    assert event.call.legs[0].sip_status == "503"
    assert event.call.legs[0].channel_id == "ca6339d4-0b52-465e-87db-0df522916b8e"


def test_outbound_queue_id_correlation():
    event = parse_webhook(REAL_COMPLETED)
    assert event.call.outbound_queue_id == 300735


def test_accepts_json_string_and_bytes():
    as_str = parse_webhook(json.dumps(REAL_COMPLETED))
    as_bytes = parse_webhook(json.dumps(REAL_COMPLETED).encode())
    assert as_str.call.id == as_bytes.call.id == REAL_COMPLETED["call"]["id"]


def test_unknown_event_passes_through():
    event = parse_webhook({"event": "call.brand_new", "call": {"id": "x"}})
    assert event.event == "call.brand_new"
    assert event.call.id == "x"


def test_invalid_json_raises():
    import pytest

    with pytest.raises(ValueError):
        parse_webhook("{not json")

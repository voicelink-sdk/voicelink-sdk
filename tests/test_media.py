"""Media protocol: audio specs, inbound parsing, and outbound builders."""

import base64
import json

import pytest

from voicelink.enums import AudioFormat
from voicelink.media import (
    ConnectedEvent,
    MarkEvent,
    MediaEvent,
    StartEvent,
    StopEvent,
    UnknownEvent,
    build_clear,
    build_media,
    build_transfer,
    parse_message,
    resolve_spec,
    spec_for,
)

# --- audio specs ------------------------------------------------------------


def test_l16_16k_spec():
    spec = spec_for(AudioFormat.L16_16K)
    assert spec.sample_rate == 16000
    assert spec.sample_width == 2
    assert spec.is_linear is True
    # 20 ms of 16 kHz / 16-bit / mono = 16000 * 2 * 0.02 = 640 bytes.
    assert spec.bytes_per_ms(20) == 640


def test_alaw_spec_is_companded_8k():
    spec = spec_for("alaw")
    assert spec.sample_rate == 8000
    assert spec.sample_width == 1
    assert spec.is_linear is False


# --- inbound parsing --------------------------------------------------------


def test_resolve_spec_reads_the_wire_encoding_a_real_call_sent():
    # Captured verbatim from a live call: the wire name carries an "audio/" prefix that
    # the configured format never has, and the rate arrives as a string.
    spec = resolve_spec("audio/alaw", "8000")
    assert spec.format is AudioFormat.ALAW
    assert spec.sample_rate == 8000
    # Every media frame on that call was exactly 160 bytes.
    assert spec.bytes_per_ms(20) == 160
    assert spec.duration_ms(160) == 20.0


def test_resolve_spec_covers_all_four_formats():
    assert resolve_spec("audio/alaw", 8000).format is AudioFormat.ALAW
    assert resolve_spec("audio/ulaw", 8000).format is AudioFormat.ULAW
    assert resolve_spec("audio/l16", 8000).format is AudioFormat.L16
    assert resolve_spec("audio/l16", 16000).format is AudioFormat.L16_16K


def test_resolve_spec_separates_l16_rates_by_sample_rate_alone():
    # Both linear formats share one encoding string, so the rate is the only thing that
    # tells 8 kHz PCM from 16 kHz PCM. Getting this wrong resamples at double speed.
    assert resolve_spec("audio/l16", 8000).bytes_per_ms(20) == 320
    assert resolve_spec("audio/l16", 16000).bytes_per_ms(20) == 640


def test_resolve_spec_tolerates_prefix_and_casing():
    for value in ("alaw", "ALAW", "audio/alaw", "Audio/ALaw", "audio/pcma"):
        assert resolve_spec(value, 8000).format is AudioFormat.ALAW


def test_resolve_spec_rejects_the_unknown_rather_than_guessing():
    # Guessing would feed corrupted audio to a transcriber, which fails silently.
    with pytest.raises(ValueError):
        resolve_spec("audio/opus", 48000)
    with pytest.raises(ValueError):
        resolve_spec("audio/l16", 44100)
    with pytest.raises(ValueError):
        resolve_spec("audio/alaw", "not-a-number")


def test_parse_connected():
    ev = parse_message({"event": "connected"})
    assert isinstance(ev, ConnectedEvent)


def test_parse_start_metadata():
    frame = {
        "event": "start",
        "sequence_number": 0,
        "stream_sid": "stream_abc123",
        "start": {
            "stream_sid": "stream_abc123",
            "call_sid": "callabcdef1234",
            "account_sid": "42",
            "from": "+14155550100",
            "to": "+14155550199",
            "custom_parameters": {"campaign_id": "summer", "language": "en"},
            "media_format": {"encoding": "audio/alaw", "sample_rate": "8000"},
        },
    }
    ev = parse_message(frame)
    assert isinstance(ev, StartEvent)
    assert ev.stream_sid == "stream_abc123"
    assert ev.call_sid == "callabcdef1234"
    assert ev.from_number == "+14155550100"
    assert ev.custom_parameters["campaign_id"] == "summer"
    assert ev.encoding == "audio/alaw"
    assert ev.sample_rate == 8000


def test_parse_media_and_decode():
    audio = b"\x01\x02\x03\x04"
    payload = base64.b64encode(audio).decode()
    ev = parse_message({"event": "media", "media": {"track": "inbound", "payload": payload}})
    assert isinstance(ev, MediaEvent)
    assert ev.track == "inbound"
    assert ev.decode() == audio


def test_parse_stop_uses_camelcase_callsid():
    # The stop event uses camelCase `callSid`, unlike start's snake_case call_sid.
    ev = parse_message({"event": "stop", "stop": {"callSid": "callabcdef1234"}})
    assert isinstance(ev, StopEvent)
    assert ev.call_sid == "callabcdef1234"


def test_parse_mark():
    ev = parse_message({"event": "mark", "mark": {"name": "greeting_done"}})
    assert isinstance(ev, MarkEvent)
    assert ev.name == "greeting_done"


def test_unknown_event_does_not_raise():
    ev = parse_message({"event": "brand_new", "foo": 1})
    assert isinstance(ev, UnknownEvent)
    assert ev.event == "brand_new"


def test_parse_accepts_json_string():
    ev = parse_message(json.dumps({"event": "connected"}))
    assert isinstance(ev, ConnectedEvent)


# --- outbound builders ------------------------------------------------------


def test_build_media_omits_stream_sid_by_default():
    msg = build_media("QUJD")
    assert msg == {"event": "media", "media": {"payload": "QUJD"}}
    assert "stream_sid" not in msg


def test_build_media_includes_stream_sid_when_given():
    msg = build_media("QUJD", stream_sid="s1")
    assert msg["stream_sid"] == "s1"


def test_build_clear():
    assert build_clear("s1") == {"event": "clear", "stream_sid": "s1"}


def test_build_transfer_keeps_target_as_string():
    # Leading-zero / plus preservation: target must not be coerced to int.
    msg = build_transfer("09812345678")
    assert msg["target"] == "09812345678"
    assert isinstance(msg["target"], str)

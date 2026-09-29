"""Pipecat integration: the media serializer and the VoiceLink-side provisioner.

Skipped entirely if the optional ``pipecat`` extra is not installed.

The serializer cases below use frames captured from a real VoiceLink call, so they assert
what the platform actually sends rather than what its documentation claims - notably that
a bot configured for ``l16_16k`` streamed ``audio/alaw`` at 8 kHz.
"""

import ast
import asyncio
import base64
import importlib.util
import json
from pathlib import Path

import pytest

pytest.importorskip("pipecat.serializers.base_serializer")

from pipecat.frames.frames import (  # noqa: E402
    EndFrame,
    InputAudioRawFrame,
    InterruptionFrame,
    StartFrame,
    TTSAudioRawFrame,
)

from voicelink.enums import AudioFormat, InboundRoute, OutboundRoute, Status  # noqa: E402
from voicelink.integrations.pipecat import (  # noqa: E402
    PipecatProvisioner,
    VoiceLinkFrameSerializer,
)
from voicelink.models import CallRouting, Page, WebSocketBot  # noqa: E402

PIPELINE_RATE = 16000
ALAW_SILENCE = b"\xd5" * 160  # one 20 ms frame, the exact byte a real call carried

# --------------------------------------------------------------------------- helpers


def run(coro):
    """Run one coroutine, so tests stay sync and need no pytest-asyncio."""
    return asyncio.run(coro)


def start_frame(encoding="audio/alaw", sample_rate="8000"):
    return json.dumps(
        {
            "event": "start",
            "stream_sid": "stream_abc",
            "start": {
                "stream_sid": "stream_abc",
                "call_sid": "abc",
                "account_sid": "123",
                "from": "9000000001",
                "to": "919484950416",
                "media_format": {"encoding": encoding, "sample_rate": sample_rate},
            },
        }
    )


def media_frame(payload=ALAW_SILENCE, track="inbound"):
    media = {"track": track, "chunk": "1", "payload": base64.b64encode(payload).decode()}
    return json.dumps({"event": "media", "streamSid": "stream_abc", "media": media})


async def ready(**kwargs):
    """A serializer that has seen the pipeline StartFrame and a VoiceLink start frame."""
    ser = VoiceLinkFrameSerializer(**kwargs)
    await ser.setup(
        StartFrame(audio_in_sample_rate=PIPELINE_RATE, audio_out_sample_rate=PIPELINE_RATE)
    )
    await ser.deserialize(start_frame())
    return ser


# ------------------------------------------------------------------------ serializer


def test_start_frame_supplies_identity_and_format():
    ser = run(ready())
    assert ser.stream_sid == "stream_abc"
    assert ser.call_sid == "abc"
    # The bot is configured l16_16k; the wire said otherwise and the wire wins.
    assert ser.audio_spec.format.value == "alaw"
    assert ser.audio_spec.sample_rate == 8000


def test_start_frame_itself_produces_no_pipecat_frame():
    ser = VoiceLinkFrameSerializer()
    run(ser.setup(StartFrame(audio_in_sample_rate=PIPELINE_RATE,
                             audio_out_sample_rate=PIPELINE_RATE)))
    assert run(ser.deserialize(start_frame())) is None


def test_media_becomes_pcm_at_the_pipeline_rate():
    ser = run(ready())

    async def feed():
        out = []
        for _ in range(20):  # the stream resampler buffers, so feed enough to flush
            frame = await ser.deserialize(media_frame())
            if frame is not None:
                out.append(frame)
        return out

    frames = run(feed())
    assert frames, "no audio emerged from 20 media frames"
    assert all(isinstance(f, InputAudioRawFrame) for f in frames)
    assert all(f.sample_rate == PIPELINE_RATE for f in frames)
    assert all(f.num_channels == 1 for f in frames)


def test_media_before_start_is_dropped_not_guessed():
    ser = VoiceLinkFrameSerializer()
    run(ser.setup(StartFrame(audio_in_sample_rate=PIPELINE_RATE,
                             audio_out_sample_rate=PIPELINE_RATE)))
    assert run(ser.deserialize(media_frame())) is None


def test_outbound_track_is_ignored_so_the_bot_never_hears_itself():
    ser = run(ready())
    assert run(ser.deserialize(media_frame(track="outbound"))) is None


def test_stop_ends_the_pipeline():
    ser = run(ready())
    stopped = run(ser.deserialize(json.dumps({"event": "stop", "streamSid": "stream_abc"})))
    assert isinstance(stopped, EndFrame)


def test_unknown_events_are_ignored():
    ser = run(ready())
    assert run(ser.deserialize(json.dumps({"event": "something-new"}))) is None


def test_bot_audio_becomes_a_voicelink_media_message():
    ser = run(ready())
    chunk = b"\x00\x00" * int(PIPELINE_RATE * 0.02)

    async def feed():
        for _ in range(20):
            out = await ser.serialize(
                TTSAudioRawFrame(audio=chunk, sample_rate=PIPELINE_RATE, num_channels=1)
            )
            if out is not None:
                return json.loads(out)
        return None

    message = run(feed())
    assert message is not None, "nothing was serialized from 20 audio frames"
    assert message["event"] == "media"
    assert base64.b64decode(message["media"]["payload"])


def test_outbound_messages_carry_both_stream_sid_spellings_by_default():
    # VoiceLink is inconsistent inbound (start uses stream_sid, media uses streamSid) and
    # its outbound expectation is unverified, so both are sent until a live call decides.
    ser = run(ready())
    clear = json.loads(run(ser.serialize(InterruptionFrame())))
    assert clear["event"] == "clear"
    assert clear["stream_sid"] == "stream_abc"
    assert clear["streamSid"] == "stream_abc"


def test_the_camelcase_alias_can_be_turned_off():
    ser = run(ready(params=VoiceLinkFrameSerializer.InputParams(send_stream_sid_alias=False)))
    clear = json.loads(run(ser.serialize(InterruptionFrame())))
    assert clear["stream_sid"] == "stream_abc"
    assert "streamSid" not in clear


def test_linear_formats_need_no_companding():
    ser = VoiceLinkFrameSerializer()
    run(ser.setup(StartFrame(audio_in_sample_rate=PIPELINE_RATE,
                             audio_out_sample_rate=PIPELINE_RATE)))
    run(ser.deserialize(start_frame(encoding="audio/l16", sample_rate="16000")))
    assert ser.audio_spec.is_linear
    assert ser.audio_spec.sample_rate == PIPELINE_RATE


@pytest.mark.parametrize(
    "bad",
    ["", "hello", b"\x00\x01\x02", "[1,2,3]", '{"event":"media","media":{"payload":"!!!"}}'],
)
def test_a_malformed_frame_is_skipped_not_raised(bad):
    # Pipecat's transport calls deserialize() inside a try that catches only
    # ConnectionClosed, so anything else we raise escapes the read loop and ends the call.
    # Losing one 20 ms frame is the correct trade against hanging up on a customer.
    ser = run(ready())
    assert run(ser.deserialize(bad)) is None


def test_a_second_start_frame_resets_the_resamplers():
    # Resamplers hold a few samples of history. Carrying that across a format change
    # produces audible artefacts, so a fresh start frame must start fresh converters.
    ser = run(ready())
    first_in, first_out = ser._input_resampler, ser._output_resampler
    run(ser.deserialize(start_frame(encoding="audio/l16", sample_rate="16000")))
    assert ser.audio_spec.format is AudioFormat.L16_16K
    assert ser._input_resampler is not first_in
    assert ser._output_resampler is not first_out


def test_an_unreadable_sample_rate_falls_back_without_crashing():
    # A 16 kHz stream silently treated as 8 kHz plays at half speed, so the fallback
    # warns rather than passing it off as a normal negotiation.
    ser = VoiceLinkFrameSerializer()
    run(ser.setup(StartFrame(audio_in_sample_rate=PIPELINE_RATE,
                             audio_out_sample_rate=PIPELINE_RATE)))
    run(ser.deserialize(start_frame(encoding="audio/alaw", sample_rate="not-a-number")))
    assert ser.audio_spec.sample_rate == 8000


def test_an_unknown_wire_format_fails_loudly():
    ser = VoiceLinkFrameSerializer()
    run(ser.setup(StartFrame(audio_in_sample_rate=PIPELINE_RATE,
                             audio_out_sample_rate=PIPELINE_RATE)))
    with pytest.raises(ValueError):
        run(ser.deserialize(start_frame(encoding="audio/opus", sample_rate="48000")))


# ----------------------------------------------------------------------- provisioner


class _Bots:
    def __init__(self, bots):
        self.bots = list(bots)
        self.calls = []

    def list(self, **kw):
        return Page(items=list(self.bots), page=1, last_page=1)

    def create(self, **kw):
        self.calls.append(("create", kw))
        bot = WebSocketBot(id=99, bot_name=kw["bot_name"], websocket_url=kw["websocket_url"])
        self.bots.append(bot)
        return bot

    def update(self, bot_id, **kw):
        self.calls.append(("update", {"id": bot_id, **kw}))
        return WebSocketBot(id=bot_id, bot_name=kw.get("bot_name"),
                            websocket_url=kw.get("websocket_url"))


class _Routing:
    def __init__(self, rules):
        self.rules = list(rules)
        self.calls = []

    def list(self, **kw):
        return Page(items=list(self.rules), page=1, last_page=1)

    def create(self, **kw):
        self.calls.append(("create", kw))
        return CallRouting(id=7, did_number=kw.get("did_number"))

    def update(self, routing_id, **kw):
        self.calls.append(("update", {"id": routing_id, **kw}))
        # Apply the change to stored state, so a later find_routing() sees it. The real
        # API stores it too - it just answers with a bare {"id": ...}, which is what the
        # hollow CallRouting returned here stands in for.
        for i, rule in enumerate(self.rules):
            if rule.id == routing_id:
                self.rules[i] = CallRouting(
                    id=routing_id,
                    did_number=rule.did_number,
                    for_inbound_call=int(kw["inbound"]),
                    for_outbound_call=int(kw["outbound"]),
                    inbound_sip_trunk_id=kw.get("inbound_sip_trunk_id"),
                    inbound_websocket_bot_id=kw.get("inbound_websocket_bot_id"),
                    outbound_sip_trunk_id=kw.get("outbound_sip_trunk_id"),
                    outbound_websocket_bot_id=kw.get("outbound_websocket_bot_id"),
                    status=int(kw.get("status", Status.ACTIVE)),
                )
                break
        return CallRouting(id=routing_id)


class _Client:
    def __init__(self, bots=(), rules=()):
        self.websocket_bots = _Bots(bots)
        self.routing = _Routing(rules)


LIVEKIT_RULE = CallRouting(
    id=7,
    did_number="919484950416",
    for_inbound_call=int(InboundRoute.SIP_TRUNK),
    for_outbound_call=int(OutboundRoute.SIP_TRUNK),
    inbound_sip_trunk_id=213,
    outbound_sip_trunk_id=213,
    status=int(Status.ACTIVE),
)


def test_fresh_account_creates_bot_and_routing():
    client = _Client()
    result = PipecatProvisioner(client).setup_inbound(
        bot_name="agent", websocket_url="wss://a/ws", did="919484950416"
    )
    assert result.bot_created and result.routing_created
    assert result.previous_routing is None
    assert client.routing.calls[0][0] == "create"


def test_rerunning_updates_instead_of_duplicating():
    # A development tunnel gets a new address on every restart, so this is the common path.
    existing = WebSocketBot(id=50, bot_name="agent", websocket_url="wss://old/ws")
    client = _Client([existing], [LIVEKIT_RULE])
    result = PipecatProvisioner(client).setup_inbound(
        bot_name="agent", websocket_url="wss://new/ws", did="919484950416"
    )
    assert not result.bot_created and not result.routing_created
    kind, sent = client.websocket_bots.calls[-1]
    assert kind == "update"
    assert sent["websocket_url"] == "wss://new/ws"
    # The update endpoint rejects the request without these, even unchanged.
    assert sent["bot_name"] == "agent"
    assert sent["status"] is not None


def test_taking_inbound_leaves_the_outbound_trunk_alone():
    client = _Client([], [LIVEKIT_RULE])
    PipecatProvisioner(client).setup_inbound(
        bot_name="agent", websocket_url="wss://a/ws", did="919484950416"
    )
    _, sent = client.routing.calls[-1]
    assert sent["inbound"] is InboundRoute.WEBSOCKET_BOT
    assert sent["outbound"] == int(OutboundRoute.SIP_TRUNK)
    assert sent["outbound_sip_trunk_id"] == 213


def test_taking_outbound_leaves_the_inbound_trunk_alone():
    client = _Client([], [LIVEKIT_RULE])
    PipecatProvisioner(client).setup_outbound(
        bot_name="agent", websocket_url="wss://a/ws", did="919484950416"
    )
    _, sent = client.routing.calls[-1]
    assert sent["outbound"] is OutboundRoute.WEBSOCKET_BOT
    assert sent["inbound"] == int(InboundRoute.SIP_TRUNK)
    assert sent["inbound_sip_trunk_id"] == 213


def test_restore_previous_puts_every_field_back():
    client = _Client([], [LIVEKIT_RULE])
    prov = PipecatProvisioner(client)
    result = prov.setup_inbound(
        bot_name="agent", websocket_url="wss://a/ws", did="919484950416"
    )
    assert result.replaced_inbound is InboundRoute.SIP_TRUNK

    prov.restore_previous(result)
    _, sent = client.routing.calls[-1]
    assert sent["inbound"] == int(InboundRoute.SIP_TRUNK)
    assert sent["inbound_sip_trunk_id"] == 213
    assert sent["outbound"] == int(OutboundRoute.SIP_TRUNK)
    assert sent["outbound_sip_trunk_id"] == 213


def test_restore_previous_refuses_when_there_was_nothing_before():
    client = _Client()
    prov = PipecatProvisioner(client)
    result = prov.setup_inbound(
        bot_name="agent", websocket_url="wss://a/ws", did="919484950416"
    )
    with pytest.raises(ValueError):
        prov.restore_previous(result)


def test_restore_sip_trunk_clears_the_bot_from_both_directions():
    # A DID used for both an inbound and an outbound Pipecat test must come back fully:
    # restoring inbound alone would leave outbound calls still going through the bot.
    both_on_bot = CallRouting(
        id=7,
        did_number="919484950416",
        for_inbound_call=int(InboundRoute.WEBSOCKET_BOT),
        for_outbound_call=int(OutboundRoute.WEBSOCKET_BOT),
        inbound_websocket_bot_id=99,
        outbound_websocket_bot_id=99,
    )
    client = _Client([], [both_on_bot])
    PipecatProvisioner(client).restore_sip_trunk(did="919484950416", sip_trunk_id=213)
    _, sent = client.routing.calls[-1]
    assert sent["inbound"] is InboundRoute.SIP_TRUNK
    assert sent["outbound"] is OutboundRoute.SIP_TRUNK
    assert sent["inbound_sip_trunk_id"] == 213
    assert sent["outbound_sip_trunk_id"] == 213
    assert sent["inbound_websocket_bot_id"] is None
    assert sent["outbound_websocket_bot_id"] is None


def test_restore_sip_trunk_reports_state_read_back_from_the_api():
    # The update endpoint answers with only {"id": ...}. Returning that would show every
    # field as None and read as though the DID had been wiped.
    # Start with the DID taken over by a bot, so restoring is a real change.
    on_bot = CallRouting(
        id=7,
        did_number="919484950416",
        for_inbound_call=int(InboundRoute.WEBSOCKET_BOT),
        for_outbound_call=int(OutboundRoute.WEBSOCKET_BOT),
        inbound_websocket_bot_id=99,
        outbound_websocket_bot_id=99,
    )
    client = _Client([], [on_bot])
    result = PipecatProvisioner(client).restore_sip_trunk(did="919484950416", sip_trunk_id=213)
    assert result.for_inbound_call is not None, "returned the hollow update response"
    assert result.for_inbound_call == int(InboundRoute.SIP_TRUNK)
    assert result.inbound_sip_trunk_id == 213
    assert result.inbound_websocket_bot_id is None


def test_restore_sip_trunk_can_target_one_direction():
    client = _Client([], [LIVEKIT_RULE])
    PipecatProvisioner(client).restore_sip_trunk(
        did="919484950416", sip_trunk_id=213, outbound=False
    )
    _, sent = client.routing.calls[-1]
    assert sent["inbound"] is InboundRoute.SIP_TRUNK
    assert sent["outbound"] == int(OutboundRoute.SIP_TRUNK)  # untouched


def test_place_call_sends_the_national_number_not_a_doubled_country_code():
    # Verified live: customer_number="919000000001" with no country_code failed with
    # "38 - Network out of order"; "9000000001" + country_code="91" connected (cause 16).
    # The country code must reach VoiceLink once, in its own field.
    class _Calls:
        def __init__(self):
            self.sent = None

        def create(self, **kw):
            self.sent = kw
            return "queued"

    class _C(_Client):
        def __init__(self):
            super().__init__()
            self.calls = _Calls()

    for supplied in ("9000000001", "919000000001", "+91 90000-00001"):
        client = _C()
        PipecatProvisioner(client).place_call(
            did="919484950416", customer_number=supplied, country_code="91"
        )
        assert client.calls.sent["customer_number"] == "9000000001", supplied
        assert client.calls.sent["country_code"] == "91"


def test_place_call_leaves_a_number_alone_when_no_country_code_is_given():
    class _Calls:
        def __init__(self):
            self.sent = None

        def create(self, **kw):
            self.sent = kw
            return "queued"

    class _C(_Client):
        def __init__(self):
            super().__init__()
            self.calls = _Calls()

    client = _C()
    PipecatProvisioner(client).place_call(did="919484950416", customer_number="919000000001")
    assert client.calls.sent["customer_number"] == "919000000001"


def test_find_bot_ignores_case_and_surrounding_space():
    client = _Client([WebSocketBot(id=50, bot_name=" MN_Bot ")])
    assert PipecatProvisioner(client).find_bot("mn_bot").id == 50


def test_find_routing_ignores_number_formatting():
    client = _Client([], [CallRouting(id=7, did_number="+91 94849-50416")])
    assert PipecatProvisioner(client).find_routing("919484950416").id == 7


# --- The quickstart bot must answer more than one call at a time -------------------
#
# VoiceLink opens a separate WebSocket per call. Pipecat's WebsocketServerTransport keeps
# one client and closes every other with code 1013 - the platform still answers the call,
# so the caller hears an open, silent line and nothing anywhere reports an error. These
# two guards exist because that shipped once.

_QUICKSTART = Path(__file__).resolve().parent.parent / "examples" / "pipecat_quickstart.py"


def _load_quickstart():
    """Import the quickstart by path; ``examples/`` is deliberately not a package."""
    spec = importlib.util.spec_from_file_location("pipecat_quickstart", _QUICKSTART)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_quickstart_does_not_use_the_single_client_transport():
    """``WebsocketServerTransport`` is a deprecated alias that hides what it does."""
    # Imported names only: the prose above and in the quickstart names the class on
    # purpose, to explain why it is not used.
    imported = {
        alias.name
        for node in ast.walk(ast.parse(_QUICKSTART.read_text(encoding="utf-8")))
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    banned = imported & {"WebsocketServerTransport", "WebsocketServerParams"}
    assert not banned, f"single-client transport is back: {sorted(banned)}"
    assert "FastAPIWebsocketTransport" in imported


def test_quickstart_serves_two_calls_at_once():
    pytest.importorskip("fastapi", reason="needs the pipecat extra")
    from fastapi.testclient import TestClient

    started: list[int] = []

    async def handler(websocket, call_id):
        started.append(call_id)
        while True:
            message = await websocket.receive_text()
            if message == "bye":
                return
            # Echo the call id, so each client can prove which run answered it.
            await websocket.send_text(f"{call_id}:{message}")

    app = _load_quickstart().build_app(handler)
    with TestClient(app) as client:
        with client.websocket_connect("/") as first, client.websocket_connect("/") as second:
            first.send_text("hi")
            second.send_text("hi")
            first_reply = first.receive_text()
            second_reply = second.receive_text()
            first.send_text("bye")
            second.send_text("bye")

    assert len(started) == 2, "the second call never reached a handler"
    assert started[0] != started[1], "both calls shared one pipeline"
    assert first_reply.split(":")[0] == str(started[0])
    assert second_reply.split(":")[0] == str(started[1])

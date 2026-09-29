"""Parse VoiceLink's call-lifecycle webhooks into clean, typed objects.

VoiceLink POSTs JSON to your configured webhook URL as a call progresses. The real
payload nests the call under a ``call`` key (the flat shape in the public docs is
out of date), so this module maps the actual delivered structure.

    from voicelink.webhooks import parse_webhook

    event = parse_webhook(request_body)   # dict or JSON string / bytes
    if event.event is CallEvent.COMPLETED:
        print(event.call.id, event.call.status, event.call.duration_sec)

Always respond ``200`` to VoiceLink after handling, or it may retry.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .enums import CallEvent


@dataclass
class CallLeg:
    """One leg (channel) of a call, as reported in the ``legs`` array."""

    leg_type: str | None = None
    channel_id: str | None = None
    sip_status: str | None = None
    hangup_reason: str | None = None
    ring_time: str | None = None
    answer_time: str | None = None
    end_time: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CallLeg:
        return cls(
            leg_type=d.get("legType"),
            channel_id=d.get("channelId"),
            sip_status=_as_str(d.get("sipStatus")),
            hangup_reason=d.get("hangupReason"),
            ring_time=d.get("ringTime"),
            answer_time=d.get("answerTime"),
            end_time=d.get("endTime"),
            raw=d,
        )


@dataclass
class WebhookCall:
    """The ``call`` object carried by every webhook event."""

    id: str | None = None
    direction: str | None = None
    call_type: str | None = None
    from_number: str | None = None
    to_number: str | None = None
    status: str | None = None
    hangup_cause: str | None = None
    hangup_reason: str | None = None
    sip_status: str | None = None
    call_status: str | None = None
    started_at: str | None = None
    ringing_at: str | None = None
    answered_at: str | None = None
    ended_at: str | None = None
    ring_duration_sec: int | None = None
    duration_sec: int | None = None
    custom_parameters: dict[str, Any] = field(default_factory=dict)
    legs: list[CallLeg] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any], legs: list[dict[str, Any]] | None = None) -> WebhookCall:
        return cls(
            id=_as_str(d.get("id")),
            direction=d.get("direction"),
            call_type=d.get("callType"),
            from_number=_as_str(d.get("from")),
            to_number=_as_str(d.get("to")),
            status=d.get("status"),
            hangup_cause=d.get("hangupCause"),
            hangup_reason=d.get("hangupReason"),
            sip_status=_as_str(d.get("sipStatus")),
            call_status=d.get("callStatus"),
            started_at=d.get("startedAt"),
            ringing_at=d.get("ringingAt"),
            answered_at=d.get("answeredAt"),
            ended_at=d.get("endedAt"),
            ring_duration_sec=_as_int(d.get("ringDurationSec")),
            duration_sec=_as_int(d.get("durationSec")),
            custom_parameters=d.get("customParameters") or {},
            legs=[CallLeg.from_dict(leg) for leg in (legs or [])],
            raw=d,
        )

    @property
    def outbound_queue_id(self) -> int | None:
        """The queue id VoiceLink injects into ``customParameters`` for outbound calls.

        Use it to correlate a webhook back to the ``client.calls.create(...)`` that
        started the call.
        """
        return _as_int(self.custom_parameters.get("outboundQueueId"))


@dataclass
class WebhookEvent:
    """A parsed webhook: the event type plus its call object."""

    event: CallEvent | str
    timestamp: str | None
    call: WebhookCall
    raw: dict[str, Any] = field(default_factory=dict)


def parse_webhook(body: str | bytes | dict[str, Any]) -> WebhookEvent:
    """Parse a raw webhook body (JSON string, bytes, or dict) into a WebhookEvent.

    Raises :class:`ValueError` if the body is not valid JSON.
    """
    if isinstance(body, (str, bytes)):
        try:
            payload = json.loads(body)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Webhook body is not valid JSON: {exc}") from exc
    else:
        payload = body

    if not isinstance(payload, dict):
        raise ValueError("Webhook body must be a JSON object")

    call_dict = payload.get("call")
    if not isinstance(call_dict, dict):
        call_dict = {}
    legs = payload.get("legs") if isinstance(payload.get("legs"), list) else []

    return WebhookEvent(
        event=_parse_event(payload.get("event")),
        timestamp=payload.get("timestamp"),
        call=WebhookCall.from_dict(call_dict, legs),
        raw=payload,
    )


def _parse_event(value: Any) -> CallEvent | str:
    try:
        return CallEvent(value)
    except ValueError:
        return value  # unknown/new event type — pass the string through unchanged


def _as_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

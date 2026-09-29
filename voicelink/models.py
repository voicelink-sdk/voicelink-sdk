"""Typed data objects returned by the SDK.

These are light dataclasses that wrap the API's JSON so callers get attribute access and
editor autocompletion instead of raw dicts. Every model keeps the original response on
``.raw`` so nothing is ever lost, even fields the SDK does not model explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

T = TypeVar("T")


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass
class Page(Generic[T]):
    """A page of list results, plus the pagination metadata around it.

    Iterate the page directly to walk its items:

        for bot in client.websocket_bots.list():
            ...
    """

    items: list[T]
    page: int = 1
    per_page: int = 0
    total: int = 0
    last_page: int = 1
    raw: dict[str, Any] = field(default_factory=dict)

    def __iter__(self):
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)

    @property
    def has_next(self) -> bool:
        return self.page < self.last_page

    @classmethod
    def from_payload(cls, data: Any, item_parser) -> Page[T]:
        """Build a Page from either a Laravel paginator dict or a bare list.

        Some endpoints return ``{"data": [...], "current_page": ...}`` and others return a
        plain list; this handles both.
        """
        if isinstance(data, dict):
            rows = data.get("data", [])
            return cls(
                items=[item_parser(r) for r in rows],
                page=_to_int(data.get("current_page")) or 1,
                per_page=_to_int(data.get("per_page")) or len(rows),
                total=_to_int(data.get("total")) or len(rows),
                last_page=_to_int(data.get("last_page")) or 1,
                raw=data,
            )
        rows = data or []
        return cls(
            items=[item_parser(r) for r in rows],
            page=1,
            per_page=len(rows),
            total=len(rows),
            last_page=1,
            raw={"data": rows},
        )


@dataclass
class WebSocketBot:
    """An AI bot endpoint that VoiceLink streams live call audio to."""

    id: int
    bot_name: str | None = None
    websocket_url: str | None = None
    webhook_url: str | None = None
    audio_format: str | None = None
    noise_cancel: int | None = None
    status: int | None = None
    client_id: int | None = None
    reseller_id: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> WebSocketBot:
        return cls(
            id=_to_int(d.get("id")),
            bot_name=d.get("bot_name"),
            websocket_url=d.get("websocket_url"),
            webhook_url=d.get("webhook_url"),
            audio_format=d.get("audio_format"),
            noise_cancel=_to_int(d.get("noise_cancel")),
            status=_to_int(d.get("status")),
            client_id=_to_int(d.get("client_id")),
            reseller_id=_to_int(d.get("reseller_id")),
            raw=d,
        )


@dataclass
class SipTrunk:
    """A SIP connection linking DIDs to a telephony network or bot provider."""

    id: int
    trunk_name: str | None = None
    status: int | None = None
    bot_provider_id: int | None = None
    client_id: int | None = None
    sip_server_host: str | None = None
    sip_server_port: int | None = None
    transport_type: int | None = None
    transport_label: str | None = None
    username: str | None = None
    registration_password: str | None = None
    audio_format: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SipTrunk:
        fmt = d.get("audio_format")
        return cls(
            id=_to_int(d.get("id")),
            trunk_name=d.get("trunk_name"),
            status=_to_int(d.get("status")),
            bot_provider_id=_to_int(d.get("bot_provider_id")),
            client_id=_to_int(d.get("client_id")),
            sip_server_host=d.get("sip_server_host"),
            sip_server_port=_to_int(d.get("sip_server_port")),
            transport_type=_to_int(d.get("transport_type")),
            transport_label=d.get("transport_label"),
            username=d.get("username"),
            # The bridge authenticates outbound to VoiceLink with these trunk credentials.
            # VoiceLink returns them on create (auto-generated when not supplied); list/get
            # may omit the password, so capture your own or read it from the create result.
            registration_password=d.get("registration_password"),
            audio_format=fmt if isinstance(fmt, list) else [],
            raw=d,
        )


@dataclass
class BotProvider:
    """A preset SIP bot-provider server (e.g. VAPI, Retell, ElevenLabs)."""

    id: int
    name: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> BotProvider:
        return cls(id=_to_int(d.get("id")), name=d.get("name"), raw=d)


@dataclass
class CallRouting:
    """The rule binding one DID to its inbound and outbound handlers."""

    id: int
    did_id: int | None = None
    did_number: str | None = None
    for_inbound_call: int | None = None
    for_outbound_call: int | None = None
    inbound_sip_trunk_id: int | None = None
    inbound_websocket_bot_id: int | None = None
    outbound_sip_trunk_id: int | None = None
    outbound_websocket_bot_id: int | None = None
    status: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CallRouting:
        return cls(
            id=_to_int(d.get("id")),
            did_id=_to_int(d.get("did_id")),
            did_number=_str_or_none(d.get("did_number")),
            for_inbound_call=_to_int(d.get("for_inbound_call")),
            for_outbound_call=_to_int(d.get("for_outbound_call")),
            inbound_sip_trunk_id=_to_int(d.get("inbound_sip_trunk_id")),
            inbound_websocket_bot_id=_to_int(d.get("inbound_websocket_bot_id")),
            outbound_sip_trunk_id=_to_int(d.get("outbound_sip_trunk_id")),
            outbound_websocket_bot_id=_to_int(d.get("outbound_websocket_bot_id")),
            status=_to_int(d.get("status")),
            raw=d,
        )


@dataclass
class Did:
    """A phone number (DID) in the account's inventory."""

    id: int
    did_number: str | None = None
    type_label: str | None = None
    country_code: str | None = None
    status: int | None = None
    status_label: str | None = None
    client_id: int | None = None
    expiry_date: str | None = None
    is_expired: bool | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Did:
        return cls(
            id=_to_int(d.get("id")),
            did_number=_str_or_none(d.get("did_number")),
            type_label=d.get("type_label"),
            country_code=_str_or_none(d.get("country_code")),
            status=_to_int(d.get("status")),
            status_label=d.get("status_label"),
            client_id=_to_int(d.get("client_id")),
            expiry_date=d.get("expiry_date"),
            is_expired=d.get("is_expired"),
            raw=d,
        )


@dataclass
class LeadResult:
    """Result of a single outbound-call trigger (``add_lead``)."""

    outbound_queue_id: int | None = None
    bot_id: int | None = None
    carrier_id: int | None = None
    client_id: int | None = None
    reseller_id: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> LeadResult:
        if not isinstance(d, dict):
            return cls(raw={"data": d})
        return cls(
            outbound_queue_id=_to_int(d.get("outbound_queue_id")),
            bot_id=_to_int(d.get("bot_id")),
            carrier_id=_to_int(d.get("carrier_id")),
            client_id=_to_int(d.get("client_id")),
            reseller_id=_to_int(d.get("reseller_id")),
            raw=d,
        )


@dataclass
class BulkLeadResult:
    """Result of a bulk outbound-call trigger (``add_lead`` with a ``leads`` array)."""

    accepted_leads: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> BulkLeadResult:
        if not isinstance(d, dict):
            return cls(raw={"data": d})
        return cls(accepted_leads=_to_int(d.get("accepted_leads")), raw=d)


def _str_or_none(value: Any) -> str | None:
    """The API sometimes returns phone numbers as ints; normalize to string."""
    if value is None:
        return None
    return str(value)

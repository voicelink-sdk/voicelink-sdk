"""SIP Trunks — connect DIDs to a telephony network or a preset bot provider.

There are two ways to create a trunk:

* :meth:`create_for_bot_provider` — pick a preset provider (VAPI, Retell, ElevenLabs);
  credentials and host are inherited from the provider server.
* :meth:`create_custom` — supply your own SIP host/port/transport/credentials and codecs.
  This is the path used for integrations like LiveKit that are not preset providers.

The API has no delete endpoint; deactivate with :meth:`update` instead.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..enums import SipCodec, Status, TransportType
from ..models import BotProvider, Page, SipTrunk
from .base import Resource


class SipTrunksResource(Resource):
    def bot_providers(self) -> list[BotProvider]:
        """List the preset SIP bot-provider servers and their ids."""
        data = self._transport.request("GET", "/v1/sip-trunk/bot-provider/list")
        rows = data if isinstance(data, list) else (data or {}).get("data", [])
        return [BotProvider.from_dict(r) for r in rows]

    def create_for_bot_provider(
        self,
        *,
        trunk_name: str,
        bot_provider_id: int,
        client_id: int | None = None,
        status: Status | int = Status.ACTIVE,
    ) -> SipTrunk:
        """Create a trunk using a preset bot provider (host/credentials inherited)."""
        body = self._clean(
            {
                "trunk_name": trunk_name,
                "bot_provider_id": bot_provider_id,
                "status": int(status),
                "client_id": self._resolve_client_id(client_id),
            }
        )
        data = self._transport.request("POST", "/v1/sip-trunk/create", json=body)
        return SipTrunk.from_dict(data or {})

    def create_custom(
        self,
        *,
        trunk_name: str,
        sip_server_host: str,
        transport_type: TransportType | int,
        audio_format: Sequence[SipCodec | str],
        client_id: int | None = None,
        sip_server_port: int | None = None,
        username: str | None = None,
        registration_password: str | None = None,
        status: Status | int = Status.ACTIVE,
    ) -> SipTrunk:
        """Create a custom SIP trunk with your own host, transport, and codecs.

        ``audio_format`` is a list of one or more codecs (e.g. ``[SipCodec.ALAW]``).
        If ``username`` / ``registration_password`` are omitted, the API auto-generates
        them.
        """
        if not audio_format:
            raise ValueError("audio_format must list at least one codec")

        body = self._clean(
            {
                "trunk_name": trunk_name,
                "sip_server_host": sip_server_host,
                "sip_server_port": sip_server_port,
                "transport_type": int(transport_type),
                "audio_format": [_codec(c) for c in audio_format],
                "username": username,
                "registration_password": registration_password,
                "status": int(status),
                "client_id": self._resolve_client_id(client_id),
            }
        )
        data = self._transport.request("POST", "/v1/sip-trunk/create", json=body)
        return SipTrunk.from_dict(data or {})

    def list(
        self,
        *,
        page: int = 1,
        per_page: int = 10,
        client_id: int | None = None,
    ) -> Page[SipTrunk]:
        """List SIP trunks visible to the account."""
        params = {
            "page": page,
            "per_page": per_page,
            "client_id": self._resolve_client_id(client_id),
        }
        data = self._transport.request("GET", "/v1/sip-trunk/list", params=params)
        return Page.from_payload(data, SipTrunk.from_dict)

    def update(
        self,
        trunk_id: int,
        *,
        trunk_name: str | None = None,
        status: Status | int | None = None,
        sip_server_host: str | None = None,
        sip_server_port: int | None = None,
        transport_type: TransportType | int | None = None,
        audio_format: Sequence[SipCodec | str] | None = None,
        username: str | None = None,
        registration_password: str | None = None,
    ) -> SipTrunk:
        """Update a trunk. Only the fields you pass are changed.

        Beyond name/status, this can repoint a custom trunk's destination — host, port,
        transport, and codecs — which is needed to move a trunk between endpoints (e.g.
        from a direct provider to a SIP bridge). The API requires ``trunk_name`` and
        ``status`` on every update, so pass them (or the SDK sends the ones you set).
        """
        body = self._clean(
            {
                "trunk_name": trunk_name,
                "status": None if status is None else int(status),
                "sip_server_host": sip_server_host,
                "sip_server_port": sip_server_port,
                "transport_type": None if transport_type is None else int(transport_type),
                "audio_format": None if audio_format is None else [_codec(c) for c in audio_format],
                "username": username,
                "registration_password": registration_password,
            }
        )
        data = self._transport.request("POST", f"/v1/sip-trunk/update/{trunk_id}", json=body)
        return SipTrunk.from_dict(data or {})


def _codec(value: SipCodec | str) -> str:
    return value.value if isinstance(value, SipCodec) else str(value)

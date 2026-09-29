"""Build and execute LiveKit SIP configuration for a VoiceLink connection.

Two layers live here:

* Pure ``build_*`` functions that assemble LiveKit request objects with sensible
  VoiceLink defaults. They are easy to inspect and unit-test, and they normalize the
  dispatch-rule "randomize" flag so callers never hit LiveKit's inverted ``no_randomness``.
* :class:`LiveKitProvisioner`, a thin async wrapper over ``livekit.api.LiveKitAPI`` that
  executes those requests and can also create the matching VoiceLink-side SIP trunk.

LiveKit terminates SIP/RTP itself, so nothing here touches call audio — this is purely
provisioning.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from livekit import api as lk

from ...enums import SipCodec, TransportType

if TYPE_CHECKING:
    from ...client import VoiceLinkClient

# VoiceLink codec -> LiveKit SDP codec name. (LiveKit matches on the rtpmap name.)
_CODEC_NAME: dict[SipCodec, str] = {
    SipCodec.ALAW: "PCMA",
    SipCodec.ULAW: "PCMU",
    SipCodec.G722: "G722",
    SipCodec.G729: "G729",
}
# SIP rtpmap clock rate. Note G.722 uses 8000 by SDP convention despite 16 kHz sampling.
_CODEC_RATE: dict[str, int] = {"PCMA": 8000, "PCMU": 8000, "G722": 8000, "G729": 8000}

_TRANSPORT: dict[TransportType, Any] = {
    TransportType.UDP: lk.SIPTransport.SIP_TRANSPORT_UDP,
    TransportType.TCP: lk.SIPTransport.SIP_TRANSPORT_TCP,
    TransportType.TLS: lk.SIPTransport.SIP_TRANSPORT_TLS,
}


def map_codec(codec: SipCodec | str) -> Any:
    """Map a VoiceLink codec to a LiveKit ``SIPCodec``."""
    codec = SipCodec(codec) if not isinstance(codec, SipCodec) else codec
    name = _CODEC_NAME[codec]
    return lk.SIPCodec(name=name, rate=_CODEC_RATE[name])


def map_transport(transport: TransportType | int) -> Any:
    """Map a VoiceLink transport type to a LiveKit ``SIPTransport``."""
    transport = TransportType(int(transport))
    return _TRANSPORT[transport]


def _media_config(codecs: Sequence[SipCodec | str] | None) -> Any | None:
    if not codecs:
        return None
    return lk.SIPMediaConfig(
        only_listed_codecs=True,
        codecs=[map_codec(c) for c in codecs],
    )


def build_inbound_trunk_request(
    *,
    name: str,
    numbers: Sequence[str],
    allowed_addresses: Sequence[str] | None = None,
    auth_username: str | None = None,
    auth_password: str | None = None,
    codecs: Sequence[SipCodec | str] | None = None,
    krisp_enabled: bool = False,
) -> Any:
    """Build a ``CreateSIPInboundTrunkRequest`` accepting calls from VoiceLink.

    ``allowed_addresses`` (an IP allowlist) and ``auth_username``/``auth_password``
    (digest auth) are independent — set either, both, or neither to match how the
    VoiceLink trunk authenticates.
    """
    info = lk.SIPInboundTrunkInfo(
        name=name,
        numbers=list(numbers),
        krisp_enabled=krisp_enabled,
    )
    if allowed_addresses:
        info.allowed_addresses.extend(allowed_addresses)
    if auth_username is not None:
        info.auth_username = auth_username
    if auth_password is not None:
        info.auth_password = auth_password
    media = _media_config(codecs)
    if media is not None:
        info.media.CopyFrom(media)
    return lk.CreateSIPInboundTrunkRequest(trunk=info)


def build_outbound_trunk_request(
    *,
    name: str,
    address: str,
    numbers: Sequence[str],
    transport: TransportType | int | None = None,
    auth_username: str | None = None,
    auth_password: str | None = None,
    codecs: Sequence[SipCodec | str] | None = None,
) -> Any:
    """Build a ``CreateSIPOutboundTrunkRequest`` that dials out through VoiceLink.

    ``address`` is the VoiceLink SIP host (e.g. ``app.voicelink.co.in:3300``) with no
    ``sip:`` prefix.

    ``transport`` is optional — when omitted, LiveKit auto-negotiates (``SIP_TRANSPORT_AUTO``).
    Set it explicitly (e.g. ``TransportType.TCP``) when VoiceLink requires a specific one.
    """
    resolved_transport = (
        lk.SIPTransport.SIP_TRANSPORT_AUTO if transport is None else map_transport(transport)
    )
    info = lk.SIPOutboundTrunkInfo(
        name=name,
        address=address,
        transport=resolved_transport,
        numbers=list(numbers),
    )
    if auth_username is not None:
        info.auth_username = auth_username
    if auth_password is not None:
        info.auth_password = auth_password
    media = _media_config(codecs)
    if media is not None:
        info.media.CopyFrom(media)
    return lk.CreateSIPOutboundTrunkRequest(trunk=info)


def build_dispatch_rule_request(
    *,
    trunk_ids: Sequence[str],
    room_prefix: str = "call-",
    name: str | None = None,
    agent_name: str | None = None,
    randomize: bool = True,
) -> Any:
    """Build a ``CreateSIPDispatchRuleRequest`` routing inbound calls to rooms/agents.

    Uses the "individual" rule (a fresh room per caller). ``randomize`` controls whether
    room names get a random suffix — this SDK normalizes LiveKit's inverted
    ``no_randomness`` flag so ``randomize=True`` means what it says.

    Set ``agent_name`` to auto-dispatch a specific agent into each call's room.
    """
    individual = lk.SIPDispatchRuleIndividual(
        room_prefix=room_prefix,
        no_randomness=not randomize,
    )
    info = lk.SIPDispatchRuleInfo(
        rule=lk.SIPDispatchRule(dispatch_rule_individual=individual),
        trunk_ids=list(trunk_ids),
    )
    if name is not None:
        info.name = name
    if agent_name:
        info.room_config.CopyFrom(
            lk.RoomConfiguration(agents=[lk.RoomAgentDispatch(agent_name=agent_name)])
        )
    return lk.CreateSIPDispatchRuleRequest(dispatch_rule=info)


def build_agent_dispatch_request(
    *,
    room_name: str,
    agent_name: str,
    metadata: str | None = None,
) -> Any:
    """Build a ``CreateAgentDispatchRequest`` to place an agent into a specific room.

    Inbound calls get their agent from the dispatch *rule* (see
    :func:`build_dispatch_rule_request`). Outbound calls have no such rule — you create
    the room and dial a participant into it yourself — so the agent must be dispatched
    explicitly. Do this *before* :meth:`LiveKitProvisioner.place_call` so the agent is
    already in the room when the callee answers.
    """
    req = lk.CreateAgentDispatchRequest(room=room_name, agent_name=agent_name)
    if metadata is not None:
        req.metadata = metadata
    return req


def build_sip_participant_request(
    *,
    sip_trunk_id: str,
    call_to: str,
    room_name: str,
    participant_identity: str,
    participant_name: str | None = None,
    krisp_enabled: bool = False,
    wait_until_answered: bool = False,
) -> Any:
    """Build a ``CreateSIPParticipantRequest`` to place an outbound call into a room."""
    req = lk.CreateSIPParticipantRequest(
        sip_trunk_id=sip_trunk_id,
        sip_call_to=call_to,
        room_name=room_name,
        participant_identity=participant_identity,
        krisp_enabled=krisp_enabled,
        wait_until_answered=wait_until_answered,
    )
    if participant_name is not None:
        req.participant_name = participant_name
    return req


class LiveKitProvisioner:
    """Async helper that executes LiveKit SIP provisioning for a VoiceLink connection.

        async with LiveKitProvisioner(
            livekit_url="wss://my.livekit.cloud",
            api_key="…", api_secret="…",
        ) as prov:
            trunk = await prov.create_inbound_trunk(
                name="voicelink-in", numbers=["919484950416"],
                allowed_addresses=["1.2.3.4/32"],
            )
            await prov.create_dispatch_rule(
                trunk_ids=[trunk.sip_trunk_id], agent_name="support",
            )

    Optionally pass a :class:`~voicelink.client.VoiceLinkClient` to also create the
    matching VoiceLink-side SIP trunk via :meth:`create_voicelink_trunk`.
    """

    def __init__(
        self,
        *,
        livekit_url: str,
        api_key: str,
        api_secret: str,
        voicelink: VoiceLinkClient | None = None,
    ) -> None:
        self._api = lk.LiveKitAPI(livekit_url, api_key, api_secret)
        self._voicelink = voicelink

    # -- LiveKit side ------------------------------------------------------------

    async def create_inbound_trunk(self, **kwargs: Any) -> Any:
        """Create a LiveKit inbound trunk. Accepts :func:`build_inbound_trunk_request` args."""
        return await self._api.sip.create_inbound_trunk(build_inbound_trunk_request(**kwargs))

    async def create_outbound_trunk(self, **kwargs: Any) -> Any:
        """Create a LiveKit outbound trunk. Accepts :func:`build_outbound_trunk_request` args."""
        return await self._api.sip.create_outbound_trunk(build_outbound_trunk_request(**kwargs))

    async def create_dispatch_rule(self, **kwargs: Any) -> Any:
        """Create a LiveKit dispatch rule. Accepts :func:`build_dispatch_rule_request` args."""
        return await self._api.sip.create_dispatch_rule(build_dispatch_rule_request(**kwargs))

    async def dispatch_agent(self, **kwargs: Any) -> Any:
        """Dispatch an agent into a room. Accepts :func:`build_agent_dispatch_request` args.

        Use for OUTBOUND calls: dispatch the agent into the room before placing the call,
        so it is present when the callee answers.
        """
        return await self._api.agent_dispatch.create_dispatch(
            build_agent_dispatch_request(**kwargs)
        )

    async def place_call(self, **kwargs: Any) -> Any:
        """Place an outbound call. Accepts :func:`build_sip_participant_request` args."""
        return await self._api.sip.create_sip_participant(build_sip_participant_request(**kwargs))

    async def list_inbound_trunks(self) -> list[Any]:
        """List LiveKit inbound SIP trunks."""
        resp = await self._api.sip.list_inbound_trunk(lk.ListSIPInboundTrunkRequest())
        return list(resp.items)

    async def list_outbound_trunks(self) -> list[Any]:
        """List LiveKit outbound SIP trunks."""
        resp = await self._api.sip.list_outbound_trunk(lk.ListSIPOutboundTrunkRequest())
        return list(resp.items)

    async def delete_trunk(self, sip_trunk_id: str) -> Any:
        """Delete a LiveKit SIP trunk (inbound or outbound) by id."""
        return await self._api.sip.delete_trunk(lk.DeleteSIPTrunkRequest(sip_trunk_id=sip_trunk_id))

    # -- VoiceLink side ----------------------------------------------------------

    def create_voicelink_trunk(self, **kwargs: Any):
        """Create the VoiceLink-side custom SIP trunk (delegates to the core client).

        Requires a ``VoiceLinkClient`` to have been supplied. Accepts the same arguments
        as :meth:`voicelink.resources.sip_trunks.SipTrunksResource.create_custom`.
        """
        if self._voicelink is None:
            raise ValueError("Pass a VoiceLinkClient to the provisioner to use this method")
        return self._voicelink.sip_trunks.create_custom(**kwargs)

    # -- lifecycle ---------------------------------------------------------------

    async def aclose(self) -> None:
        await self._api.aclose()

    async def __aenter__(self) -> LiveKitProvisioner:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

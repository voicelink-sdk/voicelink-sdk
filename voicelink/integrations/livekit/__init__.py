"""LiveKit integration for VoiceLink.

LiveKit connects to VoiceLink over SIP — there is no media/serializer plugin to write, so
this integration is *configuration only*. It provides helpers that build LiveKit's SIP
requests with VoiceLink-appropriate defaults (codec mapping, transport, dispatch rules)
and a :class:`LiveKitProvisioner` that executes them.

Requires the ``livekit`` extra::

    pip install voicelink[livekit]
"""

try:  # pragma: no cover - exercised via the import-error message only
    import livekit.api  # noqa: F401
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "The LiveKit integration requires the 'livekit' extra. "
        "Install it with:  pip install voicelink[livekit]"
    ) from exc

from .provisioning import (
    LiveKitProvisioner,
    build_agent_dispatch_request,
    build_dispatch_rule_request,
    build_inbound_trunk_request,
    build_outbound_trunk_request,
    build_sip_participant_request,
    map_codec,
    map_transport,
)

__all__ = [
    "LiveKitProvisioner",
    "build_inbound_trunk_request",
    "build_outbound_trunk_request",
    "build_dispatch_rule_request",
    "build_agent_dispatch_request",
    "build_sip_participant_request",
    "map_codec",
    "map_transport",
]

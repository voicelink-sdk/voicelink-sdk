"""Pipecat integration for VoiceLink.

Pipecat has no telephony of its own — it expects a transport to hand it raw PCM over a
WebSocket. VoiceLink speaks its own JSON dialect with base64 G.711 inside. This
integration supplies the translator between them.

That makes it the mirror image of the LiveKit integration: LiveKit terminates SIP itself
and needs *configuration only*, while Pipecat needs a media serializer and never sees SIP.

Requires the ``pipecat`` extra::

    pip install voicelink[pipecat]
"""

try:  # pragma: no cover - exercised via the import-error message only
    import pipecat.serializers.base_serializer  # noqa: F401
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "The Pipecat integration requires the 'pipecat' extra. "
        "Install it with:  pip install voicelink[pipecat]"
    ) from exc

from .provisioning import PipecatProvisioner, Provisioned
from .serializer import VoiceLinkFrameSerializer

__all__ = ["PipecatProvisioner", "Provisioned", "VoiceLinkFrameSerializer"]

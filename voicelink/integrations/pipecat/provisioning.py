"""Configure the VoiceLink side of a Pipecat deployment.

Where :mod:`~voicelink.integrations.pipecat.serializer` handles audio *during* a call,
this module handles everything that must exist *before* one: the WebSocket bot that names
your server, and the routing rule that sends a DID to it.

Done by hand in the portal, that is a four-step chain with one non-obvious trap (the
``WebSocket API`` toggle silently kills the media stream — see :class:`PipecatProvisioner`).
Here it is one call::

    from voicelink import VoiceLinkClient
    from voicelink.integrations.pipecat import PipecatProvisioner

    result = PipecatProvisioner(client).setup_inbound(
        bot_name="pipecat-agent",
        websocket_url="wss://my-bot.example.com/ws",
        did="919484950416",
    )

Every operation is idempotent: run it twice and the second run updates rather than
failing. That matters because a bot's public URL changes constantly during development
(an ngrok tunnel gets a new address on every restart) and because a DID may already be
routed to something else — LiveKit, most likely — when a customer tries Pipecat.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ...enums import AudioFormat, InboundRoute, NoiseCancel, OutboundRoute, Status
from ...models import CallRouting, LeadResult, WebSocketBot

if TYPE_CHECKING:  # pragma: no cover - import cycle guard, types only
    from ...client import VoiceLinkClient

# Pages to walk when searching for an existing bot or routing rule. The list endpoints are
# paginated and neither supports a server-side filter on the field we need.
_MAX_PAGES = 50
_PER_PAGE = 100


@dataclass(frozen=True)
class Provisioned:
    """What :meth:`PipecatProvisioner.setup_inbound` created or changed.

    Attributes:
        bot: The WebSocket bot VoiceLink will stream audio to.
        routing: The routing rule binding the DID to that bot.
        bot_created: ``True`` if the bot was new, ``False`` if an existing one was updated.
        routing_created: ``True`` if the DID had no routing rule before.
        previous_routing: The DID's routing rule exactly as it was before this call, or
            ``None`` if it had none. Pass the whole :class:`Provisioned` back to
            :meth:`PipecatProvisioner.restore_previous` to undo the change - no need to
            note down trunk ids by hand.
    """

    bot: WebSocketBot
    routing: CallRouting
    bot_created: bool
    routing_created: bool
    previous_routing: CallRouting | None = None

    @property
    def replaced_inbound(self) -> InboundRoute | None:
        """The inbound route that was overwritten, if the DID pointed elsewhere before.

        Typically :attr:`~voicelink.enums.InboundRoute.SIP_TRUNK` when taking a number
        over from a LiveKit deployment.
        """
        if self.previous_routing is None:
            return None
        previous = _as_inbound_route(self.previous_routing.for_inbound_call)
        return previous if previous is not InboundRoute.WEBSOCKET_BOT else None


class PipecatProvisioner:
    """Create and maintain the VoiceLink objects a Pipecat bot needs.

    .. warning::
       The bot's **WebSocket API** toggle must stay **off**. With it on, VoiceLink answers
       the call and hangs up within a second without ever opening the media WebSocket -
       verified by A/B test on a live call. The REST API exposes no field for it, so the
       SDK cannot set it; bots created here inherit the platform default. If a bot created
       through this class receives no audio, check that toggle in the portal first.

    .. note::
       ``audio_format`` is advisory. A bot configured for ``l16_16k`` was observed
       streaming ``audio/alaw`` at 8 kHz.
       :class:`~voicelink.integrations.pipecat.serializer.VoiceLinkFrameSerializer` reads
       the real format from each call's ``start`` frame, so a mismatch here is harmless.
    """

    def __init__(self, voicelink: VoiceLinkClient, *, client_id: int | None = None) -> None:
        """Initialize the provisioner.

        Args:
            voicelink: A configured :class:`~voicelink.client.VoiceLinkClient`.
            client_id: Sub-account to operate on. Required for reseller accounts unless
                the client already carries a default.
        """
        self._vl = voicelink
        self._client_id = client_id

    # ------------------------------------------------------------------ lookups

    def find_bot(self, bot_name: str) -> WebSocketBot | None:
        """Return the bot with this exact name, or ``None``.

        Args:
            bot_name: Name to match, compared case-insensitively after trimming.
        """
        wanted = bot_name.strip().casefold()
        for page in range(1, _MAX_PAGES + 1):
            result = self._vl.websocket_bots.list(
                page=page, per_page=_PER_PAGE, client_id=self._client_id
            )
            for bot in result:
                if (bot.bot_name or "").strip().casefold() == wanted:
                    return bot
            if not result.has_next:
                break
        return None

    def find_routing(self, did: str) -> CallRouting | None:
        """Return the routing rule for a DID, or ``None`` if it has none yet.

        Args:
            did: The DID in the same form the portal shows, e.g. ``"919484950416"``.
        """
        wanted = _digits(did)
        for routing in self._vl.routing.list(client_id=self._client_id):
            if _digits(routing.did_number or "") == wanted:
                return routing
        return None

    # ------------------------------------------------------------- bot lifecycle

    def ensure_bot(
        self,
        *,
        bot_name: str,
        websocket_url: str,
        webhook_url: str | None = None,
        audio_format: AudioFormat | str = AudioFormat.L16_16K,
        noise_cancel: NoiseCancel | int = NoiseCancel.OFF,
        status: Status | int | None = None,
    ) -> tuple[WebSocketBot, bool]:
        """Create the bot, or update it in place if the name already exists.

        Args:
            bot_name: Name for the bot. Also the key used to find an existing one.
            websocket_url: Public ``wss://`` address of your Pipecat server.
            webhook_url: Optional ``https://`` endpoint for call-lifecycle events.
            audio_format: Requested wire format. Advisory - see the class note.
            noise_cancel: VoiceLink's own noise suppression.
            status: Active flag. New bots default to
                :attr:`~voicelink.enums.Status.ACTIVE`; an existing bot keeps whatever it
                already has unless a value is given here. Bots streaming audio normally
                have been observed reporting ``status=0``, so this is deliberately not
                "corrected" on the caller's behalf.

        Returns:
            The bot, and ``True`` if it was newly created.
        """
        existing = self.find_bot(bot_name)
        if existing is None:
            bot = self._vl.websocket_bots.create(
                bot_name=bot_name,
                websocket_url=websocket_url,
                webhook_url=webhook_url,
                audio_format=audio_format,
                noise_cancel=noise_cancel,
                status=status if status is not None else Status.ACTIVE,
                client_id=self._client_id,
            )
            return bot, True

        # A development tunnel changes address on every restart, so re-pointing an
        # existing bot is the common case rather than the exception.
        #
        # The update endpoint is a full replace despite its name: it rejects the request
        # with 422 if bot_name or status is absent, even when neither is changing.
        #
        # Default to ACTIVE rather than echoing back whatever the list endpoint reported.
        # Call routing refuses an inactive bot ("Selected WebSocket bot is not valid, not
        # active..."), and the list endpoint has been observed reporting status=0 for bots
        # that are in use - so preserving that value makes the bot unroutable.
        keep_status = status if status is not None else Status.ACTIVE
        bot = self._vl.websocket_bots.update(
            existing.id,
            bot_name=bot_name,
            websocket_url=websocket_url,
            webhook_url=webhook_url,
            audio_format=audio_format,
            noise_cancel=noise_cancel,
            status=keep_status,
            client_id=self._client_id,
        )
        return bot, False

    # --------------------------------------------------------------- routing

    def _upsert_routing(
        self,
        did: str,
        *,
        inbound: InboundRoute | int | None = None,
        inbound_bot_id: int | None = None,
        outbound: OutboundRoute | int | None = None,
        outbound_bot_id: int | None = None,
    ) -> tuple[CallRouting, bool, CallRouting | None]:
        """Create or update a DID's single routing rule, touching only what is given.

        A DID has exactly one rule covering both directions, so changing one half must
        resend the other half untouched - otherwise pointing a number at a Pipecat bot
        would silently drop a working SIP trunk on the opposite direction.
        """
        existing = self.find_routing(did)

        if existing is None:
            routing = self._vl.routing.create(
                did_number=did,
                inbound=inbound if inbound is not None else InboundRoute.WEBSOCKET_BOT,
                outbound=outbound if outbound is not None else OutboundRoute.ONLY_ANSWER,
                inbound_websocket_bot_id=inbound_bot_id,
                outbound_websocket_bot_id=outbound_bot_id,
                status=Status.ACTIVE,
            )
            return routing, True, None

        # For each direction: if a bot id was supplied we are taking that direction over,
        # so send the bot and drop the old trunk. If not, echo back what is already there.
        takes_inbound = inbound_bot_id is not None
        takes_outbound = outbound_bot_id is not None
        keep_in = existing.for_inbound_call or InboundRoute.WEBSOCKET_BOT
        keep_out = existing.for_outbound_call or OutboundRoute.ONLY_ANSWER

        routing = self._vl.routing.update(
            existing.id,
            inbound=inbound if inbound is not None else keep_in,
            outbound=outbound if outbound is not None else keep_out,
            status=Status.ACTIVE,
            inbound_sip_trunk_id=None if takes_inbound else existing.inbound_sip_trunk_id,
            inbound_websocket_bot_id=inbound_bot_id or existing.inbound_websocket_bot_id,
            outbound_sip_trunk_id=None if takes_outbound else existing.outbound_sip_trunk_id,
            outbound_websocket_bot_id=outbound_bot_id or existing.outbound_websocket_bot_id,
        )
        return routing, False, existing

    def route_inbound_to_bot(
        self,
        *,
        did: str,
        bot_id: int,
        outbound: OutboundRoute | int | None = None,
    ) -> tuple[CallRouting, bool, CallRouting | None]:
        """Point a DID's **inbound** calls at a WebSocket bot.

        Replaces whatever the DID's inbound half pointed at before. Nothing is deleted -
        a SIP trunk routed here still exists and can be restored with
        :meth:`restore_previous` or :meth:`restore_sip_trunk`.

        Args:
            did: The DID to route.
            bot_id: Target bot, from :meth:`ensure_bot`.
            outbound: Outbound behaviour. When omitted the outbound half is left exactly
                as it was, and a brand-new rule gets
                :attr:`~voicelink.enums.OutboundRoute.ONLY_ANSWER`.

        Returns:
            The routing rule, ``True`` if newly created, and a snapshot of the rule as it
            was beforehand (``None`` if the DID had none).
        """
        return self._upsert_routing(
            did, inbound=InboundRoute.WEBSOCKET_BOT, inbound_bot_id=bot_id, outbound=outbound
        )

    def route_outbound_to_bot(
        self,
        *,
        did: str,
        bot_id: int,
        inbound: InboundRoute | int | None = None,
    ) -> tuple[CallRouting, bool, CallRouting | None]:
        """Point a DID's **outbound** calls at a WebSocket bot.

        Required before :meth:`place_call`: VoiceLink refuses to dial unless the DID has
        an active outbound WebSocket bot configured.

        Args:
            did: The DID calls will originate from.
            bot_id: Target bot, from :meth:`ensure_bot`.
            inbound: Inbound behaviour. When omitted the inbound half is left exactly as
                it was, so a number already answering on LiveKit keeps doing so.

        Returns:
            The routing rule, ``True`` if newly created, and a snapshot of the rule as it
            was beforehand (``None`` if the DID had none).
        """
        return self._upsert_routing(
            did, outbound=OutboundRoute.WEBSOCKET_BOT, outbound_bot_id=bot_id, inbound=inbound
        )

    def restore_sip_trunk(
        self,
        *,
        did: str,
        sip_trunk_id: int,
        inbound: bool = True,
        outbound: bool = True,
    ) -> CallRouting:
        """Hand a DID back to a SIP trunk, in one or both directions.

        Restoring only one direction leaves the other pointed at the bot, which is easy to
        miss on a shared number: after testing outbound, an inbound-only restore leaves
        outbound calls still going through Pipecat. Both directions are restored by
        default for that reason.

        Args:
            did: The DID to re-route.
            sip_trunk_id: The SIP trunk to hand the chosen directions back to.
            inbound: Restore inbound calls to the trunk.
            outbound: Restore outbound calls to the trunk.

        Returns:
            The routing rule as it now stands, re-read from the API. The update endpoint
            answers with only ``{"id": ...}`` and no other fields, so its response cannot
            be shown to a caller - every field would read ``None`` and look like the DID
            had been wiped. This method re-reads instead, at the cost of one extra request,
            because handing a number back to a live integration is precisely where a
            caller needs to see confirmed state rather than a hopeful echo.

        Raises:
            ValueError: If the DID has no routing rule, or neither direction was selected.
        """
        if not inbound and not outbound:
            raise ValueError("Select at least one of inbound or outbound to restore")
        existing = self.find_routing(did)
        if existing is None:
            raise ValueError(f"DID {did!r} has no routing rule to restore")

        self._vl.routing.update(
            existing.id,
            inbound=InboundRoute.SIP_TRUNK if inbound else (
                existing.for_inbound_call or InboundRoute.WEBSOCKET_BOT
            ),
            outbound=OutboundRoute.SIP_TRUNK if outbound else (
                existing.for_outbound_call or OutboundRoute.ONLY_ANSWER
            ),
            status=Status.ACTIVE,
            inbound_sip_trunk_id=sip_trunk_id if inbound else existing.inbound_sip_trunk_id,
            inbound_websocket_bot_id=None if inbound else existing.inbound_websocket_bot_id,
            outbound_sip_trunk_id=sip_trunk_id if outbound else existing.outbound_sip_trunk_id,
            outbound_websocket_bot_id=None if outbound else existing.outbound_websocket_bot_id,
        )
        return self.find_routing(did) or existing

    def restore_previous(self, provisioned: Provisioned) -> CallRouting:
        """Put a DID back exactly as it was before :meth:`setup_inbound`.

        Restores every field of the previous rule - inbound and outbound handler, their
        ids, and status - so a number borrowed for a Pipecat test returns to its original
        integration untouched. The bot stays registered and can be re-selected later.

        Args:
            provisioned: The result returned by :meth:`setup_inbound`.

        Returns:
            The restored routing rule.

        Raises:
            ValueError: If the DID had no routing rule before, leaving nothing to restore.
        """
        previous = provisioned.previous_routing
        if previous is None:
            raise ValueError(
                "Nothing to restore: this DID had no routing rule before setup_inbound()"
            )
        return self._vl.routing.update(
            previous.id,
            inbound=previous.for_inbound_call or InboundRoute.WEBSOCKET_BOT,
            outbound=previous.for_outbound_call or OutboundRoute.ONLY_ANSWER,
            status=previous.status or Status.ACTIVE,
            inbound_sip_trunk_id=previous.inbound_sip_trunk_id,
            inbound_websocket_bot_id=previous.inbound_websocket_bot_id,
            outbound_sip_trunk_id=previous.outbound_sip_trunk_id,
            outbound_websocket_bot_id=previous.outbound_websocket_bot_id,
        )

    # ------------------------------------------------------------ the one-liner

    def setup_inbound(
        self,
        *,
        bot_name: str,
        websocket_url: str,
        did: str,
        webhook_url: str | None = None,
        audio_format: AudioFormat | str = AudioFormat.L16_16K,
        noise_cancel: NoiseCancel | int = NoiseCancel.OFF,
        outbound: OutboundRoute | int | None = None,
    ) -> Provisioned:
        """Register the bot and route a DID to it, in one call.

        This is the whole VoiceLink-side setup for an inbound Pipecat agent, and replaces
        the manual portal sequence of create-bot then configure-routing. Safe to re-run.

        Args:
            bot_name: Name for the bot; reused to find an existing one.
            websocket_url: Public ``wss://`` address of your Pipecat server.
            did: The number callers dial.
            webhook_url: Optional ``https://`` endpoint for call-lifecycle events.
            audio_format: Requested wire format. Advisory - see the class note.
            noise_cancel: VoiceLink's own noise suppression.
            outbound: Outbound behaviour; existing settings are preserved when omitted.

        Returns:
            A :class:`Provisioned` describing what was created or changed.
        """
        bot, bot_created = self.ensure_bot(
            bot_name=bot_name,
            websocket_url=websocket_url,
            webhook_url=webhook_url,
            audio_format=audio_format,
            noise_cancel=noise_cancel,
        )
        routing, routing_created, previous = self.route_inbound_to_bot(
            did=did, bot_id=bot.id, outbound=outbound
        )
        return Provisioned(
            bot=bot,
            routing=routing,
            bot_created=bot_created,
            routing_created=routing_created,
            previous_routing=previous,
        )


    def setup_outbound(
        self,
        *,
        bot_name: str,
        websocket_url: str,
        did: str,
        webhook_url: str | None = None,
        audio_format: AudioFormat | str = AudioFormat.L16_16K,
        noise_cancel: NoiseCancel | int = NoiseCancel.OFF,
        inbound: InboundRoute | int | None = None,
    ) -> Provisioned:
        """Register the bot and route a DID's outbound calls to it, in one call.

        The mirror of :meth:`setup_inbound`. Run this before :meth:`place_call`. The
        inbound half is left untouched, so the same DID can answer on one integration
        while dialling out through Pipecat.

        Args:
            bot_name: Name for the bot; reused to find an existing one.
            websocket_url: Public ``wss://`` address of your Pipecat server.
            did: The number calls originate from.
            webhook_url: Optional ``https://`` endpoint for call-lifecycle events.
            audio_format: Requested wire format. Advisory - see the class note.
            noise_cancel: VoiceLink's own noise suppression.
            inbound: Inbound behaviour; left as-is when omitted.

        Returns:
            A :class:`Provisioned` describing what was created or changed.
        """
        bot, bot_created = self.ensure_bot(
            bot_name=bot_name,
            websocket_url=websocket_url,
            webhook_url=webhook_url,
            audio_format=audio_format,
            noise_cancel=noise_cancel,
        )
        routing, routing_created, previous = self.route_outbound_to_bot(
            did=did, bot_id=bot.id, inbound=inbound
        )
        return Provisioned(
            bot=bot,
            routing=routing,
            bot_created=bot_created,
            routing_created=routing_created,
            previous_routing=previous,
        )

    def place_call(
        self,
        *,
        did: str,
        customer_number: str,
        custom_parameters: Mapping[str, Any] | None = None,
        country_code: str | None = None,
        websocket_url: str | None = None,
        webhook_url: str | None = None,
    ) -> LeadResult:
        """Ask VoiceLink to dial a number and connect it to the bot.

        Pipecat has no telephony of its own and cannot originate a call, so VoiceLink
        places it. Requires :meth:`setup_outbound` to have run for this DID.

        ``websocket_url`` overrides the bot's registered address for this one call, which
        lets a single bot registration serve many different agents - useful for resellers
        running one bot per customer without creating a bot record for each.

        ``custom_parameters`` travels with the call and arrives in the media ``start``
        frame, so the agent can identify who it is calling. VoiceLink also injects an
        ``outboundQueueId`` there for correlating webhooks back to this request.

        .. important::
           VoiceLink wants the **national** number plus ``country_code`` separately. A
           number with the country code baked in and no ``country_code`` produces a dial
           string the carrier cannot route, and the call fails with
           ``38 - Network out of order`` - which reads like a dead carrier rather than a
           malformed request. Verified live: ``919000000001`` alone failed with cause 38,
           while ``9000000001`` with ``country_code="91"`` connected normally (cause 16).

           To make that unhittable, a country code present on both arguments is stripped
           from the number before sending, so all three of these dial the same person::

               place_call(customer_number="9000000001", country_code="91")
               place_call(customer_number="919000000001", country_code="91")
               place_call(customer_number="+91 90000-00001", country_code="+91")

        .. warning::
           This dials a real number and consumes account balance. Unlike inbound setup,
           nothing here is free to test.

        Args:
            did: The DID to originate from; must have an active outbound bot.
            customer_number: The number to dial.
            custom_parameters: Arbitrary data delivered back on the ``start`` frame.
            country_code: Optional country code for ``customer_number``.
            websocket_url: Per-call override of the bot's WebSocket address.
            webhook_url: Per-call override of the bot's webhook address.

        Returns:
            The queued lead, carrying the id that later webhooks refer to.
        """
        return self._vl.calls.create(
            did_number=did,
            customer_number=_national_number(customer_number, country_code),
            custom_parameters=custom_parameters,
            country_code=country_code,
            websocket_url=websocket_url,
            webhook_url=webhook_url,
        )


def _national_number(customer_number: str, country_code: str | None) -> str:
    """Strip a leading country code so VoiceLink receives the national number.

    Sending the country code twice - once inside the number, once as ``country_code`` -
    yields a dial string the carrier rejects with ``38 - Network out of order``. Only
    strips when the prefix is genuinely redundant and digits remain after it, so a
    national number that happens to begin with the same digits is left alone.
    """
    digits = _digits(customer_number)
    prefix = _digits(country_code or "")
    if prefix and digits.startswith(prefix) and len(digits) > len(prefix):
        return digits[len(prefix):]
    return digits


def _digits(value: str) -> str:
    """Reduce a phone number to bare digits so formatting differences don't matter."""
    return "".join(ch for ch in value if ch.isdigit())


def _as_inbound_route(value: int | None) -> InboundRoute | None:
    """Best-effort conversion of a raw route integer into its enum member."""
    if value is None:
        return None
    try:
        return InboundRoute(value)
    except ValueError:
        return None

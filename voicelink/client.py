"""The VoiceLink client — the object you construct and use.

    from voicelink import VoiceLinkClient
    from voicelink.enums import InboundRoute, OutboundRoute

    client = VoiceLinkClient(api_token="…", client_id=560)

    bot = client.websocket_bots.create(
        bot_name="Support",
        websocket_url="wss://my-agent.example.com/ws",
    )
    client.routing.create(
        did_number="919484950416",
        inbound=InboundRoute.WEBSOCKET_BOT,
        inbound_websocket_bot_id=bot.id,
        outbound=OutboundRoute.WEBSOCKET_BOT,
        outbound_websocket_bot_id=bot.id,
    )

Authenticate with a long-lived API token, or exchange a username/password once with
:meth:`VoiceLinkClient.login`.
"""

from __future__ import annotations

import httpx

from ._transport import Transport
from .errors import VoiceLinkConnectionError, error_from_status
from .resources import (
    AgentsResource,
    AuthResource,
    CallLogsResource,
    CallRoutingResource,
    CallSettingsResource,
    CallsResource,
    ClientsResource,
    DidsResource,
    KycResource,
    PaymentsResource,
    PurchaseResource,
    RenewalsResource,
    ResellerResource,
    SipTrunksResource,
    SoundsResource,
    SubUsersResource,
    TimeSettingsResource,
    WebSocketBotsResource,
    WebsocketManagementResource,
    WebsocketTimeGroupsResource,
)

# Production base URL. NOTE: confirm the production API host with VoiceLink — this is
# inferred from the platform domain and can be overridden via ``base_url``.
DEFAULT_BASE_URL = "https://app.voicelink.co.in/api"
#: The UAT / staging environment, for convenience during development.
UAT_BASE_URL = "https://voicelinkuat.elisiontec.com/api"


class VoiceLinkClient:
    """Entry point to the VoiceLink API.

    Args:
        api_token: A bearer token for authentication.
        base_url: API base URL. Defaults to production; use :data:`UAT_BASE_URL` for
            staging, or pass your own.
        client_id: Default client (tenant) id applied to reseller-scoped calls when one
            is not passed explicitly. Optional.
        timeout: Per-request timeout in seconds.
        max_retries: How many times to retry transient network / 5xx failures.
    """

    def __init__(
        self,
        api_token: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        client_id: int | None = None,
        timeout: float = 30.0,
        max_retries: int = 2,
    ) -> None:
        if not api_token:
            raise ValueError("api_token is required")

        self.base_url = base_url.rstrip("/")
        self.client_id = client_id
        self._transport = Transport(
            self.base_url,
            api_token,
            timeout=timeout,
            max_retries=max_retries,
        )

        # Resource namespaces.
        # -- telephony (connect numbers to agents) --
        self.websocket_bots = WebSocketBotsResource(self)
        self.sip_trunks = SipTrunksResource(self)
        self.routing = CallRoutingResource(self)
        self.calls = CallsResource(self)
        self.dids = DidsResource(self)
        self.call_logs = CallLogsResource(self)
        self.agents = AgentsResource(self)
        # -- IVR / scheduling config --
        self.sounds = SoundsResource(self)
        self.time_settings = TimeSettingsResource(self)
        self.call_settings = CallSettingsResource(self)
        self.websocket_management = WebsocketManagementResource(self)
        self.websocket_time_groups = WebsocketTimeGroupsResource(self)
        # -- account / reseller administration --
        self.auth = AuthResource(self)
        self.clients = ClientsResource(self)
        self.reseller = ResellerResource(self)
        self.sub_users = SubUsersResource(self)
        self.purchase = PurchaseResource(self)
        self.renewals = RenewalsResource(self)
        self.kyc = KycResource(self)
        self.payments = PaymentsResource(self)

    # -- construction from credentials -------------------------------------------

    @classmethod
    def login(
        cls,
        username: str,
        password: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        client_id: int | None = None,
        timeout: float = 30.0,
        max_retries: int = 2,
    ) -> VoiceLinkClient:
        """Exchange a username/password for a token and return a ready client."""
        token = _login_for_token(base_url, username, password, timeout=timeout)
        return cls(
            token,
            base_url=base_url,
            client_id=client_id,
            timeout=timeout,
            max_retries=max_retries,
        )

    # -- lifecycle ---------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        self._transport.close()

    def __enter__(self) -> VoiceLinkClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def _login_for_token(base_url: str, username: str, password: str, *, timeout: float) -> str:
    """POST /v1/auth/login and return the bearer token from the response."""
    url = base_url.rstrip("/") + "/v1/auth/login"
    try:
        response = httpx.post(
            url,
            json={"username": username, "password": password},
            headers={"Accept": "application/json"},
            timeout=timeout,
        )
    except httpx.TransportError as exc:
        raise VoiceLinkConnectionError(f"Could not reach VoiceLink: {exc}") from exc

    payload = response.json() if response.content else None
    failed = response.status_code >= 400 or (
        isinstance(payload, dict) and payload.get("status") is False
    )
    if failed:
        message = None
        if isinstance(payload, dict):
            message = payload.get("message")
        raise error_from_status(response.status_code, message or "Login failed", payload=payload)

    data = payload.get("data") if isinstance(payload, dict) else None
    token = None
    if isinstance(data, dict):
        token = data.get("token") or data.get("access_token") or data.get("plain_api_token")
    if not token:
        raise error_from_status(
            response.status_code or 500,
            "Login succeeded but no token was returned",
            payload=payload,
        )
    return token

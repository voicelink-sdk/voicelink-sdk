"""Shared helpers for the VoiceLink <-> LiveKit setup scripts in this folder.

Keep this file next to provision_inbound.py, provision_outbound.py and check_setup.py -
they import it. Settings come from a `.env` file in the current directory (see
env.example); real environment variables win over it.
"""

from __future__ import annotations

import asyncio
import ipaddress
import os
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path

from voicelink import UAT_BASE_URL, VoiceLinkClient
from voicelink.enums import InboundRoute, OutboundRoute, SipCodec, Status, TransportType
from voicelink.errors import AuthenticationError, VoiceLinkError

INBOUND_TRUNK_NAME = "voicelink-inbound"
OUTBOUND_TRUNK_NAME = "voicelink-outbound"
VOICELINK_TRUNK_NAME = "livekit-bridge"
PEER_MONITORING_REMINDER = (
    "  ACTION NEEDED  : in the VoiceLink portal (Voice Services -> SIP Trunk Management -> edit"
    " this trunk) turn Peer Monitoring ON. The API cannot set it, and without it inbound calls"
    ' fail with "out of network coverage" (CHANUNAVAIL).'
)


# ------------------------------------------------------------------ settings


def load_dotenv(path: str = ".env") -> None:
    """Read KEY=VALUE lines from `path` if it exists. Real environment variables win."""
    file = Path(path)
    if not file.is_file():
        return
    for line in file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.split(" #", 1)[0].strip().strip("\"'")  # drop inline comments
        os.environ.setdefault(key.strip(), value)


def need(name: str) -> str:
    """A required setting, or a clear exit naming it."""
    value = os.environ.get(name, "").strip()
    if not value:
        sys.exit(f"{name} is not set. Add it to .env (see env.example).")
    return value


def digits(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit())


def did() -> str:
    number = digits(need("VOICELINK_DID"))
    if len(number) < 8:
        sys.exit("VOICELINK_DID must be the full number with country code, e.g. 91XXXXXXXXXX.")
    return number


def bridge() -> tuple[str, int]:
    """The SIP bridge's public IPv4 and port. An IP is required: it becomes the LiveKit
    inbound trunk's allowlist entry `<ip>/32`, which a hostname cannot be."""
    host = need("VOICELINK_BRIDGE_HOST")
    try:
        ipaddress.IPv4Address(host)
    except ValueError:
        sys.exit(f"VOICELINK_BRIDGE_HOST must be the bridge's public IPv4 address "
                 f"(e.g. 203.0.113.10), got {host!r}.")
    port_text = need("VOICELINK_BRIDGE_PORT")
    if not port_text.isdigit() or not 0 < int(port_text) < 65536:
        sys.exit(f"VOICELINK_BRIDGE_PORT must be a port number, got {port_text!r}.")
    return host, int(port_text)


def agent_name() -> str:
    return os.environ.get("LIVEKIT_AGENT_NAME", "").strip() or "voice-assistant"


def voicelink_client() -> VoiceLinkClient:
    base = os.environ.get("VOICELINK_BASE_URL", "").strip() or UAT_BASE_URL
    cid_text = os.environ.get("VOICELINK_CLIENT_ID", "").strip()
    if cid_text and not cid_text.isdigit():
        sys.exit(f"VOICELINK_CLIENT_ID must be a number, got {cid_text!r}.")
    cid = int(cid_text) if cid_text else None
    token = os.environ.get("VOICELINK_TOKEN", "").strip()
    if token:
        return VoiceLinkClient(token, base_url=base, client_id=cid)
    return VoiceLinkClient.login(
        need("VOICELINK_USER"), need("VOICELINK_PASS"), base_url=base, client_id=cid
    )


def require_livekit_settings() -> None:
    """Check LiveKit settings before any network call, so the message names the setting."""
    url = need("LIVEKIT_URL")
    if not url.startswith(("wss://", "https://", "ws://", "http://")):
        sys.exit(f"LIVEKIT_URL must look like wss://your-project.livekit.cloud, got {url!r}.")
    need("LIVEKIT_API_KEY")
    need("LIVEKIT_API_SECRET")


def livekit_provisioner(vl: VoiceLinkClient):
    from voicelink.integrations.livekit import LiveKitProvisioner

    url = need("LIVEKIT_URL")
    if not url.startswith(("wss://", "https://", "ws://", "http://")):
        sys.exit(f"LIVEKIT_URL must look like wss://your-project.livekit.cloud, got {url!r}.")
    return LiveKitProvisioner(
        livekit_url=url,
        api_key=need("LIVEKIT_API_KEY"),
        api_secret=need("LIVEKIT_API_SECRET"),
        voicelink=vl,
    )


# ------------------------------------------------------------------ VoiceLink lookups


def find_voicelink_trunk(vl: VoiceLinkClient, host: str, port: int):
    """The trunk at the bridge's host, else one named livekit-bridge.

    VoiceLink allows only one trunk per SIP server host (a second create fails with 422
    "This SIP server host is already in use") and has no delete endpoint, so a trunk on the
    bridge host is reused - and repointed if its port differs - never duplicated.
    """
    by_name = None
    for page in range(1, 51):
        result = vl.sip_trunks.list(page=page, per_page=100)
        for trunk in result:
            if (trunk.sip_server_host or "").strip() == host:
                return trunk
            if (trunk.trunk_name or "").strip().casefold() == VOICELINK_TRUNK_NAME:
                by_name = by_name or trunk
        if not result.has_next:
            break
    return by_name


def trunk_credentials() -> tuple[str | None, str | None]:
    """Fixed trunk digest credentials from .env, so the bridge is configured once.

    The bridge's outbound leg authenticates to VoiceLink with these. Left unset, VoiceLink
    generates new ones for every trunk, which then have to be copied into the bridge by hand.
    """
    user = os.environ.get("VOICELINK_TRUNK_USERNAME", "").strip() or None
    password = os.environ.get("VOICELINK_TRUNK_PASSWORD", "").strip() or None
    if bool(user) != bool(password):
        sys.exit("Set both VOICELINK_TRUNK_USERNAME and VOICELINK_TRUNK_PASSWORD, or neither.")
    return user, password


def ensure_voicelink_trunk(vl: VoiceLinkClient, host: str, port: int):
    """Reuse the bridge trunk if VoiceLink already has one; repoint or create otherwise."""
    user, password = trunk_credentials()
    trunk = find_voicelink_trunk(vl, host, port)
    if trunk is None:
        trunk = vl.sip_trunks.create_custom(
            trunk_name=VOICELINK_TRUNK_NAME,
            sip_server_host=host,
            sip_server_port=port,
            transport_type=TransportType.UDP,
            audio_format=[SipCodec.ALAW],
            username=user,
            registration_password=password,
        )
        if not user:
            print("  NOTE           : VoiceLink generated this trunk's username/password. Copy them from"
                  " the portal into the bridge's outbound auth, or set VOICELINK_TRUNK_USERNAME/PASSWORD"
                  " in .env so every run uses the same ones.")
        print(f"VoiceLink trunk  : created {trunk.trunk_name!r} (id {trunk.id}) -> {host}:{port}")
        print(PEER_MONITORING_REMINDER)
        portal = (os.environ.get("VOICELINK_BASE_URL", "").strip() or UAT_BASE_URL)
        portal = portal.rstrip("/").removesuffix("/api")
        print(f"                  Open: {portal}/admin/sip-trunks/{trunk.id}/edit")
        return trunk
    creds_differ = bool(user) and (trunk.username or "") != user
    if creds_differ or (trunk.sip_server_host, trunk.sip_server_port, trunk.status) != (host, port, Status.ACTIVE):
        # The update endpoint needs trunk_name and status on every call.
        vl.sip_trunks.update(
            trunk.id, trunk_name=trunk.trunk_name or VOICELINK_TRUNK_NAME, status=Status.ACTIVE,
            sip_server_host=host, sip_server_port=port,
            username=user, registration_password=password,
        )
        print(f"VoiceLink trunk  : repointed {trunk.trunk_name!r} (id {trunk.id}) -> {host}:{port}")
    else:
        print(f"VoiceLink trunk  : reusing {trunk.trunk_name!r} (id {trunk.id}) -> {host}:{port}")
    return trunk


def find_routing(vl: VoiceLinkClient, number: str):
    for rule in vl.routing.list():
        if digits(rule.did_number or "") == number:
            return rule
    return None


def route_to_trunk(vl: VoiceLinkClient, number: str, trunk_id: int, *, inbound: bool, outbound: bool):
    """Set the chosen direction(s) of the DID's single routing rule for a SIP-bridge setup.

    Inbound  -> SIP trunk (VoiceLink delivers callers to the bridge).
    Outbound -> ONLY_ANSWER, with no trunk. Calls placed by the bridge already arrive on the
                trunk; routing the DID's outbound half to the SIP trunk makes VoiceLink send the
                answered call back to the bridge as a second, inbound call - two LiveKit calls,
                a media-timeout on the real one and a drop after ~45 s (verified on a live call).

    The other direction is sent back unchanged.
    """
    rule = find_routing(vl, number)
    if rule is None:
        vl.routing.create(
            did_number=number,
            inbound=InboundRoute.SIP_TRUNK, inbound_sip_trunk_id=trunk_id,
            outbound=OutboundRoute.ONLY_ANSWER,
        )
        print(f"Routing          : created - DID {number} inbound -> trunk {trunk_id}, outbound only-answer")
        return
    vl.routing.update(
        rule.id,
        inbound=InboundRoute.SIP_TRUNK if inbound else (rule.for_inbound_call or InboundRoute.SIP_TRUNK),
        outbound=OutboundRoute.ONLY_ANSWER if outbound else (rule.for_outbound_call or OutboundRoute.ONLY_ANSWER),
        status=Status.ACTIVE,
        inbound_sip_trunk_id=trunk_id if inbound else rule.inbound_sip_trunk_id,
        inbound_websocket_bot_id=None if inbound else rule.inbound_websocket_bot_id,
        outbound_sip_trunk_id=None if outbound else rule.outbound_sip_trunk_id,
        outbound_websocket_bot_id=None if outbound else rule.outbound_websocket_bot_id,
    )
    parts = []
    if inbound:
        parts.append(f"inbound -> trunk {trunk_id}")
    if outbound:
        parts.append("outbound -> only-answer")
    print(f"Routing          : updated - DID {number} {', '.join(parts)}")


# ------------------------------------------------------------------ running


def run(main: Callable[[], Awaitable[None]]) -> None:
    """Run an async main with .env loaded and every common failure turned into one line."""
    load_dotenv()
    try:
        from livekit.api import TwirpError
    except ImportError:
        sys.exit('LiveKit API library missing:  pip install -e ".[livekit]"  (from the SDK repo root)')
    try:
        asyncio.run(main())
    except AuthenticationError as exc:
        sys.exit(f"VoiceLink rejected the login or token: {exc}\n"
                 "Check VOICELINK_USER/VOICELINK_PASS (or VOICELINK_TOKEN) and VOICELINK_BASE_URL.")
    except VoiceLinkError as exc:
        sys.exit(f"VoiceLink error: {exc}")
    except TwirpError as exc:
        hint = ""
        if "unauthenticated" in str(exc).lower() or "401" in str(exc):
            hint = "\nCheck LIVEKIT_URL, LIVEKIT_API_KEY and LIVEKIT_API_SECRET."
        sys.exit(f"LiveKit error: {exc}{hint}")
    except OSError as exc:
        sys.exit(f"Network error: {exc}\nCheck your internet connection and LIVEKIT_URL.")

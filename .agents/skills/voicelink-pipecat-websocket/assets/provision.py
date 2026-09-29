"""Configure VoiceLink for a Pipecat bot: show, inbound, outbound, test call, restore.

    pip install -e ".[pipecat]"                 # from the voicelink-sdk repo root
    python provision.py show                     # what the DID points at now (read-only)
    python provision.py inbound                  # callers -> VoiceLink -> your bot
    python provision.py outbound                 # route outbound calls to your bot
    python provision.py outbound --call          # ...and dial CALL_TO (spends balance)
    python provision.py restore <sip_trunk_id>   # hand the DID back to a SIP trunk
    python provision.py restore <id> --inbound-only | --outbound-only

Settings come from a `.env` file in the current directory (see env.example); real
environment variables win over it. Every mode is safe to re-run: the bot is found by name
and updated, and the DID's single routing rule is updated rather than duplicated. Only the
direction you configure changes - the other half of the rule is left exactly as it was.

Start the bot server (pipecat_bot.py) and its public tunnel BEFORE `inbound` or
`outbound --call`: VoiceLink connects to it on the next call.
"""

import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

from voicelink import UAT_BASE_URL, VoiceLinkClient
from voicelink.errors import AuthenticationError, VoiceLinkError
from voicelink.integrations.pipecat import PipecatProvisioner

USAGE = __doc__


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


def ws_url() -> str:
    url = need("VOICELINK_WS_URL")
    parts = urlsplit(url)
    if parts.scheme != "wss" or not parts.netloc:
        sys.exit(f"VOICELINK_WS_URL must be a public wss:// address, got {url!r}.")
    if parts.path not in ("", "/"):
        print(f"Note: VOICELINK_WS_URL has path {parts.path!r}; pipecat_bot.py serves at '/'.")
    return url


def bot_name() -> str:
    return os.environ.get("VOICELINK_BOT_NAME", "").strip() or "pipecat-agent"


def webhook_url() -> str | None:
    return os.environ.get("VOICELINK_WEBHOOK_URL", "").strip() or None


def describe(routing) -> None:
    print(f"  routing id : {routing.id}")
    print(f"  inbound    : {routing.for_inbound_call}  (sip_trunk={routing.inbound_sip_trunk_id}, "
          f"bot={routing.inbound_websocket_bot_id})")
    print(f"  outbound   : {routing.for_outbound_call}  (sip_trunk={routing.outbound_sip_trunk_id}, "
          f"bot={routing.outbound_websocket_bot_id})")
    print("  (route codes: 1 mobile, 2 SIP trunk, 3 WebSocket bot, 4 only answer)")


# ------------------------------------------------------------------------------ modes


def show(prov: PipecatProvisioner, did: str) -> None:
    routing = prov.find_routing(did)
    if routing is None:
        print(f"DID {did} has no routing rule yet.")
    else:
        print(f"DID {did}")
        describe(routing)
    bot = prov.find_bot(bot_name())
    if bot is None:
        print(f"No bot named {bot_name()!r} yet.")
    else:
        print(f"Bot {bot.bot_name!r}: id={bot.id} url={bot.websocket_url}")


def inbound(prov: PipecatProvisioner, did: str) -> None:
    url = ws_url()
    result = prov.setup_inbound(
        bot_name=bot_name(), websocket_url=url, did=did, webhook_url=webhook_url()
    )
    print(f"Bot     : id={result.bot.id} -> {url} "
          f"({'created' if result.bot_created else 'updated'})")
    print(f"Routing : {'created' if result.routing_created else 'updated'} - "
          f"inbound calls to {did} now go to the bot")
    previous = result.previous_routing
    if result.replaced_inbound is not None and previous is not None:
        print(f"\nInbound was on {result.replaced_inbound.name} "
              f"(trunk {previous.inbound_sip_trunk_id}). To hand it back:")
        print(f"    python provision.py restore {previous.inbound_sip_trunk_id} --inbound-only")
    print("\nIn the VoiceLink portal, make sure this bot's 'WebSocket API' toggle is OFF,")
    print(f"then call {did}.")


def outbound(prov: PipecatProvisioner, did: str, place: bool) -> None:
    url = ws_url()
    to_number = country = None
    if place:  # validate before changing anything
        to_number = need("CALL_TO")
        country = os.environ.get("CALL_COUNTRY_CODE", "").strip() or "91"
    result = prov.setup_outbound(
        bot_name=bot_name(), websocket_url=url, did=did, webhook_url=webhook_url()
    )
    print(f"Bot     : id={result.bot.id} -> {url} "
          f"({'created' if result.bot_created else 'updated'})")
    print(f"Routing : {'created' if result.routing_created else 'updated'} - "
          f"outbound calls from {did} now go through the bot")
    previous = result.previous_routing
    if previous is not None and previous.outbound_sip_trunk_id:
        print(f"\nOutbound was on SIP trunk {previous.outbound_sip_trunk_id}. To hand it back:")
        print(f"    python provision.py restore {previous.outbound_sip_trunk_id} --outbound-only")

    if not place:
        print("\nNothing was dialled. Run `outbound --call` to place a test call.")
        return
    # National number and country code travel separately; place_call strips a duplicated
    # prefix, so "919XXXXXXXXX" and "9XXXXXXXXX" both work with country code 91.
    print(f"\nDialling +{country} {to_number} from {did} (this spends balance) ...")
    lead = prov.place_call(
        did=did,
        customer_number=to_number,
        country_code=country,
        custom_parameters={"source": "provision.py"},  # arrives on the bot's start frame
    )
    print(f"Queued  : outbound_queue_id={lead.outbound_queue_id}")
    print("Answer the phone; the bot server log should show the call connect.")


def restore(prov: PipecatProvisioner, did: str, args: list[str]) -> None:
    trunk_ids = [a for a in args if not a.startswith("--")]
    if len(trunk_ids) != 1 or not trunk_ids[0].isdigit():
        sys.exit("Usage: python provision.py restore <sip_trunk_id> "
                 "[--inbound-only | --outbound-only]\nRun `show` to see the trunk ids.")
    only_in, only_out = "--inbound-only" in args, "--outbound-only" in args
    if only_in and only_out:
        sys.exit("Choose at most one of --inbound-only and --outbound-only.")
    routing = prov.restore_sip_trunk(
        did=did, sip_trunk_id=int(trunk_ids[0]), inbound=not only_out, outbound=not only_in
    )
    print(f"DID {did} handed back to SIP trunk {trunk_ids[0]}:")
    describe(routing)


def main(argv: list[str]) -> None:
    if not argv or argv[0] not in ("show", "inbound", "outbound", "restore"):
        sys.exit(USAGE)
    load_dotenv()
    mode, rest = argv[0], argv[1:]
    did = need("VOICELINK_DID")
    try:
        prov = PipecatProvisioner(voicelink_client())
        if mode == "show":
            show(prov, did)
        elif mode == "inbound":
            inbound(prov, did)
        elif mode == "outbound":
            outbound(prov, did, place="--call" in rest)
        else:
            restore(prov, did, rest)
    except AuthenticationError as exc:
        sys.exit(f"VoiceLink rejected the login or token: {exc}\n"
                 "Check VOICELINK_USER/VOICELINK_PASS (or VOICELINK_TOKEN) and VOICELINK_BASE_URL.")
    except VoiceLinkError as exc:
        sys.exit(f"VoiceLink error: {exc}")
    except ValueError as exc:  # e.g. restore on a DID with no routing rule
        sys.exit(str(exc))


if __name__ == "__main__":
    main(sys.argv[1:])

"""Read-only check of the whole VoiceLink <-> LiveKit setup. Changes nothing.

    python check_setup.py

Lists what exists on both platforms and flags each known misconfiguration. Run it before
provisioning, and again whenever a call fails.
"""

from __future__ import annotations

from _common import (
    INBOUND_TRUNK_NAME, OUTBOUND_TRUNK_NAME, agent_name, bridge, did,
    find_routing, find_voicelink_trunk, livekit_provisioner, require_livekit_settings, run, voicelink_client,
)

problems: list[str] = []


def flag(msg: str) -> None:
    problems.append(msg)


async def main() -> None:
    from livekit import api as lk

    number, (host, port), agent = did(), bridge(), agent_name()
    require_livekit_settings()
    vl = voicelink_client()
    try:
        print("== VoiceLink")
        trunk = find_voicelink_trunk(vl, host, port)
        if trunk is None:
            print(f"  trunk to bridge {host}:{port}: none")
            flag("No VoiceLink trunk points at the bridge - run provision_inbound.py.")
        else:
            print(f"  trunk {trunk.trunk_name!r} id={trunk.id} -> {trunk.sip_server_host}:"
                  f"{trunk.sip_server_port} status={trunk.status}")
            if (trunk.sip_server_host, trunk.sip_server_port) != (host, port):
                flag(f"Trunk {trunk.id} points at {trunk.sip_server_host}:{trunk.sip_server_port}, "
                     f"not the bridge {host}:{port}.")
        rule = find_routing(vl, number)
        if rule is None:
            print(f"  routing for {number}: none")
            flag(f"DID {number} has no routing rule - run provision_inbound.py.")
        else:
            print(f"  routing for {number}: inbound={rule.for_inbound_call} "
                  f"(trunk {rule.inbound_sip_trunk_id}), outbound={rule.for_outbound_call} "
                  f"(trunk {rule.outbound_sip_trunk_id})  [2 = SIP trunk, 4 = only answer]")
            if trunk and (rule.for_inbound_call != 2 or rule.inbound_sip_trunk_id != trunk.id):
                flag("Inbound calls are not routed to the bridge trunk.")
            if rule.for_outbound_call == 2:
                flag("DID outbound route is SIP trunk: answered outbound calls bounce back to the bridge "
                     "as a second inbound call and drop. Run provision_outbound.py (sets only-answer).")

        async with livekit_provisioner(vl) as prov:
            print("== LiveKit")
            inbound = [t for t in await prov.list_inbound_trunks() if t.name == INBOUND_TRUNK_NAME]
            if not inbound:
                flag("No LiveKit inbound trunk - run provision_inbound.py.")
            for t in inbound:
                print(f"  inbound trunk {t.sip_trunk_id}: numbers={list(t.numbers)} "
                      f"allowed={list(t.allowed_addresses)}")
                if number not in t.numbers:
                    flag(f"LiveKit inbound trunk does not list the DID {number}.")
                if f"{host}/32" not in t.allowed_addresses:
                    flag(f"LiveKit inbound trunk does not allow the bridge {host}/32.")
                if not t.allowed_addresses and not t.auth_username:
                    flag("LiveKit inbound trunk is open to anyone - add the bridge IP allowlist.")
            rules = (await prov._api.sip.list_dispatch_rule(lk.ListSIPDispatchRuleRequest())).items
            ids = {t.sip_trunk_id for t in inbound}
            mine = [r for r in rules if ids & set(r.trunk_ids)]
            if inbound and not mine:
                flag("No dispatch rule for the inbound trunk - run provision_inbound.py.")
            for r in mine:
                agents = [a.agent_name for a in r.room_config.agents]
                print(f"  dispatch rule {r.sip_dispatch_rule_id}: agents={agents}")
                if agent not in agents:
                    flag(f"Dispatch rule sends calls to {agents}, but LIVEKIT_AGENT_NAME is {agent!r}.")
            outbound = [t for t in await prov.list_outbound_trunks() if t.name == OUTBOUND_TRUNK_NAME]
            for t in outbound:
                print(f"  outbound trunk {t.sip_trunk_id}: address={t.address} numbers={list(t.numbers)}")
                if t.address != f"{host}:{port}":
                    flag(f"LiveKit outbound trunk targets {t.address}, not the bridge {host}:{port}.")
            if not outbound:
                print("  outbound trunk: none (run provision_outbound.py if you need outbound)")
    finally:
        vl.close()

    print("\n== Result")
    if problems:
        for p in problems:
            print(f"  PROBLEM: {p}")
    else:
        print("  No problems found on VoiceLink or LiveKit.")
    print("  Not checked from here: the bridge's own config, that the agent worker is running,")
    print("  and the trunk's Peer Monitoring toggle in the VoiceLink portal - it must be ON.")


if __name__ == "__main__":
    run(main)

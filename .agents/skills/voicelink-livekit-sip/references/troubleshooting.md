# Troubleshooting VoiceLink ⇄ LiveKit SIP

From the caller's side almost every failure sounds the same ("out of network coverage", silence,
instant hang-up). Collect evidence before changing anything.

## Evidence sources

**1. VoiceLink's own record of the call** (get the call_id from the portal CDR):
```python
d = vl.call_logs.details(CALL_ID)
print(d["call_type"], d["call_status"], d["hangup_reason"], d["bot_id"])
# call_logs.pcap(...) may 404 when the channel never came up — that itself is a clue.
```

**2. Bridge SIP trace** (on the bridge host):
```bash
docker exec <bridge> asterisk -rx "pjsip set logger on"
docker logs -f <bridge> | grep -E "INVITE|OPTIONS|SIP/2.0|Dial|status="
```

**3. Packet capture on all ports** (catches traffic Asterisk never parses):
```bash
docker exec -u 0 <bridge> timeout 60 tcpdump -n -s0 -A 'net <VOICELINK_CIDR> and udp'
```
Count `INVITE` vs `OPTIONS`, and look at which destination port they hit.

**4. LiveKit** — dashboard SIP call logs / `await prov.list_inbound_trunks()`.

## Symptom → cause → fix

| Symptom | Evidence | Cause | Fix |
|---|---|---|---|
| Inbound: "out of network coverage", CDR `CHANUNAVAIL`, **no INVITE at bridge** | OPTIONS keepalives arrive and are answered, zero INVITEs | VoiceLink marks the trunk unreachable and never emits INVITE | Confirm trunk port == bridge port == router forward; ask VoiceLink to re-qualify/re-provision the trunk (toggling Peer Monitoring has worked) |
| Inbound: "out of network coverage" right after creating the trunk | CDR `CHANUNAVAIL`; few or no OPTIONS at the bridge | Trunk's **Peer Monitoring** is off | Portal -> SIP Trunk Management -> edit trunk -> Peer Monitoring ON (not settable via API) |
| Inbound: nothing at all arrives from VoiceLink | tcpdump shows 0 packets | Port blocked (ISP often blocks 5060), forward off, public IP changed | Use a high SIP port, check forward + public IP, update trunk host |
| Inbound: VoiceLink trunk pointed at LiveKit directly | CDR `CHANUNAVAIL` | VoiceLink can't do TLS | Point trunk at the bridge |
| Inbound reaches LiveKit, room empty | Room created, no agent | `agent_name` mismatch or worker not running | Match dispatch rule and worker `agent_name`; run the worker |
| Inbound reaches bridge but LiveKit rejects | 403/404 from LiveKit | Number not on inbound trunk, or bridge IP not in `allowed_addresses` | Fix trunk numbers / allowlist |
| TLS to LiveKit fails | handshake error | Dialed by IP, so no SNI | AOR contact must use the `*.sip.livekit.cloud` hostname |
| Call connects, one-way/no audio | SIP fine, RTP missing | NAT media address or RTP range not open | Set `external_media_address`, forward RTP range, keep `rtp_symmetric=yes` |
| Outbound declined `603` | LiveKit → VoiceLink directly | VoiceLink rejects LiveKit origin | Outbound trunk address = bridge |
| Outbound `403 Forbidden`, no entry in VoiceLink call logs | Bridge log: `Dial(PJSIP/...@voicelink-out)` then `403`, cause 21 | Bridge's outbound auth/host belong to another environment (e.g. UAT creds against production) or another trunk | Point the bridge at the right termination host with this trunk's username/password - set them once via VOICELINK_TRUNK_USERNAME/PASSWORD |
| Outbound "answered" instantly, phone never rings | 200 OK immediately | Bridge targets VoiceLink signalling host | Use termination host + digest auth |
| Outbound: callee hears an agent but call drops after ~45 s; LiveKit shows a second *inbound* call right after the outbound one | Outbound call ends `media-timeout`; VoiceLink logs VL-OUT then a bridge leg | DID outbound route is `SIP_TRUNK`, so VoiceLink bounces the answered call back to the bridge | Set outbound route to `ONLY_ANSWER` - `provision_outbound.py` does |
| Calls handled by an agent you didn't start; your worker logs nothing | LiveKit job shows another worker | Another worker with the same `LIVEKIT_AGENT_NAME` is running elsewhere | Stop the other worker - LiveKit gives each job to any worker with that name |
| Outbound works, but LiveKit marks it Failed `media-timeout` ~15 s after the callee hangs up | VoiceLink logs Normal Clearing; bridge log shows no BYE forwarded to LiveKit | `[livekit-in]` has no `transport=`, so Asterisk uses a transport VoiceLink's BYE can't reach | Add `transport=<your bridge UDP transport>` to `[livekit-in]` and reload pjsip |
| Outbound `401/407` | auth challenge not satisfied | Missing/wrong `outbound_auth` | Fix trunk username/password on bridge |
| Outbound cause 38 / not routed | — | Number missing country code | Dial `91XXXXXXXXXX` |
| Setup script exits naming a setting | e.g. `VOICELINK_BRIDGE_HOST must be the bridge's public IPv4` | Missing/invalid `.env` value | Fix that line in `.env` and re-run |
| `check_setup.py` reports a PROBLEM | Its message names the object | Drift between VoiceLink and LiveKit | Re-run the provision script it names - re-runs correct existing objects |
| Agent won't start: `DLL load failed ... Application Control policy` (Windows) | Agent startup message | Windows blocks a LiveKit native library | Allow it in Windows Security, or run the agent on Linux/WSL or the bridge server |
| Flood of junk calls, rooms, agent cost | many unknown callers | Open inbound trunk | `allowed_addresses=[bridge/32]`, rotate LiveKit keys |

## Checklist before a demo

1. Bridge running; `pjsip show endpoints` healthy.
2. Router forward (if behind NAT) for SIP port + RTP range; public IP unchanged.
3. `vl.sip_trunks.list()` shows the trunk at bridge host:port, UDP, active.
4. `vl.routing.list()` shows DID → that trunk.
5. LiveKit inbound trunk has the DID and bridge allowlist; dispatch rule has the right agent.
6. Agent worker running.
7. One real test call beforehand.

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
| Inbound: nothing at all arrives from VoiceLink | tcpdump shows 0 packets | Port blocked (ISP often blocks 5060), forward off, public IP changed | Use a high SIP port, check forward + public IP, update trunk host |
| Inbound: VoiceLink trunk pointed at LiveKit directly | CDR `CHANUNAVAIL` | VoiceLink can't do TLS | Point trunk at the bridge |
| Inbound reaches LiveKit, room empty | Room created, no agent | `agent_name` mismatch or worker not running | Match dispatch rule and worker `agent_name`; run the worker |
| Inbound reaches bridge but LiveKit rejects | 403/404 from LiveKit | Number not on inbound trunk, or bridge IP not in `allowed_addresses` | Fix trunk numbers / allowlist |
| TLS to LiveKit fails | handshake error | Dialed by IP, so no SNI | AOR contact must use the `*.sip.livekit.cloud` hostname |
| Call connects, one-way/no audio | SIP fine, RTP missing | NAT media address or RTP range not open | Set `external_media_address`, forward RTP range, keep `rtp_symmetric=yes` |
| Outbound declined `603` | LiveKit → VoiceLink directly | VoiceLink rejects LiveKit origin | Outbound trunk address = bridge |
| Outbound "answered" instantly, phone never rings | 200 OK immediately | Bridge targets VoiceLink signalling host | Use termination host + digest auth |
| Outbound `401/407` | auth challenge not satisfied | Missing/wrong `outbound_auth` | Fix trunk username/password on bridge |
| Outbound cause 38 / not routed | — | Number missing country code | Dial `91XXXXXXXXXX` |
| Flood of junk calls, rooms, agent cost | many unknown callers | Open inbound trunk | `allowed_addresses=[bridge/32]`, rotate LiveKit keys |

## Checklist before a demo

1. Bridge running; `pjsip show endpoints` healthy.
2. Router forward (if behind NAT) for SIP port + RTP range; public IP unchanged.
3. `vl.sip_trunks.list()` shows the trunk at bridge host:port, UDP, active.
4. `vl.routing.list()` shows DID → that trunk.
5. LiveKit inbound trunk has the DID and bridge allowlist; dispatch rule has the right agent.
6. Agent worker running.
7. One real test call beforehand.

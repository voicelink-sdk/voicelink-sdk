# Asterisk SIP Bridge — Setup Guide (VoiceLink ⇄ LiveKit Cloud)

How to build the small Asterisk "bridge" that connects a VoiceLink SIP trunk to LiveKit
Cloud, in both directions. The bridge terminates VoiceLink's **plain UDP SIP** and
re-originates to LiveKit Cloud over **TLS**, and vice-versa.

> Replace every `YOUR_...` placeholder with your own values. Nothing here is environment-
> specific except what you fill in.

---

## Why a bridge is needed

| | VoiceLink | LiveKit Cloud |
|---|---|---|
| SIP transport | plain **UDP** | **TLS only** (with SNI) |
| Auth (inbound to it) | IP-based | IP allowlist / digest |

LiveKit Cloud will **not** accept plain UDP SIP, and VoiceLink will not originate TLS SIP,
so a direct VoiceLink→LiveKit trunk fails (hangup cause `CHANUNAVAIL`). The Asterisk
bridge is the translator in the middle. It also strips VoiceLink's numeric **tech prefix**
(e.g. `45454`) before forwarding.

```
Inbound :  PSTN → VoiceLink →(UDP)→  [ Asterisk bridge ]  →(TLS)→ LiveKit → AI agent
Outbound:  AI agent → LiveKit →(TLS/UDP)→ [ Asterisk bridge ] →(UDP+auth)→ VoiceLink → PSTN
```

---

## ⚠️ Heads-up: our reference box ran behind NAT (please read)

Our test/reference deployment ran on a **home/office broadband line behind a NAT router**
— the host did **not** have a public IP directly on its interface. That works, but it
forced several NAT-specific workarounds you should be aware of. **If you deploy on a cloud
VPS with a real public IP, most of this pain disappears** — we strongly recommend that.

What NAT forced us to do (and what to watch for):

1. **Advertise the public IP in SIP.** Every transport needs
   `external_media_address` / `external_signaling_address` = the **router's public IP**,
   plus `local_net` for the private ranges. Without this, Asterisk advertises its *private*
   IP in SIP/SDP and you get failed setup or **one-way / no audio**.
2. **Port-forward on the router** — SIP + the RTP range must be forwarded from the router's
   WAN to the host's LAN IP (see the Firewall/NAT section). On a VPS you just open the
   firewall; no forwarding.
3. **Consumer ISPs often block port 5060.** Ours did — inbound `5060/udp` never arrived
   (verified: zero packets), so we moved SIP signalling to **`35060`**. If you're on a
   business line or VPS, standard `5060` is usually fine; on a home line, use a high port.
4. **Dynamic public IP.** If the ISP changes your public IP, you must update **both** the
   `external_*_address` values here **and** the host on your VoiceLink trunk. A VPS gives
   you a static IP and avoids this.
5. **Trunk shows "unreachable".** VoiceLink qualifies the trunk with SIP OPTIONS; behind
   NAT the reply must return on the same mapping. If keepalives arrive but calls fail,
   check the trunk's reachable/qualify status on the VoiceLink side and re-provision.

**Bottom line:** on a cloud VPS with a public IP, set `external_*_address` to that public
IP (or omit it — bind IP == public IP), open the firewall, use `5060`, done. The NAT notes
above only matter behind a router.

---

## Prerequisites

- A Linux host (VPS recommended) with **Docker** + **docker compose**.
- A **public IP** on the host, **or** a router you can port-forward (NAT case above).
- A **VoiceLink SIP trunk** pointing at this bridge, and its termination host + digest
  credentials (for outbound). Get from your VoiceLink account/provider.
- A **LiveKit Cloud** project and its **SIP URI** (looks like
  `YOUR_PROJECT_ID.sip.livekit.cloud`), plus an inbound trunk + dispatch rule configured in
  LiveKit (see the LiveKit SDK/CLI docs).
- The VoiceLink/carrier **signalling IP range(s)** and LiveKit's **SIP source IP ranges**
  (both are published by the respective platforms) for the IP allowlists below.

Placeholders used throughout:

| Placeholder | Meaning |
|---|---|
| `YOUR_PUBLIC_IP` | Your host's public IP (router WAN IP if behind NAT) |
| `YOUR_LAN_IP` | Host's private IP (only relevant behind NAT, e.g. `192.168.1.x`) |
| `YOUR_SIP_PORT` | SIP signalling port (`5060` on VPS; a high port like `35060` if ISP blocks 5060) |
| `YOUR_DID` | The phone number (E.164 / local digits) |
| `YOUR_TECH_PREFIX` | Numeric prefix VoiceLink prepends (e.g. `45454`); confirm with VoiceLink |
| `YOUR_PROJECT_ID.sip.livekit.cloud` | Your LiveKit project SIP host |
| `YOUR_VOICELINK_SIP_CIDR` | VoiceLink/carrier signalling IP range(s), e.g. `x.x.x.0/24` |
| `YOUR_LIVEKIT_SIP_CIDR` | LiveKit SIP source IP range(s) |
| `YOUR_VOICELINK_TERM_HOST:PORT` | VoiceLink termination server for outbound (e.g. `host:3300`) |
| `YOUR_TRUNK_USERNAME` / `YOUR_TRUNK_PASSWORD` | VoiceLink digest auth for outbound |

---

## Directory layout

```
bridge/
├── docker-compose.yml
└── asterisk/
    ├── Dockerfile
    └── etc/
        ├── pjsip.conf
        ├── extensions.conf
        └── rtp.conf
```

---

## 1. Dockerfile

```dockerfile
# asterisk/Dockerfile
FROM debian:12-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
        asterisk asterisk-modules ca-certificates tcpdump iproute2 \
    && rm -rf /var/lib/apt/lists/*
# your config is mounted at runtime (see docker-compose)
CMD ["asterisk", "-f"]
```

> You can also use a prebuilt Asterisk image. Asterisk 18+ is fine; `chan_pjsip` and
> `res_srtp`/TLS support must be present (they are in the Debian package).

## 2. docker-compose.yml

```yaml
name: bridge
services:
  asterisk:
    build: ./asterisk
    container_name: sip-bridge
    network_mode: host          # recommended: avoids double-NAT from Docker's own bridge
    volumes:
      - ./asterisk/etc/pjsip.conf:/etc/asterisk/pjsip.conf:ro
      - ./asterisk/etc/extensions.conf:/etc/asterisk/extensions.conf:ro
      - ./asterisk/etc/rtp.conf:/etc/asterisk/rtp.conf:ro
    restart: unless-stopped
```

> **`network_mode: host`** is the simplest correct choice for SIP/RTP — it removes Docker's
> NAT layer so Asterisk sees real source IPs and RTP ports map cleanly. If you instead
> publish ports, you must publish the SIP port **and the full RTP range** and you add a
> second NAT layer (which is what bit us behind the router). Prefer host networking.

## 3. pjsip.conf

```ini
; ---------- Transports ----------
; On a VPS: external_*_address = YOUR_PUBLIC_IP (== bind IP). You may omit them.
; Behind NAT: external_*_address MUST be the router's public IP, and set local_net.

[transport-udp]
type=transport
protocol=udp
bind=0.0.0.0:YOUR_SIP_PORT
external_media_address=YOUR_PUBLIC_IP
external_signaling_address=YOUR_PUBLIC_IP
local_net=192.168.0.0/16
local_net=172.16.0.0/12
local_net=10.0.0.0/8

[transport-tls]
type=transport
protocol=tls
bind=0.0.0.0:5061
method=tlsv1_2
verify_server=no
external_media_address=YOUR_PUBLIC_IP
external_signaling_address=YOUR_PUBLIC_IP
local_net=192.168.0.0/16
local_net=172.16.0.0/12
local_net=10.0.0.0/8

; ================= INBOUND: VoiceLink -> us -> LiveKit =================

; VoiceLink sends calls to us (identified by source IP)
[voicelink]
type=endpoint
context=from-voicelink
disallow=all
allow=alaw
allow=ulaw
direct_media=no
force_rport=yes
rtp_symmetric=yes
rewrite_contact=yes
dtmf_mode=rfc4733

[voicelink-identify]
type=identify
endpoint=voicelink
match=YOUR_VOICELINK_SIP_CIDR

; We send the call to LiveKit Cloud over TLS.
; Dialing by HOSTNAME is important — pjproject uses it as the TLS SNI.
[livekit-cloud]
type=endpoint
context=from-voicelink
transport=transport-tls
aors=livekit-cloud
disallow=all
allow=alaw
allow=ulaw
direct_media=no
force_rport=yes
rtp_symmetric=yes
rewrite_contact=yes
dtmf_mode=rfc4733

[livekit-cloud]
type=aor
contact=sip:YOUR_PROJECT_ID.sip.livekit.cloud:5061\;transport=tls

; ================= OUTBOUND: LiveKit -> us -> VoiceLink =================

; LiveKit Cloud originates to us (identified by source IP)
[livekit-in]
type=endpoint
context=from-livekit
disallow=all
allow=alaw
allow=ulaw
direct_media=no
force_rport=yes
rtp_symmetric=yes
rewrite_contact=yes
dtmf_mode=rfc4733

[livekit-in-identify]
type=identify
endpoint=livekit-in
match=YOUR_LIVEKIT_SIP_CIDR

; We re-originate to VoiceLink's termination server with DIGEST AUTH.
[voicelink-out]
type=endpoint
context=from-livekit
transport=transport-udp
aors=voicelink-out
disallow=all
allow=alaw
allow=ulaw
direct_media=no
force_rport=yes
rtp_symmetric=yes
rewrite_contact=yes
dtmf_mode=rfc4733
from_user=YOUR_DID
from_domain=YOUR_PUBLIC_IP
outbound_auth=voicelink-out-auth

[voicelink-out]
type=aor
contact=sip:YOUR_VOICELINK_TERM_HOST:PORT

[voicelink-out-auth]
type=auth
auth_type=userpass
username=YOUR_TRUNK_USERNAME
password=YOUR_TRUNK_PASSWORD
```

**Notes**
- `force_rport` + `rtp_symmetric` + `rewrite_contact` are what make SIP/RTP survive NAT and
  asymmetric routing — keep them on.
- Inbound is **IP-authenticated** (VoiceLink's IP is on the allowlist). Outbound needs
  **digest auth** because you are *sending* to VoiceLink's termination (this is the
  toll-fraud-sensitive direction — keep the credentials secret).
- Confirm the tech prefix and termination host/port with VoiceLink; they vary per account.

## 4. extensions.conf (dialplan)

```ini
[general]
autofallthrough=yes

[default]
exten => _X.,1,Hangup()

; ---- Inbound: VoiceLink -> LiveKit ----
[from-voicelink]
; VoiceLink prepends the tech prefix; strip it, then relay to LiveKit over TLS.
; (Example strips a 5-digit prefix like 45454 -> ${EXTEN:5}. Adjust the length.)
exten => _YOUR_TECH_PREFIXX.,1,NoOp(inbound ${EXTEN} -> strip prefix -> ${EXTEN:5} -> LiveKit)
 same => n,Dial(PJSIP/${EXTEN:5}@livekit-cloud,60)
 same => n,NoOp(dial ended status=${DIALSTATUS} cause=${HANGUPCAUSE})
 same => n,Hangup()

; fallback for un-prefixed numbers (direct tests / self-invite)
exten => _[+0-9].,1,NoOp(inbound ${EXTEN} (no prefix) -> LiveKit)
 same => n,Dial(PJSIP/${EXTEN}@livekit-cloud,60)
 same => n,Hangup()

; ---- Outbound: LiveKit -> VoiceLink -> PSTN ----
[from-livekit]
exten => _[+0-9].,1,NoOp(OUTBOUND ${EXTEN} -> VoiceLink)
 same => n,Dial(PJSIP/${EXTEN}@voicelink-out,60)
 same => n,NoOp(OUTBOUND ended status=${DIALSTATUS} cause=${HANGUPCAUSE})
 same => n,Hangup()
```

> Replace `YOUR_TECH_PREFIX` and the `${EXTEN:5}` offset to match your prefix length
> (a 5-digit prefix → strip 5). If VoiceLink sends no prefix, just use the fallback pattern.

## 5. rtp.conf

```ini
[general]
rtpstart=10400
rtpend=10450
strictrtp=no
```

> Pick any range you like, but it must match what you open in the firewall / forward on the
> router. Keep it modest (a few hundred ports is plenty for a test bridge).

---

## 6. Bring it up

```bash
cd bridge
docker compose up -d --build

# health checks
docker exec sip-bridge asterisk -rx "pjsip show endpoints"
docker exec sip-bridge asterisk -rx "dialplan show from-voicelink"
```

To change the dialplan later without dropping calls:
```bash
# edit asterisk/etc/extensions.conf, then:
docker exec sip-bridge asterisk -rx "dialplan reload"
```

---

## 7. Firewall / port forwarding

Open (or forward) on the host / router:

| Port | Proto | Direction | Purpose |
|---|---|---|---|
| `YOUR_SIP_PORT` | UDP | inbound | SIP from VoiceLink |
| `10400-10450` | UDP | inbound | RTP media |
| `5061` | TCP | outbound | SIP/TLS to LiveKit (usually allowed by default) |

- **VPS:** just allow the above in the cloud firewall/security group.
- **Behind NAT (our case):** on the router, forward WAN `YOUR_SIP_PORT/udp` and
  `10400-10450/udp` to `YOUR_LAN_IP`. Confirm the WAN IP equals `YOUR_PUBLIC_IP`.

---

## 8. Verify a call

Turn on SIP tracing and watch:
```bash
docker exec sip-bridge asterisk -rx "pjsip set logger on"
docker logs -f sip-bridge
```

**Inbound (call YOUR_DID):** expect
`INVITE ... from VoiceLink` → `from-voicelink` NoOp → `Dial(...@livekit-cloud)` →
`180 Ringing` → `200 OK`. The LiveKit agent joins and speaks.

**Reachability sanity:** you should periodically see VoiceLink's OPTIONS keepalives arrive
and be answered `200 OK` — that's how VoiceLink knows the trunk is up.

---

## 9. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Caller hears "out of network coverage" / `CHANUNAVAIL`, **no INVITE at the bridge** | VoiceLink can't reach the bridge, or trunk marked unreachable | Check port-forward + public IP; confirm SIP port isn't ISP-blocked (see NAT note #3); ask VoiceLink to re-qualify the trunk |
| OPTIONS arrive but calls still fail | Trunk stuck "unreachable" on VoiceLink side | Re-provision / toggle qualify on the VoiceLink trunk |
| Call connects but **one-way or no audio** | NAT media address wrong | Set `external_media_address` to the public IP; open the full RTP range; keep `rtp_symmetric=yes` |
| LiveKit TLS handshake fails | SNI/hostname wrong | Dial LiveKit **by hostname** (`...@livekit-cloud` whose AOR contact is the `.sip.livekit.cloud` host), not by IP |
| Inbound 5060 never arrives | ISP blocks 5060 | Use a high SIP port (e.g. `35060`) and update the VoiceLink trunk to match |
| Outbound rejected (`401/407`) | Missing/wrong digest auth | Fix `[voicelink-out-auth]` username/password; confirm termination host/port |

---

## 10. Security notes

- Lock inbound identify to the **exact** VoiceLink/LiveKit source ranges. Never leave an
  open `anonymous` endpoint or `0.0.0.0/0` allowlist — open SIP is a fraud magnet.
- The outbound digest credentials spend money if leaked — keep `pjsip.conf` off any shared
  repo and out of screenshots.
- Only expose the SIP + RTP ports you actually use.

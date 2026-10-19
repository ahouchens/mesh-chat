# Reachability planner specification

Status: implementation increment on `codex/android-reply-diagnostics`.
Scope: server-free reachability preparation for the direct connection wizard.
This specification adds no STUN, TURN, rendezvous, signaling, relay, VPN, or
third-device dependency.

## 1. Problem

The current wizard can report `prepared`, `no_public_candidate`,
`no_route`, `network_changed`, or `refresh_required`, but it does not show
which local mechanism produced the result. Users see “Check this device” and
then a generic failure. In particular there is no visible distinction between:

- no Internet route;
- no global IPv6 or public IPv4 address;
- PCP, UPnP, or NAT-PMP absent versus denied;
- a mapping created for a router that is itself behind another NAT or CGNAT;
- a mapping that exists but is blocked by the host firewall;
- a manual UDP forward that the user has not configured yet;
- a candidate that is prepared but not yet authenticated by the peer.

This increment makes each step observable, actionable, and bounded. It does
not change the signed Offer/Answer/Ready protocol, the saved workspace request,
or the rule that only an authenticated peer check proves reachability.

## 2. Definitions

- **Prepared** — the device has a native UDP socket and evidence of a public
  tuple (global address, router mapping, IPv6 pinhole, or manual forward).
  This is not reachability.
- **Verified** — the intended peer authenticated a QUIC connection over the
  exact prepared socket. Only this state may be described as connected.
- **Blocked** — no local strategy can produce a usable candidate.
- **Upstream NAT** — the first-hop router’s external address is private,
  shared (`100.64.0.0/10`), or otherwise not public. A local mapping cannot
  make the device reachable through it.
- **Manual forward** — the user configures the router to forward an external
  UDP port to the device’s local UDP port. The app validates the declared
  public address but cannot verify it without the peer.

## 3. Planner ladder

The planner evaluates strategies in order and records every result. It stops
trying a strategy when a candidate is prepared; it does not require both
devices to be public.

| Order | Strategy | Precondition | Evidence |
| --- | --- | --- | --- |
| 0 | Existing authenticated path | Reticulum/LAN path already works | Existing path, no public tuple |
| 1 | Global IPv6 | Global, non-deprecated IPv6 route | IPv6 candidate; optional pinhole |
| 2 | Public IPv4 | Device has a public IPv4 address | IPv4 candidate |
| 3 | PCP | Router supports PCP | External UDP tuple and lease |
| 4 | UPnP IGD | Router responds to discovery | External UDP tuple and lease |
| 5 | NAT-PMP | Router responds | External UDP tuple and lease |
| 6 | Manual UDP forward | User controls router; public IP known | User-declared public tuple |
| 7 | Role reversal | Other device may be reachable | Other side’s candidate set |
| 8 | Blocked | None worked | Allowlisted blockers |

A received peer tuple is a destination-specific observation, not a general
reachability claim. It is never exported as a public address.

## 4. Planner result

The service returns a plan with the setup result and readiness checks:

```json
{
  "state": "prepared | needs_action | blocked",
  "candidate_count": 1,
  "steps": [
    {"id": "ipv6", "state": "unavailable", "reason": "no_global_ipv6_route"},
    {"id": "public_ipv4", "state": "unavailable", "reason": "no_public_ipv4"},
    {"id": "pcp", "state": "failed", "reason": "pcp_no_response"},
    {"id": "upnp", "state": "prepared", "reason": "mapping_prepared"},
    {"id": "nat_pmp", "state": "not_tried", "reason": null},
    {"id": "manual", "state": "not_tried", "reason": "manual_forward_available"},
    {"id": "firewall", "state": "needs_consent", "reason": "firewall_permission_required"}
  ],
  "primary_action": {"kind": "allow_firewall", "label": "Allow UDP in Windows Firewall"},
  "blockers": [],
  "manual_forward": {"local_host": "192.168.1.20", "local_port": 54321}
}
```

Step states: `prepared`, `verified`, `unavailable`, `failed`,
`needs_consent`, `not_tried`, `skipped`, `blocked`.

`manual_forward` contains local details only; the external tuple is in the
signed invitation and is not copied into diagnostics. The renderer may show the
user their own local address and port so they can configure the router.

## 5. Strategy behavior

### IPv6 and public IPv4

The existing collector already prefers public IPv6 and records public
addresses. The planner adds explicit evidence for:

- no global IPv6 route;
- global IPv6 without a pinhole;
- pinhole success/failure;
- no public IPv4.

An IPv6 pinhole failure does not discard a global IPv6 candidate; it is a
warning that the host or router firewall may still block inbound traffic.

### Mapping protocols

`create_port_mapping` records each PCP/UPnP/NAT-PMP attempt instead of
returning only the final error. The planner reports which protocols were
tried, which were denied, and which were not tried because an earlier protocol
succeeded.

An `upstream_nat_detected`, `upnp_wan_private`, or `upnp_wan_shared` result is
a blocker: the local router cannot make the device reachable through another
NAT. The UI must not suggest waiting or re-copying as a remedy.

### Manual UDP forward

The owner or joiner may supply a public numeric IPv4/IPv6 address and an
external UDP port when preparing the Offer or Answer. The service:

1. validates the address as globally routable and rejects private, shared,
   loopback, link-local, multicast, documentation, benchmark, and unspecified
   addresses;
2. validates the port as 1–65535;
3. adds one `manual` candidate for the exact prepared socket and expiry;
4. signs the document once with the existing generation rules;
5. reports the local host and port so the user can configure the router.

The UI must explain that the mapping is **manual and unverified** until the
peer check succeeds. The app never configures the router or requests the
user’s router credentials.

### Host firewall

On Windows, the setup may install one temporary inbound UDP rule for the exact
service executable, local port, and active firewall profile. This requires the
operating system’s elevation prompt. The rule is removed when the setup is
cancelled, expires, fails, or the service closes.

Non-Windows platforms return `firewall_check_unsupported`; the UI must not
claim that inbound UDP is permitted. Android has no equivalent host-firewall
control.

### Role reversal

If this device has no usable candidate but the other device does, the wizard
may offer the existing role-reversal flow. The planner does not rewrite the
deterministic native roles; it only recommends which side should host.

## 6. Wizard behavior

### Preparing

The screen replaces the single “Check this device” result with a compact
evidence list:

```text
Make this device reachable

Internet route            Found
IPv6                      Not available
Router UDP mapping        Ready — PCP, 3:58 left
Windows firewall          Needs permission
Other device              Waiting

[ Allow UDP in Windows Firewall ]
```

One primary action is shown at a time. Technical details are under
**What was checked**. The user can still cancel or copy diagnostics.

### Mapping denied or unsupported

```text
No public address on this device

- PCP: no response
- UPnP: disabled or unavailable
- NAT-PMP: no response
- IPv6: no global address

[ Set up manual UDP forward ]  [ Try the other device as host ]
```

### Upstream NAT

```text
This router is behind another NAT

The router reported a private or shared external address
(100.64.x.x). A local mapping cannot make this device reachable.
Try IPv6, the other device's network, or an explicitly approved
access point.

[ Manual UDP forward ]  [ Other options ]
```

### Prepared but not verified

```text
A public address is prepared.
This is not yet proof that the other device can reach it.
Send the invitation and keep both apps open.

[ Copy invitation ]  [ Test connection ]
```

### Blocked

```text
Neither device can be reached on this network

- No Internet route, or
- No public address/mapping, and
- No existing Mesh route.

A relay or approved access point is required for this network pair.
```

No “copy again” or “wait” loop is offered for a blocked pair.

## 7. Diagnostics and privacy

- Diagnostics record allowlisted strategy/reason codes, not addresses,
  hostnames, router URLs, executable paths, or invitation contents.
- `Copy diagnostics` gains a `reachability` summary with step states and
  reasons, but no local/public tuples.
- The UI may show the user their own local address/port for manual forwarding.
- The signed invitation continues to carry only the public candidate tuple and
  existing signed controls.

## 8. Security

- No silent UPnP enabling, DMZ, port forwarding, firewall change, or relay.
- Firewall rules are exact-program, exact-port, exact-profile, temporary, and
  cleaned up.
- Manual addresses are validated; no private/reserved/loopback endpoints.
- No port prediction, birthday-paradox scanning, STUN observation service, or
  third-party rendezvous.
- No private keys, invitation documents, or addresses in diagnostics.
- The saved workspace request, identity, membership, and outbox are unchanged.

## 9. Acceptance criteria

1. A prepared public IPv6/public IPv4/mapped/manual candidate produces a plan
   with the correct source and a `prepared` state.
2. PCP/UPnP/NAT-PMP failures are individually visible; an earlier success
   makes later protocols `not_tried`.
3. Upstream NAT produces a `blocked` plan with an `upstream_nat` blocker.
4. No route produces a `blocked` plan with `no_route`; no mapping and no
   public address produces `no_public_candidate`.
5. Manual forwarding rejects non-public addresses and invalid ports and adds
   exactly one signed candidate.
6. The Windows UDP rule is exact, temporary, removable, and only offered on
   Windows. A denied elevation returns a failure, not a false success.
7. The wizard shows one primary action, a plan list, a manual-forward form,
   and a terminal blocked explanation.
8. Copying diagnostics omits addresses and invitation text while including
   allowlisted plan reasons.
9. Existing Offer/Answer/Ready, saved-request, receipt, cancellation, and
   replay tests remain green.
10. Frontend/package/native builds and physical device testing remain in
    GitHub Actions.

## 10. Out of scope

- STUN/TURN/relay/rendezvous infrastructure.
- Automatic router administration or credential collection.
- Port prediction or address guessing.
- Guaranteed connectivity on CGNAT or inbound-blocked networks.
- A claim that a prepared mapping is reachable before peer authentication.

## 11. Implementation status, 2026-10-19

Implemented in this increment:

- `reachability.py`: deterministic plan builder, allowlisted step states and
  reasons, manual-endpoint validation, and no address export in diagnostics.
- `direct_candidates.py`: per-protocol PCP/UPnP/NAT-PMP attempts, IPv6 pinhole
  evidence, IPv6/public-IPv4/upstream-NAT classification, and one `manual`
  candidate for the exact native socket.
- `direct_setup.py`: `manual_host`/`manual_port` on Offer and Answer
  preparation, `configure_direct_firewall`, temporary-rule cleanup, and the
  plan attached to setup results and readiness checks.
- `firewall.py`: exact temporary **UDP** rule support with a protocol-specific
  marker while retaining the existing TCP default.
- Service, desktop, Android bridge, diagnostics, and renderer allowlists for
  `configure_direct_firewall`.
- Wizard: reachability step list, one primary action, **Allow UDP in Windows
  Firewall**, **Set up manual UDP forward**, and blocked/upstream-NAT text.
- Diagnostics: network failure reasons and plan reasons remain allowlisted;
  addresses and invitation contents are excluded.

Validation: 127 focused tests passed; the full local service suite passed 958
with 40 expected skips and 12 deselected legacy setup-pipeline cases. Those 12
source/native setup-pipeline cases also fail at the preceding commit on this
machine, so they are not attributed to this change. Frontend/TypeScript/package
execution, Windows/Android builds, and physical device testing remain in GitHub
Actions. Version: 0.2.65 / Android 2065.

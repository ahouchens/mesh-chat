# I2P support for Mesh Chat — Windows and Android

Status: design and roadmap proposal. No I2P implementation exists in Mesh Chat
today. This document defines the target behavior, constraints, and a staged
delivery plan.

## 1. Summary

Add an optional **I2P transport path** so Mesh Chat users can join a workspace
or a 1:1 conversation through an I2P access point when neither device has a
public IPv4/IPv6 endpoint.

The path is:

```text
Windows Mesh Chat ──outbound I2P──> I2P access point <──outbound I2P── Android Mesh Chat
```

It is a **relay/overlay path**, not a direct QUIC path. It is intended for:

- workspace invitation delivery, join requests, owner approval, receipts;
- 1:1 contact requests, approval, messages, and offline delivery;
- users behind CGNAT, double NAT, or restrictive firewalls;
- users who want to avoid exposing their IP address to the other peer.

It is not intended for:

- direct QUIC/NAT hole punching;
- real-time low-latency traffic;
- anonymous messaging claims beyond what I2P actually provides;
- replacing TCP access points or local-network connectivity.

## 2. Definitions

- **I2P router** — an I2P daemon, normally `i2pd`, exposing the SAM API.
- **SAM** — I2P's client control API. Reticulum's `I2PInterface` uses
  `127.0.0.1:7656` by default, overridable with `I2P_SAM_ADDRESS`.
- **I2P destination** — the access point's cryptographic I2P address, shown as
  a `*.b32.i2p` address.
- **I2P access point** — a Reticulum transport node with an `I2PInterface`.
  It may be `connectable` (accept inbound I2P tunnels), have outbound `peers`,
  and forward Reticulum traffic when `enable_transport = Yes`.
- **Client-only I2P** — an instance that connects to `peers` but does not
  accept inbound connections. Recommended for mobile.
- **I2P route profile** — a sealed, scoped record that stores an access point
  address, consent, expiry, optional IFAC credentials, and diagnostics state.

## 3. Current state and dependencies

### Reticulum

Reticulum 1.5.5 provides `RNS.Interfaces.I2PInterface`:

- configuration keys: `type = I2PInterface`, `enabled`, `connectable`,
  `peers`, `ifac_size`, `ifac_netname`, `ifac_netkey`;
- SAM address defaults to `127.0.0.1:7656`;
- `connectable = Yes` creates a persistent `b32.i2p` server destination;
- `peers = <b32>` creates outbound client tunnels;
- IFAC can restrict the interface to a named/private network;
- the interface reports `online` only after its tunnel setup succeeds;
- tunnel setup can take seconds to minutes and may retry indefinitely;
- Reticulum includes the I2P client code (`RNS.vendor.i2plib`) but **does not
  bundle i2pd**; the I2P router is a separate process.

The official manual describes I2P as the option for hosting a globally
reachable Reticulum instance without a public IP, including behind firewalls
and NAT: <https://reticulum.network/manual/interfaces.html#i2p-interface>.

### Mesh Chat

Mesh Chat currently has **no I2P code path**:

- `NetworkSettings` has no I2P fields;
- `write_config()` writes AutoInterface, TCP client/server, participant, LAN,
  and remote TCP blocks only;
- there is no I2P UI, command, profile type, or diagnostic;
- `ReticulumNetwork` attaches/detaches interfaces by name;
- renderer settings deliberately exclude sealed endpoints and credentials;
- Android uses an embedded Python runtime and does not bundle an I2P router.

The existing remote-access model is TCP-specific. I2P should not be forced into
the TCP `RemoteProfile` schema without a `kind` discriminator; a separate
`I2PRoute` record is safer.

## 4. Goals

1. A Windows user can enable I2P, run or connect to an access point, and reach a
   workspace or contact through it.
2. An Android user can do the same, with a client-only I2P path, when an I2P
   router is available.
3. Access points are explicit, scoped, expiring, and consent-based.
4. The invitation/join flow can carry a signed I2P access point descriptor.
5. The UI clearly says “relayed via I2P”, never “direct” or “anonymous”.
6. Failure is actionable: SAM missing, tunnel pending, wrong b32, IFAC mismatch,
   access point offline, or transport disabled.
7. No silent I2P enablement or silent access point selection.
8. No plaintext or credentials cross the renderer boundary.

## 5. Non-goals

- Direct QUIC over I2P or NAT hole punching.
- Making I2P the default connection path.
- Bundling an I2P router in the first Windows or Android increment.
- Guaranteed anonymity, censorship resistance, or availability.
- Replacing approved TCP access points.
- Running a general-purpose public relay without operator consent and quotas.
- Using I2P for large attachments or real-time media in early increments.

## 6. User experience

### 6.1 Settings → Network → I2P

Fields and controls:

- **Use I2P** (off by default).
- **I2P router status**: `not found`, `SAM connected`, `starting`, `error`.
- **Run a connectable access point** (desktop only; advanced).
- **Access point address**: `*.b32.i2p` input.
- **Private network** (optional): network name and passphrase; stored sealed,
  never rendered back.
- **Bandwidth limit**: low / normal / high, translated to i2pd configuration.
- **This is a relay** disclosure: “I2P hides your IP from the other peer and
  relays traffic through the I2P network. It does not create a direct
  connection. The access point can see connection metadata, not message
  contents.”
- **Test I2P** action with bounded status, no address logging.

### 6.2 Invite / join

Under **Other connection options**:

- **I2P access point** — paste a `b32.i2p` address, or import a signed
  invitation that includes one.
- The joiner sees: access point label, abbreviated b32, expiry, and “traffic
  will be relayed through this access point”.
- The joiner must explicitly consent before the interface is attached.
- The UI never labels the result “direct”; it shows **Relayed via I2P**.

### 6.3 Workspace and 1:1

- Workspace join request, owner approval, receipt, and messages can use the
  I2P path.
- 1:1 contact request, approval, and messages can use the I2P path.
- The existing saved-request, replay, expiry, and approval semantics remain
  unchanged.
- If the access point is offline, the request stays queued; the UI says so.
- If both direct and I2P are available, the user chooses the route; the app
  does not silently switch.

### 6.4 Diagnostics

Add an I2P section to the reachability/connection plan:

| Field | Values |
|---|---|
| Router | `not_installed`, `sam_unavailable`, `sam_connected` |
| Interface | `disabled`, `starting`, `online`, `failed` |
| Access point | `not_configured`, `resolving`, `connected`, `offline` |
| Transport | `relay_enabled`, `relay_disabled` |
| Last error | allowlisted code only |
| Path | `relayed_i2p` |

No b32 addresses in copied diagnostics beyond the existing allowlist; no
passphrases, private keys, or raw SAM output.

## 7. Architecture

### 7.1 Service settings

Add to `NetworkSettings`:

```python
i2p_enabled: bool = False
i2p_connectable: bool = False
i2p_peers: list[str] = field(default_factory=list)   # validated b32
i2p_bandwidth: str = "normal"
i2p_route_ids: list[str] = field(default_factory=list)  # sealed profiles
```

Do **not** expose:

- SAM address (service-owned; default localhost);
- IFAC names/passphrases (sealed vault records);
- private keys or tunnel state.

### 7.2 Config writer

Add an `[[I2P]]` block when enabled:

```ini
  [[I2P]]
    type = I2PInterface
    enabled = Yes
    connectable = Yes/No
    peers = <b32>,<b32>
    ifac_size = 128
    ifac_netname = <sealed>
    ifac_netkey = <sealed>
```

Rules:

- `connectable = Yes` only on desktop, and only with explicit consent.
- Mobile defaults to client-only.
- Validate b32 with `^[a-z2-7]{52}\.b32\.i2p$`.
- Limit peers to a small number (for example 4).
- Add a bounded startup wait; a slow I2P tunnel must not block the app.
- Keep the interface optional and isolate failures like the existing guarded
  interface synthesis.

### 7.3 Interface lifecycle

- Attach after settings/profile consent.
- Detach on disable, profile revoke, expiry, or app shutdown.
- Report `online` only when `I2PInterface.online` is true.
- Retry tunnel setup with bounded backoff and visible state.
- Do not mark path reachable until an authenticated Reticulum/LXMF delivery or
  receipt succeeds.
- Clean up the I2P storage directory on profile deletion only with user consent.

### 7.4 I2P route profile

A sealed record:

```json
{
  "id": "opaque",
  "label": "Community I2P access point",
  "kind": "i2p",
  "b32": "<52 chars>.b32.i2p",
  "connectable": false,
  "network_name": null,
  "passphrase": null,
  "created_at": 0,
  "expires_at": 0,
  "consent_at": 0,
  "scope": ["personal", "workspace"],
  "state": "active"
}
```

- At most four active I2P routes.
- Expiry cannot exceed the invitation/access-point policy.
- Revocation is local and immediate; a signed invitation can also carry an
  expiry.
- Renderer sees label, abbreviated b32, counts, booleans, and safe states.

### 7.5 Invitation descriptor

Add an additive, signed descriptor to the invitation manifest:

```json
{
  "kind": "i2p_access_point",
  "b32": "<52 chars>.b32.i2p",
  "label": "optional",
  "expires_at": 0,
  "relay": true
}
```

- Signed by the inviter/authority.
- Preview verifies syntax and expiry only; no network probe.
- Acceptance requires the joiner’s explicit consent.
- Older readers ignore the descriptor and retain their existing behavior.
- The descriptor does not grant membership or trust by itself.

## 8. Security and privacy

1. **Explicit consent** for enabling I2P, running a connectable access point,
   and using an access point from an invitation.
2. **Relay disclosure**: the access point can see connection metadata, timing,
   and volume; message contents remain end-to-end encrypted.
3. **No anonymity promise**: I2P reduces IP exposure but is not a guarantee
   against a global adversary or timing analysis.
4. **IFAC**: optional private network name/passphrase for a closed access
   point; sealed at rest.
5. **No open relay by default**: a Mesh Chat access point serves only approved
   scopes/contacts; quotas and rate limits are required before public use.
6. **Abuse controls**: bounded peers, bandwidth limits, connection caps, and
   local blocklist.
7. **Bounded failure**: a broken I2P interface must not crash or block the app.
8. **No credential leakage**: b32 is public; IFAC secrets and SAM details are
   service-only.

## 9. Platform plan

### Windows

- **I2P router:** external `i2pd` first; bundled `i2pd` later.
- **SAM:** localhost `127.0.0.1:7656`; detect and report missing SAM.
- **Lifecycle:** optional user process; no admin required; stop on app exit if
  Mesh Chat started it.
- **Installer:** include licenses/notices; do not silently install a service.
- **Firewall:** outbound only; no inbound Windows firewall rule for I2P.
- **Bandwidth:** default low/normal; user-configurable.

### Android

- **I2P router:** external `i2pd`/I2P app with SAM first; bundled binary later.
- **Client-only default:** `connectable = No` to avoid inbound tunnels and
  battery drain.
- **SAM reachability:** verify whether an external Android I2P app exposes SAM
  on localhost; this is a research gate.
- **Background:** I2P tunnels must survive screen-off/network changes or show
  an explicit “I2P paused” state.
- **Bundled binary:** APK size, native execution, foreground service, battery,
  and SELinux are go/no-go criteria. Do not promise a bundled Android router
  until the spike proves it.

### 9.1 Cost and operations

- **Software:** i2pd, Reticulum, and Mesh Chat are free/open source.
- **Public IP:** not required for I2P; this is its main advantage over a TCP
  access point on a CGNAT connection.
- **Ongoing cost:** the access point operator pays for electricity and
  bandwidth; an always-on Windows machine or small VPS can host it. I2P routers
  also relay other traffic by default, so bandwidth limits and consent matter.
- **No paid relay service is required.** A volunteer/community access point is
  best-effort; a self-hosted access point is more reliable but has hosting
  costs.
- **Packaging cost:** a bundled Windows i2pd increases installer size; a
  bundled Android i2pd increases APK size and battery use. Those are the
  trade-offs behind the I2/I5 decision gates.
- **No account, subscription, or API key** is needed for I2P.

## 10. Roadmap

| Increment | Platform | Outcome | Effort | Depends on |
|---|---|---|---|---|
| I0 | Desktop | Prove Reticulum-over-I2P with external i2pd | S | — |
| I1 | Windows | Manual I2P transport, settings, diagnostics | M | I0 |
| I2 | Windows | Managed i2pd, user-ready install | M | I1 |
| I3 | Windows + remote | Signed I2P access point in invitations/workspaces | M | I1/I2 |
| I4 | Android | Client-only I2P with external router | M/L | I3 |
| I5 | Android | Bundled i2pd go/no-go | L | I4 |
| I6 | Both | Hardening, multi-access-point, quotas | Ongoing | I3/I4 |

### I0 — Protocol spike (desktop, external i2pd)

**Goal:** prove the Reticulum I2P path works end-to-end with two desktop
instances and no Mesh Chat UI.

Scope:

- install `i2pd` on Windows/Linux, enable SAM;
- run two Reticulum instances with `I2PInterface`, one `connectable`, one
  `peers`;
- exchange LXMF messages and a workspace join request;
- measure tunnel setup time, delivery latency, reconnect behavior, and
  bandwidth;
- verify b32 persistence across restart.

Exit criteria:

- authenticated LXMF delivery succeeds in both directions;
- b32 address is stable;
- SAM down, wrong b32, and tunnel timeout produce bounded errors;
- no public IP or port forward is used.

Effort: S (1–2 days). Owner: native/service.

### I1 — Windows I2P transport foundation (external i2pd)

**Goal:** advanced Windows users can enable I2P and connect manually.

Scope:

- `NetworkSettings` I2P fields and validation;
- `write_config()` I2P block;
- attach/detach lifecycle and bounded startup;
- Settings UI with router status and b32 input;
- diagnostics state and allowlisted errors;
- no invitation integration yet.

Exit criteria:

- Windows can run client-only or connectable I2P;
- restart restores the route;
- disabling removes the interface;
- missing SAM and wrong b32 are actionable;
- no secrets cross the renderer;
- unit and Windows integration tests pass.

Effort: M (1–2 weeks).

### I2 — Managed Windows i2pd (user-ready)

**Goal:** a normal Windows user does not install i2pd separately.

Scope:

- bundle or download `i2pd` with license notices;
- start/stop as a child process with a dedicated config/data directory;
- SAM enabled on localhost only;
- bandwidth and connection caps;
- uninstall cleanup;
- no Windows service or admin requirement by default;
- installer size and signature checks.

Exit criteria:

- fresh install → enable I2P → online without command-line steps;
- app exit stops the managed process;
- crash/restart does not orphan the process;
- uninstall leaves no service or firewall rule;
- license/notice review complete.

Effort: M (1–2 weeks).

### I3 — Invitation and workspace integration

**Goal:** I2P access points are part of the signed connection flow.

Scope:

- signed I2P descriptor in personal/workspace invitations;
- preview, consent, expiry, revocation;
- workspace join/approval/receipt over I2P;
- 1:1 request/approval/messages over I2P;
- route selection UI (`Direct`, `TCP access point`, `I2P access point`);
- diagnostics `relayed_i2p`;
- saved-request and replay semantics unchanged.

Exit criteria:

- a Windows owner and a remote joiner can join a workspace over I2P without a
  public IP;
- approval and receipt are verified;
- an offline access point leaves the request queued, not failed;
- direct setup remains optional and never replaces the saved request;
- Android can import/preview the invitation even before Android I2P support.

Effort: M (1–2 weeks).

### I4 — Android I2P client (external router)

**Goal:** Android can use an I2P access point when an I2P router is available.

Scope:

- research gate: external Android I2P app/SAM accessibility;
- client-only I2P interface;
- Settings UI, consent, diagnostics;
- foreground/background behavior and network-change recovery;
- physical-device test with Windows access point;
- fallback to TCP/LAN when I2P is unavailable.

Exit criteria:

- Android joins a workspace over I2P on a physical device;
- screen-off and Wi-Fi/cellular transitions are documented;
- no public IP or port forward is required;
- battery and data use are measured;
- if external SAM is not reachable, the increment is re-scoped to TCP.

Effort: M/L (research-dependent).

### I5 — Android bundled i2pd (research)

**Goal:** decide whether Mesh Chat can ship an embedded I2P router on Android.

Scope:

- native `i2pd` binary or library packaging for arm64;
- foreground service and lifecycle;
- APK size, battery, memory, and thermal impact;
- Android execution/SELinux constraints;
- license/notice compliance;
- go/no-go review.

Exit criteria:

- a prototype starts, connects, and stops cleanly on a physical device;
- APK size and battery are acceptable;
- no background-start or store-policy violation;
- if not viable, Android remains client-only with an external router.

Effort: L (3–6 weeks, research).

### I6 — Hardening and scale

- multiple access points and failover;
- access point discovery (manual first, optional Reticulum discovery);
- IFAC private networks;
- quotas, rate limits, abuse controls;
- revocation and expiry propagation;
- metrics without addresses;
- documentation and operator guide;
- security review.

Effort: ongoing.

### 10.1 Decision gates

- **Gate A (after I0):** authenticated LXMF and workspace join work reliably
  over two I2P-connected Reticulum instances. If not, stop and document the
  blocker; do not build UI on an unproven path.
- **Gate B (after I2):** a fresh Windows install can enable I2P without
  command-line steps, and the managed router stops cleanly. If not, keep I2P
  as an advanced external-router option.
- **Gate C (after I3):** a real workspace join/approval/receipt completes over
  I2P with no public IP. If not, fix the transport before Android work.
- **Gate D (after I4):** external Android SAM is reachable and stable enough
  for a client-only route. If not, re-scope Android to TCP access points.
- **Gate E (after I5):** bundled Android i2pd meets size, battery, lifecycle,
  and policy constraints. If not, Android stays external-router-only or
  desktop I2P remains the supported configuration.

## 11. Testing plan

### Unit

- b32 validation and normalization;
- settings allowlist and config generation;
- I2P block ordering and IFAC omission when absent;
- route profile scope/expiry/consent;
- diagnostics allowlist;
- renderer never receives SAM address, passphrase, or private key.

### Integration

- two Reticulum instances over local i2pd (Linux CI container or Windows);
- LXMF delivery both directions;
- workspace join → approval → receipt;
- access point offline → queued;
- SAM unavailable → `sam_unavailable`;
- wrong b32 → `access_point_offline`;
- IFAC mismatch → `ifac_rejected`;
- restart and reconnect;
- interface disable/removal;
- no public IP/port forward.

### Windows

- installer with/without bundled i2pd;
- child-process lifecycle and orphan cleanup;
- firewall outbound-only;
- sleep/resume and network change;
- no admin requirement.

### Android

- external i2pd/SAM reachability;
- client-only mode;
- screen-off and network transitions;
- battery/data measurement;
- physical device join test;
- bundled-router spike, if pursued.

### CI

- unit tests always;
- optional integration job with an i2pd Linux service and two RNS instances;
- no dependency on the public I2P network for required CI;
- Windows/Android packaging remains in GitHub Actions.

## 12. Acceptance criteria

1. I2P is off by default and requires explicit consent.
2. Windows can use an external or managed i2pd router.
3. Android can use a client-only I2P route when a router is available.
4. A workspace join, approval, receipt, and messages can complete over I2P
   without a public IP or port forward.
5. A 1:1 contact request, approval, and messages can complete over I2P.
6. The UI says “relayed via I2P” and never “direct”.
7. An offline access point leaves the request saved and queued.
8. Disabling/revoking I2P removes the interface and does not affect other
   routes.
9. No SAM address, passphrase, private key, or raw tunnel log reaches the
   renderer.
10. Existing direct/TCP/LAN behavior is unchanged when I2P is disabled.
11. Windows and Android packages pass CI; physical results are recorded
    separately.

## 13. Open questions

1. Should Windows bundle i2pd, download it on first use, or require a separate
   install?
2. Can an external Android I2P app expose SAM to Mesh Chat reliably, or must
   Mesh Chat bundle a router?
3. Should a mobile device ever be `connectable`, or always client-only?
4. Is I2P an access-point profile or a general interface setting?
5. Should invitations auto-select a configured I2P route, or always ask?
6. What bandwidth defaults are acceptable for a volunteer access point?
7. Do we support Reticulum interface discovery for I2P access points, or only
   manual/signed b32 addresses?
8. What is the support policy for i2pd versions and SAM compatibility?

## 14. Out of scope

- Direct QUIC over I2P.
- NAT hole punching.
- Anonymous/untraceable messaging guarantees.
- Public open relays without quotas.
- I2P for large attachments or real-time media in early increments.
- Replacing the existing direct/TCP/LAN paths.
- Bundling an Android I2P router before the I5 go/no-go.

## 15. References

- Reticulum I2P interface:
  <https://reticulum.network/manual/interfaces.html#i2p-interface>
- Reticulum internet connectivity guidance:
  <https://reticulum.network/manual/gettingstartedfast.html#connecting-reticulum-instances-over-the-internet>
- Reticulum announce/path model:
  <https://reticulum.network/manual/understanding.html#the-announce-mechanism-in-detail>
- i2pd:
  <https://i2pd.website>

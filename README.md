# Mesh Chat

**Server-free, end-to-end encrypted messaging for small groups — built directly on Reticulum and LXMF.**

Mesh Chat is a desktop and mobile messenger with no account service, no signaling service, no key directory, no hosted relay, and no required always-on machine. Each installation creates its own Reticulum identity; a message is an ordinary LXMF message addressed to another person's device. The application adds the parts a messenger needs — explicit consent, signed invitations, group and workspace authority, an encrypted local history, and honest delivery evidence.

The design accepts real trade-offs. Delivery depends on peers being reachable, history lives only on the devices that received it, and no operator can recover a lost identity. For a small trusted team, that is the point.

An optional **I2P relay path** can bootstrap a workspace or 1:1 connection when neither device has a public endpoint. It is an explicit, consented fallback: the invitation carries one signed `*.b32.i2p` access point, both sides need an I2P router, and the access point relays encrypted Reticulum traffic rather than creating a direct link. I2P is not the default, is not available on Android yet, and does not replace the direct/LAN/access-point paths.

> **Status — security-sensitive prototype.** The source tree is at 0.3.2. It has not been independently audited, and several physical-device and packaging gates are still open. Read [Status and verification](#status-and-verification) before relying on it.

## What problem it solves

Mesh Chat addresses a specific gap: **private small-group messaging without an account provider, signaling service, key directory, hosted relay, or always-on server.**

Reticulum and LXMF already provide identities, routing, and encryption. Mesh Chat adds the messenger/application layer those protocols do not: consent, invitations, group and workspace authority, durable local state, and delivery evidence.

In short, it solves **“how do a few people message and coordinate privately without trusting or paying for a messaging service?”** — while accepting weaker reachability, recovery, and metadata-privacy guarantees than a hosted messenger.

| Problem | What Mesh Chat provides | How it stays server-free |
| --- | --- | --- |
| **Accounts, phone numbers, or a vendor service** | **One-to-one chat.** A signed invitation, a contact request, and an explicit acceptance per person. Every message is one ratchet-encrypted LXMF delivery. | Each installation creates its own Reticulum identity. Both devices talk directly; a receipt means the other app committed the message, not that a person read it. |
| **Unsolicited contact and unclear trust** | **Explicit consent.** Invitations are signed and single-use; the recipient reviews the inviter, fingerprint, and workspace details before approving. | Trust is established peer-to-peer. Delivery never implies approval. |
| **Group chat normally needs a hosted room** | **Private groups.** Up to eight people, owner-signed membership, an announcement-channel mode, and per-recipient delivery state. | One logical message becomes one separately encrypted copy per member. There is no group server and no shared group key. |
| **Workspace collaboration normally needs a server** | **Shared workspaces.** Up to eight people, 32 public/private channels including `#general`, workspace DMs, one-level threads, mentions, edits, deletion tombstones, reactions, local search, and cooperative retention. | One authority-signed manifest chain describes membership; every device receives its own signed copy of each event. |
| **First contact usually needs STUN, TURN, or a rendezvous service** | **Direct Internet invitations.** A temporary listener on the inviter's device asks their router for a mapping, then signs the resulting endpoint and credential into the invitation. | PCP â†’ UPnP IGD â†’ NAT-PMP on the participant's router. No rendezvous, STUN, TURN, or Mesh Chat service is contacted. |
| **No public endpoint and no directly reachable access point** | **I2P relay invitations.** A signed `MESHI2P1:` / `MESHI2P1W:` envelope carries one `*.b32.i2p` Reticulum access point; the joiner must consent before traffic is relayed. | Each side runs an I2P router with SAM. The access point relays encrypted Reticulum/LXMF traffic; no public IP or port forward is needed on either participant. |
| **One network path is not enough** | **Explicit fallbacks.** Nearby discovery, signed direct TCP, an operator-run access point, an email/reverse handshake, and an experimental QUIC underlay. | Each path is a visible choice, never a silent downgrade. See [Reaching another device](#reaching-another-device). |
| **Cloud chat means cloud-held history and metadata** | **Local-only privacy.** Encrypted vault, sealed local search, no telemetry, analytics, crash upload, CDN, or remote artwork fetch. | Search and history stay on the device; there is no hosted index to query. |
| **Offline peers and unclear delivery** | **Offline-tolerant delivery.** An optional LXMF propagation node stores recipient-encrypted objects until the recipient fetches them. A durable outbox, deduplication, and per-device evidence cover the rest. | The propagation node is separately consented and never becomes an identity, member, or delivery receipt. |
| **Desktop and mobile implementations diverge** | **Desktop and mobile.** Tauri 2 shell with a bundled Python service on desktop; embedded CPython on Android and iOS. | Same Rust/Python/React stack and the same data model, with no platform-specific server. |

### What it deliberately does not solve

- **Universal reachability.** If neither side can accept inbound traffic and no shared path exists, setup fails and says so. It is not a guaranteed NAT-traversal system. I2P helps only when each side can run an I2P router and reach a configured access point; Android does not bundle one yet.
- **Asynchronous delivery without infrastructure.** An offline recipient needs an explicitly approved propagation node; there is no push service.
- **Identity or authority-key recovery.** Lost keys are not recoverable, and lost workspace authority freezes administration.
- **Anonymity.** IP endpoints, timing, and traffic analysis remain exposed; I2P hides participant IP addresses from each other but the access point and the I2P network still see relay metadata. There is no anonymity claim.
- **Broad messenger scope.** Attachments, calls, discoverable public channels, cloud backup, remote push, and multi-owner membership are out of scope.
- **Production assurance.** The project describes itself as a security-sensitive prototype: it has not been independently audited, and physical-device, packaging, and platform gates remain open. See [Status and verification](#status-and-verification) and [THREAT_MODEL.md](THREAT_MODEL.md).

## Architecture

![Mesh Chat architecture: renderer, Tauri shell, Python service, Reticulum/LXMF with optional I2P, protected profile, and the network paths they use](docs/architecture/overview.png)

The application is four cooperating layers plus the network below them. Reticulum already owns identity, routing, and encryption across very different links, so Mesh Chat does not re-implement any of that: it adds only the application semantics those layers do not provide.

1. **React renderer** — the conversation list, chats, groups, workspaces, threads, search, and settings. It holds UI state and drafts only. It never receives a private key, the vault key, a filesystem path, or a socket.
2. **Tauri 2 shell (Rust)** — the only component allowed to start and stop the messaging service. It retrieves or creates a 32-byte vault key in the operating system's credential store, supplies the app-private profile path, validates every renderer command against a named allowlist and a size limit, and applies a strict content security policy.
3. **`mesh-chat-service` (Python 3.11+)** — the security boundary. It parses and verifies every signed document, owns contact/group/workspace consent, commits state to the vault, runs the outbox and receipt jobs, and hands messages to LXMF only after the local transaction is durable. It speaks a framed stdin/stdout protocol; there is no localhost HTTP or WebSocket control server.
4. **Reticulum 1.5.5 + LXMF 1.2.0** — the pinned reference stack. Reticulum supplies identities, destinations, paths, Links, and transport; LXMF supplies message serialization plus direct and propagated delivery. Mesh Chat adds no custom cipher, group key, or routing envelope. An optional Reticulum `I2PInterface` can carry the same LXMF traffic over I2P when a local `i2pd` router and an access point are explicitly configured. An optional **community relay** (TURN plus a Reticulum TCP access point) can carry encrypted packets when direct Internet paths fail; it is not an authority and does not store messages.

Underneath them, one **protected profile** holds everything at rest: the sealed vault, Reticulum path/ratchet state, and the LXMF message store. The service verifies OS-level encryption for that directory (and enables NTFS EFS on Windows when needed) and refuses to start if it cannot confirm it — FileVault, fscrypt / dm-crypt / LUKS, or an app-private Android/iOS container.

### Where state lives

All durable application records live in SQLite, but the values are individually sealed: AES-256-GCM on desktop with a fresh nonce and table/record identity as associated data; on mobile, a per-record key derived with HMAC-SHA-256 and RNS's authenticated Token construction. The 32-byte master key is held only in the OS credential store and in service memory. SQLite itself runs in `DELETE` journal mode with `synchronous=FULL`, `temp_store=MEMORY`, and `secure_delete=ON`, so rollback journals contain ciphertext too.

A mutating command is not acknowledged until its vault transaction commits. That is why retrying a send after a crash reuses the same logical message and operation identifiers instead of creating a duplicate.

## Reaching another device

Reticulum routes packets, but it cannot make an arbitrary NAT accept an inbound connection. Mesh Chat therefore offers several deliberately explicit ways to get the first authenticated path:

| Invitation | Prefix | What it bootstraps | Requirement |
| --- | --- | --- | --- |
| **v1 — nearby** | `MESHCHAT1:` / `MESHWORKSPACE1:` | Reticulum nearby discovery, plus optional signed TCP host/port hints | Both devices on a reachable network |
| **v2 — access point** | `MESHCHAT2:` / `MESHWORKSPACE2:` | Outbound TCP to an explicitly approved operator-run Reticulum transport | A third-party or self-hosted access point |
| **v3 — participant-hosted** | `MESHCHAT3:` / `MESHWORKSPACE3:` | The inviter opens a short-lived, invitation-scoped listener on their device and asks their router to publish it; the signed envelope carries the public endpoints and a fresh Reticulum IFAC credential | Inviter online; router mapping succeeds |
| **v4 — email-ready** | `MESHCHAT4:` / `MESHWORKSPACE4:` | Outbound-first attempt, with an optional signed callback and role reversal if the invitee must host instead | An out-of-band channel to exchange signed documents |
| **I2P relay** | `MESHI2P1:` / `MESHI2P1W:` | A signed outer envelope around the complete inner invitation, carrying one validated `*.b32.i2p` access point, its expiry, and the owner binding | Each side runs an I2P router with SAM; the access point is reachable through I2P |
| **Direct setup** | `mesh-direct:` | Signed Offer â†’ Answer â†’ Ready over an experimental QUIC underlay, then an isolated bootstrap interpreter | Both sides can reach each other; physical qualification pending |

Accepting an invitation never creates trust by itself. The recipient reviews the inviter, fingerprint, and workspace details, and the request must still be approved. The first contact on a shared path is bounded by invitation expiry, single use, and explicit consent.

Two honest limits follow from having no infrastructure: if neither participant can accept inbound traffic and they share no already-working path, setup fails and says so; and a self-hosted access point or propagation node is a separate deployment, not a Mesh Chat service. See [deploy/remote-access](deploy/remote-access/README.md).

### Optional community relay

Mesh Chat now has an **optional relay** for easier connectivity over the
Internet. It is not a central account, directory, or message store.

- **TURN** relays encrypted WebRTC/DTLS packets for an active call or WebRTC
  onboarding session.
- A **Reticulum TCP access point** can route encrypted Reticulum/LXMF packets
  when no direct path exists.
- Direct/LAN paths are preferred; the relay is a fallback.
- The relay cannot approve contacts or workspace members.
- It sees connection metadata and encrypted traffic, never message plaintext.
- It does not store messages or workspace history.
- Relay failure leaves local state unchanged.
- Users can opt in, opt out, or provide a community/custom relay.

Cloudflare TURN is supported through a small credential broker
([deploy/cloudflare-turn](deploy/cloudflare-turn/README.md)): the long-term
TURN API token stays on the broker, while Mesh Chat receives short-lived
`iceServers` credentials. Self-hosted coturn remains available at
[deploy/relay](deploy/relay/README.md).

In **Settings → WebRTC calls**, users can enter a Cloudflare TURN broker URL,
override the built-in default, or disable the broker. The built-in default is
`https://staether.webtechalex.workers.dev/credentials`; it is **not used until
the user enables relay consent** and can be changed at any time. See
[the community relay spec](docs/COMMUNITY_RELAY_SPEC.md).

**I2P is an opt-in relay, not the default.** A normal invitation still starts with nearby/direct/participant-hosted/remote choices. I2P is selected explicitly, and the joiner sees the access point and must consent. The access point is a Reticulum `I2PInterface` node addressed by `*.b32.i2p`; it relays encrypted Reticulum/LXMF traffic and does not see message plaintext. Windows bundles and manages `i2pd`; Android has the settings and consent UI but no bundled I2P router yet, so Android cannot complete an I2P join in 0.3.2.

## Workspaces: authority without a server

A group or workspace is a small signed state machine, not a hosted room:

- A **genesis document** names the workspace, its owner, and the one authority device allowed to sign the next manifest.
- Each **manifest epoch** is hash-linked to its predecessor and performs exactly one change: admit a member, deactivate a member, apply a display-name change, update metadata, change a policy, or close. Only the authority device signs it.
- Each **channel** has its own manager-signed chain of records; a private channel adds a signed roster chain that is delivered only to its members.
- Each **message, edit, deletion, reaction, thread reply, and mention list** is a canonical signed event. It binds its author device, per-device sequence and predecessor, the exact manifest and channel heads it was authorized under, and (for private content) a frozen audience. Events arriving before their controls stay inert in a bounded queue rather than becoming visible.
- **Delivery is per device.** A workspace event is copied to each active recipient device, including the sender's other linked devices. Aggregates count devices ("3 of 4 reached") and never turn one receipt into group-wide proof.

Roles are operational, not co-authority: administrators can create and post under an `owner_and_admins` policy and manage channels whose signing key they hold, but only the owner's authority device can change membership, policy, retention, or ownership. Authority can be rotated to another device of the same owner, or transferred to a named member with that member's countersignature. If the authority key is permanently lost, ordinary chat keeps working and administration freezes — the app explains the replacement-workspace path instead of pretending to recover.

## Message lifecycle

```mermaid
sequenceDiagram
    autonumber
    participant UI as React renderer
    participant S as mesh-chat-service
    participant V as Encrypted vault
    participant L as Reticulum / LXMF
    participant P as Peer device

    UI->>S: send_message(contact, text)
    S->>V: commit message + outbox rows (one transaction)
    S-->>UI: queued (durable)
    S->>L: hand off when the recipient ratchet is known
    L->>P: encrypted LXMF delivery
    P-->>L: endpoint proof
    L-->>S: received_by_endpoint
    P->>P: commit message, queue application receipt
    P-->>S: signed receipt for the logical message ID
    S->>V: mark delivered
    S-->>UI: message_status event
```

The UI reports evidence, not optimism:

| State | What it means |
| --- | --- |
| `waiting_for_keys` | Stored locally as ciphertext, but the recipient's current ratchet is not known yet. |
| `queued` | Durable and waiting for a route, retry, or a consent-dependent action. |
| `sending` | Handed to LXMF; the recipient has not committed it yet. |
| `stored_for_delivery` | An LXMF propagation node accepted the recipient-encrypted object. Not a receipt. |
| `received_by_endpoint` | Native transport proof that the recipient device received a copy. |
| `delivered` | The recipient's app committed the message and returned a signed application receipt. |
| `expired` / `failed` / `cancelled` | The seven-day live window ended, validation failed, or the recipient left before the leg completed. |

Receipts are ordinary end-to-end encrypted LXMF messages. They are never acknowledged themselves, and a propagation node's acceptance is never displayed as human read state.

## Security model

| Component | Owns | Must not own |
| --- | --- | --- |
| React renderer | Presentation, in-memory drafts, validated view models | Vault key, private identity, paths, process launch, arbitrary navigation |
| Tauri shell | Credential entry, profile path, IPC validation, process and deep-link lifetime | Routing, message encryption, chat persistence |
| Android/iOS plugin | Embedded CPython lifecycle, app-private path, Keystore/Keychain access | Renderer data, contact policy, routing decisions |
| Python service | Identity, consent, durable state, Reticulum/LXMF integration | OS credential lookup, arbitrary commands, remote control |
| Reticulum / LXMF | Paths, Links, transport, wire format, encryption | Contact trust, membership, durable-delivery claims |
| I2P router / access point | I2P tunnels, relay forwarding, connection metadata | Message plaintext, contact trust, membership, delivery receipts |

The wire uses native RNS identities and destination encryption with ratchets enforced before any send. Invitations are re-derived and signature-checked; a destination that does not match the embedded identity is rejected. Every inbound message must pass native signature validation, exact destination matching, schema validation, expiry checks, and a trust-policy check before it enters the vault. Unknown senders may only create a bounded pending contact request; a workspace has exactly one unknown-source exception — a fully verified join.

The threat model is explicit about what is *not* protected: traffic analysis, IP endpoints and timing, propagation-node metadata, a compromised unlocked endpoint, and content already delivered to another member. There is no anonymity claim, no remote-erasure promise, and no recovery after permanent authority-key loss. Read [THREAT_MODEL.md](THREAT_MODEL.md) for the full list of adversaries, controls, and residual risks.

## Limits

| Limit | Value |
| --- | --- |
| Workspaces per profile | 16 |
| People per workspace | 8 (including owner) |
| Linked devices per member | 3 |
| Active workspace destinations | 24 per workspace |
| Active channels per workspace | 32 (including `#general`) |
| People per private group / announcement channel | 8 |
| Message text | 16 KiB UTF-8 |
| Live delivery and deduplication window | 7 days |
| Default cooperative retention | 90 days (30 / 90 / 365 / indefinite) |
| Local search | Exact tokens; 25 results by default, 50 maximum |
| IPC frame / renderer payload | 4 MiB / 32 KiB default |
| Optional propagation cache (client) | 100 MiB |
| I2P access points per device | 4 |
| Managed I2P router | Local `i2pd` with SAM on `127.0.0.1:7656`; low-bandwidth, no transit, no web console/proxies |
| Attachments, calls, public channels, push notifications | Not supported |

## Status and verification

| Platform | What exists | Recorded verification |
| --- | --- | --- |
| Windows x64 | MSI and NSIS installers, standalone executable plus service sidecar, bundled/managed `i2pd`, I2P invitation and consent UI, 1:1 audio/video call surface | 0.3.2 published; installer launch not rerun after the temporary-folder disk fix |
| Android arm64 | Debug APK, plus release/AAB signing path; I2P settings and invitation preview, 1:1 audio/video call surface | Built and package-inspected; no bundled I2P router and no physical call test in the recorded run |
| macOS | Build path, FileVault adapter | No package built or run in this repository |
| Linux | Build path, fscrypt/dm-crypt adapters | No package built or run in this repository |
| iOS | Plugin and build script | Requires macOS and Xcode; not built or run in this repository |

Automated verification is substantial: Python, Vitest, and Rust suites, plus opt-in real-stack harnesses — a four-process Aâ†’Bâ†’Câ†’D Reticulum/LXMF topology, a two-process direct-LAN harness, a three-process remote-access harness, a packaged-sidecar harness, and QUIC fabric/recovery runs in CI. The recorded evidence, exact hashes, and per-version notes are in [TESTING.md](TESTING.md).

Still open: physical Windowsâ†”Android runs, real router/NAT and cellular traversal, propagation independence, crash-injection matrices, hostile-input fuzzing, accessibility review, macOS/Linux/iOS packages, and an independent security review. CI passing is not a substitute for those gates.

## Repository map

| Path | Contents |
| --- | --- |
| [`service/src/mesh_chat/`](service/src/mesh_chat/) | Protocol documents, vault, RNS/LXMF adapters, I2P router/invitation support, personal/group/workspace/remote services |
| [`src/`](src/) | React messenger interface; no identity or vault access |
| [`src-tauri/`](src-tauri/) | Rust shell: command allowlist, IPC, sidecar lifecycle, CSP, deep links |
| [`vendor/`](vendor/) | Bundled Windows `i2pd` binary and its BSD-3-Clause license |
| [`plugins/tauri-plugin-mesh-runtime/`](plugins/tauri-plugin-mesh-runtime/) | Android/iOS embedded-Python bridge and native device key storage |
| [`experiments/direct-fabric/`](experiments/direct-fabric/) | Rust QUIC underlay proof used by the direct-setup path |
| [`deploy/remote-access/`](deploy/remote-access/) | Example self-hosted Reticulum transport and LXMF propagation host |
| [`deploy/turn/`](deploy/turn/) | Example self-hosted coturn relay for cross-network WebRTC calls |
| [`scripts/`](scripts/) | Build, packaging, release, and verification drivers |
| [`docs/adr/`](docs/adr/) | Nineteen architecture decision records |
| [`service/tests/`](service/tests/) | Unit, integration, and opt-in real-stack harnesses |

## Build and test

Prerequisites: Node.js 20+, pnpm 11.25.0, Python 3.11–3.14, Rust 1.77.2+, and the [Tauri 2 platform prerequisites](https://v2.tauri.app/start/prerequisites/).

```sh
python -m venv .venv
. .venv/bin/activate                      # Windows: .\.venv\Scripts\activate
python -m pip install -r service/requirements-dev.lock
pnpm install --frozen-lockfile

python scripts/test.py                    # Python + frontend + artwork + typecheck + build
python scripts/release.py build --platform all
```

Desktop installers must be built on their target operating system. Android builds on Windows, macOS, or Linux; iOS requires macOS with Xcode. Development packages are not code-signed.

## Documentation

| Document | Why read it |
| --- | --- |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Component boundaries, workspace internals, persistence, crash consistency |
| [PROTOCOL.md](PROTOCOL.md) | Exact signed documents, LXMF fields, limits, delivery evidence |
| [WORKSPACE_SPEC.md](WORKSPACE_SPEC.md) | Product scope, roles, requirements, and release gates for workspaces |
| [THREAT_MODEL.md](THREAT_MODEL.md) | Adversaries, controls, metadata leakage, and open security blockers |
| [TESTING.md](TESTING.md) | Recorded verification, acceptance matrix, and exact artifact evidence |
| [docs/RELEASES.md](docs/RELEASES.md) | Release-by-release notes and installation history for earlier versions |
| [docs/adr/](docs/adr/) | Why the stack, IPC, groups, workspaces, retention, and connectivity work this way |
| [Direct connectivity roadmap](docs/DIRECT_CONNECTIVITY_ROADMAP.md) | Invitation bootstrap, traversal, recovery phases, and qualification status |
| [I2P support specification](docs/I2P_SUPPORT_SPEC.md) | I2P access-point architecture, Windows/Android roadmap, consent, and limits |
| [WebRTC adapter roadmap](docs/WEBRTC_ADAPTER_SPEC.md) | DataChannel connection bootstrap, STUN/TURN policy, 1:1 call increments, and decision gates |
| [C5 DataChannel bridge spec](docs/C5_DATACHANNEL_BRIDGE_SPEC.md) | Reticulum-over-DataChannel bridge, IPC, signaling, onboarding, and TURN policy |
| [Relay deployment](deploy/relay/README.md) | One-command TURN relay with TCP/UDP 443, credentials, and VPS hardening |
| [Cloudflare TURN broker](deploy/cloudflare-turn/README.md) | Short-lived Cloudflare TURN credentials without shipping the API token |
| [Community relay spec](docs/COMMUNITY_RELAY_SPEC.md) | Opt-in default/community relays, TURN + Reticulum access point, consent, failover, and no central store |
| [WebRTC physical test plan](docs/WEBRTC_PHYSICAL_TEST_PLAN.md) | Windows/Android call, TURN, foreground-service, and privacy qualification matrix |
| [docs/ANDROID_PARITY.md](docs/ANDROID_PARITY.md) | Android capability status and the physical test matrix |
| [deploy/remote-access](deploy/remote-access/README.md) | Running an access point or propagation node without becoming a Mesh Chat service |
| [deploy/turn](deploy/turn/README.md) | Self-hosted coturn relay and quota boundary for cross-network calls |

Third-party artwork, emoji data, and their licenses are listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## License

Mesh Chat is released under the [MIT License](LICENSE). Third-party artwork and data remain under their own licenses, listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md); the bundled Reticulum, LXMF, Python, and JavaScript dependencies keep their upstream licenses. The license does not grant rights to the Mesh Chat name or logo.

# Mesh Chat direct connectivity implementation specification

Status: ready for implementation in a new session. The user explicitly selected fully server-free operation and accepts that some networks cannot connect.

Date: October 18, 2026.

Audited baseline: version 0.2.50, commit `509a2822d5f8ff20e995bcc7f2e52b92d970bb96`. Recheck the current branch before implementation. This document specifies new work; it does not claim that the features or acceptance tests below already pass.

## Intended outcome

A Windows device behind a home router and an Android device on mobile data must be able to collect all permitted connection information and attempt a direct connection without making manual port forwarding the default solution. Where usable peer addresses are known and coordinated NAT traversal succeeds, the devices must connect directly, deliver the signed workspace join request, obtain owner approval, and exchange messages with endpoint receipts. Where no public tuple can be learned without external services, or direct traversal fails, the app must retain the request and explain precisely why it remains disconnected.

Preserve the existing Reticulum identity, LXMF messaging, workspace admission, signed receipts, encrypted storage, QUIC transport, and relationship recovery. Extend the missing discovery and traversal layers. A successful transport connection must never substitute for owner acknowledgment or membership approval.

This is an incremental specification, not a replacement project. Many requirements below describe behavior that already exists and must continue working after traversal changes. Lack of physical qualification is not evidence that a feature is unimplemented. Do not rebuild a capability merely because it appears in an outcome or acceptance row.

The primary physical acceptance case is the user's Windows home network and Android cellular network. Android must remain on cellular throughout that case. Connecting both devices to Wi-Fi does not satisfy it. The observed failure does not establish that these networks are inherently impossible to hole-punch. This specification does not guarantee that this particular pair can connect under the server-free constraint; its measured result must be reported honestly.

## Observed failure and current implementation

The user installed the updated builds and completed the newer Offer, Answer, Ready exchange. The app returned:

> Neither device supplied a public direct candidate. The saved join request continues over existing routes, including signed TCP routes.

Windows detected an Internet route but reported no usable global IPv6 and no PCP, UPnP, or NAT-PMP discovery response. These observations establish that the current collector supplied no usable candidates. They do not establish the exact router filtering behavior, carrier NAT type, or impossibility of a direct connection.

The source audit found the following:

| Component | Existing behavior | Gap to close |
| --- | --- | --- |
| Native transport | Tauri imports the crate under `experiments/direct-fabric`; it is shipping code despite its directory name | Keep the shared Windows and Android integration |
| Candidate collection | Chooses one eligible route, binds a native UDP socket, and advertises a global address or router-created UDP mapping | Multiple eligible paths, complete permitted sources, and authenticated peer-reflexive discovery |
| Initial connection | One deterministic client performs bounded standard QUIC dialing; the other listens | Coordinated checks from both endpoints before QUIC establishment |
| Empty candidate sets | Returns `existing_routes_only` before native activation | Attempt permitted discovery first; explain unavailable discovery and existing routes separately |
| Recovery | Retains relationships, recollects candidates, sends signed updates, renews mappings, supports migration and alternating dial/listen roles | Extend the existing engine to multiple paths and the new coordinated checks |
| Setup interface | Separate invitation and connection-document flows; four-minute setup chain and a bounded activation window | One guided manual exchange, automatic coordination over an existing authenticated peer path, and clear expiry/recovery |
| Qualification | Source tests and controlled real-QUIC pipelines | Controlled NAT traversal evidence and physical Windows-to-cellular evidence |

Relevant implementation entry points:

- [Candidate collector](../service/src/mesh_chat/direct_candidates.py), [setup controller](../service/src/mesh_chat/direct_setup.py), and [role selection](../service/src/mesh_chat/direct_path.py).
- [Native dispatcher](../src-tauri/src/direct_native.rs), [Android native integration](../src-tauri/src/mobile_direct.rs), and [shipping dependency](../src-tauri/Cargo.toml).
- [Initial traversal](../experiments/direct-fabric/src/traversal.rs), [native activation](../experiments/direct-fabric/src/host.rs), and [recovery](../experiments/direct-fabric/src/recovery.rs).
- [Setup interface](../src/DirectConnectionSetup.tsx), [invitation interface](../src/App.tsx), and [setup regressions](../service/tests/test_direct_setup.py).

The existing no-candidate regression intentionally asserts that native activation does not occur. Revise that behavior only when discovery supplies authorized candidates; never fix it by sending to guessed destinations or pretending an empty set is reachable.

### Flow integration and observed failure stages

The newer setup is wired to the service: `DirectConnectionSetup` calls `prepare_direct_offer`, `prepare_direct_answer`, `prepare_direct_ready`, `accept_direct_ready`, and `connect_direct_setup`. The latter dispatches to the controller whose no-candidate branch produced the user's final message. That result is not evidence of a disconnected button or an uncalled native feature; it is the configured stop before native activation.

The product flow is only partially consolidated. The workspace invitation dialog still defaults to the older participant-hosting route, exposes the newer setup as an additional section after creating an invitation, and offers both ordinary invitation text and separate direct connection documents. Ordinary invitation imports use the saved-request/callback path; direct connection documents use the newer controller. The user's early attempts followed the ordinary path, while the final Offer/Answer/Ready attempt reached the newer controller and stopped because no public candidate was supplied.

Separate these causes during implementation: route-detection defects, navigation/document confusion, expiry or lost socket ownership, and absence of usable endpoints. Fixing navigation alone cannot make two unknown public mappings reachable. Conversely, a network limitation must not be used to dismiss incorrect navigation or missing calls. Add a user-level regression from the default Invite entry point through recipient receipt and approval on a supported topology; isolated component tests and a correctly displayed fallback message are insufficient product acceptance.

## Existing work to preserve and remaining implementation delta

Recent development did implement the direct transport and substantial setup and recovery behavior. The [Phase 2 evidence](DIRECT_CONNECTIVITY_PHASE2_EVIDENCE.md) records the implemented exchange and native integration, while the [Phase 3 evidence](DIRECT_CONNECTIVITY_PHASE3_EVIDENCE.md) records completed automated recovery qualification at `5ba2b44`. Those records retain physical validation as a separate gate.

| Capability | Baseline status | Required action in this work |
| --- | --- | --- |
| Native QUIC on Windows and Android; private service/native boundary | Implemented and covered by native/package qualification | Reuse the engine and dispatcher; adapt reception only as needed for coordinated checks |
| Native socket ownership through prepare, inspect, arm, and activate | Implemented, with substitution and lost-ownership regressions | Preserve and extend to multiple candidate sockets; do not replace with a second discovery socket |
| Public IPv4/IPv6 and PCP, UPnP, NAT-PMP UDP candidates | Implemented and protocol-tested | Improve route coverage and fair selection; do not rewrite working mapping protocols |
| Signed Offer, Answer, Ready; reply without a local public candidate | Implemented and covered by setup/path tests | Integrate the check protocol and improve the workflow while retaining authorization |
| Expiry, stale exports, replay, selected-peer checks, and suspension invalidation | Implemented and tested | Preserve rejection rules; improve resume and diagnostic usability |
| Signed join receipt and durable request before route work | Implemented and tested, including retry/restart | Preserve exact request identity and distinguish receipt from approval |
| Existing direct TCP fallback and no-candidate queue status | Implemented | Verify coexistence with new attempts; improve explanation without inventing reachability |
| Durable relationships, signed updates, lease renewal, retry fairness, port reuse, restart reconciliation | Implemented and covered by Phase 3 suites | Integrate the new candidate/check engine; retain current scheduling and cleanup guarantees |
| Alternating recovery roles, authenticated migration, safe replacement before retirement | Implemented and qualified in controlled native tests | Preserve; do not misrepresent these as initial two-sided punching |
| Initial coordinated checks from both peers and path nomination | Missing from the initial shipping path | Implement and prove with the NAT fixture and negative control |
| Multiple-route candidate coverage and candidate-pair fairness | Partial; collector currently retains one preferred candidate | Extend collection and scheduling; prove alternatives are not starved |
| Guided pending-join recovery without the original clipboard; normal Android sharing/resume UX | Partial; existing refresh and invalidation are present | Fix the specific usability and recovery gaps, not the underlying signed exchange wholesale |
| Version display and copied diagnostics | Shared Settings already renders the package version; the older connection checker can copy a sanitized summary | Improve discoverability and extend copying to the newer setup, recent connection logs, and runtime build identity |
| Physical home-router-to-cellular traversal proof | Not established | Execute and record separately; do not treat either compilation or an unsupported result as a connection pass |

Useful existing regressions are [candidate tests](../service/tests/test_direct_candidates.py), [setup tests](../service/tests/test_direct_setup.py), [role/path tests](../service/tests/test_direct_path.py), [join receipt tests](../service/tests/test_workspace_join_receipt.py), [recovery tests](../service/tests/test_direct_recovery.py), and [renewal/port tests](../service/tests/test_direct_recovery_candidates.py). Use these as the baseline, adding tests for actual deltas instead of duplicating them under new names.

Before implementation, produce a short delta checklist mapping each F1–F8 feature to existing functions/tests, the smallest missing behavior, and its acceptance evidence. A feature already satisfying the requirement needs verification and preservation, not a new implementation. In particular, F4 is mostly preservation, F5 is integration with an existing recovery system, and F3/F6 are improvements to a working but confusing setup flow. F7/F8 extend existing diagnostic-copy and version-display primitives. F2 and multi-candidate coverage in F1 contain the principal new transport work.

## Server free operation

The user chose: **Require fully server-free operation, accepting some networks cannot connect.** This resolves the assistance-policy question. The next session must not ask the same question again or change this requirement to make acceptance easier.

The implementation must add no public or self-hosted STUN observation service, public-IP lookup, rendezvous server, signaling server, TURN or other relay, DHT/bootstrap service, VPN service, or mandatory third-device helper. Local router protocols and the two communicating devices are permitted; a peer listening for the other's connection is not a separately operated service. No optional external-service mode is part of this implementation.

Users may continue choosing their own email, messaging app, QR, file, or clipboard to move signed connection documents. Mesh Chat must not integrate with, poll, or depend on an email provider API. The application exchanges controls automatically only over an existing authorized peer path. Existing unrelated Reticulum configurations must remain compatible, but neither an access point nor an unrelated mesh participant may be counted as satisfying this direct, two-device acceptance case.

Peer-to-peer STUN-formatted authenticated connectivity checks are allowed as an implementation technique; that does not authorize contacting a separately operated STUN observation service. Permitted address evidence comes from local global addresses, actual local-router mappings, existing valid signed peer information, or authenticated observations made by the intended peer when a path to it already exists. An authenticated peer may learn the other's observed tuple during checks, but it cannot report an observation before traffic reaches it.

When both public mappings are unknown and there is no usable path, the protocol must stop with an explicit discovery limitation. It must not guess a tuple, scan address ranges, infer a public endpoint from a private address, or claim that additional email exchanges will discover one. Preserve this boundary in code, network-audit tests, documentation, and release claims.

## User outcomes

### O1 One guided join workflow

The owner creates a workspace invitation and the recipient imports it. One guided workflow manages the required signed manual exchanges and explains who must act next. Once an authenticated peer path exists, both apps exchange refresh and coordination controls automatically. The owner sees a join request only after its durable validation; approval is still explicit. Users must not have to choose among overlapping ordinary invitation, callback, and QUIC screens to find the supported path.

### O2 Direct connection through compatible NATs

Where usable tuples are already known or can be learned through permitted peer interaction, devices behind compatible NATs exchange authenticated checks from their retained sockets, select a working path, and establish QUIC directly. A tuple is an IP address and port; learning one is not proof that another device can reach it. At least one known reachable endpoint may permit learning the other through authenticated checks; both devices do not need to advertise public candidates initially.

### O3 Honest fallback

If no UDP path works within the attempt budget, try an existing authorized direct TCP route only when one is actually available. Otherwise retain the request and show a concrete reason and available action. Do not imply that waiting, a new invitation, or repeated copies will discover an unknown mapping. Do not use a relay or third-device path to turn a failed direct test into a pass.

### O4 Recovery without new admission

App restart, short outages, mapping renewal, and supported network changes preserve the admitted relationship and queued logical message IDs. Recollect permitted candidates and validate paths as needed. When every known path is unavailable, request a refreshed manual exchange if it can supply useful information; otherwise explain the discovery limitation without claiming a connection.

### O5 Recoverable setup

Users can resume a pending request without retaining the original clipboard text. Connection-detail refresh keeps the exact underlying invitation and signed join request where still valid. If a new invitation is necessary, require an explicit restart flow that safely retires the old local attempt, handles possible remote approval races, and does not silently change identities or duplicate admission.

### O6 Debugging without developer tools

On both Windows and Android, a user can see the installed version and copy a useful, sanitized diagnostic report or recent connection log directly from the app. This must work from a stalled or failed setup without leaving the workflow, losing the pending request, opening a console, finding files, or taking screenshots of technical text. The user chooses whether and where to share the copied information; the app never uploads it automatically.

## Architecture and responsibilities

Keep the current division of responsibility:

- The protected Python service owns RNS identity, signature verification, invitation and membership authority, replay generations, durable records, and permitted network policy. Existing local-router mapping transactions also run in the service; preserve that implementation unless an ADR justifies moving it.
- Native Rust owns sockets, socket-bound connectivity checks, QUIC, path selection, timers, packet demultiplexing, and lifecycle cancellation. Service-provided mapping results must still match fresh native socket ownership evidence.
- React renders sanitized states and user actions. It must not gain raw socket control, packet injection, private keys, or unchecked destination probing.
- The intended peer may report a tuple it actually observes on authenticated traffic. This evidence does not create workspace membership, prove reachability from another destination, or replace the identity trust anchor.

Maintain one receive owner for each native socket. Discovery, checks, and QUIC must share a deliberate packet dispatcher or a reviewed integration with equivalent guarantees. Do not add competing readers, advertise a socket then replace it, or bind a second discovery socket and assume its public mapping applies to QUIC. Multiple interfaces may use multiple owned sockets, each with its own candidate generation and mapping evidence.

The transport path remains:

```text
Mesh Chat and LXMF
        |
Reticulum and authorized private adapter
        |
Native candidate checks and QUIC
        |
Direct peer path

Signed connection controls travel through a user-mediated document
exchange or an existing authenticated path between the same peers.
```

## Required features

### F1 Candidate discovery and provenance

Gather bounded candidates across eligible IPv4 and IPv6 routes instead of exclusively trying the first preferred route. Include global addresses, actual PCP/UPnP/NAT-PMP results, and still-valid signed peer information where applicable. Add peer-reflexive candidates only from authenticated connectivity checks. Do not introduce a public observer to fill an empty candidate set.

Record each candidate's source, socket ownership, interface generation, address family, lifetime, and validation status. A peer-observed address is a destination-specific observation, not an unconditional reachability claim. Do not advertise private or shared upstream router addresses as public endpoints. Keep nearby candidates in their existing explicit scope.

Handle absent IPv6, several default routes, VPNs, stale mappings, network switches, discovery timeouts, malformed responses, and changes between observation and use. A failed preferred route must not prevent testing another permitted route. Preserve the Windows single-stack default-route regression fixed in 0.2.50.

### F2 Coordinated checks from both devices

Implement a standards-based ICE check and nomination process, or document and independently review a smaller equivalent protocol before implementation. Prefer an established interoperable implementation where it can satisfy native socket ownership and the existing authorization model. A loop of QUIC client handshakes against a passive listener does not meet this feature.

Both endpoints must be able to send authenticated connectivity checks to authorized candidate pairs during overlapping attempt windows, before declaring a nominated path usable. Specify role conflict resolution, transaction matching, short-lived check credentials, authentication of replies, peer-reflexive candidate handling, liveness consent, and expiry. Separate check roles from the eventual QUIC client/server roles.

Schedule candidate pairs fairly with bounded concurrency and retransmissions. An unreachable first candidate, broken IPv6 path, or unresponsive peer or router must not consume the whole attempt budget and starve working alternatives. Bind the QUIC handshake to the validated identity and selected path, not merely to successful STUN or an address response.

### F3 Resilient coordination between devices

Keep signed Offer, Answer, Ready controls or replace them with a documented versioned exchange that provides equivalent authorization. Make manual sharing explicit, guide the user to the next action, and ensure both endpoints have overlapping connection windows. Once either direct path works, exchange subsequent fresh controls over it automatically instead of requiring further copy/paste.

Separate invitation expiry, candidate lifetime, socket generation, and attempt timeout. Display the actual remaining setup time. Explain whether refresh will extend the deadline; the old implementation's refresh during an active lease did not. Expired controls must remain rejected, and a refreshed exchange must preserve the saved join request and selected peer. Never extend an advertised mapping beyond its actual lease or resurrect a lost socket to make a countdown appear longer.

Define durable versus runtime state, duplicate and reordered imports, clock skew handling, cancellation, and revocation. Use monotonic attempt timers and bounded signed wall-clock validity. A stale manual document must lead to a specific refresh action rather than a generic unverifiable-document message. Manually exchanged controls cannot discover an unknown public tuple by themselves.

### F4 Direct fallback and unsupported topology handling

Preserve existing authenticated direct TCP routes and test them as a separate path when UDP cannot be established. A viable signed TCP endpoint must exist; do not infer one from the successful exchange of a file. Do not reintroduce mandatory Windows port forwarding as the default implementation of this requirement.

If no direct path remains, report the limiting evidence: no permitted public-address source, no response to checks, invalid or expired controls, lost socket ownership, or a known policy denial. Distinguish confirmed policy from a timeout whose cause is unknown. Keep a durable request and provide safe refresh/cancel actions. No connection state may suggest that repeated waiting guarantees success.

With both addresses unknown and no existing path, this feature's correct outcome is an honest unsupported discovery state. That result is acceptable under the user's server-free choice, but it does not count as a successful physical direct connection.

### F5 Integrate initial setup and recovery

Use the new discovery and check engine for both initial admission and recovery. Retain useful known paths while validating replacements. Preserve signed generations, replay protection, candidate cleanup, port reuse where supported, and existing migration behavior. Revalidate authority before activation and before accepting a replacement path.

On Android, explicitly handle activity pause, stop, resume, Doze, process death, and network changes. Normal sharing through another app must either retain the setup under a supported lifecycle policy or transparently refresh it on return using the same durable request. Split-screen must not be an undocumented requirement. Do not promise background availability that the OS cannot provide; any foreground service requires appropriate user-visible behavior and platform permissions.

### F6 Simple guided setup

The product must expose one clear **Invite someone** entry point and one **Join or connect** entry point, or equally clear final labels. Use the same workflow on Windows and Android. Route legacy invitations and newer connection documents through a shared user-facing controller that selects the correct verified backend action. Internal protocol compatibility may remain; duplicate public workflows must not.

Every setup screen must answer three questions in plain language: **What happened? Who needs to act next? What should I do now?** Name the device or role explicitly, such as **On this phone** and **On the owner's computer**. Show a short progress indicator and one primary next action. Keep technical terms such as candidate, QUIC, Offer/Answer/Ready, NAT-PMP, and socket ownership in optional details, not instructions a user must understand to proceed.

Use a guided exchange like the following, adapting device labels to the actual platform:

| Stage | Plain-language explanation | Primary action |
| --- | --- | --- |
| Owner starts | Send this invitation to the person you want to add | Share invitation |
| Recipient imports | Invitation checked. Send this reply back to the owner | Share reply |
| Owner receives reply | Reply checked. Send the final connection message to their device, if the protocol requires one | Share connection message |
| Recipient receives final message | The connection message is ready to use | Connect |
| Network attempts are running | Both devices need to stay open while we try to connect | Show bounded progress; expose Cancel and diagnostics as secondary actions |
| Owner has received the request | The request reached the owner and needs approval | Approve or decline on the owner; Wait for approval on the recipient |
| Connection cannot proceed | Explain the observed problem, say the request is saved, and name the available next step | Resume, refresh, or another action that actually applies |

Provide one clearly labeled paste/import field that accepts any supported invitation or connection message, detects its verified type, and guides the next step. Do not ask the user to choose the document format or search for a different paste field. Hide raw document text behind a details control where possible; Copy, Share, Save, and QR must all represent the same current outgoing step. Do not place an ordinary invitation QR beside a different connection document with equally prominent copy buttons. If an older document is pasted, explain how the app will continue rather than silently moving the user into an unrelated wizard.

Keep the active step and pending request accessible after closing a dialog. The workspace status card must offer **Continue setup** with the correct next action. Expiry must display a clear countdown and a refresh action; an unrelated week-long invitation expiry must not appear to explain a short-lived connection error. Do not default to instructions to use the same Wi-Fi network during a cellular test or present router configuration as the normal next step.

The primary action, status, and diagnostic-copy controls must fit phone layouts without horizontal scrolling or squeezed columns. Support keyboard navigation, screen readers, large text, and clear button labels instead of unexplained icon-only actions. A new user must be able to follow the normal flow using only on-screen instructions, without a developer explaining where to paste each document.

Provide a single guided interface that shows progress and the actual remaining action:

- Preparing connection details.
- Collecting permitted public addresses and router mappings.
- Trying direct paths.
- Connected directly, with UDP/QUIC or direct TCP identified in diagnostics.
- Join request received and awaiting approval.
- Joined, with message and endpoint receipt state shown separately.
- No usable path, with a structured reason and permitted next action.

Distinguish missing candidates, no permitted discovery source, checks timed out, policy denial, UDP blocking evidence, expired controls, lost socket ownership, invalid signatures, replay, and wrong invitation. Do not expose raw secrets or assert a NAT classification that has not been established. A signature-valid document is not a live connection.

Display separate invitation and connection-detail expiries. Offer Resume setup, Refresh connection details, and Cancel pending attempt from the saved workspace. Cancellation must preserve unrelated local data and explain any request already received by the owner. Never require deleting app data or creating another workspace to recover an ordinary setup failure.

### F7 Copyable diagnostics and connection logs

Add **Copy diagnostics** to every setup, failure, pending-workspace, and recovery status surface. One click or tap on that control must copy a self-contained report without cancelling or restarting the attempt. Also provide **Settings → Help and diagnostics**, reachable within two navigational actions from the main app, for the current or most recent attempt. Reuse the older connection checker's sanitizer and report fields where appropriate; extend coverage to the newer controller, native checks, and application receipt stages.

In the same view, offer **Copy connection log** for a chronological, bounded set of recent structured events. This is a distinct action from copying a summary. Users must not need filesystem access, developer mode, a terminal, or knowledge of where logs are stored. Preserve the latest sanitized failure report across an ordinary app restart so a crash or relaunch does not destroy the only debugging context. Apply the existing protected storage policy and a documented retention/size limit; provide **Clear diagnostic history** without deleting messages, identity, or workspace state.

The diagnostic report must include:

- Mesh Chat version, platform, available OS version, Android versionCode or Windows build identity, build commit, and report-format version. Show unknown fields as unavailable rather than guessing.
- Capture time with time-zone offset and a non-authorizing attempt reference. Use the same reference to correlate summary and log events; it must not be an invitation or session credential.
- Current user-visible step, controller/transport path selected, and whether checks were attempted or stopped before native activation.
- Candidate counts by source and address family, check/response counts, elapsed time, relevant expiry or refresh reason, and direct UDP/QUIC versus TCP path category.
- Application facts separately: request saved, owner receipt confirmed, approval pending/complete, and message/receipt outcome where applicable.
- Sanitized error codes, a plain-language explanation, the next available action, and any missing subsystem data.

Log events must cover preparation, permitted address collection, local mapping outcome, manual import/export type, validation result, attempt start/stop, selected path, lifecycle interruption, refresh, receipt, and approval. Record times, elapsed durations, phase transitions, and outcome codes rather than unrestricted raw exceptions or packet dumps. Initial export limits should be explicit, for example the latest 200 events capped at 64 KiB; if a different bound is chosen, document it. State when the output is truncated.

Generate copied output from an allowlisted diagnostic schema. Exclude private keys, invitation bearer tokens, full connection documents, check passwords, message contents, personal names, full fingerprints, IP/MAC addresses, and sensitive local paths. Add seeded-secret regression tests across renderer, service, and native events. Do not log pasted clipboard contents. A debug log must never become an alternate source of usable invitation credentials.

Copying must show a short **Copied** confirmation. On clipboard denial or failure, show selectable text and a **Save diagnostics** or user-initiated Share action. Do not claim success before the clipboard operation succeeds. Copying diagnostics must not require a healthy networking service; return available app/build information plus a clear service-unavailable field when needed. Nothing is uploaded, emailed, or sent to another app until the user explicitly selects a sharing action.

### F8 Visible installed version on both platforms

Preserve the existing `Mesh Chat {packageInfo.version}` display and improve its visibility. On both Windows and Android, show **Mesh Chat version X.Y.Z** near the top of the first Settings screen, without requiring scrolling to the bottom. Also show the version in Help and diagnostics and as a compact footer in connection status/error details, so screenshots and copied reports identify the build.

Offer **Copy version details** from Settings or Help and diagnostics. Include platform, installed app version, Android versionCode where applicable, build commit/identifier, and available native/service versions. Read metadata from the installed build and actual responding components; do not hard-code a release number or substitute the repository's current source version for an older installed service. If components disagree, report their versions and the mismatch explicitly.

The app version must remain available when networking is offline or the protected service cannot start. Obtain non-sensitive application build metadata without requiring a successful connection or workspace join. Release validation must compare displayed/exported metadata with package manifests and built artifact identity on both Windows and Android. Improving this display must not obscure existing attribution or accessibility content.

## Security and compatibility requirements

Do not weaken signature, audience, invitation, device, membership, or replay validation to make traversal succeed. Check credentials may authorize only bounded connectivity work; they cannot authorize ordinary workspace traffic before admission. Preserve the existing isolated bootstrap and fresh admitted transport handoff.

Reject malformed or oversized candidate sets, prohibited address classes, stale generations, unauthorized peer instructions, and packets from the wrong session. Limit preauthentication responses and probe traffic to prevent amplification, reflection, scanning, and resource exhaustion. Rate-limit per peer and globally. Cancel native work when authority expires, the workspace is removed, or the service loses ownership.

No external or separately operated discovery, signaling, or relay service may be contacted, including as an emergency fallback. Permitted local-router protocols and intended-peer checks remain allowed. Test this boundary by observing the networking process and its descendants. User-mediated sharing is separate from runtime network behavior; the app must neither access the sharing account nor treat its operator as a trusted participant.

Version any new control schema; preserve readers for existing supported invitations. Validate bounds and compatibility before network side effects. Bind candidate provenance and check credentials into authenticated controls as appropriate. Review protocol changes with the existing [threat model](../THREAT_MODEL.md) and [protocol](../PROTOCOL.md).

## Acceptance and evidence

Every feature must have evidence tied to a commit. Separate source tests, native integration, emulated NAT results, and physical network results. Existing synthetic-public-address-to-loopback tests remain useful integration tests, but they cannot count as NAT traversal proof.

The initial attempt budget should remain bounded to 60 seconds unless an ADR justifies a change. Target direct establishment within that budget once both peers have fresh controls and are actively participating in a supported test topology. Record actual timings and failures; do not claim measured performance from this target. Candidate counts, pair counts, concurrent work, packet rates, queue sizes, and session budgets must be explicit and tested before release.

| ID | Scenario | Required evidence |
| --- | --- | --- |
| A1 | Public IPv4 or reachable IPv6 on one side; other side unhosted | Direct QUIC, signed owner receipt, approval, and bidirectional messages with endpoint receipts |
| A2 | Both peers behind controlled compatible NATs; usable tuples supplied as test-only evidence; no explicit router mappings | Both send authenticated checks from retained sockets before establishment; direct communication succeeds without an external service |
| A3 | Negative control for A2 | Disable coordinated checks while retaining the same topology; passive inbound connection must fail, proving the fixture actually requires punching |
| A4 | One known reachable peer; other tuple initially unknown | Intended peer observes authenticated check traffic from the actual socket; peer-reflexive learning and path nomination work without an observer service |
| A5 | Both public tuples unknown; no permitted source or existing route | Correct bounded discovery failure; no guessed probes, hidden external services, or false owner acknowledgment |
| A6 | Unreachable preferred candidate and reachable alternative; IPv4 and IPv6 combinations | Working alternatives receive attempts within the budget; no starvation or unsafe family mixing |
| A7 | Destination-dependent mapping and restrictive filtering | Record actual behavior; no universal success claim. Failed traversal produces an explicit unsupported direct outcome |
| A8 | UDP blocked at one side and at both sides | Existing authorized direct TCP works if available; otherwise bounded explicit failure without repeated invitation loops |
| A9 | Mapping lease expires or all known addresses change | Recollect and refresh over a surviving direct path, or request a useful manual update; no fabricated address or external fallback |
| A10 | Setup refresh, duplicate/reordered controls, clock skew, expired chain, and lost original clipboard | Same request can resume safely; stale/replayed/mismatched controls remain rejected; no duplicate admission |
| A11 | Restart, sleep, Android sharing and resume, and network switches | Relationship and queued logical IDs preserved; fresh path validation and key handling; receipts remain meaningful |
| A12 | Cancellation, revocation, failed ownership, and hostile traffic | Active work and leases retire within defined bounds; no cross-workspace effects or unauthorized packets |
| A13 | Server-free boundary | Network observation proves no external observers, signaling services, relays, DHT/bootstrap nodes, or helper dependencies are used |
| A14 | Physical Windows home router and Android cellular | Record builds and coarse topology; on a supported path complete join, owner approval, and bidirectional message/receipt checks; otherwise record the exact unsupported condition |
| A15 | Simultaneous initiation, check-role conflict, and duplicate successful paths | Both devices agree on one nominated session; losing paths retire without duplicate joins, duplicate approval dialogs, or loss of the selected request |
| A16 | User starts at the default Invite screen and follows the displayed steps on both devices | The intended controller is invoked, document types/actions are unambiguous, and a supported topology reaches signed receipt and approval; no hidden second setup flow or manual knowledge of internal document types is required |
| A17 | Usability on Windows and Android, including 360/393px phone widths and large text | A fresh tester follows only in-app instructions; one current outgoing item and one import entry point; correct device/next action, no horizontal overflow, and setup can resume from the workspace |
| A18 | Copy diagnostics and Copy connection log from pending, failed, expired, and offline states | Correct build and attempt information, chronological bounded events, explicit missing data, no seeded secrets, successful-copy feedback, and usable clipboard-denial fallback; the active request remains unchanged |
| A19 | Installed version visibility and copy on both platforms | Version appears near the top of Settings and in diagnostic surfaces; copied version/build metadata matches the installed artifact; service absence and component mismatch are handled accurately |
| A20 | Restart after a connection failure and clear diagnostic history | Most recent sanitized failure remains copyable after restart; limits/truncation are visible; clearing diagnostics preserves identity, requests, workspaces, and messages |

The A2 fixture must drop unsolicited inbound UDP at both peers until the necessary outbound traffic creates the allowed filtering state. Capture enough sanitized evidence to establish address mapping, packet direction, same-socket use, and absence of relaying. Use real native transport inside the controlled topology. The harness may inject simulator-known public tuples through a test-only signed input to isolate traversal from discovery. Label that provenance explicitly: it proves punching with known tuples, not a deployable solution to two unknown public mappings. No fixture bypass may ship. A fabricated NAT label, mocked success response, or loopback-only handshake does not satisfy A2.

Run a repeatable set of trials for each supported NAT profile, recording totals, failures, elapsed times, packet budgets, and cleanup. Include mapping expiration, changing external ports, double NAT, endpoint-dependent mapping, and asymmetric reachability. Advanced port prediction is outside the initial implementation; it may be evaluated later only with measured benefit and explicit resource bounds.

A14 is an outstanding physical gate. Do not mark the physical connection passed from CI, a build artifact, a prepared candidate, or an accurate unsupported message. If the user's topology has no server-free path, record that limitation and qualify supported direct topologies separately. The user accepts some network failures; do not reinterpret that acceptance as permission to claim universal connectivity or to omit physical testing.

## Implementation sequence and deliverables

1. **Confirm implementation and architecture.** Recheck shipped paths against this baseline and produce the F1–F8 delta checklist. Preserve completed behavior and identify the smallest changes needed; do not rebuild Phases 2 or 3. The server-free policy is already decided. Write the ADR for permitted candidate sources, check protocol, manual/direct coordination, socket integration, and resource bounds. Update contradictory claims in the roadmap and troubleshooting guide.
2. **Build the controlled NAT harness.** Establish the failing A2/A3 baseline against the shipping dispatcher before claiming new traversal. Keep all existing identity and transport tests.
3. **Implement candidate collection and coordinated checks.** Add multiple paths and provenance, intended-peer observation, shared socket reception, fair scheduling, nomination, and authorization. Prove direct traversal under the server-free boundary.
4. **Integrate coordination and recovery.** Improve manual exchange, automate refresh over surviving authenticated peer paths, preserve direct TCP fallback, and reuse the engine for admitted relationships.
5. **Complete the user workflow.** Replace overlapping setup paths with one plain-language controller, actionable failures, pending-request recovery, and supported Android lifecycle behavior. Deliver visible installed-version information and copyable sanitized diagnostics/logs on both platforms, including offline and clipboard-failure paths.
6. **Qualify and release.** Run required suites and NAT evidence jobs, produce versioned Windows/Android artifacts, execute physical acceptance, and report remaining gaps explicitly.

Required deliverables are the ADR, implementation, meaningful regressions, controlled NAT harness and reports, updated protocol/threat-model/troubleshooting documentation, and an acceptance table with links to exact-commit evidence. A feature is not complete because its UI, configuration, mock, or isolated experiment exists. Physical execution that requires user devices must remain a clearly recorded gate until performed.

## Build and release discipline

Follow the repository's current [testing instructions](../TESTING.md). Native execution, frontend/package qualification, and Windows/Android release builds run in GitHub Actions. Use the existing direct-fabric and release workflows, extending them for isolated NAT evidence as needed. Do not run local native builds to bypass that constraint.

The baseline version is 0.2.50. Choose the next unused version at release time and increment Android versionCode. Use `scripts/release.py version <version>` and `scripts/release.py check --expected-version <version>` to keep manifests and the lockfile consistent. Do not hard-code a stale workflow input or publish multiple different user-test builds with the same version. Record commit, build run, artifact names, and hashes for physical tests.

Creating this spec does not start a new chat, implementation, deployment, merge, or CI run. The next session should execute the scope requested by the user and preserve unrelated changes and local attachments.

## Standards and existing decisions

- [RFC 8445 ICE](https://www.rfc-editor.org/rfc/rfc8445.html): candidate exchange, connectivity checks, and path nomination.
- [RFC 8489 STUN](https://www.rfc-editor.org/rfc/rfc8489.html): peer-to-peer connectivity-check primitives. Public STUN observation services remain excluded.
- [RFC 9000 QUIC](https://www.rfc-editor.org/rfc/rfc9000.html): transport, path validation, and migration behavior.
- [RFC 5128 NAT traversal](https://www.rfc-editor.org/rfc/rfc5128.html): mapping and filtering behavior and traversal limitations.
- [Existing roadmap](DIRECT_CONNECTIVITY_ROADMAP.md), [underlay ADR](adr/0018-authenticated-direct-underlay.md), [Phase 2 evidence](DIRECT_CONNECTIVITY_PHASE2_EVIDENCE.md), and [Phase 3 evidence](DIRECT_CONNECTIVITY_PHASE3_EVIDENCE.md).

Use the standards to inform implementation; this spec does not claim that existing Mesh Chat implements ICE. Any selected implementation must support disabling external discovery and relay mechanisms completely. Check current maintained dependencies and relevant errata before choosing an implementation.

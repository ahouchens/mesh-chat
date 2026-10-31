# Acceptance reconciliation: specification invariants and scenarios

This page reconciles [the specification](Mesh_Chat_Connection_Runtime_Spec.md)
with executed evidence. It is deliberately conservative: a requirement is only
marked at the level the evidence actually reaches, and physical-only acceptance
is marked unavailable rather than inferred from emulation or CI.

## Status vocabulary

| Status | Meaning |
| --- | --- |
| `local` | Deterministic or in-process tests exercise the production policy, facade or adapter boundary on the recorded source. |
| `component` | A native, emulator or packaged component run in CI proves the behavior for the recorded source and artifacts. |
| `workflow` | The required qualification matrix and final gate executed for the exact source. |
| `partial` | Evidence covers a named part of the requirement; the remainder is listed. |
| `open` | No executing evidence. |
| `unavailable` | Requires physical devices or an isolated physical network, neither of which exists in this environment. |

Component evidence never implies a supported release, and emulator evidence is
never described as physical-device qualification.

## Invariants

| ID | Status | Evidence and remaining gap |
| --- | --- | --- |
| INV01 | `local` | Supervisor fairness, single-owner and single-negotiation tests; the shared composition constructs exactly one owner at trusted startup. |
| INV02 | `local` | Stale epoch, generation, operation and timer regressions in the policy suite; runtime reconciliation tests pin bounded tombstones. |
| INV03 | `component` | Late-allocation disposal by exact handle is tested locally; Android JNI instrumentation and packaged Windows checks exercise native disposal. |
| INV04 | `local` | Stop, lock, revocation, quarantine and incompatible-authority regressions in the reducer, runtime and intent transactions. |
| INV05 | `local` | Reconnect cannot create trust, membership or disclosure; separate consent and workspace-authority suites. |
| INV06 | `component` | Manual-carrier adoption requires signed SDP, capabilities, device binding and privacy authority; native adoption scenarios exercise it on Android. |
| INV07 | `local` | Readiness requires an authorized bridge plus current route/path evidence; path loss invalidates readiness without retiring a healthy carrier. |
| INV08 | `component` | Bridge repair and mailbox-outage separation are covered locally; packaged Windows crash recovery reuses the surviving carrier. |
| INV09 | `component` | Stale cleanup and replacement retirement fences; packaged scenarios prove exact carrier reuse after restart. |
| INV10 | `component` | Durable outbox and logical IDs are covered locally; packaged crash/restart delivers without a duplicate visible message. |
| INV11 | `component` | Only an authenticated application receipt establishes delivery; packaged peers assert receipts. |
| INV12 | `partial` | Policy, effect-runner, JNI ingress, startup-packet and Windows endpoint bounds are tested, including concurrent-client and idle-session limits. Other legacy queues have not been re-qualified as part of this work. |
| INV13 | `local` | Every phase has a deadline, cancellation path and classified exit in the reducer corpus; cleanup reservations survive late completion. |
| INV14 | `local` | Fair scheduling and capacity tests, including the property corpus. |
| INV15 | `component` | Committed Stop fences immediately; packaged lifecycle proves the reopened profile keeps its identity and committed preference. |
| INV16 | `partial` | The shared composition has one owner across foreground/background. Full platform lifecycle parity for every mode remains open. |
| INV17 | `partial` | Shared-policy UI detach cannot retire a transferred carrier; media-call teardown parity across all modes is not re-qualified. |
| INV18 | `local` | Deterministic traces, replay and the seeded simulator corpus. |
| INV19 | `local` | Failed persistence keeps the in-memory denial and never reports durable success; intent-batch and authority-write regressions. |
| INV20 | `partial` | The gate rejects failed, canceled, skipped or missing required evidence; publication now requires that manifest and re-hashes staged assets against it. No tag has executed the release path yet. |
| INV21 | `partial` | The facade enforces caller, profile, permission and private-event boundaries in tests, and a Windows named-pipe endpoint now adds OS access control plus executable allowlisting. No Android endpoint or packaged consumer exercises the boundary yet. |
| INV22 | `partial` | The client carries no peer policy and cannot start a runtime. Exclusive data-directory ownership is checked by the host, which is not implemented. |
| INV23 | `local` | Durable enqueue receipts, conflicting payload rejection and stable logical IDs across restart; acknowledgments never change peer delivery state. |
| INV24 | `local` | Explicit `resync_required` for gaps, expiry and authority change; the client consumer clears its position and resnapshots. Long-term retention is not promised. |
| INV25 | `partial` | A declared compatibility file fixes the public API, IPC, peer-wire and client namespaces; both clients refuse an unsupported major before side effects, and the aggregator checks the contract. No published package matrix or upgrade fixtures exist. |
| INV26 | `open` | No packaged SDK, runtime distribution or independent consumer exists. |

## Required scenarios

| ID | Status | Evidence and remaining gap |
| --- | --- | --- |
| SC01 | `component` | Packaged Windows peers exchange messages and authenticated receipts in both roles; no physical cross-device run. |
| SC02 | `local` | Simultaneous start, duplicate signaling and role collisions are covered by the reducer/supervisor corpus. |
| SC03 | `local` | Old answers, late native callbacks and expired timers cannot advance state; exact orphan cleanup is asserted. |
| SC04 | `partial` | Partitions are simulated deterministically; the 30-second real-clock recovery budget is not measured. |
| SC05 | `partial` | Loss and delayed control are simulated; no real impairment run carries the policy traffic. |
| SC06 | `local` | Mailbox failure keeps a healthy carrier and reports degraded future reconnect separately. |
| SC07 | `local` | Carrier failure with a healthy mailbox schedules a permitted new negotiation. |
| SC08 | `component` | Packaged Windows kills the service and reclaims the same carrier binding without new negotiation. |
| SC09 | `component` | Process and adapter restart produce a fresh epoch; packaged tests reopen the profile and preserve preferences. |
| SC10 | `component` | Stop, lock, revocation and quarantine during native creation are fenced locally; Android instrumentation covers cancelled gathering. |
| SC11 | `partial` | Execution-state changes are policy inputs with one owner; full Android background/foreground parity is open. |
| SC12 | `partial` | Direct Fabric suites exercise real controlled paths and NAT filters, but selected-path and negative-control evidence is not bound to policy traffic. |
| SC13 | `local` | Multiple contacts, scopes and devices are covered for fairness and isolation; no cross-device packaged run. |
| SC14 | `local` | Delayed attachment and missing path are bounded with truthful readiness. |
| SC15 | `component` | Lost receipts, duplicate packets and restart preserve one visible message per logical ID in packaged runs. |
| SC16 | `partial` | Policy and JNI queues enforce budgets and quarantine; a packaged saturation run is absent. |
| SC17 | `partial` | Legacy media-call and pairing-closure coverage exists; it has not been re-qualified against the shared policy. |
| SC18 | `partial` | Signed fixtures and existing peers still interoperate; no explicit wire-version matrix. |
| SC19 | `local` | Persistence failure during intent or adoption bookkeeping is tested for safe in-memory behavior. |
| SC20 | `workflow` | The final gate fails on missing, skipped, canceled or stale required evidence for the exact source. |
| SC21 | `unavailable` | Independent Windows and Android applications installing packages and exchanging messages cannot be built or run here. |
| SC22 | `component` | Wrong caller, profile/scope and private-control attempts are rejected before effects in facade tests. |
| SC23 | `local` | Lost reply, timeout and duplicate request after restart resolve by idempotency key; conflicting payloads fail. |
| SC24 | `local` | Bounded replay, explicit gaps, cursor expiry and consumer deduplication are covered by facade and client tests. |
| SC25 | `open` | No supported SDK/API/package version pairs exist to validate or reject. |
| SC26 | `partial` | Detach does not stop the runtime, and the Windows endpoint serves a bounded number of concurrent local clients. An owner-initiated runtime stop and packaged multi-client evidence are not implemented. |

## Completion boundaries

| Boundary | Status | Note |
| --- | --- | --- |
| Shared policy complete | `partial` | One owner drives the experimental Android and desktop compositions, but manual-pairing parity, Windows-and-Android interoperability and legacy-loop removal are open. |
| Headless messaging complete | `partial` | Android native transport and packaged Windows WebView2 scenarios qualify components; the production native Windows DataChannel adapter does not exist. |
| External integration complete (M5) | `open` | No authenticated host endpoint, supported SDK/CLI, packaged consumer or compatibility matrix. |
| Release gating complete | `partial` | The gate enforces the matrix; publication does not yet require exact-artifact aggregation. |

## Physical checklist

Unavailable in this environment: Wi-Fi/cellular switching, screen-off/Doze,
real process death by OS policy, Stop/lock on physical devices and end-to-end
receipts on physical hardware. No emulator, packaged or CI result on this branch
is presented as that evidence.

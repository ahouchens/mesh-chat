# Mesh Core R0 baseline reference

Status: **user-identified working release; exact installed bytes still unconfirmed** as of 2026-11-13. The user identifies **0.9.66 from `main`** as the last known working build on their physical Windows and Android devices. This establishes a useful behavioral reference despite the architectural changes. The release tag and published artifact metadata are pinned below; neither the current `main` tip nor a refactor build substitutes for that historical release. The user's statement does not establish that every acceptance scenario was exercised.

## User-identified release pins

The remote annotated tag `v0.9.66` has tag object
`964848e68ed54ceffcbbb8b4a2355f46995e2efa` and resolves to commit
`7c40f7b23eab3e9d83ff7ca1075c90c4d84ce516`, tree
`96daefa74c38a5cfd7863e37e3effcb7a06dc6cd`. This is the October 29, 2026
main-branch merge of PR #34. The published
[Mesh Chat 0.9.66 release](https://github.com/ahouchens/mesh-chat/releases/tag/v0.9.66)
has release ID `428222939`, targets `main`, and was published at
`2026-10-29T18:04:32Z`. Its GitHub asset metadata supplies these pins:

| Asset | Asset ID | Bytes | SHA-256 from publisher metadata |
| --- | --- | --- | --- |
| `Mesh-Chat_0.9.66_x64-setup.exe` | 689437206 | 28012178 | `a20b381a8c7199c40aeba0487634c1302043c3e07d8b66c7838be8abfc050e23` |
| `Mesh-Chat_0.9.66_x64_en-US.msi` | 689437207 | 30011392 | `dadbffdedb39c1714abc426d9a2ded1eb815d84be0dfb11e7c7c88c332f2f34e` |
| `mesh-chat-0.9.66-android-arm64-release.apk` | 689437208 | 46971989 | `ea5d18576e36c6562a25902620b131f21096d27ac90031c64fbcdff45958a5f6` |
| `SHA256SUMS.txt` | 689437204 | 303 | `6306c25b130e10287b857829a29a6ea9b4dbfa27acaa9c1a25550e95345410a4` |

Metadata is retained in `.test-tmp/baseline-v0.9.66-release.json`. The binaries
were not downloaded or executed during this lookup; hashes are publisher
metadata, not hashes measured from the user's installed files. Release/source
identity is now a concrete comparison candidate. Exact on-device bytes, the
Windows installer variant, build-manifest provenance and the physically tested
flow list remain unconfirmed. This does not block continued automated work.
The remote `main` tip observed during this lookup is
`13fda6f20c4eafdaf30611c547b76973814029b1`, a later preview-card change from
October 30. The user's version/branch identification alone does not distinguish
the published release from a later local build off `main`; do not assert that
the physical devices ran the tag's exact bytes.

## Provenance and confidence

| Evidence | What it establishes | Limit |
| --- | --- | --- |
| User reply on November 13, 2026: last known working build was 0.9.66 off `main` | User-attested working physical Windows/Android release baseline. | No claim that all scenarios passed or that published asset bytes were measured on the devices. Architectural changes affect test applicability, not the value of the observed product behavior. |
| `TESTING.md`, “Recorded 0.2.7 desktop-reply concurrency verification” (lines 4748–4763) | A physical 0.2.6 Windows/Android run delivered the phone's first direct message to the desktop. Process inspection in a later attempted retest identified the running Windows `mesh-chat.exe` as version 0.2.6, SHA-256 `42A320E157B2C2743CA87127E00E8BB1E55E6C2DE8C7F80D9434307933908DCA`, and its sidecar as SHA-256 `9901F7844739DABA0D0FF37B298A108C91B0305B504DE99C43AC9025D4EE4107`. The release table also records the 0.2.6 Android debug APK SHA-256 `C67159232A3F45628F039E97E67914A47487C36BFE6B0ABB0C18EF4DD0441D44`. | The desktop reply failed in the physical run. The record does not establish that the APK's bytes were inspected on the phone, nor identify the source commit used to build the binaries. This is a partially successful, **failed** candidate, not a working baseline. Confidence: high for the recorded behavior and Windows process hashes; low for APK-on-device byte identity. |
| `TESTING.md`, 0.2.4–0.2.6 physical-run sections (lines 4550–4682) | The preceding physical runs reached approval on the prior release, connected peers on 0.2.4 but did not show the first chat, and completed invitation/acceptance on 0.2.5 but did not deliver the phone's chat. | None proves a complete bidirectional conversation. Confidence: high for the documented outcomes. |
| `TESTING.md`, 0.2.7 package section (lines 4835–4858) | 0.2.7 packages were built and inspected. | The exact 0.2.7 pair was explicitly awaiting a physical reply retest. Confidence: high. |
| `git log main`, `git blame TESTING.md`, and local tags | The current local `main` tip is `7c40f7b23eab3e9d83ff7ca1075c90c4d84ce516` (0.9.66). The 0.2.6 physical-run account entered this repository in the 2026-10-06 import commit `428986596da6f146287a453ab3908863896e1e0b`. | The import commit is the **documentation provenance**, not the 0.2.6 build source. The local history and tags do not bind a physically successful later build to a historical `main` SHA. Confidence: high for the Git provenance; unresolved for the requested build identity. |

The older restart handoff and R0 roadmap predate the user's release identification.
Their unidentified-version gap is superseded by the reply and release lookup
above. Exact installed-artifact and scenario provenance remain separate gaps.

## Comparison scope after the reference is found

Compare the historical product and integrated Mesh Core on the user-visible flows that share the changed boundary: desktop Tauri/WebView2 and Android UI profile selection/unlock, invitation and approval, direct and workspace messages and authenticated receipts, reconnect and restart, and conversation state. Include audio/video call start, end, failure, dialog closure, navigation, and message delivery while a call is active, because the UI, media signaling, permissions, and packaging remain part of the product. The headless native Windows messaging peer exercises transport and core behavior only; its success cannot certify WebView2 UI or media coexistence. Physical device qualification remains a separate gate from local/CI and emulator results.

## Evidence searched and next step

The earlier search of `TESTING.md`, release and refactor documents, local history,
tags/blame and worker reports found only partial/failed physical records. The
user has now supplied the missing working release identity. Use the pinned
0.9.66 release for applicable behavioral comparisons, and verify downloaded
bytes and release build provenance before any automated installed comparison.
Keep device-specific observations and automated results labeled separately.

## R0 policy and timing audit at integration commit `82c3364`

This is a read-only evidence map against `docs/Mesh_Chat_Connection_Runtime_Spec.md` §§8, 9.1, 9.4 and 9.6. The policy/test files named below match `82c3364`; no production source or acceptance status was changed in this audit.

| Requirement | Existing evidence | Actionable gap or disposition |
| --- | --- | --- |
| INV01–04, INV06–07, INV09, INV13, INV18; SC03/SC10 | `test_reducer.py`, `test_supervisor.py`, `test_phase_cancellation.py` and `test_properties.py` exercise production transitions, late allocations, authority/epoch fences, readiness and replay. The phase matrix executes 14 phases × 7 interruptions × 3 late completions = 294 cases, including replacement protection. | No missing *pure-policy* phase-interruption case found. The acceptance ledger correctly keeps packaged phase parity open for SC10. |
| INV05, INV08, INV10–11, INV15, INV19; SC19 | Focused consent, bridge recovery, message/receipt and `test_intent_transactions.py` regressions cover their respective domain or storage boundaries; acceptance assigns local/component evidence. | These are not all properties of the pure reducer. The §9.1 simulator does not independently check durable intent or logical message identity, so its ownership oracle must not be cited alone for those claims. Existing focused tests remain the direct evidence. |
| INV12, INV16–17; SC16 | Acceptance already labels these `partial`: legacy queue inventory, full platform foreground/background behavior, real UI/media coexistence and packaged saturation remain open. | Platform/packaged qualification belongs with the integration and D gates; adding another pure reducer assertion would not close these rows. |
| INV14; SC13 | `test_supervisor.py::test_concurrency_bound_and_fair_admission` proves the third of three actors starts after one of two worker slots frees. The Hypothesis simulator has only one actor. | No sustained mixed contact/device/scope trace was found that demonstrates bounded fair service and isolation under repeated completions, stops and re-admission. Keep SC13 `local` scoped to the existing narrow evidence until that trace executes. |
| SC02 | `test_reducer.py::test_initial_negotiation_obeys_deterministic_roles` checks both role choices separately; duplicate terminal completion and single-key ownership have focused assertions. | No executing two-peer simultaneous-start/duplicate-signaling interleaving was found. The current `local` description in `docs/Mesh_Chat_Connection_Runtime_Acceptance.md` overstates that evidence. A policy test can cover simultaneous actor dispatch and duplicate effect completion; actual duplicate signed signaling needs adapter evidence. |
| SC18 | Acceptance already says `partial`; signed fixtures exist, but no explicit historical-peer wire-version matrix is named. | Preserve `partial` until an exact historical artifact/protocol fixture and compatible/incompatible pair results are recorded. This depends on the unresolved baseline identity above. |
| §9.1 corpus and classification | `test_properties.py` sets 1,000 examples × 100 steps. `service/tools/connection_harness/simulation.py` saves normalized action traces with schema, policy and implementation digest, and `test_replay.py` checks replay/refusal. `test_phase_cancellation.py` enumerates every current `Phase`. | The generated alphabet is one actor's advance, intent, network and completion actions; it does not generate authority/adapter changes, bridge loss, rate limiting or storage failure. There is no cross-product classification assertion for all six event types across stopped, negotiating, ready, and replacing states. Hypothesis shrinking does not itself retain a minimized failing trace artifact. Preserve these as corpus limits, not a claim that INV01–19 lack focused evidence. |
| M0 and §9.6 timing | The roadmap records baseline *policy values* and single-run historical CI job durations; it still lists platform timing baselines as open. §9.6 calls its 20-second bridge, 240-second recovery, 30-second receipt and 100-iteration budgets proposed targets. | No CI record here measures those targets on the exact headless Windows/Android pair under the declared 150 ms RTT profile. Virtual-time tests do not close this gap. D owns real-clock platform capture; keep M0 timing open. |

Two labels need correction in the owning records after review: the definition-of-done row in `docs/Mesh_Chat_Connection_Qualification_Ledger.md` says “M2: INV01–INV19” but lists “INV12/16/17/20” as partial; INV20 is outside that range. The `test_phase_cancellation.py` module docstring names INV05, although its test asserts stale-operation fencing and disposal, not trust/membership/privacy non-escalation.

**Smallest proposed C-owned policy batch (review before editing):** add one focused multi-actor trace in `service/tests/connection/test_supervisor.py` that starts two opposite-role actors together, duplicates an admitted completion, then repeatedly frees one of two worker slots while mixed scope/device actors wait. Assert one current operation per key, no duplicate allocation/adoption, no cross-key retirement, and bounded admission of each eligible actor. This would tighten SC02/SC13/INV01/INV14 without claiming actual signed-signaling or packaged behavior. If accepted, add a table-driven `test_reducer.py` case only for any state/event classification hole exposed by that trace; otherwise retain the existing 294-case phase matrix. The test files are proposed C ownership; no production edits are proposed.

### Approved focused trace

The integration lead approved a narrower test-only implementation in new `service/tests/connection/test_supervisor_competing_actors.py`. It registers six mixed contact/device/scope keys at one supervisor tick with two worker slots and opposite initial role choices. The trace duplicates an old completion, releases slots repeatedly, and independently bounds each actor's first and second admission by four and ten releases respectively. It checks one current operation per key and exact resource identity without synthesizing signed signaling. This strengthens local SC13/INV01/INV14 and the scheduler portion of SC02. Two-peer simultaneous **signed-signaling** behavior remains open. The misleading module docstring in `test_phase_cancellation.py` was corrected to INV02/03/04/09; the 294-case body is unchanged. Acceptance and ledger status edits remain integration-lead owned.

### Production reducer event classification

The six `Event` families in `service/src/mesh_chat/connection/model.py` are `Tick`, `ContextChanged`, `Result`, `Failed`, `Adopted` and `Observed`. The table maps meaningful state/event combinations to executing evidence. “Existing” means the earlier `test_reducer.py` or 294-case `test_phase_cancellation.py` corpus; “new” means `test_reducer_event_classification.py`. The table is an evidence map, not a claim that all six families are valid transitions in every state.

| State | Tick | ContextChanged | Result | Failed | Adopted | Observed |
| --- | --- | --- | --- | --- | --- | --- |
| Stopped | New: cannot restart after old observation | Existing Stop/Start and denial | Existing late result after cancellation | Existing late failure after cancellation | Existing late adoption after cancellation | New: old ready observation cannot resurrect |
| Negotiating | Existing deadline and polling | New: lower authority revision cannot revoke current work; existing interruption matrix | Existing phase progression and stale-result fencing | New: rate-limit cooldown survives Stop/Start; existing interruption matrix | Existing exact DISCOVER adoption and invalid/stale fences | Not applicable until a carrier exists; repair with current carrier is covered below |
| Ready carrier | Existing scheduled health inspection | Existing revocation and mailbox-loss tests | New: stale result cannot retire current resource | New: stale rate-limit failure cannot alter readiness/cooldown | New: stale adoption cannot replace current resource | New: loss triggers exact ATTACH; a later READY observation cannot bypass repair |
| Replacing after carrier loss | New: due retry creates a distinct resource | Existing cancellation/revision matrix covers current operations; no replacement-specific context trace added | Existing old-result/replacement fence in phase matrix | Existing old-failure/replacement fence in phase matrix | Existing old-adoption/replacement fence in phase matrix | New: old carrier observation cannot make the replacement ready |

| Outside the reducer Event model | Classification | Applicable evidence |
| --- | --- | --- |
| Adapter epoch change | Remaining adapter/supervisor boundary; no `ContextChanged` field or other reducer event | Exact adapter resource provenance and reconciliation tests |
| Storage failure | Remaining domain/persistence boundary; no reducer event | `test_intent_transactions.py` for INV19/SC19 |
| Duplicate signed signaling | Adapter/protocol boundary; no signed document event in the reducer | New `test_reconnect_signed_collision.py` component interleaving for SC02 |

The smallest C-owned SC02 protocol trace now lives in `service/tests/connection/test_reconnect_signed_collision.py`. It starts both opposite-role reconnect actors at the same reducer tick and routes actual signed `reconnect_request`, `reconnect_offer`, and `reconnect_answer` documents through `ReconnectExecutor` ports. A correctly signed offer for another attempt remains pending before native acceptance; the matching offer then completes one native allocation and one ready carrier per actor. Replaying the already-completed signed request in a fresh local negotiation stays pending without a second offer. The mailbox and native peer are doubles, so this is component interleaving evidence; actual HTTP, WebRTC transport, packaged and physical SC02 behavior remain open. Focused verification: 44 passed across this trace, the adjacent adapter tests and reconnect protocol tests (0.93 s).

This batch strengthens INV02/03/04/07/09 and SC03/10's *policy* edges without changing acceptance labels. `Failed(RATE_LIMITED)` is a modeled event; the new trace asserts its cooldown even after Stop and Start. Packaged lifecycle, media coexistence and real-clock §9.6 budgets remain open at their respective integration/D boundaries.

Focused verification on this branch: 356 passed across the new event-classification file, reducer, phase cancellation, Hypothesis properties and trace replay (23.32 s); configured strict mypy passed for the two policy source files. This is local policy evidence, not Android/Windows or full native qualification.

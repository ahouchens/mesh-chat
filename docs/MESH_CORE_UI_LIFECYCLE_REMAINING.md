# Mesh Core UI lifecycle and media coexistence: remaining work

Updated November 14, 2026 against integrated source
`fa1addb78e05ad015b6cbfcf95d09a0def6f99a4` (tree
`278e3e560e0550fb74ba3ba4e3631f824b8161d7`). The `82c3364` call-site
map, proposed batch and early candidate below record their original inspection
point; the completed checkpoints and current disposition at the end of this
document supersede those proposals. This update changes documentation only.

Prepared November 13, 2026 for lead review. This is an R3/R5 gap inventory, not
qualification or an implementation assignment. Source inspection used exact
`82c336423d6dae4d9d19c1923824cf7db0bed0b0` (tree
`6eade6145309d100f6db82869a31638eb5da2fd3`) in the lead checkout. This
document alone is added in B's owned checkout, whose starting HEAD was
`503b18ee0ede2019a65d03cbce0b7f394ffea3b4`. No lifecycle or UI production
files were changed. The lead reported 6,640 local cases passed and CI run
`43529724766` active at assignment time; neither is treated here as R3/R5
packaged acceptance. Refresh those results before integration.

The governing boundaries are [specification §3.3, §4, §6 and
§9.7](Mesh_Chat_Connection_Runtime_Spec.md), [acceptance INV17/21/22 and
SC17/26](Mesh_Chat_Connection_Runtime_Acceptance.md), and the
[Windows/media handoff](NATIVE_WINDOWS_WEBRTC_HANDOFF.md). R1 native cold restart
and required aggregate qualification remain open. R2 shared-owner promotion and
legacy messaging retirement follow accepted R1 evidence and relevant failure
disposition. A passing renderer suite does not close either gate.

## Current call-site map

| Flow and roadmap item | Actual UI to host path at `82c3364` | Existing test/evidence level | Missing packaged case |
| --- | --- | --- | --- |
| First profile creation, catalog, select, unlock, lock; R3 | `src/App.tsx` holds the keyed first-run create identity, boots catalog, requests native authentication, submits Core lifecycle actions, and retires old renderer work through `src/profile-lifetime.ts`. `src/core-profiles.ts` validates catalog/capabilities and sends `profile.catalog/select/unlock/lock` through `src/api.ts`. `src-tauri/src/lib.rs` routes desktop Core requests to the protected pipe and mobile requests to the plugin; unlock credential is a private host action. Android's `MeshRuntimePlugin.kt`, `MeshCoreRuntime.kt`, `NativeProfileProvider.kt`, and Python `native_profile_lifecycle.py`/`mobile_profile_host.py` implement host/key/lifecycle boundaries. | `src/App.profiles.test.tsx`, `src/profile-lifetime.test.ts`, Android `NativeProfileProviderTest.kt` and profile result instrumentation, and Python lifecycle/Core tests cover catalog, late result, keyed retry, host generation and cancellation at component level. Acceptance records successful native device credential confirmation and full installed platform lifecycle as open. | On installed Windows and Android candidates: cold locked start, real OS authentication, create/select/unlock/lock, restart with the same identity/authority, canceled and late credential results, foreground/background and exact owned-resource/key release. Do not infer OS authentication from mocked renderer or provider unit tests. |
| Contact and workspace pairing/approval; R3/R5 | `src/WebRTCOnboarding.tsx` creates public Core invitations and decisions but still uses `serviceCommand` for native offer/answer verification/binding; its browser branch registers `src/webrtc-session.ts` channels. `src/App.tsx` opens/closes the dialog, approves peers through Core, and retains/resumes pairing presentation state. Core routes live in `src/api.ts`, `service/src/mesh_chat/core_api/service_pairing.py`, `service_pairing_intents.py`, the supervisor pairing adapter, and private native host commands. | `src/WebRTCOnboarding.test.tsx` covers native handoff, dialog dismissal, late contact invitation, canceled/failed gathering, and browser control behavior with substitutes. Python pairing/retirement tests and packaged native path tests cover narrower private behavior. Full accepted Windows–Android restart/receipt evidence is absent. | Packaged fresh contact and workspace pairing/approval on both roles, current consent and selected carrier, dialog closure before/after adoption, late answer/cancel, restart and authenticated message receipt. Assert closure retires only onboarding resources and does not close adopted messaging or media calls. Keep private transport control out of the public SDK. |
| Manual personal/workspace participant paths; R3 | `src/App.tsx` still calls `prepare_manual_participant_host`, `configure_participant_firewall`, `connect_using_reply`, `stop_participant_host` and workspace connectivity commands through `serviceCommand`. Public invitation/relationship mutations use `src/api.ts` and Core. Host ownership is in `service/src/mesh_chat/participant_service.py`, direct bootstrap/recovery modules and Core workspace/peer adapters. Several dialog cleanup paths deliberately use the exact host ID and best-effort stop. | App/direct setup tests and `service/tests/connection/test_participant_keyed_preparation.py`, direct recovery and boundary tests cover local preparation and keyed service behavior. The acceptance register still classifies complete application/platform lifecycle and transfer parity as partial. | A real packaged manual invite/reply for both personal and workspace modes: authorized carrier transfer, recipient readiness, dialog dismiss, owner Stop/lock/revocation, late setup response, foreground/background return and exact cleanup. Preserve the original setup error separately from a later cleanup failure. |
| Supported messaging facade and pending UI actions; R3/R5/R6 | `src/api.ts` has Core wrappers for profiles, invitations, workspace/admin, direct/group send, drafts, reads, reactions and call control. `src/App.tsx` fences async results with profile lifetime and keeps keyed composer identities. `src/reconnect-runtime.ts` and `src/DirectRecovery.tsx` still coordinate renderer reconnect/status polling and private service commands; `src/webrtc-session.ts` retains browser messaging sessions. Their actual call sites must be classified before retiring any wrapper or loop. | `src/App.core.test.tsx`, group composer, lifetime, recovery and Core boundary tests prove scoped serialization, lost-reply keys, lock fencing and some transfer cases. The acceptance ledger says the *supported* Mesh Chat messaging UI through the final public facade is not yet qualified; the later reconciliation calls transitional renderer policy/bridge loops partial. | Installed UI uses the same supported facade and authorized host as an independent consumer through profile switch, lock, reconnect, pending durable send/receipt, dialog close and window reattach. Show one policy owner and no duplicate message or lost queued work. Do not delete Direct/QUIC recovery or browser call support while classifying messaging-only paths. |
| Audio/video call start, answer, failure, hangup and recovery; R5/INV17/SC17 | `src/CallDialog.tsx` owns browser `getUserMedia` and `RTCPeerConnection`; `src/call-core.ts`, `src/call-operation.ts` and `src/api.ts` send keyed `call.control` and query media through Core. `src/call-audio.ts` serializes Android audio focus. `src-tauri/src/lib.rs` exposes media permission/audio hooks; Android `CallService.kt` supports an active WebView call in background, while `MeshRuntimePlugin.kt` mediates permissions/focus. `service/src/mesh_chat/call_manager.py` owns signed call state. | `src/CallDialog.test.tsx` exercises substituted capture, answered cycles, cleanup, lost replies, profile switches and late media results; service/Core call tests cover scoped control. Acceptance INV17/SC17 explicitly remain partial. | Actual packaged WebView2 and Android media capture/track teardown beside adopted native messaging and authenticated receipts across repeated start/answer/end/fail/reconnect, native messaging restart/replacement, profile lock, pairing closure and window navigation. Verify each operation retires only its own media/carrier resources. Emulator media results still do not establish physical microphone/camera behavior. |
| UI/window attachment and runtime ownership; R3/R5/R7/SC26 | `src/App.tsx` mounts the messenger under the profile generation and detaches renderer effects on lock; Core host is reached by `src-tauri/src/lib.rs` or Android plugin/Binder. The spec requires window/client detach to leave durable runtime work alive until explicit authorized owner stop. | Acceptance SC26 reports installed same-application Windows sessions and Android detach/rebind/cold locked process components. Separate consumer-process/caller isolation, helper retirement and full UI plus SDK attachment remain open. | Close/reopen UI while another authorized client is attached and a durable message is pending; reject competing owner; preserve runtime epoch/data authority and receipt recovery; explicit owner stop releases exact resources. Test both platforms with packaged hosts, not only simulated React unmount. |

## Focused boundary findings

1. The coexistence surface is real: `CallDialog.tsx` still creates browser media
   peer connections; the native messaging adapter must not retire their tracks.
   `CallService.kt` explicitly keeps an Android WebView-owned call alive in the
   background. Retaining WebView2 in the desktop package is required.
2. Pairing and reconnect are still mixed at the renderer boundary.
   `WebRTCOnboarding.tsx` uses Core for invitation/consent and private native
   commands for transport; `reconnect-runtime.ts` issues service reconnect
   commands and owns browser sessions. This inventory does not prove every such
   call is obsolete. Trace caller, resource owner, purpose and replacement before
   any R2/R5 deletion. Keep media, onboarding and shared signaling callers.
3. The renderer has meaningful generation/idempotency fencing, but it cannot be
   treated as the connection policy owner. R3/R5 closure needs an installed UI
   flow using supported Core projections and showing the supervisor retains
   authority after dialog/window closure. Public-consumer SC21 and SC26 remain
   separate acceptance boundaries.
4. The current qualification ledger and acceptance table are historical and
   report component-level success for these paths. No focused restart diagnostic,
   local count, browser substitute or private native harness case is evidence
   that packaged media and supported UI facade obligations passed at `82c3364`.

## Proposed coherent implementation batch after lead assigns file ownership

**R3/R5 supported UI lifecycle and coexistence batch.** First freeze the
specific public intent/snapshot and private host control contract for profile,
pairing, participant transfer and calls, using a call-site ownership table.
Then bind the remaining supported UI pending actions to Core-owned identities
and truthful results; remove only verified superseded renderer messaging policy
after R1/R2 promotion and rollback coverage. Preserve `CallDialog` browser
media, WebView2 packaging, audio focus, shared signaling and Direct/QUIC paths.
Add boundary regressions at the actual owner transfer and pending-response sites.
Finally run packaged Windows and Android UI scenarios alongside native messaging
receipts, including call teardown, pairing closure and window detach/reattach.

Suggested file split for lead approval: B owns only `src/` UI and its tests once
assigned; C owns Python supervisor/host lifecycle and Rust/Android runtime host
files under its current boundary; A owns public API/SDK contracts and independent
consumer fixtures; D owns exact-source packaged/native qualification evidence;
the lead owns integration and INV/SC reconciliation. No production file is
transferred by this document. R1 repair and full native/aggregate acceptance
remain the next prerequisite for R2 retirement. The next R3/R5 milestone is a
reviewed call-site ownership table and a packaged coexistence scenario whose
results are bound to one integrated source and artifact set.

## Narrow call-site ownership review and independent pending action

This follow-up inspected the same `82c3364` tree. Its four modules have different
jobs; a common `WebRTC` or `recovery` name is not a deletion criterion.

| Call site | Active selector and policy owner | Resource and retained use | Exact replacement or deletion gate |
| --- | --- | --- | --- |
| `src/reconnect-runtime.ts` with `src/reconnect-coordinator.ts` | `MeshChatService` constructs `_connection_runtime` only for `shared-native` (`service.py`); `reconnect_service.py` then emits `policy_owner: "service"` and a connection projection. The coordinator displays that projection and excludes that profile from renderer negotiation. Profiles without the marker still run the renderer retry/mailbox/offer/answer path. `App.tsx` mounts the coordinator and network/visibility listeners for both. | Service supervisor owns marked profile policy/carrier. The renderer still tracks legacy browser sessions and some native session health/close handles; `connection.start/stop` are Core-first with a private-command fallback. UI Disconnect, Retry and unmount paths need exact owner review because they still invoke close helpers. | R1 native cross-platform acceptance, R2 shared-owner promotion and a per-call-site proof that service-owned profiles never receive renderer retry or foreign-carrier close. Then retire only the unmarked-profile policy branch and fallback commands after installed UI parity/rollback coverage. Preserve presentation and explicit user intent. |
| `src/webrtc-session.ts` | Registry is used by the unmarked reconnect path and the browser branch of `WebRTCOnboarding.tsx`; keys and `controlPurpose` distinguish reconnect from onboarding. `getWebRTCSessionWithControl` excludes reconnect control from onboarding actions. | It owns only its registered messaging DataChannel, bridge and `RTCPeerConnection`; exact-key/bridge-ID removal fences a replacement. It does not own `CallDialog.tsx` media tracks. Browser onboarding control, contact binding and shared signaling still use it after dialog handoff. | Delete messaging registry paths only after all browser onboarding and legacy reconnect callers are replaced and tested on installed UI. Preserve media `RTCPeerConnection`, onboarding delivery and shared signaling; prove closing one messaging session neither retires an adopted replacement nor stops a call. |
| `src/DirectRecovery.tsx` | Mounted in active workspace Connections settings. Its two-second `direct_recovery_status` poll is a display query; pause/resume, recovery transfer and one-hop helper consent/relay are explicit user actions, not the reconnect coordinator's peer retry loop. | Service Direct/QUIC relationship and signed recovery update ownership remains separate. Core already handles import/export; private commands still serve status, helper and pause/resume actions. | No blanket R2 deletion. Replace a command only after an equivalent authorized Core/host route and Direct/QUIC packaged parity exist, including workspace scope, signed update freshness and existing membership. Keep status/consent/manual recovery semantics. |
| `src/WebRTCOnboarding.tsx` | `usesServiceWebRTCTransport` chooses native on Android or the host service-transport hint; otherwise Windows browser onboarding remains. Both branches use private offer/answer verification; the native branch also binds through a private host command, while Core handles invitation/consent and call signaling. | The dialog owns a pending peer until exact handoff; `handedOffRef` prevents unmount cleanup of an adopted native or browser carrier. Browser `mesh-onboarding` control can deliver invitations/capabilities after closure. Media calls use separate `CallDialog` resources. | R1/R2 pairing/adoption proof plus installed fresh pairing, approval, dialog-close, delayed invitation and receipt cases for each selected branch. Remove only a branch with no remaining supported host or shared-signaling caller; never treat dialog dismissal as carrier cancellation. |

**Independent R3/R5 pending-action candidate:** received workspace invitation
prompt dismissal. In `App.tsx`, `dismissContactInvite` passes `undefined` for the
idempotency key to `fetchWorkspaceConnection`; `api.ts` therefore creates a new
key on every click. A lost successful reply leaves the prompt visible with a
retryable error. Core already supports keyed `workspace.connection` action
`prompt_dismiss`; `service_workspace_admin.py` delegates to the atomic
`dismiss_workspace_invitation_prompt` operation, and
`test_core_workspace_effects.py::test_prompt_dismissal_is_atomic_and_conflicts_on_changed_target`
proves same-key replay and changed-prompt conflict. The snapshot includes only
pending, unexpired prompts. This action does not create or retire a native
carrier, so UI recovery can be prepared independently of R1/R2.

Proposed *separate, lead-assigned* UI slice: B owns `src/App.tsx` and
`src/App.test.tsx` only; `src/api.ts` already accepts the explicit key. Keep one
opaque key per current profile and prompt through an uncertain response and UI
remount, with bounded session-local storage cleared on confirmed completion or
fresh snapshot absence. Retry the same prompt with the same key; a different
prompt gets a different key. Do not optimistically claim dismissal on an
unknown result. Profile lock/host-generation change fences late completion and
does not replay under another profile. Behavior tests should inject commit plus
lost reply, stale snapshot, remount, repeat click, changed prompt, definitive
rejection and profile retirement; assert one Core action identity, truthful
pending/error presentation and no native or call teardown. The existing
`App.test.tsx` happy-dismiss/error tests and Core atomicity test are the starting
evidence. This remains a proposed implementation, not a completed flow or
packaged acceptance claim.

## Workspace prompt dismissal UI checkpoint

The narrow R3/R5 slice above was implemented on source parent `82c3364` in
`36b8d52386900f5f0eee2e7049f879aeca04ff3e`. `App.tsx` now keeps one opaque
Core `prompt_dismiss` operation ID for each prompt in the mounted App's current
profile generation and destination. An uncertain reply leaves the prompt visible
with an explicit retry action, and retry sends the same ID. A full invitation
snapshot that no longer contains the prompt clears its retained ID; a partial
snapshot does not. A different prompt receives a different ID. Confirmed success
removes the visible prompt; a definitive Core refusal keeps it visible with an
error and retires that operation ID.

The ID is held in memory for the mounted App lifetime. A Messenger presentation
rerender can reuse it, but an App unmount or a new profile lifetime cannot
automatically replay it. Profile lock and native host generation changes fence
late responses from altering the new view. The change does not touch native
carrier or browser media ownership. `src/App.test.tsx` covers lost replies,
same-ID retry, stale and partial snapshots, distinct prompts, definitive refusal,
profile retirement, App remount and host generation fencing. The complete App
test file passed 195/195 on this commit; TypeScript build passed. This is UI
component evidence only. Installed Windows and Android supported-facade flows,
restart behavior and native/media coexistence remain open in the acceptance
register.

## Workspace channel creation retry checkpoint

The next R3/R5 public Core mutation audit found a concrete uncertain-reply gap
in `App.tsx`: channel creation generated a new operation ID on every submit.
Core's keyed `workspace.channel_create` can replay the original result, while
the workspace directory permits duplicate display names. A committed creation
whose reply was lost could therefore be submitted again as a second channel.
The new regression first failed on two distinct IDs for that exact retry.

Commit `1a21455fd6b18b28f9c0bd40d7949f898bd1ed85` retains an ID only for
an actually submitted channel creation intent, fingerprinted by workspace
handle, name, topic, visibility and member handles. Retrying the same details
after an uncertain reply, including after closing and reopening the dialog in
the same Messenger profile lifetime, reuses that ID. Changed details receive a
new ID without discarding the earlier uncertain intent. A definitive Core
refusal or completed refresh retires its ID; a successful Core reply followed
by refresh failure is shown as created but not yet opened. Late results after
profile retirement cannot update the new view. No private host, media, native
carrier or shared-owner call site changed.

The two focused App regressions cover lost reply and dialog reopening, changed
details, return to an earlier uncertain intent and definitive refusal. The
complete `src/App.test.tsx` file passed 197/197 and the TypeScript build passed
on this code commit. This remains component-level UI evidence. Installed
Windows/Android supported-facade behavior, native restart, and media
coexistence remain open.

## Verified-contact workspace invitation retry checkpoint

The next bounded R3/R5 UI action was `invite_contact` from the workspace
invitation dialog. Before the change, each send omitted the Core operation ID.
A successful atomic invitation/outbox commit with a lost response left Send
available, and a retry could create another signed invitation and outbound
message. The new App regression first failed because its first send had no
explicit `operation_id`.

Commit `abbf4682952a8b869d691b1c9d806d57c4e1490a` passes an explicit ID
for each submitted workspace/contact intent. The current Messenger profile
lifetime retains an uncertain ID through dialog closure and reopening. A
different contact receives a separate ID; definitive refusal and visible
confirmed success retire only that intent. A reply arriving after dialog close
cannot update the reopened dialog or erase its retry ID. Profile retirement
fences a late reply and starts a new lifetime with a new ID. The UI labels an
unknown result as unconfirmed. This change neither creates nor retires native,
WebRTC or media resources.

Four focused App tests cover committed lost reply, closure while pending,
changed contact and refusal, confirmed later send, and profile retirement. The
complete `src/App.test.tsx` file passed 201/201 and the TypeScript build passed.
Core's atomic same-key invitation/outbox replay is separately covered by
`test_core_workspace_consent.py`; these App tests exercise the renderer with
substitutes. Exact-source packaged Windows/Android delivery, independent client
attachment, native restart and media coexistence remain open.

## Integrated R3/R5 retry disposition at `fa1addb`

The mounted-renderer retry work now covers five distinct UI actions. The first
three checkpoints above remain accurate for prompt dismissal, channel creation
and verified-contact workspace invitation send. Later source commits
`d3ca3fd`, `85cdf56`, `75f23b2`, `ad2f6b9` and `dfa48ec` add these two paths:

| Action | Current source and focused evidence | Honest recovery boundary |
| --- | --- | --- |
| Workspace access recommendation **send** | `src/App.tsx` retains the signed recommendation and one `operationId` for its workspace/profile scope through an uncertain send and settings close/reopen. `src/App.test.tsx` tests same-key retry, changed signed text, opaque workspace-handle refresh, later refusal after an unknown outcome, and scope retirement (`workspace access recommendations` cases). | One mounted Messenger profile lifetime. A confirmed Send again is a new action; a changed signed recommendation is a new intent. An unknown send remains unconfirmed. |
| Workspace administrator **request submit** | `src/App.tsx::submitWorkspaceAdminRequest` retains the intent/key, prevents concurrent submission, pins the first Core or legacy route and Core handles, and retries an uncertain result through the same route. A confirmed submit followed by failed refresh only retries the refresh. `src/App.test.tsx` `administrator request recovery` covers lost replies, route/handle changes, refusal, refresh failure and profile fencing. | One mounted Messenger profile lifetime. Only initial explicit Core unavailability selects legacy; an uncertain Core outcome cannot switch ID namespaces. A later refusal cannot erase an earlier unknown commit. |

These are renderer component guarantees, supported by the integrated App/Core/
profile local suite (295 tests) and `tsc -b --force` reported passing for this
source. They do not make pending UI identities durable across a renderer process
restart. The current UI has no protected Core readback/reconciliation contract
for every uncertain action above after such a restart. A new App/Messenger
lifetime therefore must not be described as replaying an earlier unknown action.

## Remaining lifecycle and coexistence gates

- Installed Windows and Android supported-UI execution must show the same public
  facade and authorized host as the independent consumer, including a pending
  durable send, actual receipt, profile switch/lock, window detach/reattach and
  an independent attached client. Preserve the runtime epoch and exact owner
  resource accounting; component substitutes do not establish this boundary.
- A renderer restart during an unknown mutation needs a protected Core-owned
  pending-intent/readback and reconciliation design before claiming automatic
  replay or exactly-once UI recovery. The mounted-lifetime maps above are a
  narrower guarantee. Actual native cold restart and required aggregate
  qualification remain separate R1 gates for R2 shared-owner promotion.
- The actual installed `CallDialog.tsx` WebView2/Android media path must run
  beside native messaging, with capture, tracks, audio focus, authenticated
  receipts and exact teardown through call failure, pairing closure, reconnect,
  profile lock and window navigation. Local call/media tests and preflight do not
  prove this coexistence. Keep browser media and its packaging while classifying
  messaging-only policy paths.
- `src/reconnect-runtime.ts`, `src/webrtc-session.ts`, `src/DirectRecovery.tsx`,
  `src/WebRTCOnboarding.tsx` and manual participant `serviceCommand` paths still
  have the distinct owners and callers in the table above. Remove a private
  service route or renderer loop only after an equivalent authorized Core/host
  route and installed behavior exist for that exact caller. R2 legacy retirement
  remains behind accepted native qualification and failure disposition.

The integrated-source full qualification, call and release-continuity workflows
were still active at the lead handoff (`43590284216`, `43590281431` and
`43590279206`, respectively). This document records no result for them and no
packaged UI/media or renderer-restart acceptance.

## Next concrete pending mutation boundary

The next bounded R3/R5 candidate is **Core workspace invitation creation** in
the workspace invitation dialog. At `src/App.tsx::WorkspaceInviteDialog`
`create`, each click passes `newOperationId()` to
`coreApiCreateWorkspaceInvitation` (`src/api.ts` already accepts an explicit
key). A committed create whose reply is lost leaves the dialog retryable; a
second click then uses a different key. In
`service/src/mesh_chat/workspace_service.py::create_workspace_invitation_command`,
same-key replay returns the stored result before preparing a new signed
invitation, while a new key prepares another nonce and commits another active
invitation record. The
`test_owner_creates_a_signed_workspace_invitation_through_the_facade` case in
`service/tests/connection/test_core_workspace_admin.py` proves
same-key facade replay, but the dialog has no lost-reply identity regression.
This is a source-derived duplicate-invitation risk, not an observed packaged
duplicate.

A narrow UI slice can first pin the operation ID to the exact current profile,
workspace and normalized connection payload for nearby/remote/I2P creation,
retain an uncertain result through dialog close/reopen in the same Messenger
lifetime, and distinguish a confirmed result from an unknown reply.
Changing the connection payload starts a new intent without discarding an
earlier unknown one; late results must be fenced by the profile lifetime.
Before applying that pattern to manual, participant, guided/email or WebRTC modes,
review their prepared host access and DataChannel transfer ownership: replaying
the Core result must neither create a second host nor send an invitation twice.
The test boundary is a committed lost reply followed by exact-key retry,
changed-payload conflict/new intent, dialog close/reopen, definitive refusal,
profile retirement and mode-specific host/transfer checks. This candidate
needs its own reviewed implementation and installed follow-up; it is not a
renderer-restart recovery claim.

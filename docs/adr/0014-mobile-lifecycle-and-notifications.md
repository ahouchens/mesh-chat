# ADR 0014: Mobile lifecycle and local notifications

Status: accepted for workspace protocol v1, increment 15.

## Decision

Mesh Chat exposes local operating-system notifications only while the embedded
mobile runtime is able to execute. It does not use FCM, APNs remote delivery, a
hosted relay, or a background server. Suspension or process termination may
delay all work until the user opens Mesh Chat. The UI states this limit and
never describes local notifications as push availability.

A mobile installation creates its own private identity, destination, counters,
and protected vault. It joins an existing member through the unchanged
Increment 14 sponsor offer, fresh-device countersignature, owner review, and
exact authority-signed manifest delta. Neither a QR/bearer offer nor an
acceptance grants membership. Three devices per member, 24 active
destinations, and the authority-device removal guard remain unchanged. No
platform marker is added to canonical device cards or historical documents.

Notification presentation is local policy. It is not a canonical event,
delivery receipt, endpoint receipt, read state, social read receipt, or
notification-open receipt. Older peers safely ignore the new sealed records.

## Frozen notification precedence

The service considers a notification only after a new canonical message has
passed signature, manifest, channel, audience, sequence, fork, duplicate, and
current-authorization validation and is being committed as live content.
History/catch-up acceptance sets `historical=true` and cannot enqueue work.

The precedence is:

1. The workspace must be active or in incomplete-but-safe synchronization;
   forked, terminal, and removed-device states suppress.
2. A message authored by the local member is quiet, including a send from that
   member's other linked device. This is deliberate: linked endpoints do not
   notify one another for the person's own sends.
3. The platform must report native support and current permission `allowed`.
   The sealed permission value is a cache refreshed from the OS, never an
   authority over the operating system.
4. The runtime must be backgrounded or at the suspended boundary. Foreground
   presentation is suppressed; in-app unread state remains visible.
5. A conversation preference overrides the workspace preference. Effective
   modes are `all`, `mentions_only`, and `muted`; the default is `all`.
6. Mention muting is evaluated against the signed structured mention-member
   list. Text such as `@name` has no mention semantics. Mention mute wins.
7. An unsubscribed public channel stores and indexes the event but suppresses
   ordinary notification. An eligible structured mention may still notify.
8. Hidden workspace DMs, inactive channels, private-channel nonmembership, and
   no-longer-visible events suppress.
9. Root messages and workspace DMs follow the effective conversation mode.
   Replies use `thread_reply` but follow that mode. Structured mentions use
   `mention`. Edits, reactions, deletions, controls, read hints, rebuilds, and
   retention work never notify.
10. The sealed device-wide **Hide notification previews** choice is applied
    last, before native handoff. It replaces both strings with `Mesh Chat` and
    `New message`.

Retries, renderer reloads, invalidation replay, and restart reuse one
HMAC-derived notification ID per workspace event. A retained decision ledger
prevents a second logical notification. OS replacement uses that opaque ID.

## Service-to-native boundary

The internal native work item is:

```text
{
  notification_id: 64 lowercase hex characters,
  category: mention | thread_reply | direct_message | channel_message,
  title: sanitized plain text, at most 80 Unicode characters,
  body: sanitized plain text, at most 160 Unicode characters,
  sequence: positive local durable sequence,
  created_at: local timestamp,
  grouping_key: 32 lowercase hex characters
}
```

Native JSON is at most 1,024 UTF-8 bytes. The queue has at most 128 IDs
and a drain returns at most 16 items. Control, format, surrogate, bidi, and
newline injection is removed by the service and rejected again by native code.
Strings are never HTML and links are never executed.

Workspace, conversation, thread, and event routing remains only in separately
sealed records keyed by the opaque notification ID. The native item, Android
tag/group/intent, iOS identifier/thread/userInfo, logs, and SQLite identifiers
contain no raw routing UUID, destination, identity, invitation, or canonical
document. Preview text is the only optional plaintext passed to the OS.

Canonical event, derived message/unread state, notification decision, ledger,
route, work, and queue update share the event `put_many` transaction. A crash
after commit leaves the same pending work. `accepted` acknowledgment means only
that the platform API accepted a local request; `retry` is bounded to three
attempts. It does not alter delivery or read state.

The renderer can read state, change preferences, request an
authorization-checked open, and ask for reconciliation. It cannot call native
permission-state injection, lifecycle transition, work drain, or
acknowledgment commands. Android/iOS call those directly inside the plugin,
independently of renderer polling.

## Permission and native presentation

Android API 33+ uses `POST_NOTIFICATIONS` through a declared permission alias.
The prompt occurs only after **Enable notifications** and is recorded so denial
cannot create a loop. API 24–32 uses the OS notification-enabled state without
a runtime prompt. States are `not_requested`, `allowed`, `denied`, and
`settings_required`; the latter states offer **Open system settings**.

Android creates stable `mesh_chat_messages_v1` (default importance) and
`mesh_chat_mentions_v1` (high importance) channels. Names contain no workspace
data. Notifications group by an opaque HMAC key, replace by an opaque stable
ID, and open only `meshchat://notification/<opaque-id>` in the single-task
activity.

iOS source uses `UNUserNotificationCenter`, local `UNNotificationRequest`, an
explicit request, settings recovery, opaque identifiers/thread identifiers,
and the same deep link. Foreground presentation is suppressed. This Windows
release cannot claim iOS completion: it still requires macOS/Xcode compilation,
signing, and physical suspend/resume, lock-screen, tap, and upgrade evidence.
APNs registration is absent.

Already displayed notifications cannot be recalled reliably. OS lock-screen
policy, history, screenshots, backups, accessibility services, and a
compromised or unlocked endpoint remain outside Mesh Chat's control.

## Lifecycle and reconciliation

The plugin sends ordered foreground, background, and observable suspension
boundary transitions. Android uses activity pause/stop/resume; iOS records
background and the following suspension boundary. Process death has no
guaranteed callback. Initialization and visible renderer recovery therefore
also enter foreground reconciliation.

One sealed profile lifecycle record holds transition generation, last
reconciled generation, invalidation generation, overflow flag, bounded reason,
and state. Workspace invalidations include the durable generation. The mobile
bridge queue is capped at 256 events; dropping an oldest event persists the
overflow flag. Foreground reconciliation marks `reconciling`, drains bounded
prerequisite controls before dependent pending events, advances only sharded
due-work schedulers, and finishes `caught_up`. It never selects a fork.

Resume reads bounded summaries, pending queues, and due-work shards; it does
not enumerate `workspace_event` or `workspace_delivery`. Existing operation,
event, delivery, replay, and notification IDs preserve idempotence. Historical
recovery remains quiet. Removal/private-channel controls received during
suspension take effect before dependent events and notification-open checks.

The service makes no execution claim after OS suspension or termination. Work
committed before suspension remains sealed until a later runtime opportunity.
Outbox expiry/cancellation, history scheduling, offline reconnect, activity
recreation, renderer recreation, and restart reuse their existing paths.

## Sealed records and erasure

New local kinds are:

- `workspace_notification_settings`: preview, capability/permission hints, and
  durable sequence;
- `workspace_notification_preference`: keyed workspace/conversation mode and
  mention mute;
- `workspace_notification_ledger`: one decision and state per event;
- `workspace_notification_work`: retryable native work plus sealed route;
- `workspace_notification_route`: authorization-checked open scope;
- `workspace_notification_queue`: bounded opaque-ID queue and overflow count;
- `workspace_lifecycle_state`: device-local generation, cursor, overflow, and
  diagnostic summary.

All IDs are HMAC-derived. Workspace erasure deletes its preferences, ledgers,
routes, work, and queue references. The profile lifecycle summary contains no
workspace scope. Retention pruning removes an event's ledger/route/work and
queue reference, so pruned history cannot be reopened. Downgrade ignores
unknown sealed kinds without deleting unrelated state.

## Open authorization

A tap validates the 64-character opaque ID and loads its sealed route. The
service requires a live workspace, exact conversation and event digest,
retained canonical message, no local hide marker, historical entitlement,
current member/channel/direct authorization, and current private admission.
Failure opens a generic explanation. Success returns presentation routing
only. The ordinary conversation-open path may then commit read state; tap,
dismissal, and native acknowledgment do not.

## Compatibility

No canonical bytes change. Genesis, manifest, device link, authority, channel,
event, history, read-hint, and removal documents remain byte compatible with
0.2.34. Mobile uses the same Increment 14 link limits. Existing Android 0.2.12
application ID, API 24 minimum, API 36 target/compile level, backup-disabled,
cleartext-disabled policy, protected vault, and debug signing lineage remain.
New sealed kinds are local and non-authoritative.

## Release-minimum benchmark

The named Windows host is recorded in
`docs/benchmarks/increment-15-mobile-lifecycle-notifications.json`. The gate
uses exactly 50,000 events, eight members, 32 public/private/archived channels,
three encrypted profiles, the Increment 14 three-device/24-destination cap, 30
samples, and the real sealed store.

Frozen p95 limits are: policy/duplicate below 25 ms; durable enqueue,
background transition, and open below 100 ms; preference update/native drain
below 750 ms for a fully authorized 16-item batch; no-change resume below 500 ms; overflow/network reconciliation
below 750 ms; pending-work restart below 2 seconds; live acceptance to native
request below 250 ms. Queue/batch/payload/title/body limits are 128, 16, 1,024
bytes, 80 characters, and 160 characters. The fixture must prove no whole
event/delivery scan, no historical storm, no preview leak, denial purge,
authorization failure after removal/fork, unchanged unread/delivery state on
open, and zero identity copies.

Physical Android memory and battery evidence is mandatory for physical
completion but cannot be fabricated without an authorized disposable device.

## Physical completion gates

Automated tests, source inspection, APK assembly, signature verification, and
an emulator do not establish physical completion. Android remains physically
incomplete until an authorized disposable device passes fresh and 0.2.12
upgrade installs; linking; permission allow/deny/repeated-denial/settings;
foreground/background, screen-off, suspension, process death, offline/reconnect,
rotation and renderer recreation; all/mentions/muted and preview-hidden
lock-screen/history; private/DM/thread/tap routing; catch-up, retry, crash,
overflow and removal; no false read; protected-profile, intent, tag, log and
SQLite scans; memory and battery evidence.

iOS additionally requires macOS/Xcode, signing/provisioning, a physical device,
and equivalent evidence before it may be advertised complete.

## Accepted tradeoffs

- Promptness depends on the OS allowing execution.
- Enabled previews disclose minimum text to the OS; generic previews cannot
  retroactively erase prior presentation.
- Same-member linked-device sends are quiet.
- Preferences are device-specific and create no canonical traffic.
- A bounded authoritative refresh after an invalidation gap is preferable to
  trusting an incomplete renderer event stream.

## Rejected alternatives

- FCM, APNs remote push, hosted push/storage, cloud relays, trusted relays,
  always-on hosted services, and telemetry.
- Android foreground services or battery-optimization exemptions.
- Identity/vault cloning.
- Renderer polling as the notification source.
- Notifications for catch-up/rebuilds.
- Notification tap/presentation as read or delivery.
- Raw routing IDs in native intents, tags, or grouping keys.

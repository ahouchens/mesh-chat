# Independent TypeScript application

This new application imports only Node and the installed public
`@mesh-chat/core-client` package. Copy it outside the checkout, install the exact
staged SDK archive with offline npm and scripts disabled, then run:

```sh
node consumer.mjs --pipe HOST_SUPPLIED_LOCAL_PIPE
```

On Windows the application can own a separately installed frozen runtime:

```sh
node consumer.mjs --runtime C:\\installed\\mesh-service.exe --data-directory C:\\app-data\\independent
```

This starts the normal `--app-owned-native` mode with a unique authenticated
pipe, the current executable image and parent PID, and an explicit app data
directory. It waits for the framed startup acknowledgement before opening the
SDK session. The host owns protected key storage and starts with no identity;
`profile.create` still requires an explicit application request and caller key.
Closing application input detaches the SDK and requests host shutdown by EOF.
Retirement is accepted only after `runtime_stopped` and successful process exit.
No private command is sent to the host's lifetime stream.

The host must be a separately installed normal app-owned runtime. The pipe is
explicitly supplied by that application's trusted bootstrap, which authenticates
the executable image. The SDK does not open a vault or retrieve a vault key.
The production host route and public pairing are implemented. Installed-host
qualification requires exact-source retained reports; source and protocol checks
alone do not establish packaged host or SC21 qualification.

`bootstrap-check.mjs` is a separate installed application check. It uses only
this normal launch route and the installed public SDK to verify a fresh empty
host, explicit profile creation, same-key replay, changed-payload rejection and
the same public identity after a clean host reopen. The Python qualification
producer separately checks actual EFS attributes on the profile directory and
vault file. Its retained report contains selected checks and artifact hashes;
it excludes the identity, paths, caller key and raw host output. This bootstrap
check does not exchange peer messages or qualify SC21.

`pairing-check.mjs` separately starts two normal application host instances with
fresh protected data directories. It disables LAN/discovery/help routes through
public settings, explicitly consents to broker use, requests relay-only ICE and
declines direct-IP disclosure on both public pairing intents, then exchanges
a public pairing code, accepts the signed invitation and approves the pending
contact. Both intents must transfer. Cancelling those transferred intents must
preserve public messaging readiness and delivery. One message in each direction
must reach authenticated `delivered` state, retain the same message on original
key replay and produce exactly one outbound/inbound public record.

The lifetime sequence attaches two SDK sessions from this same Node application
to one host. Closing one session must leave the other usable, and a replacement
session must observe the same authorized profile, contact and messages. A second
owner launch against the same data must report refusal and positively exit while
the original host stays usable. The receiver then exits before new work is
enqueued. The sender must preserve that pending message, its opaque handle and
original caller key across a trusted owner stop and reopen, without another
profile creation or pairing. Changed payload with the original key must conflict
without adding any outbound message record to the authorized conversation.

Three normal host incarnations must acknowledge shutdown and positively exit;
the refused owner's exit is counted separately. The producer checks actual EFS
on the two distinct profile directories and vaults. A passing report qualifies
SDK session-close independence within one application, not exit of a separate
consumer process or caller/cross-user/multi-application isolation. Host shutdown
acknowledges the in-process native host, but does not certify exit of every
isolated bootstrap helper. Pending-message preservation does not prove its
subsequent delivery after restart. The original 240-second main deadline remains.
The report is Windows-only. Android, selected ICE paths and SC21 remain separate.
The public pairing disclosure option governs gathering; it does not grant
persistent per-contact direct-IP messaging consent. This check uses the supported
relay-only route and never injects that separate consent through a private API.

`separate-process-check.mjs` is a separate fresh-profile diagnostic fixture. One
normal owner keeps the runtime and one public SDK session; it starts an installed
`consumer.mjs --pipe` child, observes the same public profile, requires that
child to detach and exit while the owner stays usable, then attaches a replacement
child. With the replacement attached, the owner stops the host and requires
positive host retirement, failed post-stop child access and bounded child exit.
It retains only fixed check counts, timing and a failure stage. The fixture is
not yet in the installed staging list or qualification workflow. It does not
cover paired pending work, wrong-image callers, cross-application isolation or
full SC22/SC26 acceptance: same-user Node processes with the exact allowed
executable image currently receive the same owner grant.

The qualification pairing check opts into a one-shot owner diagnostic with
`MESH_CHAT_APP_PAIRING_DIAGNOSTICS=1`; ordinary launches leave it disabled.
After a public failure, the owner sends EOF and observes the exact child's
bounded terminal pairing cause before SDK detachment and service cleanup.
The additional observation window is at most two seconds, shared concurrently
by the original two hosts. A missed window remains unavailable even if a frame
arrives later. Only fixed phase/event/reason labels are retained, with no
documents or identifiers. This private lifetime observation grants no Core
capability and never satisfies pairing, receipt, or shutdown acceptance.

Input and output are bounded newline-delimited JSON on dedicated inherited
streams. Each input contains `id`, `operation`, `params`, and, for a keyed
mutation, the caller's explicit `idempotency_key`. The operation allowlist covers
profile creation, public pairing intent, explicit contact decisions, supported
settings, connection intent, messages and receipt/event queries. It excludes
private native commands, raw signaling, test dispatch and grant injection.

Core owns native negotiation, retries and transport custody. This application
does not automatically approve a relationship or replace a failed request. Core
errors return their typed code; a transport failure terminates the client, so
the caller must resolve an uncertain mutation explicitly after reconnecting.
In `--pipe` mode closing input leaves host lifetime with its external owner.

Pairing codes, message text and caller keys can appear in these private control
streams. The test infrastructure must capture them in memory and keep them out
of logs and retained reports. Retained qualification evidence must identify the
installed SDK/runtime hashes, source, actual host platform and real authenticated
receipt cases. Installing or syntax-checking this app alone is component evidence.

`scripts/windows_public_consumer_session.py` adds a reusable Python controller
for one installed ordinary Windows consumer process. It requires the exact
source-bound normal bootstrap report and retained TypeScript SDK archive,
installs this application outside the checkout, and validates the frozen host,
SDK and copied application bytes before launch and after positive exit. Call
`WindowsPublicConsumerSession(...).open()`, issue allowlisted `request(operation,
params, key)` calls, then `finish()` or `close()` to close stdin and require
consumer exit code zero. `runtime.mjs` requires the normal host's stopped marker
and exact child exit before that consumer can exit successfully. The controller
retains its owned workspace on timeout or failed retirement; remove it only
after confirmed retirement with `cleanup_workspace()`. Its standalone smoke
command creates and queries a fresh public profile only. No Windows–Android
pairing, receipt, restart or network interruption has been executed by it yet.

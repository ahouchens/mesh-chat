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
The production host route and public pairing are being integrated. This source
and its protocol checks do not establish packaged host or SC21 qualification.

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
key replay and produce exactly one outbound/inbound public record. Both hosts
must acknowledge clean shutdown, and the producer checks EFS on both vaults.
The report is Windows-only. Android, selected ICE paths and SC21 remain separate.
The public pairing disclosure option governs gathering; it does not grant
persistent per-contact direct-IP messaging consent. This check uses the supported
relay-only route and never injects that separate consent through a private API.

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

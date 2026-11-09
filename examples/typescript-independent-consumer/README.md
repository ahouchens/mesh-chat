# Independent TypeScript application

This new application imports only Node and the installed public
`@mesh-chat/core-client` package. Copy it outside the checkout, install the exact
staged SDK archive with offline npm and scripts disabled, then run:

```sh
node consumer.mjs --pipe HOST_SUPPLIED_LOCAL_PIPE
```

The host must be a separately installed normal app-owned runtime. The pipe is
explicitly supplied by that application's trusted bootstrap, which authenticates
the executable image. The SDK does not open a vault or retrieve a vault key.
The supported host launch/bootstrap integration is still being implemented;
this source scaffold does not establish SC21 traffic qualification.

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
Closing input detaches the client and leaves host lifetime with its owner.

Pairing codes, message text and caller keys can appear in these private control
streams. The test infrastructure must capture them in memory and keep them out
of logs and retained reports. Retained qualification evidence must identify the
installed SDK/runtime hashes, source, actual host platform and real authenticated
receipt cases. Installing or syntax-checking this app alone is component evidence.

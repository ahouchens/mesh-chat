# Signaling mailbox validation — 2026-10-28

The global Worker is live at
[mesh-chat-signal.webtechalex.workers.dev](https://mesh-chat-signal.webtechalex.workers.dev/health).
Its base URL is embedded in `service/src/mesh_chat/deployment_defaults.py` and
verified in the rebuilt Windows service without environment overrides. Existing
custom/disabled settings are preserved. Updated desktop/mobile installers have
not been distributed; physical-device release qualification remains pending.

## Production deployment

- Deployed 2026-10-28 with Wrangler 4.154.0 to the authenticated project account.
- Worker: `mesh-chat-signal`; version: `a46c56c7-4fc2-4d5d-a087-a422a240a94f`.
- Base URL: `https://mesh-chat-signal.webtechalex.workers.dev`.
- Upload: 7.88 KiB / 2.57 KiB compressed; reported startup time: 3 ms.
- Health: HTTP 200, `{"protocol":2,"writes_enabled":true}`.
- Legacy plaintext route: HTTP 410; missing access token: HTTP 401.
- Hosted encrypted onboarding, personal reconnect, and workspace reconnect:
  3 passed (12 passed including mailbox unit/crypto tests).
- Two freshly built Windows service processes used the embedded default and
  completed a signed, encrypted offer/answer exchange over production HTTPS.
  Custom and disabled choices and clean shutdown also passed. This test uses
  synthetic SDP and does not establish physical WebRTC connectivity.
- Windows service SHA256:
  `57DF59C11BF8C193229D91BBD9CB641480E321F70C5782B4BD8EAAF65C3130B9`.
- After default activation: full service suite passed (1,367 passed, 49
  environment-dependent skips); `dist/reports/signal-production-service-tests.txt`.
- Reports: `dist/reports/signal-production-deployment.json`,
  `signal-production-health.json`, and `signal-production-packaged-smoke.json`.

Production testing found Cloudflare rejects urllib's generic Python identifier
with error 1010. The client now identifies itself as `MeshChat-Signaling/2`.
The HTTP/load harnesses use the same verified certificate context as the app;
TLS verification remains enabled and redirects remain disabled.

## Implementation checks (before production activation)

| Check | Evidence |
| --- | --- |
| Worker protocol and abuse tests | 11 passed: ciphertext-only envelopes, streaming size bounds, token pinning, concurrency, TTL, cleanup, bounded counters, edge limits and write suspension |
| Full Python service suite | 1,366 passed, 49 skipped; `dist/reports/signal-service-tests.txt` lists environment-dependent skips |
| Workspace migration regression | 14 scope tests passed, including the additional upgrade/queue-retry test added after full-suite collection |
| Frontend | 480 tests passed; TypeScript check and production bundle succeeded |
| Real local Cloudflare runtime | 3 HTTP tests passed: encrypted onboarding and personal/workspace handshakes |
| Desktop/mobile crypto | Fixed derivation/ciphertext vector and cross-provider round trips passed, including Reticulum's internal provider used without desktop cryptography |
| Long outage/revocation | Simulated 45-day personal and workspace outages preserve authorization; current block/removal still prevents reconnect |
| Worker packaging | Wrangler 4.154.0 dry run passed with Durable Object and both rate-limit bindings |
| Windows service package | Built successfully; SHA256 `0F7403B8FF370AC3C9DD738811ED19B78012BD1E24F945FC025D6EA8F8763173` |
| Packaged IPC smoke | Fresh protected profile, custom URL normalization, disabled choice, signed onboarding offer and clean shutdown after host pipe closure passed; `dist/reports/signal-packaged-smoke.json` |

The frontend build needed a temporary, untracked Node preload to force esbuild's
supported IPC-input fallback because Windows denied deletion of esbuild's input
temporary file. No dependencies or committed build scripts were changed for this
workaround; the resulting bundle cache matches current frontend sources.

The standalone packaged harness initially kept stdin open after shutdown and
hit its process-exit timeout. Closing the host input pipe after the acknowledged
shutdown produced a clean exit; no production shutdown code was changed.

## Capacity and cleanup

The 30-minute local test uses 100 independent encrypted rooms, maximum-size
48 KiB synthetic plaintext documents, all three slots, staggered writes below
the single-IP budget, and two reads per room per minute. Writes stop for the
last ten minutes. It tests HTTP storage and expiry, not 100 real simultaneous
WebRTC negotiations. Completed against Wrangler's local runtime:

- 1,200 successful PUTs and 5,754 GETs (6,954 total HTTP requests).
- 754 expected expired-document responses; zero unexpected failures.
- 78,774,000 uploaded bytes; HTTP p95 42.09 ms on this machine.
- Final read-only SQLite inspection: zero application records across all local
  room databases, confirming expired ciphertext and counters were removed.
- Aggregate report: `dist/reports/signal-mailbox-load.json`.

These numbers are local measurements, not hosted latency or billing estimates.

During the run, read-only inspection found exactly two application storage keys
per active room (room and fixed counters). No per-IP or guessed-token keys were
allocated. Ciphertext remains capped at three slots per room.

## Remaining installer release qualification

Android instrumentation tests now cover the embedded default and saved choices
across process restart, packaged crypto, and personal/workspace reconnect after
injected outages, lifecycle changes and sealed-profile reload. The optimized
host and test APK build locally; 145 related host service tests passed. Both
recovery fixtures and the crypto round trip passed against the local Worker
with a native transport double. On 2026-10-28 all five mailbox instrumentation
invocations then passed on Android 15/API 35 AOSP ATD x86_64 with real packaged
crypto and JNI/WebRTC, alongside three Chromium/native interoperability tests.
The run exposed and fixed a shared negotiation deadline and continuous ICE
gathering that prevented prompt completion of native SDP creation.
See [coverage and run instructions](../../docs/ANDROID_SIGNAL_MAILBOX_TESTS.md).

- Complete the hosted capacity run and record provider latency, actual compute,
  operations, storage and projected cost. Local request counts cannot establish
  hosting cost or the effectiveness of globally distributed edge limits.
- Follow SELF_HOSTING.md from a clean checkout against a separate deployment.
- Verify two packaged physical clients: encrypted pairing, personal/workspace
  reconnect, network loss/change, simultaneous/staggered restarts, long offline
  periods, token rotation, revocation, mailbox outages, and bidirectional message
  delivery with receipts. Desktop/mobile crypto compatibility alone does not
  prove this device matrix.
- Build and distribute updated desktop/mobile installers after qualification.
  The rebuilt Windows service already verifies the embedded default and
  custom/disabled choices; installed apps are not modified by Worker deployment.

The full requirements remain in [the spec](../../docs/SIGNAL_MAILBOX_SPEC.md).

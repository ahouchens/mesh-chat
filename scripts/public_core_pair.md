# Installed public Core fresh-pair diagnostic

This diagnostic runs one ordinary Windows application-owned host through the
installed TypeScript SDK and one ordinary Android app through its Binder SDK.
Both start with a fresh profile. Windows offers, Android explicitly accepts the
invitation, and Windows explicitly approves the contact. Each sends one unique
text message through Core and observes its delivered state and exactly one
corresponding incoming record. Pairing cancellation after transfer must preserve
the approved relationship and subsequent messaging.

This is the first combined public-consumer scenario. It does not qualify native
policy promotion, restart, partition, upgrade, calls, physical devices or the
complete SC21 requirement. Public `messaging_ready` does not identify an exact
native resource or prove the selected ICE path.

## Components and custody

- `public_core_pair_flow.py` uses only an already-open peer's public `request`
  method. It caps each role at 96 requests, polls at least five seconds apart,
  bounds phase attempts, and checks a 60-second finish reserve. Typed transport
  errors fail the scenario; it never retries an uncertain mutation.
- `public_core_pair_controller.py` admits the manual CI role and exact source,
  verifies downloaded platform bytes, exchanges setup keys, and opens the
  platform adapter. It rechecks source and producer inputs after positive finish.
  Failed Windows workspaces are retained. Android cleanup is restricted to the
  admitted disposable emulator and owned app/forward/process resources.
- `public_core_pair_rendezvous.py` and `public_core_pair_artifacts.py` exchange
  only public keys and sealed setup. Their own job/phase allowlists do not reuse
  native diagnostic admission. Context includes repository ID, run, attempt,
  source, and a deterministically derived pair ID. X25519/HKDF/AES-GCM binds the
  setup to that context with a distinct domain and one-use phases.
- `public-core-pair-action` supplies the Actions runtime token to the Python
  child. It drains output without logging it, enforces an outer timeout, and
  treats timeout or uncertain child retirement as failure. The public uploader
  reuses the pinned artifact SDK dependency but has separate admission.
- `check_public_core_pair.py` requires successful producer and peer jobs, exact
  report-byte hashes, unchanged application sources, matching peer identities
  and directional message hashes, explicit approval and confirmed finish/cleanup.
  Missing, stale, duplicate-field, overlarge or failed reports cannot pass.

Product messages and authenticated receipts never use Actions artifacts. Test
message text is independently derived from pair ID and role and sent via
`message.enqueue`; only its digest appears in the bounded result.

## Same-run inputs and outputs

The Windows role downloads `desktop-transport-${SHA}` to `dist/reports`, retaining
`windows-independent-bootstrap.json` and its relative SDK archive, and
`native-windows-tested-${SHA}` to the checkout root for the frozen sidecar and
hidden build manifest. The Android role downloads `android-webrtc-debug` to the
checkout root, retaining the independent APKs, Maven publications and
`android-independent-distribution.json`.

Each role uploads its `public-core-pair-<role>.json` and the unchanged producer
report it consumed. The checker receives these from the same workflow run and
uses the actual `needs` results for `verification`, `android`, `windows_public`
and `android_public`. The normal required qualification gate remains separate.

The role CLI accepts `--role`, `--expected-source` and `--output`. Android also
requires `--disposable-emulator-serial emulator-5554`. Run through the Node Action
while the disposable emulator is alive; an ordinary shell step does not supply
the artifact runtime authority. The checker accepts `--windows-report`,
`--android-report`, `--windows-bootstrap`, `--android-distribution`,
`--expected-source` and `--output`, with actual job outcomes in `PUBLIC_PAIR_NEEDS`.
It derives the pair ID from CI context; an optional `--pair-id` must match.

The `connection-qualification.yml` manual input `public_pair_diagnostic=true`
selects `public-core-pair-diagnostic.yml`; it conflicts with the first-cold
diagnostic input. Both are false by default. Separate concurrency groups keep
the public run and its producers from canceling ordinary qualification or the
native diagnostic. The Android wrapper runs inside the emulator runner's live
script, which inherits the Node Action environment. The initial key exchange
allows up to 600 seconds for platform setup skew, within the unchanged
1200-second controller limit; application sessions begin afterward.

## Verification and limits

At integration `1955823`, 171 focused tests passed across the adapters' controller
composition, flow, strict evidence, sealed transport and actual Node admission
wrappers. These include wrong role/run/phase, expired or
replayed setup, late completion, bounded trickling responses, altered artifacts,
missing receipts and failed cleanup. Protocol doubles and fake artifact SDKs
exercise admission; they do not substitute for the first paired platform run.

HTTP body waits and uploader execution respect the supplied phase deadline.
Underlying DNS/connection setup still has urllib/socket timeout limitations.
The outer Action deadline fails closed and makes no descendant-host retirement
claim if it must terminate the Python controller. Source/byte checks and explicit
cleanup evidence remain required even when earlier flow operations succeed.

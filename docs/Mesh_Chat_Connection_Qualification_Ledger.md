# Connection runtime qualification ledger

This ledger records the automated evidence behind the connection-runtime refactor at
commit `67ac8fe34b19db335fc9b772af0bd0cd7ff78d49` (tree
`bd09a02ade1b83a2515fd2a0f515c7f4d23467bd`, 2026-11-01). It separates what was
executed from what this environment cannot execute; it is not a physical-device
qualification.

## Connection qualification workflow

Run [41293162273](https://github.com/ahouchens/mesh-chat/actions/runs/41293162273)
concluded **success** with every required job and the final gate:

| Job | Result |
| --- | --- |
| policy / policy | success |
| verification / Verify and test | success |
| verification / Check Windows desktop host | success |
| direct / android-compile | success |
| direct / controlled-peers (ubuntu-latest) | success |
| direct / controlled-peers (windows-latest) | success |
| layout / browser-layout | success |
| Select dependent qualification suites | success |
| android / Android build and optimized native Chromium interop | success |
| policy / Required connection policy gate | success |
| Required connection qualification gate | success |

The Android job ran the emulator suites and emitted
`android_emulator_optimized_native_and_python_components` evidence whose
`source_tree` equals the tree above; GitHub supplies a synthetic merge commit as
`source_commit` for pull-request runs, so the tree is the binding identifier.

## Main CI and packaged Windows

Workflow-dispatch run
[41295548962](https://github.com/ahouchens/mesh-chat/actions/runs/41295548962)
concluded **success**:

- Verify and test: 2,600 passed, 51 skipped (skips are platform-bound packaged
  tests), SDK conformance 1 passed, frontend 587 passed.
- Check Windows desktop host: `cargo test --lib` 27 passed and
  `--features experimental-shared-webview` 27 passed; packaged lifecycle,
  WebView2 private-host transport, packaged pre-approved peers and explicit
  pairing evidence all report `passed: true` with `source_commit` exactly
  `67ac8fe…` and the tree above.

## Local qualification

| Suite | Command | Result |
| --- | --- | --- |
| Required policy inventory | `python scripts/connection_evidence.py --run --junit … --expected-source <tree>` | 1,402 passed, zero skips |
| Strict typing | `mypy --config-file mypy-connection.ini` | clean |
| Frontend | `node scripts/run-frontend-tests.mjs` | 587 passed |
| TypeScript client + package | `node --test sdk/typescript/dist/**/*.test.js` | 38 passed |
| Compatibility | `pytest service/tests/connection/test_core_compatibility.py` | 17 passed |
| Budget conformance | `pytest service/tests/connection/test_core_budgets.py` | 3 passed (exact advertised limits; over-budget rejected; edges accepted) |

## Explicit limits

These were **not** executed and are not claimed anywhere in this ledger:

- physical-device qualification across independent Android and Windows devices;
- packaged Windows↔Android interoperability (the packaged evidence above is a
  single Windows host with WebView2 and frozen peers);
- a packaged Android consumer application;
- published SDK/package artifacts and a supported version-pair matrix;
- executed release qualification (requires a tag) and any release publication;
- a native Windows DataChannel implementation.

The corresponding acceptance rows (INV21, INV22, INV25, INV26, SC01, SC21, SC25)
remain partial or open for exactly these reasons.

## Reproduction

```text
python scripts/connection_evidence.py --run \
  --junit dist/reports/connection-policy.xml \
  --expected-source "$(git rev-parse HEAD)" \
  --output dist/reports/connection-policy.json
cd service && mypy --config-file mypy-connection.ini
node scripts/run-frontend-tests.mjs
node --test "sdk/typescript/dist/**/*.test.js"
```

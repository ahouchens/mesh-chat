# UI / Core boundary qualification

This suite replaces only Tauri `invoke` and OS event subscriptions. It renders
the production `App` and executes the production `api.ts` serializers against a
separate Python process running `FramedSession`, `CoreSession`, domain services
and a fresh encrypted test vault. Network startup is disabled. It neither maps
typed operations into legacy command mocks nor claims native transport evidence.

The retained request vectors separately exercise every advertised component
operation through JSON serialization, schema validation, the production parser
and permission admission. The permission-denied session must reject before any
domain effect. Unsupported future operations are not advertised as implemented.

After committing source, run the exact-source fast gate:

```text
python scripts/check_core_ui_boundary.py --expected-source <HEAD SHA> --node <Node 20+ executable>
```

It rejects dirty or mismatched source, missing runtimes, empty results, skipped
tests, failing tests and incomplete execution. Python uses the existing
collection/run inventory binding. JSON evidence records the source commit/tree,
JUnit hashes, runtime version and wall time under `dist/reports/`. CI executes it
immediately after dependency installation, before distribution package checks.
The full qualification matrix remains a separate required integration gate.

For development, run `pytest service/tests/connection/test_ui_core_boundary*.py`
or `vitest run --config tests/core-ui-boundary/vitest.config.ts` directly.
`MESH_BOUNDARY_PYTHON` selects the Python interpreter; the default is the local
`.venv` on Windows and `python` on other platforms. Tests create and remove their
own directories under `.test-tmp/core-ui-boundary/`.

The baseline at `435b497` deliberately fails the new regressions: direct sends
use a new idempotency key on retry, accepted text is restored after a failed
snapshot, and workspace requests fail at parser/session admission. The control
case verifies one queued durable direct message without a forged delivery state.

The Android counterpart is the separately owned
`TypedCoreBridgeBoundaryTest.kt`. It calls the production typed app bridge and
real Binder/dispatcher/mobile session, with private access only for isolated
fixture setup. Its three cases are mandatory members of the existing
artifact-bound Android qualification inventory. They require C's typed bridge
implementation and A's parser/session fixes. Compilation or emulator execution
has not been claimed locally; disk-constrained native builds run in GitHub CI.

## Timing evidence

`ci-baseline-timing.json` retains step durations from the integration lead's
GitHub jobs API snapshot for run `42598859239`, at the exact baseline. The
verification job took 519 seconds, including 478 seconds in `Validate and test`;
the Windows host job took 387 seconds. These are CI workflow measurements,
excluding queue time, and do not measure the full Android/Direct matrix.

The first local boundary run took 19.20 seconds (7.63 seconds executing five
tests); the request/parser/session corpus took 3.00 seconds. These are local
Windows samples, not a prediction for CI. The new fast gate records fresh wall
time so integrated CI can quantify the change. Dependency selection narrows only
isolated boundary/test changes to their actual policy and verification consumers.
Production, Android, workflow, tooling, mixed, manual and release changes retain
the conservative full matrix. No required final evidence is removed.

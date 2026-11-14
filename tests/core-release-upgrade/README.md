# Published 0.9.66 release byte intake

`scripts/stage_core_release_baseline.py` checks explicitly supplied local
release files. It reads no network data and installs nothing. Supply the retained
public release metadata snapshot and a directory containing exactly these four
files: `Mesh-Chat_0.9.66_x64-setup.exe`,
`Mesh-Chat_0.9.66_x64_en-US.msi`,
`mesh-chat-0.9.66-android-arm64-release.apk`, and `SHA256SUMS.txt`.

```sh
python scripts/stage_core_release_baseline.py \
  --release-metadata tests/core-release-upgrade/release-metadata.json \
  --assets-dir <local-release-assets-directory> \
  --output <retained-report.json>
```

The validator requires the annotated `v0.9.66` tag object
`964848e68ed54ceffcbbb8b4a2355f46995e2efa`, source commit
`7c40f7b23eab3e9d83ff7ca1075c90c4d84ce516`, and tree
`96daefa74c38a5cfd7863e37e3effcb7a06dc6cd`. The pinned metadata
snapshot hashes to
`3543c26f91da885de97cd7389185e637abbf35e99863ccb1bc3d98f344685981`;
its retained checksum text hashes to
`6306c25b130e10287b857829a29a6ea9b4dbfa27acaa9c1a25550e95345410a4`.
The script checks release and asset IDs, sizes, SHA-256 digests, exact directory
inventory, and the checksum text. A failed input produces a bounded failure
report without private local paths. An output path that overlaps the metadata,
asset directory, or pinned fixture is rejected on stdout without writing a
report.

The old SDK component rebuild fixture in `tests/core-sdk-upgrade/` remains
separate. Its source commit is
`174728edad62aae6ef16e95b075183d06c5cdda3` and cannot qualify as
the published release source. A passing byte intake reports only
`published_release_byte_intake_only`. It establishes no native upgrade,
installed Windows/Android pair, physical-device identity, or support window.
The committed metadata is a retained snapshot of the public release record;
the binaries themselves must be supplied locally for any passing intake.

## Windows installed-app UI contract and disposable controller

`windows-ui-execution-manifest.json` records the actual released MSI and NSIS
identity and the unresolved installed whole-app switch. Candidate installer and
installed-file hashes are intentionally null in this static contract; actual
execution reports retain the exact candidate binding and observed bytes.
The released MSI is machine-scope WiX, defaults to `ProgramFiles64Folder/Mesh Chat`,
and has a selectable `INSTALLDIR`; it installs `mesh-chat.exe` and
`mesh-chat-service.exe` together. The published NSIS archive lists the same
launcher and sidecar. The existing R5 guarded NSIS launcher in
`scripts/run_packaged_media_preflight.py` and loopback CDP driver in
`scripts/packaged_call_gui.mjs` provide reusable installation and UI boundaries.
Neither installer has been run for this contract. Both the released and current
candidate app versions are `0.9.66`, so installer replacement semantics remain
unproven. The MSI has a WebView2 download action when that runtime is absent;
the disposable runner positively preflights WebView2 before installation.

`scripts/check_windows_release_ui.mjs` is the separate bounded CDP seed/readback
contract. The Windows-only orchestrator launches the exact installed app
with a fresh loopback WebView2 debugging port and feed one JSON object on stdin:

```json
{"phase":"seed","expected_source":"7c40f7b23eab3e9d83ff7ca1075c90c4d84ce516","expected_version":"0.9.66","workspace_name":"R8 CI space 001","message_text":"R8 CI message 001","draft_text":"R8 CI draft 001"}
```

Run `node scripts/check_windows_release_ui.mjs <port>` with Node 22+ and the
object above on stdin. The seed phase requires a fresh app snapshot, then uses
CDP mouse and keyboard input on visible onboarding, workspace and composer
controls. It creates one synthetic profile, a sole-owner workspace, one message
and one saved draft. It calls only the app-origin read-only `snapshot` and
`list_workspace_messages` service commands for readback; `app_build_info`
checks the installed source/version. The success result contains SHA-256 hashes
of the profile destination, workspace and channel IDs, message ID/text and
draft text. It contains no raw key, snapshot, text or path. The candidate
`observe` phase takes the same marker strings and its exact source commit;
it makes no mutation. Run it once when the candidate first opens and again
after a clean candidate close/reopen. Compare the three bounded reports with
`node scripts/check_windows_release_ui_reports.mjs <seed.json> <observe.json> <reopen.json> <candidate-source>`.
Stdin is capped at 2 KiB and must reach EOF within five seconds. CDP frames
are capped at 64 KiB before parsing; command deadlines clear on completion.
The driver reports success only after its CDP socket closes. On uncertain
socket retirement it emits a fixed failure and the owning runner must retain
custody of the app and report the failure.

The driver does not install, launch or retire either application, inspect EFS,
or establish an installed upgrade. `scripts/run_windows_release_continuity.py`
owns those operations on a fresh GitHub Windows runner and retains bounded
binary, UI hash, process cleanup and fixed failure evidence. It first proves fresh
GitHub Windows runner app-data and OS credential state, exact published and
candidate installed bytes, EFS, and complete old app/sidecar retirement before
switching whole installations. It must confirm a clean candidate reopen and
retirement. Until same-version installer behavior is proven, the execution
manifest stays at `contract_only_switch_unproven` and every installed upgrade,
peer receipt, schema refusal, physical-device and full R8 claim remains false.

The `windows-release-continuity-r8.yml` workflow runs manually or when its own
file changes on `codex/mesh-core-restart-diagnostic`. It builds an exact-source
candidate and downloads the pinned published installer, then attempts the
same-version replacement. An unchanged/mixed installation or uncertain
retirement fails the run. It executes installers only on the disposable runner;
the local custody tests use controlled substitutes. A successful continuity
diagnostic is narrower than a supported version upgrade or full R8 acceptance.

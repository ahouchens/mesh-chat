# Windows packaged media preflight

Run `packaged_media_preflight.py` on a fresh interactive Windows user after the
exact release candidate is installed. Supply the installed `mesh-chat.exe`, the
same candidate's published `manifest.json`, the passed desktop build report from
`scripts/release.py build`, both independently retained SHA-256 digests, the
expected source commit/tree, and the CI run ID/attempt. Use Node 24 or newer for
the WebView2 DevTools probe. The runner writes
`dist/reports/packaged-media-preflight.json` even when a check fails.
The run ID and attempt must match `GITHUB_RUN_ID` and `GITHUB_RUN_ATTEMPT` in
the executing job.

The runner checks the clean source commit/tree, the delivery report's clean
source commit and desktop manifest/app/sidecar hashes, the installed app and
sidecar bytes against that manifest, and that neither Tauri app-data directory exists
for the current Windows user. It does not delete app data. It launches one normal
app process, attaches to that process's WebView2 through a fresh loopback DevTools
port, checks the app's embedded source through the public `app_build_info` command,
and exercises real `getUserMedia` audio capture and track/peer closure with
WebView2's virtual device flags. The result contains only bounded boolean checks,
hashes, source/run binding, and a failure phase. After the probe it rechecks source,
both provenance files, installed binaries and driver bytes, then retires the app
and requires the DevTools port to close. The CI route must supply the two expected
digests from its exact-run artifact index; the runner does not infer them from a
release manifest.

This is a prerequisite, not INV17/SC17 coexistence evidence. The remaining test
needs an independent authorized Core peer: `src-tauri/src/lib.rs` enables Tauri
single-instance behavior, so two same-identity app GUIs cannot stand in for two
peers. The next runner must drive the actual `src/App.tsx` pairing and
`src/CallDialog.tsx` start/answer/hangup UI through public Core flows, provide a
real media answerer on that independent peer, and verify authenticated message
receipts and the same adopted native carrier before, during, and after the call.
The existing `scripts/check_independent_core_pairing.py` offers public pairing
and receipt fixture logic; it does not currently connect an installed app GUI or
answer a media call. No private native qualification command should be used as
the app's messaging path.

The virtual capture device exercises WebView2's real media engine without a
physical microphone. Android installed-app behavior, video, call failure and
reconnect, and physical device capture need separate evidence.

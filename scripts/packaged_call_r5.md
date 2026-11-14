# Installed Windows call and public SDK peer diagnostic

This is an R5 diagnostic workflow, not a release qualification result. It has
not run in CI yet. A successful local syntax check does not prove that Edge,
WebView2, the relay, or two runners can complete this scenario.

The workflow builds one exact-source NSIS candidate after CI verification. The
GUI role installs it, runs the existing seven-check real WebView2 audio capture
preflight, and relaunches that installation. Its driver sends CDP mouse and
keyboard events to visible UI controls. Page evaluation reads DOM state and
the Tauri `app_build_info` identity only. It does not call Core mutations or
replace `getUserMedia`, `RTCPeerConnection`, or Tauri product flow.

The peer role stages the ordinary application-owned Windows host and public
TypeScript SDK from exact-source producer artifacts. The consumer admits only
the public call ICE, media query, and control operations added for this case.
An isolated Edge page owns a real captured audio track and WebRTC peer
connection. It receives an incoming offer through the public SDK, creates an
answer, and returns the SDP through a bounded local pipe. It never receives
the Core grant or host pipe.

The two roles exchange only a sealed pairing code and fixed acknowledgments
through same-run Actions artifacts. Product messages, SDP, media, private keys,
and receipts stay on the runners. Reports contain message SHA-256 values and
fixed counters rather than message text or pairing material.

The positive case requires visible signed pairing and consent, an approved
contact, two-way delivered messages before the call, GUI Call and Audio call
clicks, a real peer answer with positive incoming and outgoing RTP audio
packets, a peer-to-GUI delivered message during the modal call, GUI Hang up,
and two-way delivered messages afterward. The CallDialog modal prevents the
GUI user from composing a message during the call; this case makes no such
claim. The public Core connection snapshot exposes readiness, carrier state,
runtime epoch, and sequence. It does not expose physical carrier identity, so
the report cannot prove the exact same native resource throughout.

App, browser, host, DevTools socket, policy value, exchange, exact source,
and installed bytes must close or remain unchanged for a positive result.
The disposable runner retains reports. A failed run is diagnostic evidence,
not acceptance.

`.github/workflows/packaged-call-r5.yml` is a standalone diagnostic. It launches
on a push to `codex/mesh-core-restart-diagnostic` that changes this workflow file,
which allows its first run before default-branch registration. Manual dispatch
is retained. Source-only pushes without that workflow change do not launch it.
It runs exact-source CI verification and producers before building the NSIS
candidate or starting the two roles. Calling it from `ci.yml` as written
would recursively invoke CI. No `ci.yml` change is included in this candidate.

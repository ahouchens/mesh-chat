# Mesh Core R0 baseline reference

Status: **unresolved** as of 2026-11-13. The available records do not identify an exact historical `main` commit and artifact pair that was physically verified as a working Windows/Android product. Do not use the current `main` tip or a Mesh Core refactor build as that baseline.

## Provenance and confidence

| Evidence | What it establishes | Limit |
| --- | --- | --- |
| `TESTING.md`, “Recorded 0.2.7 desktop-reply concurrency verification” (lines 4748–4763) | A physical 0.2.6 Windows/Android run delivered the phone's first direct message to the desktop. Process inspection in a later attempted retest identified the running Windows `mesh-chat.exe` as version 0.2.6, SHA-256 `42A320E157B2C2743CA87127E00E8BB1E55E6C2DE8C7F80D9434307933908DCA`, and its sidecar as SHA-256 `9901F7844739DABA0D0FF37B298A108C91B0305B504DE99C43AC9025D4EE4107`. The release table also records the 0.2.6 Android debug APK SHA-256 `C67159232A3F45628F039E97E67914A47487C36BFE6B0ABB0C18EF4DD0441D44`. | The desktop reply failed in the physical run. The record does not establish that the APK's bytes were inspected on the phone, nor identify the source commit used to build the binaries. This is a partially successful, **failed** candidate, not a working baseline. Confidence: high for the recorded behavior and Windows process hashes; low for APK-on-device byte identity. |
| `TESTING.md`, 0.2.4–0.2.6 physical-run sections (lines 4550–4682) | The preceding physical runs reached approval on the prior release, connected peers on 0.2.4 but did not show the first chat, and completed invitation/acceptance on 0.2.5 but did not deliver the phone's chat. | None proves a complete bidirectional conversation. Confidence: high for the documented outcomes. |
| `TESTING.md`, 0.2.7 package section (lines 4835–4858) | 0.2.7 packages were built and inspected. | The exact 0.2.7 pair was explicitly awaiting a physical reply retest. Confidence: high. |
| `git log main`, `git blame TESTING.md`, and local tags | The current local `main` tip is `7c40f7b23eab3e9d83ff7ca1075c90c4d84ce516` (0.9.66). The 0.2.6 physical-run account entered this repository in the 2026-10-06 import commit `428986596da6f146287a453ab3908863896e1e0b`. | The import commit is the **documentation provenance**, not the 0.2.6 build source. The local history and tags do not bind a physically successful later build to a historical `main` SHA. Confidence: high for the Git provenance; unresolved for the requested build identity. |

The Mesh Core restart handoff states that the last physically verified product came from `main`, but names no commit or artifact. This assertion is a lead for further investigation, not sufficient provenance to promote a particular SHA. Its R0 roadmap likewise says the exact verified artifact remains unidentified.

## Comparison scope after the reference is found

Compare the historical product and integrated Mesh Core on the user-visible flows that share the changed boundary: desktop Tauri/WebView2 and Android UI profile selection/unlock, invitation and approval, direct and workspace messages and authenticated receipts, reconnect and restart, and conversation state. Include audio/video call start, end, failure, dialog closure, navigation, and message delivery while a call is active, because the UI, media signaling, permissions, and packaging remain part of the product. The headless native Windows messaging peer exercises transport and core behavior only; its success cannot certify WebView2 UI or media coexistence. Physical device qualification remains a separate gate from local/CI and emulator results.

## Evidence searched and next step

Searched `TESTING.md`, `README.md`, `docs/RELEASES.md`, the Mesh Core coordination/qualification/roadmap documents, the restart handoff and remaining-work roadmap, the local `main` history/tags/blame, and the parallel-worker reports. The available records establish failed or partial physical runs and many automated/package results, but no exact *working* physical baseline. Obtain the successful run's date/version, installed Windows and Android artifact hashes or immutable release URLs, and the source SHA or build provenance that binds those artifacts to historical `main`. Verify the claimed flows against that record before naming a regression baseline.

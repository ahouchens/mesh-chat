# Android “prepare reply” failure device check

Status: source fix and diagnostic fields implemented on
`codex/android-reply-diagnostics` for a **0.2.64 / Android 2064** test build.
No 0.2.64 package has been built or installed here, and no physical
Windows↔Android result is claimed.

## Why a distinct test build

The installed 0.2.63 build reports only that an action failed. Its
`last_failure` row has `attempt: b23a6a8439c0` (SHA-256 of `"unknown"`) and no
command, error code, failure stage, saved-workspace reason, or workspace state.
That evidence cannot distinguish:

- a different invitation for an already-saved workspace;
- a workspace that is already active or has a stopped/expired request;
- expiry between preview and preparation;
- native socket preparation/arming failure or a closed native channel; or
- persistence failure after the join or reply was saved.

The 0.2.64 test build records those allowlisted fields and routes the saved-
workspace cases to a real next action instead of the former generic error. It is
a test candidate, not a release, and its build must come from GitHub Actions as
described in [TESTING.md](../TESTING.md). Dispatch the **Release build** workflow
for this branch with version `0.2.64` (or tag `v0.2.64`); do not reuse a 0.2.63
package because it lacks these fields.

## What the build changes

- `preview_direct_connection` now returns read-only `existing_workspace`
  evidence: saved workspace id/name/state, whether the exact saved join request
  can continue, and an allowlisted reason when it cannot.
- `prepare_direct_answer` refuses a different invitation or a workspace that is
  no longer `joining` with `workspace_already_known` and a specific reason. It
  never replaces, clears, or re-signs the saved request.
- A matching invitation still prepares a newer Answer generation and keeps the
  same saved join delivery, device identity, and receipt.
- A closed native channel now reports `native_unavailable` at the
  `runtime_check` stage instead of an ambiguous `invalid_request` later.
- Diagnostics add `failure_reason`, `workspace_state`, and up to 12 recent
  events to a summary copy. Reports still exclude invitation text, addresses,
  identities, and messages.

## Device procedure (preserve data)

1. Build and install the 0.2.64 / Android 2064 test APK **over** the existing app
   without uninstalling it or clearing app data. Do not create a new workspace
   or invitation for this check.
2. Confirm **Settings → Help and diagnostics** reports 0.2.64 and versionCode
   2064. Keep the 0.2.64 Windows build available for the owner side if a reply
   must be prepared.
3. Open the affected saved workspace (or **Join or connect**) and repeat the
   same next step that previously showed “These details could not start the next
   step.” The received message is already saved; do not paste a replacement
   unless the UI explicitly asks for a different invitation.
4. Immediately choose **Copy diagnostics** and keep the text. Then copy
   **Settings → Help and diagnostics → Copy connection log**.
5. Record whether the screen now offers **Open saved workspace**, a working
   retry, or a distinct restart-native-service message.

## Reading the result

| `last_failure` fields | Meaning |
| --- | --- |
| `command: prepare_direct_answer`, `error_code: workspace_already_known`, `failure_reason: invitation_mismatch`, `workspace_state: joining` | Confirmed: a different invitation was offered for a saved join request. The UI should offer the saved workspace and explain that the owner must refresh the **original** invitation. |
| `error_code: workspace_already_known`, `failure_reason: workspace_active` | The workspace already joined on this device. Open it instead of preparing another reply. |
| `error_code: workspace_already_known`, `failure_reason: request_stopped` / `request_expired` | The saved request is terminal. Open the saved workspace; using a new invitation requires an explicit local removal first. |
| `error_code: native_unavailable`, `failure_stage: runtime_check` | The on-device native channel was already closed (for example after a timeout). Reopen Mesh Chat; the saved request remains. Report the preceding event if one is present. |
| `error_code: invalid_request`, `failure_stage: prepare_candidates` or `arm_socket` | Native preparation/arming or persistence failed before a setup result. Capture the full log; this is the remaining ambiguity this build narrows. |
| `error_code: invitation_expired`, `failure_stage: document_verification` | More than the short Offer window elapsed between preview and preparation. No membership or request change occurred. |
| `error_code: internal_error`, `failure_stage: save_join_request` or `save_reply` | Protected-storage or persistence failure. The saved workspace and request are unchanged; capture storage status. |

## What this check does not prove

It does not prove Windows-to-Android reachability, NAT traversal, firewall
permission, or that a connection succeeded. It identifies which local
preparation path failed and whether the saved-workspace recovery reached the UI.
A successful connection still requires the full
[carrier acceptance procedure](DIRECT_CONNECTIVITY_TRAVERSAL_DEVICE_TEST.md).

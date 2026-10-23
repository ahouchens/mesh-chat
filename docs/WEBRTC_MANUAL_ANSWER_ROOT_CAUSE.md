# WebRTC manual-answer failure: reproduced cause and fix

Date: 2026-10-23. Investigated against `main` at `4ad3115` (0.9.29).
Status: reproduced and fixed in a real Edge 155 browser with Cloudflare TURN;
the packaged Windows-to-Android physical retest remains pending.

## Cause

The answerer starts ICE when it applies the offer and creates its answer. The
offerer does not yet know the answerer's relay address. TURN permissions restrict
incoming traffic to known peer addresses, so the answerer's early checks can
receive no reply while the answer is being gathered, signed, copied, and pasted.
See [RFC 8656 section 3.3](https://www.rfc-editor.org/rfc/rfc8656.html#section-3.3).

The application treated the answerer's first native `failed` state as permanent:
`watchPeer` called `reportFailure`, which captured diagnostics and immediately
called `cleanup`. That closed the peer connection and its TURN allocations while
the UI was still asking the user to return the signed answer. The offerer then
received a valid SDP advertising relay endpoints that the app had already closed.

This is a signaling-lifecycle bug, not evidence that Windows cannot offer a
DataChannel. Reversing roles can change transfer timing and therefore appear to
fix it. The supplied physical results show Android failing about 34–36 seconds
before Windows in tests 3–5, consistent with this sequence. Those snapshots alone
cannot prove the exact timing of the original physical attempts.
The tester subsequently confirmed that the answer was copied and pasted manually,
with more than 15 seconds between Android creating it and Windows pressing Connect.

## Why the earlier diagnosis was misleading

An empty final `pairs` array is not a history of the ICE attempt. Chromium deletes
timed-out pairs, and emits remote-candidate stats from surviving connections.
Local relay candidates can remain visible after all pairs disappear.
[libwebrtc transport implementation](https://chromium.googlesource.com/external/webrtc/+/refs/heads/master/p2p/base/p2p_transport_channel.cc)

The reproduction observed many live relay pairs before failure, followed by the
same failure snapshot in the attachment: `connectionState: failed`,
`iceConnectionState: disconnected`, no remote candidate stats, no pairs, and
DTLS still `new`. Adding `a=end-of-candidates` cannot fix a prematurely closed
answerer. The tested SDP already included that marker.

## Controlled browser evidence

Both peers ran in real Edge 155 on Windows, with `iceTransportPolicy: relay` and
credentials from the application's existing Cloudflare broker. Only answer
delivery timing and answerer teardown policy changed. The maintained harness
also verifies an echoed DataChannel payload, not just a connection-state flag.

| Experiment | Observation | Result |
| --- | --- | --- |
| Immediate answer | Answer applied at 1.050 s; channel opened at 1.310 s | Connected; payload echoed |
| Answer delayed 45 s, old cleanup | Answerer failed at 22.171 s and closed; answer applied at 46.002 s; offerer failed at 67.990 s | Failed |
| Answer delayed 45 s, preserved answerer | Same initial failure at 22.171 s; answer applied at 46.050 s; channel opened at 46.314 s | Recovered; payload echoed |
| Answer delayed 90 s, preserved answerer | Answerer failed at 22.302 s; answer applied at 91.026 s; channel opened at 91.339 s | Recovered |

Times are elapsed from each trial's start. They are observations, not universal
browser timeout constants. The 90-second experiment was a separate exploratory
run; the maintained harness covers the three immediate/45-second comparisons.

Reproduction: [manual_answer_browser.mjs](../experiments/webrtc-call/manual_answer_browser.mjs).
Setup and command: [experiment README](../experiments/webrtc-call/README.md).
Compact redacted evidence: [browser results](benchmarks/webrtc-manual-answer-20261023.json).
The harness requires an explicitly supplied broker and makes real TURN allocations.

## Fix

- Retain the initial answerer through native ICE failure for up to 120 seconds
  from offer application, capped by the signed offer's expiry. This includes
  candidate gathering and answer transfer. Late incoming checks can recover the
  existing ICE transport, as demonstrated above.
- Stop that timer when the DataChannel opens. An unanswered attempt eventually
  closes and reports `answer-exchange-timeout` with instructions for returning
  the answer. Offerer failures retain their existing handling.
- Keep callbacks and asynchronous work tied to the peer that created them.
  Cancelled or superseded attempts cannot publish an answer or close a new peer;
  duplicate open notifications attach only one Reticulum bridge.
- Preserve a bounded, redacted timeline, including earlier pair counts and
  signaling events. Diagnostics no longer depend solely on the final snapshot.

The signed document format, trust checks, TURN configuration, and contact approval
protocol are unchanged. Release 0.9.30 packages this fix through GitHub Actions;
publication status is recorded in [TESTING.md](../TESTING.md).

## Validation and remaining physical check

Frontend regression tests cover delayed recovery, failure during gathering,
the 120-second deadline, signed expiry, immediate offerer failure, cancellation,
retry isolation, one bridge attachment, and diagnostic timer cleanup/redaction.
The full frontend suite, TypeScript check, and production bundle passed.

Install matching builds containing this patch on Windows and Android. With
Windows offering and relay-only enabled, test an immediate answer and deliberate
45- and 90-second answer delays. Keep both apps open. Repeat Android on Wi-Fi
and cellular, and verify the Reticulum contact invitation arrives. Also omit an
answer once to verify the bounded timeout. Save diagnostics if the physical
result differs; the timeline will distinguish failed checks from missing pairs.

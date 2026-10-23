# WebRTC diagnostics

The **Copy diagnostics** action in the WebRTC onboarding dialog emits a JSON
snapshot and recent event history used for connection debugging. It deliberately
contains no raw candidate IP addresses, TURN usernames, TURN credentials, ICE
passwords, or SDP bodies.

## Fields

- `environment` — browser/WebView user agent, platform, and language. This
  distinguishes Windows WebView2 from Android WebView.
- `signalingState`, `connectionState`, `iceConnectionState`,
  `iceGatheringState`, and `canTrickleIceCandidates`.
- `localDescriptionType` / `remoteDescriptionType`.
- `iceConfiguration` — transport policy, counts, sanitized ICE server URLs
  (scheme, host, port, transport), and whether any credential was supplied.
- `localSdp` / `remoteSdp` — candidate count, candidate types, protocols,
  address families, TCP types, and whether `a=end-of-candidates` was present.
  Their `structure` object records the media lines, BUNDLE group, MID values,
  ICE ufrag values, ICE password lengths (never the password), setup role, and
  ICE options.
- `candidates` — each local and remote candidate's type, protocol, relay
  protocol, address family, port, network type, and sanitized TURN URL.
- `pairs` — currently reported candidate pairs with state, nomination, byte
  counters, request counters, and resolved local/remote candidate summaries.
- `selectedPair` — the nominated or selected pair used for the transport.
- `pairStates` — counts by candidate-pair state.
- `transports` — ICE/DTLS role and state for each transport.
- `dataChannel` and `sctp` — state and byte/message counters.
- `timeline` — up to 100 records containing `elapsedMs`, an event label, and
  connection, ICE, gathering, and signaling states. State changes, candidate
  events, and application milestones trigger samples; stats are also sampled
  every second. Stats records include pair count, remote-candidate count,
  `pairStates`, and totals for `requestsSent` / `responsesReceived`.
  Creation and the first observed nonempty pair sample are retained alongside
  recent records. These counters describe each sample, not lifetime totals.
  Candidate events record only candidate type; candidate errors record only
  the numeric error code and sanitized ICE URL. The timeline excludes SDP,
  candidate addresses, ICE ufrags, passwords, and browser error text.

## What the common failures mean

- `candidateTypes` contains only `local:relay` and no `remote:relay`:
  no remote relay candidate is reported in this snapshot. Compare `remoteSdp`
  and the timeline; this does not prove that the remote side omitted candidates
  or that ICE never installed them.
- `pairStates` is empty: no pairs survive in this snapshot. Chromium can delete
  timed-out pairs before signaling failure. An earlier timeline sample with
  `stats.pairs > 0` proves pairing occurred; an empty history cannot prove it
  never occurred between samples.
- `pairStates` contains `failed` / `in-progress` but no `succeeded`:
  pairs exist but have not succeeded in this snapshot. Check request/response
  counters, answer delivery timing, TURN permissions, and network reachability.
- `iceConfiguration.urls` shows different TURN hosts or transports on the two
  devices: this is supported. Peers may use different TURN servers, and their
  client-to-server transports need not match. Compare the selected candidates
  and connectivity checks rather than requiring matching server lists.
- Either selected candidate has type `relay`: the path is relayed. A `host`
  candidate alone does not establish a direct path if the other candidate is a
  relay.

Chromium's [statistics collector](https://webrtc.googlesource.com/src/+/refs/heads/main/pc/rtc_stats_collector.cc)
reports remote candidates through current candidate pairs. Its
[ICE transport](https://chromium.googlesource.com/external/webrtc/+/refs/heads/master/p2p/base/p2p_transport_channel.cc)
removes timed-out pairs, so a failure snapshot is not a history of attempted
connections.

## Manual answer exchange

The answerer can start ICE checks before the offerer receives its answer. With
TURN, the offerer needs the remote endpoint to establish permission for incoming
traffic; an allocation alone does not grant permission.
[RFC 8656, section 3.3](https://www.rfc-editor.org/rfc/rfc8656.html#section-3.3)
describes this filtering.

During initial answer exchange, the dialog now retains the answerer's peer
connection after an ICE failure for up to 120 seconds from starting the answer,
capped by offer expiry. The timeline records
`ice-failed-awaiting-answer-exchange`. If no DataChannel opens before the
deadline, diagnostics report `answer-exchange-timeout` and the connection is
closed. This allows late offerer checks a chance to recover; it does not extend
the signed invitation's validity. Keep both windows open and return the answer
promptly. Confirmation on the reported Windows/Android devices remains pending.

Diagnostics are remembered for the global WebRTC banner and can also be copied
from the error state. The failure path captures the snapshot before closing the
peer connection. This preserves available state, but browser cleanup may already
have removed failed pairs; use the timeline to inspect earlier observations.

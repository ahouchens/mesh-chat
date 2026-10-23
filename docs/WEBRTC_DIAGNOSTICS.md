# WebRTC diagnostics

The **Copy diagnostics** action in the WebRTC onboarding dialog emits a JSON
snapshot used for connection debugging. It deliberately contains no raw IP
addresses, TURN usernames, TURN credentials, ICE passwords, or SDP bodies.

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
- `candidates` — each local and remote candidate's type, protocol, relay
  protocol, address family, port, network type, and sanitized TURN URL.
- `pairs` — every candidate pair with state, nomination, byte counters, request
  counters, and resolved local/remote candidate summaries.
- `selectedPair` — the nominated or selected pair used for the transport.
- `pairStates` — counts by candidate-pair state.
- `transports` — ICE/DTLS role and state for each transport.
- `dataChannel` and `sctp` — state and byte/message counters.

## What the common failures mean

- `candidateTypes` contains only `local:relay` and no `remote:relay`:
  the remote side did not advertise a usable relay candidate.
- `candidateTypes` contains both sides' relay candidates but `pairStates` is
  empty: ICE did not create pairs; capture diagnostics before closing the peer
  connection or inspect the SDP candidate summaries.
- `pairStates` contains `failed` / `in-progress` but no `succeeded`:
  ICE ran but the relay path could not carry checks. Check TURN relay ports,
  transport, and the two devices' network paths.
- `iceConfiguration.urls` shows different TURN hosts or transports on the two
  devices: they are not using a common relay path.
- `selectedPair.local/remote.candidateType` is `relay`: the path is relayed.
  `host` indicates a direct path.

Diagnostics are remembered for the global WebRTC banner and can also be copied
from the error state. The failure path captures the snapshot before closing the
peer connection so candidate-pair state is not lost.

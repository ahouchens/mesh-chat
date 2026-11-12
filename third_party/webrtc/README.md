# Selected TURN/TCP outer socket prototype

`patches/selected-turn-socket.patch` is an isolated, unintegrated patch against
`webrtc-sdk/webrtc` commit `73cb8180f7258ee292878d6edd05177f41883962`
(the WebRTC 150 source selected for this investigation). It is kept as a
reviewable source diff; this repository does not build or replace a WebRTC AAR
with it.

The patch reads the *current* socket owned by a ready, nonshared, direct TCP
`TurnPort`. It returns a value containing that socket's local and remote
`SocketAddress` values after a network-thread check. It rejects unspecified,
unresolved, or zero-port endpoints. Other ports return no value. It does not
cache the addresses, so a closed or replaced socket cannot yield an earlier
tuple. The patch declares the new header and its dependencies in `p2p/BUILD.gn`.

`P2PTransportChannel::GetStatsForQualification` is the explicit network-thread
entry point. It copies the tuple only onto the currently selected connection's
`ConnectionInfo`. Ordinary `GetStats` calls the same collection loop with
capture disabled, leaving the new field empty for every connection. No
`RTCStats`, JSON, log, JNI, or application API is added.

The C++ test diff covers live TURN/TCP value equality with the underlying
socket, UDP and pre-allocation absence, closure and allocation replacement,
and a three-connection channel snapshot. The channel test selects the TCP
connection, checks the opt-in tuple and ordinary stats absence, then selects
another connection and checks the tuple disappears from the snapshot.

To inspect against the pinned source checkout:

```sh
cd /path/to/webrtc-at-73cb8180f7258ee292878d6edd05177f41883962
git apply --check /path/to/this-repo/third_party/webrtc/patches/selected-turn-socket.patch
```

The patch was checked for clean application and whitespace against the fetched
pinned source subset. A native WebRTC build and the C++ tests have **not** run;
the patch is a prototype, not a qualified binary. Production integration
still needs an explicitly trusted collector/JNI delivery path and review of
all serialization boundaries. Selection revisions, socket revisions, and
continuity guarantees are not implemented here; consumers must not infer that
an old snapshot still describes the active socket.

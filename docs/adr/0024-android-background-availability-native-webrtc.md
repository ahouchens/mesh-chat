# 0024: Opt-in Android availability service with native WebRTC

Status: accepted. Narrows ADR 0014's blanket rejection of Android foreground
services to one explicit, user-enabled availability mode. Supersedes the
WebView-owned DataChannel assumption for Android onboarding and automatic
reconnect; desktop and iOS keep the renderer peer.

## Decision

1. Add an explicit, off-by-default **Stay available in background** mode. Plain
   closing, explicit lock, consent removal, or disabling the mode stops it.
2. Use one `remoteMessaging` foreground service in the existing app process. Do
   not create a second Python process, copy identity keys, or start a second
   Reticulum/LXMF runtime.
3. Move Android DataChannel ownership to a native `PeerConnection` in
   `NativeWebRtcHost`. The WebView remains the UI and the owner of calls. Native
   onboarding and automatic reconnect use the signed SDP documents unchanged.
4. Attach the existing Python `WebRTCInterface` to the native DataChannel. The
   service keeps a partial wake lock and a high-performance Wi-Fi lock, and
   releases both when the mode stops.
5. Run a bounded Python reconnect supervisor while the app is not in the
   foreground. It uses the existing signed mailbox request/offer/answer flow,
   native SDP creation, and the same consent/capability checks as the renderer.
   It does not invent a new wire format or a new trust decision.
6. Use a persistent, generic notification and a Stop action. Do not claim that
   Doze, process death, force-stop, or an OEM killer preserves a live DTLS
   session. After process death the supervisor establishes a **new** native
   session; an old session is never resumed.
7. Gate the native SDK on 16 KB page-size alignment, release APK size, and
   third-party notices. If those gates fail, disable the native path rather than
   falling back to a WebView claim.

## Consequences

- Android onboarding and automatic reconnect now create native DataChannels;
  calls remain on the WebView + `CallService` path.
- Background execution is opt-in and visibly stops on lock. Locking releases the
  service, native sessions, and Python keys.
- The app is larger and carries the libwebrtc BSD notice.
- Physical Doze, network-switch, process-death restoration, battery, and
  Windows↔Android interoperability remain qualification gates; compilation is
  not device evidence.
- FGS type acceptance by the Play policy remains a review gate. `remoteMessaging`
  is the primary type; `specialUse` is the fallback if review rejects it.

## References

- [Android background availability spec](../ANDROID_BACKGROUND_AVAILABILITY_SPEC.md)
- [ADR 0014](0014-android-native-connectivity.md)
- [WebRTC 16 KB page guidance](https://developer.android.com/guide/practices/page-sizes)

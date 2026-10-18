# Phase 2 Windows and Android device evidence

Status: pending physical execution. Use the exact implementation SHA and package
hashes recorded in the [evidence record](DIRECT_CONNECTIVITY_PHASE2_EVIDENCE.md).
CI and simulated network results do not fill this record. Do not record full
connection documents, IP addresses, private handles, keys or message contents.

## Preparation

The tester installs the CI-built Windows and Android packages. Record the Actions
run, artifact names, SHA-256 package hashes, Windows version, Android version/model
and coarse network topology. Keep both apps open and unlocked. Use a test workspace
and two separate networks; disable nearby/LAN fallback for the isolated direct
case so its success cannot be attributed to a local route. Preserve existing data.

Android retires prepared sockets when its activity is stopped. Keep Mesh Chat
visible in split-screen while using email, or transfer documents through a second
device. A full-screen email app or file picker can stop Mesh Chat and invalidate
the retained reply socket; returning must show refresh rather than revive it.
This phase does not promise background setup. Record this usability limitation
and whether split-screen sharing/import works on the tested phone.

For a reachable-host case, Windows needs public IPv6 with permitted inbound UDP
or public IPv4 behind a router that supports the app's UDP mapping request.
Android may remain unhosted on cellular. Candidate preparation is not a successful
connection test. If both peers report no candidates, record that result and run
the fallback case; it does not satisfy the direct-path gate.

## Direct exchange

1. On Windows, create a test workspace invitation and choose **Prepare direct
   offer**. Copy or save the complete connection document and send it to Android.
2. On Android, import/paste it, choose **Review connection document**, then
   **Create connection reply**. Record whether a candidate was supplied. A reply
   with no public candidate must still be exportable.
3. Send the reply to Windows. Review it and choose **Create ready document**.
   Immediately send that document to Android, then choose **Use ready document**.
   Keep both apps in the foreground; the bounded attempt window is at most 60 s.
4. Confirm the owner sees the signed join request and Android sees acknowledgment.
   Approve it on Windows. Both devices must report the fresh direct workspace
   path, load `#general`, and exchange a test message and recipient receipt in
   each direction. A connecting status or endpoint alone is insufficient.
5. Repeat with Android as owner where its network supports hosting. Separately
   record public IPv4/UDP mapping and public IPv6 results where available; an
   unavailable topology is an unmet test, not a pass.

The production path re-inspects its socket/port/certificate after router work and
before signing, retains the Answer handle through Ready, and consumes that same
socket for activation. Successful physical execution of this guarded path supplies
device evidence alongside the native ownership substitution tests. Record any
ownership rejection as failure; never bypass validation or manually edit documents.

## Expiry and interrupted setup

1. Save an Offer or reply, wait beyond its displayed expiry, then import it. The
   app must reject it or require refresh without reporting a connected path.
2. Create a fresh Offer/reply. Close or suspend Android before importing Ready.
   Reopen it and import the old Ready: lost ownership must require a fresh exchange.
3. Exchange fresh documents and repeat admission/messages using a fresh test
   invitation where the original was already consumed. No old socket is restored.
4. Cancel an active setup, then separately remove the admitted test member. The
   direct path must retire and must not authorize further workspace traffic.

## Existing-route fallback

Use an existing authenticated TCP route in a separate test. When neither device
provides a direct candidate, finish the email exchange and verify the explicit
existing-routes status, ordinary signed join acknowledgment, owner approval,
messages and receipts through that route. With neither UDP nor TCP reachability,
the app must retain pending work and give an explicit refresh/fallback outcome;
it must not claim acknowledgment or membership from a document import.

## Result to return

For each case, record: timestamp, exact SHA/package hashes, coarse topology,
owner platform, candidate supplied yes/no, last setup state, join acknowledgment,
approval/channel result, bidirectional receipt result, expiry/restart/cancel result,
and pass/fail with a short sanitized observation. Missing topology or execution
evidence stays pending. Phase 2 is complete only after its exit gates are evidenced.

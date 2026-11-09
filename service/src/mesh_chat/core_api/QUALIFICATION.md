# Private packaged qualification control

Windows: launch the retained sidecar with sole flag
`--qualification-native-webrtc`. Use its existing private length-prefixed IPCv1
initialize envelope, with exact payload `profile_dir`, `vault_key` (base64),
`parent_pid`, `display_name` (literal `Mesh qualification`). The absolute profile
leaf must start `mesh-qualification-` under a controller-owned protected parent.
First boot requires a nonexistent leaf. After platform protection and successful
initialization, a local marker authenticates the path and a random nonce with
that vault key. Only the same marked path/key may reopen. An existing ordinary
vault, copied marker, wrong key or tampered marker fails before runtime startup.
Do not retain this key or marker in qualification artifacts.

Private commands are `qualification.inventory` with `{}` and
`qualification.path_evidence` with `{logical_session,expected_physical}`. Replies
use the existing IPC `{type:"response",id,ok,result|error}` envelope. The latter
calls the production inspector with exact current resource fencing. These names
are absent from public Core, native commands and ordinary sidecar dispatch.

Android: actual host-UID instrumentation first calls
`NativeWebRtcBridge.attach(context)`, then directly imports the packaged
`mesh_chat.core_api.qualification_host` via Chaquopy. `android_initialize(raw)`
accepts exact JSON `{profile_dir,vault_key,display_name:"Mesh qualification",platform:"android"}`.
`android_control(raw)` accepts exact `{command,payload}` using the names above.
Both return JSON `{ok,result|error:{code}}`, check actual Binder calling UID
against process UID, and are outside all renderer/Core/mobile-command routes.
Initialization refuses an existing live runtime; shutdown through the normal
trusted host path before reopening. Control is fenced to the exact initialized
mobile instance. Ordinary host replacement cannot inherit qualification access.

Inspectors enforce their production 2-second sample deadline and 16KiB bound.
Evidence is valid for 2000ms only. Recheck service/profile/adapter/resource epoch
and sample sequence; discard after resource or epoch changes. Selected ICE alone
does not prove readiness or delivery. Restrict raw endpoint tuples to transient
controller memory/fault correlation; export only categories, availability,
hashes and truthful counters. Never export SDP, credentials, bearer documents,
vault keys or raw addresses. Unit admission tests are not packaged OS evidence.

# Independent application runtime host

This experimental runtime is separate from the thin public Core SDK. The
installing application owns its process, data directory and lifetime. It never
attaches to the installed Mesh Chat application's profile. This interface does
not establish packaged interoperability or a supported release qualification.

## Windows

Install the frozen service runtime and a public SDK independently. Launch the
runtime with the single argument `--app-owned-native`. The trusted launcher
provides these environment variables to that child process:

| Variable | Required value |
| --- | --- |
| `MESH_CHAT_APP_DATA_DIRECTORY` | Absolute directory owned by the installing application |
| `MESH_CHAT_CORE_API_PIPE` | Unique local name matching `\\.\pipe\mesh-chat-[a-z0-9][a-z0-9._-]{0,63}` |
| `MESH_CHAT_CORE_API_CLIENT_IMAGE` | Exact absolute Windows executable image of the application's Core client |
| `MESH_CHAT_APP_PARENT_PID` | PID of the trusted launcher, distinct from the runtime process |

For a Node client, supply the actual installed `node.exe` executable image. A
script filename is not an executable image. The existing named-pipe adapter
checks the current Windows user and exact executable image, refuses remote
clients and existing pipe names, and admits at most two client sessions.

The runtime creates `mesh-core-runtime/profile-v1` beneath the owned directory.
It retrieves its independent 32-byte vault key from `runtime-key.dpapi` in the
`mesh-core-runtime` directory using current-user Windows DPAPI, with directory
binding. An exclusive `.runtime.lock` prevents two hosts from owning that
directory. Missing, invalid or mismatched keys never silently replace an
existing vault key. The existing VaultStore encrypted workspace requirement
also applies; unavailable EFS fails startup. No plaintext storage fallback is
available through this mode. DPAPI uses the
[Windows data-protection API](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata).

Start with stdin and stdout connected to dedicated inherited pipes. There is
no JSON initialization request and no vault key in command arguments, status or
SDK traffic. Stdout carries bounded UTF-8 JSON status frames with a four-byte
unsigned big-endian length prefix, using the existing service IPC framing:

```json
{"v":1,"type":"runtime_started","pipe":"\\\\.\\pipe\\mesh-chat-example"}
```

On startup or lifetime-input failure, the host emits
`{"v":1,"type":"runtime_failed","error":"<stable_code>"}` and exits with
status 2 after cleanup. A successful startup reports only the selected pipe;
it does not create an identity, approve a contact or configure signaling.

Keep stdin open throughout the runtime's lifetime. EOF requests normal shutdown.
Any nonempty input is invalid: this stream is not the legacy command dispatcher.
The host may emit `{"v":1,"type":"runtime_retiring"}` while it retains exact
native/store cleanup ownership. It emits `{"v":1,"type":"runtime_stopped"}`
only after those resources are retired and the directory lock is released.
A disconnected status reader cannot abandon cleanup. The existing exact-parent
watchdog remains active if the launcher exits.

Connect the installed SDK to the explicitly supplied named pipe. Core traffic
on that pipe uses the public Core SDK's newline-framed protocol, separately
from the inherited startup-status framing. The session receives host-fixed
owner grants and public profile bootstrap. It does not expose `native.command`,
qualification commands, renderer compatibility commands, keys or raw signaling.

The application first calls public `profile.create` with its own explicit
idempotency key. Later pairing, contact decisions, settings and message requests
must use the public operations actually advertised in `runtime.capabilities`.
Absent operations remain unsupported. The SDK never manufactures an owner grant,
replacement intent or retry key. Closing an SDK session detaches that client;
only the trusted launcher's inherited lifetime stream controls host shutdown.

The source equivalent, `python -m mesh_chat --app-owned-native`, is useful for
component development. It does not replace testing the separately installed
frozen runtime and SDK outside the checkout.

## Android

The separate runtime-host AAR and trusted application bootstrap are under
implementation. The client AAR alone is not an independently usable host.
Do not substitute a qualification initializer or seeded test service for normal
application startup. The original Mesh Chat Keystore profile slot remains
unchanged.

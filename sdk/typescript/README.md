# Experimental TypeScript client

`@mesh-chat/core-client@0.3.0-experimental` is an unpublished, private package
for Node 22+. It implements public Core API major 1, accepts additive minors,
and rejects another major before issuing a domain command. `./node` provides
bounded inherited-stdio and explicitly selected local Windows pipe adapters.
The host authenticates callers; importing the SDK grants no authority.

The package contains protocol code and the MIT license, with no runtime,
vault, native implementation or third-party runtime dependency. It never opens
or owns a vault, data directory or key. `close()` detaches only this client;
`stop()` is a separate owner request. Profile export, key export and uninstall
erasure are not guarantees of this package.

```js
import { CoreClient } from "@mesh-chat/core-client";
import { connectNamedPipe } from "@mesh-chat/core-client/node";
const client = await CoreClient.open(await connectNamedPipe(hostSuppliedPipe));
const profile = await client.profileQuery(client.capabilities.profiles[0]);
client.close();
```

Requests are serialized and have a 30-second default deadline covering writes
and reads. `request` accepts a finite `timeoutMs` (1..3600000) and `AbortSignal`;
`CoreClient.open` accepts `requestTimeoutMs`. Pipe connection has a separate
10-second default deadline. Timeout, cancellation after dispatch, malformed
reply or lost stream closes the client so late replies cannot shift correlation.
A failed mutation can already be committed. Reconnect and explicitly resolve
its durable identity; the SDK never retries or invents keys.

`createProfile`, `workspaceJoin` and `workspaceAdmissionGrantList` require an
explicit caller key. Old calls without it now fail locally before I/O. Other
helpers preserve the manifest's current keyed/repeatable/convergent distinctions.
Repeatable group creation/send currently has no replay guarantee; this remains
a Core contract gap. Composer helpers require minor 1, all three composer
operations and all nine positive integer limits. They use Core-issued update
keys and persisted send revisions.

First composer use raises the host vault format floor from 1 to 2 atomically.
An old format-1 host must refuse it; binary downgrade after migration is
unsupported. API minor compatibility does not imply storage downgrade safety.

The experimental fixture pair is API 1.0/source 174728e with SDK 0.2 and
candidate API 1.1 with SDK 0.3. Python's first standalone wheel spells the same
cohort `0.3.0.dev0`; Kotlin uses `0.3.0-experimental`. Initial local target is
Windows x64/Node 24.22.1. Linux and Android evidence is recorded separately.
There is no supported upgrade window or redistribution release. Archive checks
and isolated import smoke are separate from installed-SDK/real-Core tests and
packaged-platform qualification, each of which must retain source/artifact hashes.

Run `node scripts/check_typescript_distribution.mjs` after compilation to pack,
install outside the checkout and inspect the archive. The independent example
under `examples/typescript-core-consumer` imports only the installed package.

`profileCatalog`, `lockProfile`, `selectProfile` and `unlockProfile` require the
four advertised lifecycle operations and four positive profile limits. Only a
runtime-level host exposes this feature; a profile service alone does not.
Unlock uses an opaque, expiring, single-use credential reference issued by the
trusted platform host. The SDK never creates it or reads an OS key slot.
Selection and reconciliation do not unlock implicitly.

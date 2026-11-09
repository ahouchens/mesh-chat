# Experimental standalone Python client

`mesh-chat-core-client==0.3.0.dev0` is the first standalone Python client wheel.
`0.3.0.dev0` is the PEP 440 spelling for the 0.3 experimental SDK cohort;
TypeScript and Kotlin use `0.3.0-experimental`. The pinned 174728e Python 0.2
client lives inside the service artifact. There is no historical standalone
Python 0.2 wheel.

This package uses only the standard library. It contains no facade, runtime,
vault, reducer, transport policy or native implementation. Hosts supply already
authenticated streams. On Windows the optional `windows.connect` adapter opens
an explicitly supplied local named pipe; endpoint trust and access control
remain the host/operator's responsibility.

```python
from mesh_chat_core_client import CoreClient
from mesh_chat_core_client.windows import connect

pipe = connect(host_supplied_pipe_name)
client = CoreClient.open(pipe.readline, pipe.write, pipe.close)
profile = client.profile()
client.close()
```

The SDK never opens or owns a vault, profile directory or key. Closing detaches
only this client. It does not stop the host, revoke identity or transfer storage
ownership. `stop()` is a separate, capability/permission-controlled owner request.
No whole-profile export, key export or uninstall-erasure guarantee is provided
by this client package.

Composer methods require API 1.1, all three composer operations and all nine
numeric composer limits. Updates use the Core-issued update key; sends use the
persisted revision. No key is invented or stored by the SDK. A timeout/EOF after
writing has an uncertain outcome: reopen the authenticated stream, query Core,
and explicitly reuse the original identity. There is no automatic retry or
fallback send.

`create_profile`, `workspace_join`, and `workspace_admission_grant_list` now take
an explicit `key` argument. Legacy calls without it fail locally before I/O.
The manifest distinguishes keyed operations from `repeatable`,
`convergent_desired_state`, and `last_write_wins`. Repeatable group sends/creates
currently have **no replay guarantee**; this SDK does not invent unsupported
keys to disguise that remaining Core contract gap.

The host owns forward storage migration. First composer use atomically raises
the vault floor from 1 to 2. An older format-1 host must refuse that migrated
vault; binary downgrade is unsupported. Public API minor compatibility is a
separate property.

The staged matrix is experimental: service API 1.0/source 174728e with its
service-carried Python 0.2 component, candidate API 1.1 with this standalone
0.3.0.dev0 wheel, and candidate client against baseline host with composer
locally unavailable. Initial local target is Windows x64/Python 3.13; Linux and
Android evidence is recorded separately by CI. Staging alone declares no
supported upgrade window or redistribution release. Actual fixture hashes,
OS/architecture, source and test results must accompany each qualified pair.

Runtime-level profile helpers require all four `profile.catalog/lock/select/unlock`
operations and the four positive `profile_*` lifecycle limits. A profile service
alone does not advertise them. The runtime host stays available after profile
lock; unlock takes an opaque, expiring, single-use credential reference issued
by trusted platform authentication. The SDK never creates that authority or
retrieves an OS key. Profile selection and reconciliation do not unlock implicitly.

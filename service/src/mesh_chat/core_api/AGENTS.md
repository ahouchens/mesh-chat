# Application API boundary

Caller identity, grants and profile bindings come from a trusted host, never
request JSON. Recheck grants on every operation. Keep private lifecycle/native
ports out of this package's public request allowlist. Return explicitly selected
fields, stable typed errors and scoped opaque handles; never raw domain records.

Changes require contract vectors, wrong-caller/scope tests, bounds and revocation
tests. Mutations must define atomic durability and idempotency before advertising
support. Keep experimental component evidence distinct from authenticated host
integration, packaged consumers and a supported API release. SDKs cannot import
this implementation, the vault, reducer or native adapters.

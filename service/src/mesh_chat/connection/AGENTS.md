# Connection runtime

Identify the state/event and specification invariant before changing policy.
Keep policy in `reducer.py`, pure types in `model.py`, and external work behind
ports. `composition.py` alone binds concrete service capabilities. Never add
peer retry timers to adapters, SDKs, or the UI.

Before a contract change, identify affected producers/consumers and versions.
Preserve signatures, consent, exact-resource cleanup, encrypted transactions,
and authenticated receipt semantics. Public clients cannot submit private events.

Add a minimal regression trace and run `service/tests/connection`, the strict
model/reducer type check, and affected service/adapter tests. Maintain explicit
labels for simulated, real transport, emulator, packaged, and physical evidence.
Required missing environments fail qualification; they are not passing skips.

Record removed legacy policy and remaining wrappers in the implementation
roadmap. Never enable both policies for one runtime. Do not promote the
experimental selector before the milestone's qualification gates pass.

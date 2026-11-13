# Installed TypeScript consumer

Copy this directory outside the checkout and install the staged
`mesh-chat-core-client-0.3.0-experimental.tgz` with offline npm and scripts
disabled. Run with Node22+ and `--pipe HOST_SUPPLIED_LOCAL_PIPE`, or provide
dedicated inherited stdin/stdout. Only installed public package entry points
are imported; no checkout alias or service implementation is used.

Default execution observes only. On a fresh synthetic qualification profile,
`--legacy` explicitly enqueues a fixed test message. `--exercise-composer`
updates, sends and explicitly replays one durable revision. After a lost
committed reply, `--recover-composer` queries acceptance and explicitly resolves
the same revision. Reports contain booleans/codes, never text, keys or revisions.
The client closes on its finite exchange deadline and never retries; detach
leaves the host running. The host owns storage and caller authentication.

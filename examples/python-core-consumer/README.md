# Installed Python consumer

Copy this directory outside the checkout and install the staged
`mesh_chat_core_client-0.3.0.dev0-py3-none-any.whl` with `pip --no-deps`.
`consumer.py --pipe HOST_SUPPLIED_LOCAL_PIPE` observes an authenticated Core.
Without `--pipe`, stdin/stdout must be dedicated inherited binary streams.
The program imports only the installed public SDK; the host owns its vault.

Default execution is read-only. In a fresh synthetic qualification profile,
`--legacy` explicitly sends a fixed test message. `--exercise-composer` updates,
sends and explicitly replays one durable revision. After a lost committed reply,
`--recover-composer` queries the accepted outcome and explicitly resolves that
same revision. Reports contain booleans and codes, never text, keys or revisions.
Closing this consumer leaves the host running. There is no automatic retry.
The synchronous Python SDK requires host/application-controlled stream deadlines.

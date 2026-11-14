# Independent Python Core consumer

This application uses the installed `mesh-chat-core-client` wheel and a separately
installed normal Windows `mesh-chat-service.exe`. The trusted application starts
`--app-owned-native` with its own private data directory, a fresh named pipe and
the exact Python executable image. Host stdin carries only lifetime EOF. Public
Core requests use the wheel's named-pipe client.

The Windows qualification script installs the wheel and copies this application
outside the checkout. The application checks an empty host, explicit profile
creation, same-key replay, conflict rejection, public profile query, clean host
shutdown and the same public identity after reopening. The producer separately
checks DPAPI/EFS protection and hashes the installed wheel and frozen host.

This fixture does not pair peers, deliver messages, exercise Android, or qualify
SC21. A source-bound staging report is required before its platform run.

# ADR 0003: Use inherited, bounded framed IPC

Status: accepted.

The packaged service uses inherited stdin/stdout. Every message is a four-byte big-endian length followed by UTF-8 JSON, capped at 4 MiB and versioned independently from the app payload. The response allowance accommodates snapshots containing message history and per-recipient group delivery state while retaining a hard allocation bound. Stdout carries only frames; stderr diagnostics are redacted and not forwarded to the renderer.

The Rust shell owns process launch, profile paths and credential access. It forwards only allowlisted commands and rejects control/path keys and renderer payloads above 32 KiB. Request IDs are journaled for idempotency. No unauthenticated localhost HTTP/WebSocket server or arbitrary shell/eval command exists.

"""Defaults embedded in every desktop/mobile service package.

The production endpoint is verified in deploy/cloudflare-signal/VALIDATION.md.
A developer's shell environment does not become a packaged default.
"""

SIGNAL_MAILBOX_URL: str | None = "https://mesh-chat-signal.webtechalex.workers.dev"

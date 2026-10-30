"""Trusted host binding for the private core API over host-owned streams.

The host constructs the service, owns the stream pair and supplies the caller
identity, grants and profile scopes before serving. Frames can never select
either: the grant is captured here, and the stream is the one the host already
accepted. This is a component binding, not an operating-system access control;
a Windows named-pipe or Android Binder endpoint still has to hand it streams.
"""

import re

from .composition import bind_service_stream
from .session import Grant


CALLER = re.compile(r"[A-Za-z0-9._:-]{8,80}\Z")
ALLOWED_PERMISSIONS = frozenset({"observe", "read", "send", "diagnose"})
ALLOWED_PROFILES = ("local",)


def host_grant(caller, permissions, profiles=ALLOWED_PROFILES):
    """Validate the facts a trusted host supplies; never accept them from JSON."""
    if not isinstance(caller, str) or CALLER.fullmatch(caller) is None:
        raise ValueError("Host caller identity is invalid")
    values = frozenset(permissions) if isinstance(permissions, (frozenset, set, tuple, list)) else None
    if not values or not values <= ALLOWED_PERMISSIONS:
        raise ValueError("Host grant requests an unsupported permission")
    if tuple(profiles) != ALLOWED_PROFILES:
        raise ValueError("Host grant targets an unsupported profile scope")
    return Grant(caller, values, ALLOWED_PROFILES)


def bind_host_stream(service, *, caller, permissions, profiles=ALLOWED_PROFILES):
    """Bind one already-trusted stream to a fixed caller and permission set."""
    grant = host_grant(caller, permissions, profiles)
    return bind_service_stream(service, lambda: grant)


def serve_host(service, reader, writer, *, caller, permissions, profiles=ALLOWED_PROFILES):
    """Serve the host's stream until EOF, then detach that session."""
    session = bind_host_stream(service, caller=caller, permissions=permissions, profiles=profiles)
    session.serve(reader, writer)
    return session

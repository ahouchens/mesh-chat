"""Trusted host binding for the private core API over host-owned streams.

The host constructs the service, owns the stream pair and supplies the caller
identity, grants and profile scopes before serving. Frames can never select
either: the grant is captured here, and the stream is the one the host already
accepted. This is a component binding, not an operating-system access control;
a Windows named-pipe or Android Binder endpoint still has to hand it streams.

Two grant scopes exist:

``consumer``
    Ordinary packaged consumers: observe, read, send and diagnostics. They may
    pair and connect on Android, but cannot administer a vault.
``owner``
    The trusted application host itself: the consumer set plus workspace
    approval, pairing and connection intent. Runtime ownership stays outside
    both scopes so a facade caller can never stop the application's runtime.
"""

import re

from .composition import bind_service_stream
from .session import Grant


CALLER = re.compile(r"[A-Za-z0-9._:-]{8,80}\Z")
CONSUMER_PERMISSIONS = frozenset({"observe", "read", "send", "diagnose"})
OWNER_PERMISSIONS = CONSUMER_PERMISSIONS | {"approve", "pair", "connect"}
SCOPES = {"consumer": CONSUMER_PERMISSIONS, "owner": OWNER_PERMISSIONS}
ALLOWED_PROFILES = ("local",)


def host_grant(caller, permissions, profiles=ALLOWED_PROFILES, *, scope="consumer",
               private_profile_bootstrap=False):
    """Validate the facts a trusted host supplies; never accept them from JSON."""
    allowed = SCOPES.get(scope) if isinstance(scope, str) else None
    if allowed is None:
        raise ValueError("Host grant scope is invalid")
    if type(private_profile_bootstrap) is not bool or (private_profile_bootstrap and scope != "owner"):
        raise ValueError("Private profile bootstrap requires the application owner")
    if private_profile_bootstrap:
        allowed = allowed | {"profile_owner"}
    if not isinstance(caller, str) or CALLER.fullmatch(caller) is None:
        raise ValueError("Host caller identity is invalid")
    values = frozenset(permissions) if isinstance(permissions, (frozenset, set, tuple, list)) else None
    if not values or not values <= allowed:
        raise ValueError("Host grant requests an unsupported permission for its scope")
    if tuple(profiles) != ALLOWED_PROFILES:
        raise ValueError("Host grant targets an unsupported profile scope")
    return Grant(caller, values, ALLOWED_PROFILES)


def bind_host_stream(service, *, caller, permissions, profiles=ALLOWED_PROFILES,
                     scope="consumer", private_native=False, private_profile_bootstrap=False,
                     private_composer_legacy=False):
    """Bind one already-trusted stream to a fixed caller and permission set."""
    grant = host_grant(caller, permissions, profiles, scope=scope,
                       private_profile_bootstrap=private_profile_bootstrap)
    if private_native and scope != "owner":
        raise ValueError("Private native binding requires the application owner")
    if type(private_composer_legacy) is not bool or (private_composer_legacy and scope != "owner"):
        raise ValueError("Private composer migration requires the application owner")
    return bind_service_stream(service, lambda: grant, private_native=private_native,
                                private_profile_bootstrap=private_profile_bootstrap,
                                private_composer_legacy=private_composer_legacy)


def serve_host(service, reader, writer, *, caller, permissions,
               profiles=ALLOWED_PROFILES, scope="consumer"):
    """Serve the host's stream until EOF, then detach that session."""
    session = bind_host_stream(service, caller=caller, permissions=permissions,
                               profiles=profiles, scope=scope)
    session.serve(reader, writer)
    return session

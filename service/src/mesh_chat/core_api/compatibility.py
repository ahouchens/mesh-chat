"""Declared compatibility rules for the experimental public API.

The public API, internal IPC and signed peer wire are separate namespaces; only
the public API major is negotiated here. A supported major accepts additive
minors, because clients must tolerate unknown fields inside that major.
"""

SUPPORTED_MAJOR = 1


def check_capabilities(value):
    """Return (major, minor) or raise ValueError with a stable reason."""
    if not isinstance(value, dict):
        raise ValueError("incompatible_version")
    major, minor = value.get("api_major"), value.get("api_minor")
    if type(major) is not int or type(minor) is not int or major < 0 or minor < 0:
        raise ValueError("incompatible_version")
    if major != SUPPORTED_MAJOR:
        raise ValueError("incompatible_version")
    return major, minor

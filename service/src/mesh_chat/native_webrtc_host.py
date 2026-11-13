"""Private host loading; platform mechanisms stay outside connection policy."""

from functools import lru_cache

from .errors import NativeUnavailable


HOST_METHODS = ("createOffer", "acceptOffer", "applyAnswer", "send", "sendControl", "stats", "close")


def require_host(host):
    if any(not callable(getattr(host, name, None)) for name in HOST_METHODS):
        raise NativeUnavailable("Native WebRTC host capabilities are incomplete")
    return host


@lru_cache(maxsize=1)
def android_host():
    try:
        from java import jclass
        return require_host(jclass("com.meshchat.runtime.NativeWebRtcHost"))
    except Exception as error:
        raise NativeUnavailable("Native WebRTC is unavailable") from error

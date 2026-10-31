"""Portable validation for the private Windows pipe endpoint.

Kept free of ctypes so its rules can be checked on every platform and cannot
silently drift away from the Windows binding.
"""

import re


PIPE_NAME = re.compile(r"\\\\.\\pipe\\mesh-chat-[a-z0-9][a-z0-9._-]{0,63}\Z")
WINDOWS_IMAGE = re.compile(r"(?:[A-Za-z]:\\|\\\\[^\\]+\\)[^\x00-\x1f]*\Z")
MAX_IMAGES = 16
MAX_IMAGE_LENGTH = 1024


def pipe_name(value):
    """Accept only names inside the product's private pipe namespace."""
    if not isinstance(value, str) or PIPE_NAME.fullmatch(value) is None:
        raise ValueError("Core API pipe name is outside the private namespace")
    return value


def allowed_images(values):
    """Validate the executable images a trusted host permits to connect."""
    if isinstance(values, str) or not isinstance(values, (tuple, list)) or not 1 <= len(values) <= MAX_IMAGES:
        raise ValueError("Core API pipe image allowlist is invalid")
    images = []
    for value in values:
        if (not isinstance(value, str) or not 1 <= len(value) <= MAX_IMAGE_LENGTH
                or WINDOWS_IMAGE.fullmatch(value) is None):
            raise ValueError("Core API pipe image must be a Windows absolute path")
        images.append(value)
    if len({image.lower() for image in images}) != len(images):
        raise ValueError("Core API pipe image allowlist contains duplicates")
    return tuple(images)


def image_allowed(observed, images):
    """A client image must exactly match an allowlisted path, ignoring case."""
    if not isinstance(observed, str) or not observed:
        return False
    return observed.lower() in {image.lower() for image in images}

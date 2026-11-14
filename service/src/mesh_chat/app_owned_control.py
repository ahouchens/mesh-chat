"""Pure codecs for the inherited, host-private owner and helper channels.

The caller owns I/O limits, deadlines, replay state, and process identity. No
value from this module is a public Core request or an admission grant.
"""

from dataclasses import dataclass, field
import re
from typing import Literal


MAX_CONTROL_LINE = 40
HELPER_PREFACE_LENGTH = 79
MAX_PID = 0xFFFFFFFF
_SEQUENCE = re.compile(r"[0-9a-f]{8}\Z")
_INVITATION = re.compile(r"[0-9a-f]{64}\Z")
_CONTROL = re.compile(rb"(REGISTER/1|REMOVE/1) ([0-9a-f]{8}) ([1-9][0-9]{0,9})\n")
_PREFACE = re.compile(rb"MESH-HELPER/1 ([0-9a-f]{64})\n")


class PrivateControlError(ValueError):
    """Malformed private protocol data; never includes received bytes."""


@dataclass(frozen=True)
class OwnerControl:
    action: Literal["register", "remove"]
    sequence: str
    pid: int


@dataclass(frozen=True)
class HelperAck:
    action: Literal["register", "remove"]
    sequence: str
    invitation: str | None = field(default=None, repr=False)


def _sequence(value: object) -> bool:
    return type(value) is str and _SEQUENCE.fullmatch(value) is not None


def _invitation(value: object) -> bool:
    return type(value) is str and _INVITATION.fullmatch(value) is not None


def encode_owner_control(action: str, sequence: str, pid: int) -> bytes:
    if (type(action) is not str or action not in ("register", "remove") or not _sequence(sequence)
            or type(pid) is not int or not 1 <= pid <= MAX_PID):
        raise PrivateControlError("Invalid private owner control")
    verb = "REGISTER/1" if action == "register" else "REMOVE/1"
    line = f"{verb} {sequence} {pid}\n".encode("ascii")
    if len(line) > MAX_CONTROL_LINE:
        raise PrivateControlError("Invalid private owner control")
    return line


def decode_owner_control(line: bytes) -> OwnerControl | None:
    """An empty byte string is clean EOF; a partial EOF line is malformed."""
    if type(line) is not bytes or len(line) > MAX_CONTROL_LINE:
        raise PrivateControlError("Invalid private owner control")
    if not line:
        return None
    match = _CONTROL.fullmatch(line)
    if match is None:
        raise PrivateControlError("Invalid private owner control")
    pid = int(match[3])
    if pid > MAX_PID:
        raise PrivateControlError("Invalid private owner control")
    return OwnerControl("register" if match[1] == b"REGISTER/1" else "remove",
                        match[2].decode("ascii"), pid)


def encode_helper_preface(invitation: str) -> bytes:
    if not _invitation(invitation):
        raise PrivateControlError("Invalid private helper preface")
    return b"MESH-HELPER/1 " + invitation.encode("ascii") + b"\n"


def decode_helper_preface(line: bytes) -> str:
    if type(line) is not bytes or len(line) != HELPER_PREFACE_LENGTH:
        raise PrivateControlError("Invalid private helper preface")
    match = _PREFACE.fullmatch(line)
    if match is None:
        raise PrivateControlError("Invalid private helper preface")
    return match[1].decode("ascii")


def helper_registered_ack(sequence: str, invitation: str) -> dict[str, object]:
    if not _sequence(sequence) or not _invitation(invitation):
        raise PrivateControlError("Invalid private helper acknowledgment")
    return {"v": 1, "type": "helper_registered", "sequence": sequence,
            "invitation": invitation}


def helper_removed_ack(sequence: str) -> dict[str, object]:
    if not _sequence(sequence):
        raise PrivateControlError("Invalid private helper acknowledgment")
    return {"v": 1, "type": "helper_removed", "sequence": sequence}


def validate_helper_ack(value: object, *, action: str, sequence: str) -> HelperAck:
    """Validate one exact acknowledgment against the launcher's pending request.

    Duplicate and late acknowledgments need external pending-state checks.
    """
    if (type(action) is not str or action not in ("register", "remove") or not _sequence(sequence)
            or type(value) is not dict):
        raise PrivateControlError("Invalid private helper acknowledgment")
    expected_type = "helper_registered" if action == "register" else "helper_removed"
    expected_keys = ({"v", "type", "sequence", "invitation"} if action == "register"
                     else {"v", "type", "sequence"})
    if (set(value) != expected_keys or type(value.get("v")) is not int or value["v"] != 1
            or type(value["type"]) is not str or value["type"] != expected_type
            or value["sequence"] != sequence
            or not _sequence(value["sequence"]) or
            (action == "register" and not _invitation(value["invitation"]))):
        raise PrivateControlError("Invalid private helper acknowledgment")
    return HelperAck(action, sequence, value.get("invitation"))

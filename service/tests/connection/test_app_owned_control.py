"""Exact, private owner command/preface/ack byte grammar only."""

import pytest

from mesh_chat.app_owned_control import (
    HELPER_PREFACE_LENGTH, MAX_CONTROL_LINE, MAX_PID, PrivateControlError,
    decode_helper_preface, decode_owner_control, encode_helper_preface,
    encode_owner_control, helper_registered_ack, helper_removed_ack,
    validate_helper_ack,
)


SEQUENCE = "deadbeef"
TOKEN = "a" * 64


@pytest.mark.parametrize("action,verb", [("register", b"REGISTER/1"), ("remove", b"REMOVE/1")])
@pytest.mark.parametrize("pid", [1, 42, MAX_PID])
def test_owner_control_canonical_roundtrip(action, verb, pid):
    line = encode_owner_control(action, SEQUENCE, pid)
    assert line == verb + b" " + SEQUENCE.encode() + b" " + str(pid).encode() + b"\n"
    assert len(line) <= MAX_CONTROL_LINE
    request = decode_owner_control(line)
    assert (request.action, request.sequence, request.pid) == (action, SEQUENCE, pid)


def test_empty_is_clean_eof_but_partial_eof_is_malformed():
    assert decode_owner_control(b"") is None
    with pytest.raises(PrivateControlError, match="^Invalid private owner control$"):
        decode_owner_control(b"REGISTER/1 deadbeef 42")


@pytest.mark.parametrize("line", [
    b"REGISTER/1 deadbeef 0\n", b"REGISTER/1 deadbeef 01\n",
    b"REGISTER/1 deadbeef 4294967296\n", b"REGISTER/1 DEADBEEF 42\n",
    b"REGISTER/2 deadbeef 42\n", b"register/1 deadbeef 42\n",
    b"REGISTER/1 deadbeef 42 extra\n", b"REGISTER/1 deadbeef 42\n\n",
    b"REGISTER/1 deadbeef 42\r\n", b"REGISTER/1 deadbeef 42\x00\n",
    b"REGISTER/1 deadbeef 4\xff\n", b"\xef\xbb\xbfREGISTER/1 deadbeef 42\n",
    b"X" * (MAX_CONTROL_LINE + 1), b"\n",
])
def test_owner_control_rejects_noncanonical_lines_without_echo(line):
    with pytest.raises(PrivateControlError) as caught:
        decode_owner_control(line)
    assert str(caught.value) == "Invalid private owner control"
    assert repr(line) not in str(caught.value)


@pytest.mark.parametrize("action,sequence,pid", [
    ("register", "deadbeef", 0), ("remove", "deadbeef", MAX_PID + 1),
    ("register", "DEADBEEF", 1), ("register", "deadbeef", True),
    ("register", "deadbeef", "1"), ("unknown", "deadbeef", 1),
])
def test_owner_control_encoder_rejects_noncanonical_fields(action, sequence, pid):
    with pytest.raises(PrivateControlError):
        encode_owner_control(action, sequence, pid)


def test_helper_preface_is_exact_79_bytes_and_token_hidden_from_repr():
    line = encode_helper_preface(TOKEN)
    assert line == b"MESH-HELPER/1 " + TOKEN.encode() + b"\n"
    assert len(line) == HELPER_PREFACE_LENGTH
    assert decode_helper_preface(line) == TOKEN
    ack = validate_helper_ack(helper_registered_ack(SEQUENCE, TOKEN),
                              action="register", sequence=SEQUENCE)
    assert ack.invitation == TOKEN
    assert TOKEN not in repr(ack)


@pytest.mark.parametrize("line", [
    b"", b"MESH-HELPER/1 " + TOKEN.encode(),
    b"MESH-HELPER/1 " + TOKEN.encode() + b"\r\n",
    b"MESH-HELPER/1 " + TOKEN.encode() + b"\n\n",
    b"MESH-HELPER/1 " + TOKEN.encode() + b"\x00",
    b"MESH-HELPER/1 " + b"A" * 64 + b"\n",
    b"MESH-HELPER/1 " + b"\xff" * 64 + b"\n",
    b"MESH-HELPER/1 " + b"a" * 63 + b"\n",
    b"\xef\xbb\xbfMESH-HELPER/1 " + TOKEN.encode() + b"\n",
])
def test_helper_preface_rejects_partial_oversized_nonascii_and_extra(line):
    with pytest.raises(PrivateControlError) as caught:
        decode_helper_preface(line)
    assert str(caught.value) == "Invalid private helper preface"
    assert TOKEN not in str(caught.value)


def test_ack_serializers_and_exact_correlation():
    registered = helper_registered_ack(SEQUENCE, TOKEN)
    removed = helper_removed_ack(SEQUENCE)
    assert registered == {"v": 1, "type": "helper_registered", "sequence": SEQUENCE,
                          "invitation": TOKEN}
    assert removed == {"v": 1, "type": "helper_removed", "sequence": SEQUENCE}
    assert validate_helper_ack(registered, action="register", sequence=SEQUENCE).invitation == TOKEN
    assert validate_helper_ack(removed, action="remove", sequence=SEQUENCE).invitation is None


@pytest.mark.parametrize("value,action,sequence", [
    ({"v": 1, "type": "helper_registered", "sequence": SEQUENCE, "invitation": TOKEN, "x": 1},
     "register", SEQUENCE),
    ({"v": True, "type": "helper_registered", "sequence": SEQUENCE, "invitation": TOKEN},
     "register", SEQUENCE),
    ({"v": 1, "type": "helper_registered", "sequence": SEQUENCE, "invitation": TOKEN},
     "register", "00000000"),
    ({"v": 1, "type": "helper_registered", "sequence": "DEADBEEF", "invitation": TOKEN},
     "register", "DEADBEEF"),
    ({"v": 1, "type": "helper_registered", "sequence": SEQUENCE, "invitation": "A" * 64},
     "register", SEQUENCE),
    ({"v": 1, "type": "helper_registered", "sequence": SEQUENCE, "invitation": TOKEN},
     "remove", SEQUENCE),
    ({"v": 1, "type": "helper_removed", "sequence": SEQUENCE, "invitation": TOKEN},
     "remove", SEQUENCE),
    ({"v": 1, "type": "helper_removed", "sequence": SEQUENCE}, "register", SEQUENCE),
])
def test_ack_validator_rejects_shape_version_type_and_correlation(value, action, sequence):
    with pytest.raises(PrivateControlError) as caught:
        validate_helper_ack(value, action=action, sequence=sequence)
    assert str(caught.value) == "Invalid private helper acknowledgment"
    assert TOKEN not in str(caught.value)


def test_ack_serializer_rejects_invalid_sequence_and_invitation():
    with pytest.raises(PrivateControlError):
        helper_registered_ack("DEADBEEF", TOKEN)
    with pytest.raises(PrivateControlError):
        helper_registered_ack(SEQUENCE, "A" * 64)
    with pytest.raises(PrivateControlError):
        helper_removed_ack("deadbee")

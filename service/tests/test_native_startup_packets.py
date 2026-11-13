import base64

import pytest

from mesh_chat.native_startup_packets import NativeStartupPackets


def encoded(packet):
    return base64.b64encode(packet).decode("ascii")


def test_packet_budget_preserves_earliest_packets_and_releases_capacity():
    packets = NativeStartupPackets()
    for number in range(16):
        assert packets.retain("physical-1", encoded(bytes([number])))
    assert not packets.retain("physical-1", encoded(b"overflow"))
    assert packets.dropped == 1
    assert packets.take("physical-1") == tuple(bytes([n]) for n in range(16))
    assert packets.take("physical-1") == ()
    assert packets.retain("physical-1", encoded(b"new"))


def test_byte_budget_is_independent_of_packet_count():
    packets = NativeStartupPackets()
    for _ in range(15):
        assert packets.retain("physical-1", encoded(b"x" * 1064))
    assert not packets.retain("physical-1", encoded(b"x" * 1064))
    assert len(packets.take("physical-1")) == 15


def test_resource_budget_and_exact_generation_disposal():
    packets = NativeStartupPackets()
    for n in range(16):
        assert packets.retain(str(n), encoded(b"packet"))
    assert not packets.retain("replacement", encoded(b"new"))
    packets.discard("0")
    assert packets.retain("replacement", encoded(b"new"))
    packets.discard("0")
    assert packets.take("0") == ()
    assert packets.take("replacement") == (b"new",)
    assert packets.take("1") == (b"packet",)


@pytest.mark.parametrize("data", ["", "!!!", "AQI=garbage", "é", encoded(b"x" * 1065), "A" * 100_000],
                         ids=["empty", "invalid", "trailing", "unicode", "over_mtu", "over_input_bound"])
def test_invalid_packets_never_consume_capacity(data):
    packets = NativeStartupPackets()
    assert not packets.retain("physical-1", data)
    assert packets.take("physical-1") == ()
    assert packets.dropped == 1

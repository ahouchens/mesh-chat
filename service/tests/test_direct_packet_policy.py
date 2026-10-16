import RNS

from tools.direct_packet_policy import PacketPolicy


def packet(destination, *, destination_type=RNS.Destination.SINGLE,
           kind=RNS.Packet.DATA, context=RNS.Packet.NONE, data=b"payload", hops=0):
    return bytes([(destination_type << 2) | kind, hops]) + destination + bytes([context]) + data


def test_only_exact_directional_destinations_and_path_requests():
    local, peer, stranger = b"a" * 16, b"b" * 16, b"c" * 16
    policy = PacketPolicy(local, peer)
    assert policy.allow(packet(local), "in")
    assert policy.allow(packet(peer), "out")
    assert not policy.allow(packet(peer), "in")
    assert not policy.allow(packet(stranger), "out")
    assert policy.allow(packet(peer, kind=RNS.Packet.ANNOUNCE), "in")
    assert not policy.allow(packet(stranger, kind=RNS.Packet.ANNOUNCE), "in")
    for direction, target in (("in", local), ("out", peer)):
        assert policy.allow(packet(policy.path_request, destination_type=RNS.Destination.PLAIN,
                                   data=target + b"tag"), direction)
        assert not policy.allow(packet(policy.path_request, destination_type=RNS.Destination.PLAIN,
                                       data=stranger + b"tag"), direction)
    assert not policy.allow(packet(local, hops=1), "in")
    assert not policy.allow(b"\x80" + packet(local)[1:], "in")
    assert not policy.allow(b"\x10" + packet(local)[1:], "in")
    assert not policy.allow(b"bad", "in")


def test_only_observed_scoped_link_requests_allow_link_packets_and_expire():
    clock = [100.0]
    policy = PacketPolicy(b"a" * 16, b"b" * 16, clock=lambda: clock[0])
    raw = packet(policy.local, kind=RNS.Packet.LINKREQUEST, data=b"x" * RNS.Link.ECPUBSIZE)
    parsed = RNS.Packet(None, raw)
    assert parsed.unpack()
    link = RNS.Link.link_id_from_lr_packet(parsed)
    data = packet(link, destination_type=RNS.Destination.LINK)
    assert not policy.allow(data, "in")
    assert policy.allow(raw, "in")
    assert policy.allow(data, "in")
    assert policy.allow(data, "out")
    assert not policy.allow(packet(b"c" * 16, destination_type=RNS.Destination.LINK), "in")
    clock[0] = 399
    assert policy.allow(raw, "in")
    clock[0] = 400
    assert not policy.allow(data, "in")


def test_receipts_require_matching_packet_and_direction_and_expire():
    clock = [100.0]
    policy = PacketPolicy(b"a" * 16, b"b" * 16, clock=lambda: clock[0])
    raw = packet(policy.peer)
    parsed = RNS.Packet(None, raw)
    assert parsed.unpack()
    proof = packet(parsed.getTruncatedHash(), kind=RNS.Packet.PROOF)
    assert not policy.allow(proof, "in")
    assert policy.allow(raw, "out")
    assert policy.allow(proof, "in")
    assert not policy.allow(proof, "out")
    clock[0] = 220
    assert not policy.allow(proof, "in")


def test_packet_tracking_tables_are_bounded():
    policy = PacketPolicy(b"a" * 16, b"b" * 16)
    for index in range(32):
        assert policy.allow(packet(policy.local, kind=RNS.Packet.LINKREQUEST,
                                   data=bytes([index]) * RNS.Link.ECPUBSIZE), "in")
    assert not policy.allow(packet(policy.local, kind=RNS.Packet.LINKREQUEST,
                                   data=b"z" * RNS.Link.ECPUBSIZE), "in")
    for index in range(256):
        assert policy.allow(packet(policy.peer, data=index.to_bytes(2, "big")), "out")
    assert not policy.allow(packet(policy.peer, data=b"overflow"), "out")
    assert len(policy.links) == 32 and len(policy.receipts) == 256

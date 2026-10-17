import pytest

from tools.direct_network_audit import audit_trace


LOOPBACK = '21 sendmsg(3, {msg_name={sa_family=AF_INET, sin_port=htons(5000), sin_addr=inet_addr("127.0.0.1")}}, 0) = 32'


def test_audit_counts_ipv4_ipv6_connected_sends_and_wildcard_binds():
    report = audit_trace([LOOPBACK,
        '22 connect(4, {sa_family=AF_INET6, sin6_addr=inet_pton(AF_INET6, "::1", &sin6_addr)}, 28) = 0',
        '22 sendto(4, ""..., 32, 0, NULL, 0) = 32',
        '21 bind(5, {sa_family=AF_INET, sin_addr=inet_addr("0.0.0.0")}, 16) = 0'])
    assert report["external_addresses"] == 0
    assert report["loopback_addresses"] == 2
    assert report["wildcard_binds"] == 1
    assert report["network_sends"] == 2


@pytest.mark.parametrize("line", [
    LOOPBACK.replace("127.0.0.1", "8.8.8.8"),
    LOOPBACK.replace("127.0.0.1", "192.168.1.1"),
    LOOPBACK.replace("127.0.0.1", "0.0.0.0"),
    '22 connect(4, {sa_family=AF_INET6, sin6_addr=inet_pton(AF_INET6, "2001:4860:4860::8888", &sin6_addr)}, 28) = -1 ENETUNREACH',
    '22 sendto(4, ""..., 32, 0, {sa_family=AF_INET, ...}, 16) = 32',
    '22 socket(AF_PACKET, SOCK_RAW, 0) = 4',
    '22 connect(4, {sa_family=AF_UNIX, sun_path="/run/local-dns-proxy"}, 32) = 0',
])
def test_audit_rejects_external_attempts_even_if_the_kernel_rejected_them(line):
    with pytest.raises(ValueError):
        audit_trace([LOOPBACK, line])


def test_empty_or_incomplete_trace_cannot_qualify_provenance():
    with pytest.raises(ValueError):
        audit_trace([])
    with pytest.raises(ValueError):
        audit_trace(['21 bind(5, {sa_family=AF_INET, sin_addr=inet_addr("127.0.0.1")}, 16) = 0'])


def test_local_source_ancillary_data_is_not_a_remote_endpoint():
    line = LOOPBACK.replace('}}, 0)', '}, msg_control=[{ipi_spec_dst=inet_addr("0.0.0.0")} ]}, 0)')
    assert audit_trace([line])["loopback_addresses"] == 1

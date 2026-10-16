"""Record stock UDP adapter boundaries, not production qualification.

RNS authenticates IFAC downstream of this adapter. Local socket existence and
receipt of bytes must never be interpreted as remote-engine authentication.
"""
import socket
import threading
from types import SimpleNamespace

import RNS
from RNS.Interfaces.UDPInterface import UDPInterface
from RNS.Interfaces.Interface import Interface


def test_stock_loopback_udp_online_is_not_remote_liveness_or_local_authentication(monkeypatch):
    received = []
    ready = threading.Event()
    # Supply constructor defaults without starting RNS's process-global router.
    # The stock socket, receive loop, and online flag below are unmodified.
    defaults = {name: getattr(Interface, name.upper()) for name in (
        "ic_burst_hold", "ic_burst_freq_new", "ic_burst_freq",
        "ic_pr_burst_freq_new", "ic_pr_burst_freq", "ic_new_time",
        "ic_burst_penalty", "ic_held_release_interval", "ec_pr_freq", "egress_control",
    )}
    defaults["ic_max_held_announces"] = Interface.MAX_HELD_ANNOUNCES
    configured = SimpleNamespace(**{
        f"_default_{name}": lambda value=value: value for name, value in defaults.items()
    })
    monkeypatch.setattr(RNS.Reticulum, "get_instance", lambda: configured)

    def inbound(data, interface):
        received.append((data, interface))
        ready.set()

    interface = UDPInterface(SimpleNamespace(inbound=inbound), {
        "name": "Mesh direct feasibility only", "listen_ip": "127.0.0.1",
        "listen_port": 0,
    })
    try:
        assert interface.online  # No native engine or peer exists.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as unrelated_process:
            unrelated_process.sendto(b"unauthenticated local input", interface.server.server_address)
        assert ready.wait(2)
        assert received == [(b"unauthenticated local input", interface)]
        assert RNS.Reticulum.MTU + 16 == 516
    finally:
        # Stock detach closes the socket before socketserver's selector stops.
        # Stop the probe's serve_forever loop first to avoid a Windows teardown
        # race leaking an exception into the following test.
        interface.server.shutdown()
        interface.detach()
    assert not interface.online

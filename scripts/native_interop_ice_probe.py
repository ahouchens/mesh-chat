"""Synthetic owned-veth socket capability check, never native qualification."""

import hashlib
from pathlib import Path
import socket
import struct
import sys
import time


USERNAME = b"probeRemote123:probeLocal456"
TRANSACTION = b"meshIceProbe"


def request():
    attributes = struct.pack("!HH", 6, len(USERNAME)) + USERNAME + b"\0" * (-len(USERNAME) % 4)
    return struct.pack("!HHI", 1, len(attributes), 0x2112A442) + TRANSACTION + attributes


def client(address, port):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as channel:
        channel.settimeout(1)
        channel.sendto(request(), (address, port))


def check(gateway):
    from native_interop_ice_capture import IceCapture
    from native_interop_gateway_probe import require
    capture = IceCapture.start(gateway)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
            server.settimeout(2)
            server.bind((gateway.host_ip, 0))
            gateway.inside("/usr/bin/python3", "-I", "-B", str(Path(__file__).resolve()),
                           gateway.host_ip, str(server.getsockname()[1]))
            payload, source = server.recvfrom(2048)
            require(payload == request(), "ice_probe_request")
            server.sendto(struct.pack("!HHI", 0x101, 0, 0x2112A442) + TRANSACTION, source)
            target = dict(zip(("local_ufrag_sha256", "remote_ufrag_sha256"),
                (hashlib.sha256(value).hexdigest() for value in reversed(USERNAME.split(b":")))))
            deadline = time.monotonic() + 2
            while True:
                value = capture.snapshot(target)
                if (value["availability"] == "selected"
                        and value["egress"]["requests"] == 1 and value["ingress"]["success_responses"] == 1):
                    return {"passed": True, "qualification": False, "kind": "synthetic_owned_veth_stun", "observation": value}
                require(time.monotonic() < deadline, "ice_probe_capture_unavailable")
                time.sleep(0.01)
    finally:
        try: capture.close()
        finally: require(not capture.cleanup_failed, "packet_broker_cleanup_unproven")


if __name__ == "__main__":
    client(sys.argv[1], int(sys.argv[2]))

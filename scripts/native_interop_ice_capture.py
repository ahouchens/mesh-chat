"""Optional capture owned by the existing gateway parent, with no packet files."""

import array
import os
from pathlib import Path
import socket
import struct
import subprocess
import tempfile
import time

from native_interop_ice_packets import IcePackets, unavailable
from native_interop_packet_socket import link_identity


class BrokerCleanupUnproven(RuntimeError):
    pass


class IceCapture:
    def __init__(self):
        self.packet = None
        self.facts = IcePackets()
        self.identity = None
        self.deadline = time.monotonic() + 900
        self.bytes = self.packets = 0
        self.cleanup_failed = False

    @classmethod
    def start(cls, gateway):
        capture = cls()
        try:
            row = gateway.identities[gateway.host]
            capture.identity = (gateway.host, row["ifindex"], row["link_index"], gateway.token)
            capture.packet = acquire_socket(capture.identity)
            capture.check_identity()
        except BrokerCleanupUnproven:
            capture.cleanup_failed = True
            capture.disable("unavailable")
        except Exception:
            capture.disable("unavailable")
        return capture

    def disable(self, reason):
        self.facts.invalidate(reason)
        self.close()

    def check_identity(self):
        link_identity(*self.identity)
        if self.packet.getsockname()[:2] != (self.identity[0], 3):
            raise ValueError("packet_identity_changed")

    def drain(self):
        if self.packet is None: return
        try:
            if time.monotonic() > self.deadline:
                self.disable("expired")
                return
            self.check_identity()
            for _ in range(4096):
                try: data, _, flags, address = self.packet.recvmsg(2048)
                except BlockingIOError: break
                self.bytes += len(data)
                self.packets += 1
                if self.bytes > 32 * 1024 * 1024 or self.packets > 131072:
                    self.disable("limit")
                    return
                if address[0] != self.identity[0]:
                    self.disable("identity_changed")
                    return
                if address[1] != 0x800: continue  # IPv6 is disabled by gateway admission.
                if address[2] not in (0, 4): continue  # Ignore broadcast/multicast.
                if flags & getattr(socket, "MSG_TRUNC", 0x20) and (len(data) < 20 or data[9] == 17):
                    self.disable("capture_gap")
                    return
                # For TCP, a snap-length truncation is irrelevant. The IPv4 UDP
                # parser rejects a truncated length before retaining any fact.
                self.facts.observe(data, "ingress" if address[2] == 4 else "egress")
            else:
                self.disable("limit")  # Could not drain to an empty receive queue.
                return
            _, drops = struct.unpack("II", self.packet.getsockopt(263, 6, 8))  # PACKET_STATISTICS
            if drops: self.disable("capture_gap")
        except Exception:
            self.disable("unavailable")

    def snapshot(self, target):
        self.drain()
        return self.facts.snapshot(target)

    def close(self):
        packet, self.packet = self.packet, None
        if packet is not None: packet.close()


def acquire_socket(identity):
    """Transfer descriptor ownership only after the root broker has exited."""
    descriptors = []
    packet = None
    try:
        with tempfile.TemporaryDirectory(prefix="mesh-ice-") as temporary:
            os.chmod(temporary, 0o700)
            path = Path(temporary) / "socket"
            with socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) as server:
                server.bind(str(path))
                server.listen(1)
                server.settimeout(1)
                name, index, peer, alias = identity
                # Use the system Python, isolated from workflow packages/env.
                command = ["sudo", "-n", "/usr/bin/timeout", "--signal=TERM", "--kill-after=1", "3",
                    "/usr/bin/python3", "-I", "-B",
                    str(Path(__file__).with_name("native_interop_packet_socket.py")),
                    "--name", name, "--index", str(index), "--peer", str(peer), "--alias", alias,
                    "--path", str(path), "--uid", str(os.getuid()), "--pid", str(os.getpid())]
                try:
                    result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL, timeout=7, env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin"})
                except subprocess.TimeoutExpired as error:
                    raise BrokerCleanupUnproven() from error
                if result.returncode != 0: raise ValueError("packet_broker_failed")
                channel, _ = server.accept()
                with channel:
                    channel.settimeout(1)
                    _, uid, _ = struct.unpack("3i", channel.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                    data, controls, flags, _ = channel.recvmsg(2, socket.CMSG_SPACE(16), socket.MSG_CMSG_CLOEXEC)
                    for level, kind, value in controls:
                        if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                            fds = array.array("i")
                            fds.frombytes(value[:len(value) - len(value) % fds.itemsize])
                            descriptors.extend(fds)
                    if (uid != 0 or data != b"1" or flags & ~(socket.MSG_CMSG_CLOEXEC | socket.MSG_EOR)
                            or len(descriptors) != 1):
                        raise ValueError("packet_broker_identity")
                packet = socket.socket(fileno=descriptors[0])
                descriptors.clear()
                try:
                    packet.setblocking(False)
                    if packet.family != socket.AF_PACKET or packet.type != socket.SOCK_DGRAM:
                        raise ValueError("packet_descriptor_type")
                except Exception:
                    packet.close()
                    packet = None
                    raise
        return packet
    except Exception:
        if packet is not None: packet.close()
        raise
    finally:
        for descriptor in descriptors: os.close(descriptor)

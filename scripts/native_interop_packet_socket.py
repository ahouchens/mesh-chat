"""One-shot Linux broker for a socket bound to an already-owned gateway veth.

Invoked with isolated Python and a minimal environment. It transfers one socket
to the owning unprivileged process and exits; it never reads or sends packets.
"""

import argparse
import array
import os
from pathlib import Path
import re
import signal
import socket
import stat
import struct


def require(value):
    if not value: raise ValueError("packet_socket_unavailable")


def link_identity(name, index, peer, alias):
    require(re.fullmatch(r"mg[0-9a-f]{10}h", name) is not None)
    require(alias == name[:-1])
    root = Path("/sys/class/net") / name
    require(int((root / "ifindex").read_text()) == index
            and int((root / "iflink").read_text()) == peer
            and (root / "ifalias").read_text().strip() == alias)


def broker(arguments):
    require(os.geteuid() == 0 and int(os.environ["SUDO_UID"]) == arguments.uid and arguments.uid > 0)
    path = Path(arguments.path)
    parent = path.parent.lstat()
    target = path.lstat()
    require(stat.S_ISDIR(parent.st_mode) and parent.st_uid == arguments.uid
            and stat.S_IMODE(parent.st_mode) == 0o700
            and stat.S_ISSOCK(target.st_mode) and target.st_uid == arguments.uid)
    link_identity(arguments.name, arguments.index, arguments.peer, arguments.alias)
    with socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) as channel:
        channel.settimeout(1)
        channel.connect(str(path))
        pid, uid, _ = struct.unpack("3i", channel.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        require(pid == arguments.pid and uid == arguments.uid)
        # Protocol zero receives nothing until binding activates this exact link.
        with socket.socket(socket.AF_PACKET, socket.SOCK_DGRAM, 0) as packet:
            packet.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
            packet.bind((arguments.name, 3))  # ETH_P_ALL includes outgoing packets.
            link_identity(arguments.name, arguments.index, arguments.peer, arguments.alias)
            require(packet.getsockname()[:2] == (arguments.name, 3))
            channel.sendmsg([b"1"], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", [packet.fileno()]))])


def main():
    signal.alarm(3)  # Independent bound even if the invoking sudo wrapper exits.
    parser = argparse.ArgumentParser()
    for name in ("name", "alias", "path"): parser.add_argument("--" + name, required=True)
    for name in ("index", "peer", "uid", "pid"): parser.add_argument("--" + name, required=True, type=int)
    try:
        broker(parser.parse_args())
        return 0
    except Exception:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

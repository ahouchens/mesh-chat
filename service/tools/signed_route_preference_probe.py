"""Isolated Reticulum probe for mobile signed-route preference.

The real mobile failure involves one destination announce arriving on nearby
discovery before the same announce arrives on a TCP client configured from a
signed invitation. Reticulum keeps the first equal-hop/equal-gravity route, so
this probe uses its actual inbound path-selection code to keep that regression
deterministic and independent of host multicast support.
"""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path
from typing import Any

import RNS

from mesh_chat.reticulum_config import SIGNED_TCP_ROUTE_GRAVITY, NetworkSettings, write_config


class _ProbeInterface(RNS.Interfaces.Interface.Interface):
    def __init__(self, name: str, gravity: int):
        super().__init__()
        self.name = name
        self.gravity = gravity
        self.online = True
        self.IN = True
        self.OUT = True
        self.receives = True
        self.HW_MTU = RNS.Reticulum.MTU
        self.ifac_size = 0
        self.ifac_identity = None
        self.ifac_signature = None
        self.mode = RNS.Interfaces.Interface.Interface.MODE_FULL
        self.announce_rate_target = None
        self.announce_rate_grace = None
        self.announce_rate_penalty = None

    def process_outgoing(self, _data: bytes) -> None:
        pass

    def __str__(self) -> str:
        return self.name


def _route_name(
    destination: bytes,
    timeout: float = 2,
    *,
    expected: str | None = None,
) -> str | None:
    deadline = time.monotonic() + timeout
    interface: Any = None
    while time.monotonic() < deadline:
        interface = RNS.Transport.next_hop_interface(destination)
        if interface is not None and (expected is None or interface.name == expected):
            break
        time.sleep(0.01)
    return None if interface is None else str(interface.name)


def run() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="mesh-chat-route-preference-") as temporary:
        root = Path(temporary)
        write_config(
            root,
            NetworkSettings(nearby_discovery=False, lan_fallback=False),
        )
        reticulum = RNS.Reticulum(
            configdir=str(root),
            loglevel=RNS.LOG_ERROR,
            logdest=lambda _line: None,
        )
        def announce_for(label: str) -> tuple[bytes, bytes]:
            identity = RNS.Identity()
            destination = RNS.Destination(
                identity,
                RNS.Destination.IN,
                RNS.Destination.SINGLE,
                "mesh-chat-probe",
                label,
            )
            announce = destination.announce(send=False)
            announce.pack()
            raw = announce.raw
            destination_hash = destination.hash
            RNS.Transport.deregister_destination(destination)
            return raw, destination_hash

        equal_raw, equal_destination = announce_for("equal")
        preferred_raw, preferred_destination = announce_for("preferred")

        nearby = _ProbeInterface("Nearby devices", 0)
        equal_tcp = _ProbeInterface("Equal-gravity TCP", 0)
        signed_tcp = _ProbeInterface(
            "Private TCP peer 1", SIGNED_TCP_ROUTE_GRAVITY
        )
        for interface in (nearby, equal_tcp, signed_tcp):
            RNS.Transport.add_interface(interface)

        RNS.Transport.inbound(equal_raw, nearby)
        RNS.Transport.inbound(equal_raw, equal_tcp)
        time.sleep(0.1)
        equal_route = _route_name(equal_destination)
        RNS.Transport.inbound(preferred_raw, nearby)
        first_route = _route_name(preferred_destination)
        RNS.Transport.inbound(preferred_raw, signed_tcp)
        preferred_route = _route_name(
            preferred_destination,
            expected="Private TCP peer 1",
        )
        # This probe always runs in its own short-lived process. Let process
        # teardown close RNS after stdout is emitted; Reticulum.exit_handler()
        # intentionally detaches stdout, which would hide the JSON result.
        _ = reticulum
        return {
            "first_route": first_route,
            "equal_gravity_route": equal_route,
            "preferred_route": preferred_route,
            "signed_tcp_gravity": SIGNED_TCP_ROUTE_GRAVITY,
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.parse_args()
    result = run()
    print(json.dumps(result, sort_keys=True))
    return 0 if result == {
        "first_route": "Nearby devices",
        "equal_gravity_route": "Nearby devices",
        "preferred_route": "Private TCP peer 1",
        "signed_tcp_gravity": SIGNED_TCP_ROUTE_GRAVITY,
    } else 1


if __name__ == "__main__":
    raise SystemExit(main())

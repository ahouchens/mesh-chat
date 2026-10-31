"""CI-only peer exercise through the production Python host/private pipe.

No vault, RNS or LXMF claims: this qualifies the WebView2 mechanism and binding.
"""

import base64
import json
import os
from pathlib import Path
from queue import Empty, Queue
import sys
from time import monotonic

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from mesh_chat.desktop_transport_host import DesktopTransportHost
from mesh_chat.direct_native import NativeChannel, NativeFrameReader
from mesh_chat.errors import NativeUnavailable
from mesh_chat.ipc import FrameWriter
from mesh_chat.native_carrier_evidence import description_hash


def main():
    writer = FrameWriter(sys.stdout.buffer)
    observed = Queue(maxsize=512)
    host = DesktopTransportHost(writer.write, lambda *event: observed.put_nowait(event))
    reader = NativeFrameReader(sys.stdin.buffer, NativeChannel(), desktop_transport=host)
    history = set()

    def wait_for(expected):
        deadline = monotonic() + 15
        while not expected <= history:
            try:
                history.add(observed.get(timeout=max(.01, deadline - monotonic())))
            except Empty:
                raise AssertionError("Expected native observation did not arrive") from None
            if monotonic() >= deadline and not expected <= history:
                raise AssertionError("Native observation deadline expired")

    phase = "offer"
    try:
        restarted = len(sys.argv) == 2
        if restarted:
            phase = "rebind"
            checkpoint = json.loads(sys.argv[1])
            inventory = host.inventory()
            assert inventory == checkpoint
            assert not host.send("native-probe-a", b"held")
            assert not host.sendControl("native-probe-b", "meshchat-reconnect", "held")
            host.activate("native-probe-a")
            host.activate("native-probe-b")
        else:
            ice = json.dumps({"iceServers": [], "iceTransportPolicy": "all"})
            channels = json.dumps([{"label": "mesh-reticulum", "ordered": True, "binary": True},
                                   {"label": "meshchat-reconnect", "ordered": True, "binary": False}])
            offer = json.loads(host.createOffer("native-probe-a", ice, channels))
            phase = "answer"
            answer = json.loads(host.acceptOffer("native-probe-b", offer["sdp"], ice, channels))
            assert offer["ok"] and answer["ok"]
            phase = "applyAnswer"
            assert json.loads(host.applyAnswer("native-probe-a", answer["sdp"]))["ok"]
            phase = "channels"
            wait_for({("channel", resource, f"{label}:open") for resource in ("native-probe-a", "native-probe-b")
                      for label in ("mesh-reticulum", "meshchat-reconnect")})
            for resource in ("native-probe-a", "native-probe-b"):
                assert json.loads(host.stats(resource))["result"]["data_channel_state"] == "open"
            phase = "inventory"
            inventory = host.inventory()
            resources = {resource["resource"]: resource for resource in inventory["resources"]}
            assert set(resources) == {"native-probe-a", "native-probe-b"}
            for resource, local, remote in (("native-probe-a", offer, answer), ("native-probe-b", answer, offer)):
                assert resources[resource]["local_sdp_sha256"] == description_hash(local["sdp"])
                assert resources[resource]["remote_sdp_sha256"] == description_hash(remote["sdp"])
                assert resources[resource]["pending"] is False
                assert resources[resource]["data_channel_state"] == "open"
            assert host.inventory()["adapter_epoch"] == inventory["adapter_epoch"]
        phase = "packets"
        assert host.send("native-probe-a", bytes([1, 2, 3]))
        assert host.send("native-probe-b", bytes([4, 5, 6]))
        phase = "control"
        assert host.sendControl("native-probe-a", "meshchat-reconnect", "probe-a")
        assert host.sendControl("native-probe-b", "meshchat-reconnect", "probe-b")
        wait_for({("message", "native-probe-b", "AQID"), ("message", "native-probe-a", "BAUG"),
                  ("control", "native-probe-b", "meshchat-reconnect:" + base64.b64encode(b"probe-a").decode()),
                  ("control", "native-probe-a", "meshchat-reconnect:" + base64.b64encode(b"probe-b").decode())})
        if not restarted:
            writer.write({"v": 1, "type": "desktop_transport_handoff", "inventory": inventory})
            # A real process exit: no destructor, reset, or transport shutdown.
            os._exit(0)
        phase = "retirement"
        host.close("native-probe-a")
        host.close("native-probe-b")
        assert host.inventory()["resources"] == []
        assert not host.send("native-probe-a", b"retired")
        try:
            host.stats("native-probe-a")
        except NativeUnavailable:
            pass
        else:
            raise AssertionError("Retired resource remained visible")
        result = {"ok": True, "checks": ["offer", "answer", "bidirectional_packets", "bidirectional_control", "resource_inventory", "process_rebind", "held_activation", "retirement"]}
    except Exception as error:
        result = {"ok": False, "phase": phase, "error_type": type(error).__name__}
    finally:
        reader.close()
    writer.write({"v": 1, "type": "desktop_transport_qualification", **result})
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

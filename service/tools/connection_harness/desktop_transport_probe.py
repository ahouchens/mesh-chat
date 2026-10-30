"""CI-only peer exercise through the production Python host/private pipe.

No vault, RNS or LXMF claims: this qualifies the WebView2 mechanism and binding.
"""

import base64
import json
from pathlib import Path
from queue import Empty, Queue
import sys
from time import monotonic

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from mesh_chat.desktop_transport_host import DesktopTransportHost
from mesh_chat.direct_native import NativeChannel, NativeFrameReader
from mesh_chat.errors import NativeUnavailable
from mesh_chat.ipc import FrameWriter


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

    try:
        ice = json.dumps({"iceServers": [], "iceTransportPolicy": "all"})
        channels = json.dumps([{"label": "mesh-reticulum", "ordered": True, "binary": True},
                               {"label": "meshchat-reconnect", "ordered": True, "binary": False}])
        offer = json.loads(host.createOffer("native-probe-a", ice, channels))
        answer = json.loads(host.acceptOffer("native-probe-b", offer["sdp"], ice, channels))
        assert offer["ok"] and answer["ok"]
        assert json.loads(host.applyAnswer("native-probe-a", answer["sdp"]))["ok"]
        wait_for({("channel", resource, f"{label}:open") for resource in ("native-probe-a", "native-probe-b")
                  for label in ("mesh-reticulum", "meshchat-reconnect")})
        for resource in ("native-probe-a", "native-probe-b"):
            assert json.loads(host.stats(resource))["result"]["data_channel_state"] == "open"
        assert host.send("native-probe-a", bytes([1, 2, 3]))
        assert host.send("native-probe-b", bytes([4, 5, 6]))
        assert host.sendControl("native-probe-a", "meshchat-reconnect", "probe-a")
        assert host.sendControl("native-probe-b", "meshchat-reconnect", "probe-b")
        wait_for({("message", "native-probe-b", "AQID"), ("message", "native-probe-a", "BAUG"),
                  ("control", "native-probe-b", "meshchat-reconnect:" + base64.b64encode(b"probe-a").decode()),
                  ("control", "native-probe-a", "meshchat-reconnect:" + base64.b64encode(b"probe-b").decode())})
        host.close("native-probe-a")
        host.close("native-probe-b")
        assert not host.send("native-probe-a", b"retired")
        try:
            host.stats("native-probe-a")
        except NativeUnavailable:
            pass
        else:
            raise AssertionError("Retired resource remained visible")
        result = {"ok": True, "checks": ["offer", "answer", "bidirectional_packets", "bidirectional_control", "retirement"]}
    except Exception as error:
        result = {"ok": False, "error_type": type(error).__name__}
    finally:
        reader.close()
    writer.write({"v": 1, "type": "desktop_transport_qualification", **result})
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

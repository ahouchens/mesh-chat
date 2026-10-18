"""CI-only malformed-UDP load against the shipping native dispatcher.

Loopback resource/isolation evidence only, never NAT or physical reachability.
The report contains counts and timings, not endpoints, keys or packet contents.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import sys
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise SystemExit("Native qualification runs only in GitHub Actions")
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "service" / "tests"))
    from direct_app_host_fixture import AppHostNative
    binary = root / "experiments/direct-app-host/target/debug" / (
        "mesh-direct-app-host-proof.exe" if os.name == "nt" else "mesh-direct-app-host-proof")
    hosts = [AppHostNative(str(binary)) for _ in range(2)]
    report = {"schema": 1, "profile": "unsupported QUIC version, 100 packets/second for five seconds",
              "physical_evidence": False, "nat_evidence": False, "passed": False}
    try:
        prepared = [host.request("prepare", address="93.184.216.34:0", generation=1,
                    remaining_ms=60000) for host in hosts]
        target = hosts[0].request("prepare", address="93.184.216.34:0", generation=2, remaining_ms=60000)
        for index, host in enumerate(hosts):
            own, peer = prepared[index], prepared[1-index]
            host.request("arm", id=own["id"], session=own["session"], generation=1, digest="ab"*32)
            host.request("activate", id=own["id"], certificate=peer["certificate"],
                local=("01" if index == 0 else "02")*16, remote=("02" if index == 0 else "01")*16,
                candidates=[{"host":"93.184.216.34", "port":peer["port"], "remaining_ms":30000}],
                client=index == 0, remaining_ms=30000)
        end = time.monotonic()+5
        while time.monotonic() < end:
            if all(host.request("poll", id=p["id"])["state"] == 1 for host,p in zip(hosts,prepared)):
                break
            time.sleep(.02)
        else:
            raise AssertionError("Healthy control session did not authenticate")
        hosts[0].request("arm", id=target["id"], session=target["session"], generation=2, digest="cd"*32)
        hosts[0].request("activate", id=target["id"], certificate=prepared[1]["certificate"],
            local="03"*16, remote="04"*16, candidates=[], client=False, remaining_ms=20000)
        # A valid long-header shape with an unsupported version elicits version
        # negotiation, proving that the probe reaches the native QUIC parser.
        header = b"\xc0\x11\x22\x33\x44\x08abcdefgh\x08ijklmnop"
        packet = header + bytes(1200-len(header))
        sent = received = received_bytes = 0
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.bind(("127.0.0.1", 0))
            probe.setblocking(False)
            def drain():
                nonlocal received, received_bytes
                while True:
                    try:
                        data, _ = probe.recvfrom(65535)
                    except BlockingIOError:
                        return
                    received += 1
                    received_bytes += len(data)
                    assert len(data) <= 3*len(packet)
            started = time.monotonic()
            for index in range(500):
                delay = started + index/100 - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
                probe.sendto(packet, ("127.0.0.1", target["port"]))
                sent += 1
                drain()
            time.sleep(.2)
            drain()
            elapsed = time.monotonic()-started
            assert 0 < received <= sent, "Probe must reach QUIC without response fan-out"
            assert received_bytes <= 3*sent*len(packet), "Unvalidated traffic amplification"
            target_state = hosts[0].request("poll", id=target["id"])
            assert target_state["state"] == 0 and target_state["packets"] == []
            closed_at = time.monotonic()
            hosts[0].request("close", id=target["id"])
            assert target["id"] not in hosts[0].owned
            close_seconds = time.monotonic()-closed_at
            assert close_seconds < 5
        # The load and retirement must not retire or contaminate another session.
        for sender in range(2):
            peer = 1-sender
            assert hosts[peer].request("poll", id=prepared[peer]["id"])["packets"] == []
            marker = (b"approved control a" if sender == 0 else b"approved control b").hex()
            hosts[sender].request("send", id=prepared[sender]["id"], packets=[marker])
            end = time.monotonic()+3
            while time.monotonic() < end:
                result = hosts[peer].request("poll", id=prepared[peer]["id"])
                assert result["state"] == 1
                if result["packets"]:
                    assert result["packets"] == [marker]
                    break
                time.sleep(.02)
            else:
                raise AssertionError("Healthy control session was disrupted")
        report.update(passed=True, sent_packets=sent, sent_bytes=sent*len(packet),
            response_packets=received, response_bytes=received_bytes,
            elapsed_seconds=round(elapsed,3), observed_input_packets_per_second=round(sent/elapsed,3),
            observed_response_packets_per_second=round(received/elapsed,3),
            max_response_amplification=3, unauthorized_application_packets=0,
            unaffected_authenticated_directions=2, close_seconds=round(close_seconds,3))
    finally:
        for host in hosts:
            host.close()
        Path(args.report).write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")


if __name__ == "__main__":
    main()

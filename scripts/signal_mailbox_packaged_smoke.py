"""Verify the embedded mailbox default and encrypted HTTP using two built services.

Uses fresh synthetic profiles and signed synthetic SDP, not real WebRTC devices.
Requires OS protected storage. Reports contain no identities or pairing secrets.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "service"), str(ROOT / "service" / "src")]
from tools.packaged_direct_harness import PackagedPeer


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True)
    parser.add_argument("--expected-default", required=True)
    args = parser.parse_args()
    # Verify the compiled default, independent of the operator's startup override.
    os.environ.pop("MESH_CHAT_DEFAULT_SIGNAL_MAILBOX", None)
    root = ROOT / ".test-tmp" / ("signal-hosted-packaged-" + uuid.uuid4().hex)
    root.mkdir(parents=True)
    clients = []
    report = {"url": args.expected_default, "physical_webrtc_test": False}
    try:
        for name in ("Owner", "Joiner"):
            peer = PackagedPeer(Path(args.binary).resolve(), root / name, "Synthetic " + name)
            clients.append(peer)
            settings, _ = peer.call("call_settings")
            assert settings["signal_mailbox_url"] == args.expected_default
            assert settings["signal_mailbox_default_url"] == args.expected_default
        report["embedded_default_without_environment"] = True
        owner, joiner = clients
        fingerprint = "sha-256 " + ":".join(["AB"] * 32)
        sdp = f"v=0\r\na=fingerprint:{fingerprint}\r\nm=application 9 UDP/DTLS/SCTP webrtc-datachannel\r\n"
        offer, _ = owner.call("webrtc_onboarding_offer", {"sdp": sdp, "dtls_fingerprint": fingerprint})
        published, _ = owner.call("signal_publish", {"document": offer["document"], "role": "offer"})
        code = published["session_id"]
        assert code.startswith("MESHPAIR2.")
        fetched, _ = joiner.call("signal_fetch", {"session_id": code, "role": "offer"})
        assert fetched["document"] == offer["document"]
        answer, _ = joiner.call("webrtc_onboarding_answer", {
            "offer_document": fetched["document"], "sdp": sdp, "dtls_fingerprint": fingerprint})
        joined, _ = joiner.call("signal_publish", {"document": answer["document"], "role": "answer"})
        assert joined["session_id"] == code
        fetched, _ = owner.call("signal_fetch", {"session_id": code, "role": "answer"})
        checked, _ = owner.call("verify_webrtc_onboarding_answer", {
            "offer_document": offer["document"], "answer_document": fetched["document"]})
        assert checked["session_id"] == offer["session_id"]
        report["encrypted_hosted_offer_answer_verified"] = True
        for value in ("https://custom.example.test/", None):
            saved, _ = owner.call("update_call_settings", {
                "stun_urls": [], "relay_only": False, "signal_mailbox_url": value})
            assert saved["signal_mailbox_url"] == (value.rstrip("/") if value else None)
            assert saved["signal_mailbox_default_url"] == args.expected_default
        report["custom_and_disabled_choices"] = True
    finally:
        clean = []
        for peer in clients:
            try:
                peer.call("shutdown", timeout=10)
                peer.process.stdin.close()
                peer.process.wait(timeout=10)
                clean.append(peer.process.returncode == 0)
            except (subprocess.TimeoutExpired, TimeoutError):
                peer.process.kill()
                peer.process.wait(timeout=10)
                clean.append(False)
        report["clean_shutdown"] = len(clean) == 2 and all(clean)
        target = ROOT / "dist" / "reports" / "signal-production-packaged-smoke.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))
    return 0 if report["clean_shutdown"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

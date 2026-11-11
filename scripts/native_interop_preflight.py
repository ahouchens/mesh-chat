"""CI-only production outbound service probes; never proof of allocation/delivery."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "service/src"))

from mesh_chat.call_settings import DEFAULT_TURN_BROKER_URL, DEFAULT_SIGNAL_MAILBOX_URL
from mesh_chat.signal_mailbox import _open as mailbox_open
from mesh_chat.turn_credentials import fetch_ice_servers
from native_interop_diagnostics import PreflightDiagnostics
from test_packaged_lifecycle import source_identity


ANDROID_NETWORK_FIELDS = frozenset({"scope", "internet_permission", "active_network", "internet_capability",
    "validated_network", "dns_servers_present", "process_bound_network", "connect_target"})


def android_network_diagnostic(value):
    """Select only fixed guest facts from one failed CI control exchange."""
    try:
        if (type(value) is not dict or set(value) != ANDROID_NETWORK_FIELDS | {"v"}
                or type(value["v"]) is not int or value["v"] != 1
                or value["scope"] != "post_failure_app_process"
                or any(type(value[name]) is not bool for name in ANDROID_NETWORK_FIELDS - {"scope", "connect_target"})
                or type(value["connect_target"]) is not str
                or value["connect_target"] not in {"broker", "proxy", "unknown"}
                or (not value["active_network"] and any(value[name] for name in
                    ("internet_capability", "validated_network", "dns_servers_present")))
                or len(json.dumps(value, separators=(",", ":")).encode("utf-8")) > 256):
            return None
        return dict(value)
    except Exception:
        return None


def outbound_services():
    if not DEFAULT_TURN_BROKER_URL or not DEFAULT_SIGNAL_MAILBOX_URL:
        raise RuntimeError("Existing production broker and encrypted mailbox defaults are required")
    servers = fetch_ice_servers(DEFAULT_TURN_BROKER_URL, timeout=8)
    advertised = set()
    for server in servers:
        urls = server["urls"] if isinstance(server["urls"], list) else [server["urls"]]
        for url in urls:
            if not url.startswith(("turn:", "turns:")):
                continue
            if not isinstance(server.get("username"), str) or not server["username"] or not isinstance(server.get("credential"), str) or not server["credential"]:
                raise RuntimeError("Required short-lived TURN credentials are absent")
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
            advertised.add("tls" if url.startswith("turns:") else query.get("transport", ["udp"])[0])
    if not {"udp", "tcp", "tls"} <= advertised:
        raise RuntimeError("Existing broker does not advertise all required transport cases")
    request = urllib.request.Request(DEFAULT_SIGNAL_MAILBOX_URL.rstrip("/") + "/health",
                                     headers={"Accept": "application/json", "User-Agent": "mesh-native-qualification/1"})
    with mailbox_open(request) as response:
        if response.status != 200:
            raise RuntimeError("Production encrypted mailbox health request failed")
        raw = response.read(4097)
    if len(raw) > 4096:
        raise RuntimeError("Production mailbox health response exceeds its budget")
    health = json.loads(raw)
    if health.get("protocol") != 2 or health.get("writes_enabled") is not True:
        raise RuntimeError("Production encrypted mailbox is unavailable for bounded qualification")
    # Credentials, URLs, signed documents and request bodies are never returned.
    return {"turn_advertised_transports": sorted(advertised), "mailbox_protocol": 2,
            "mailbox_writes_enabled": True, "scope": "outbound health and advertisement only; no allocation or selected path"}


def android_environment(adb="adb", *, diagnostics=None):
    if sys.platform != "linux" or not os.access("/dev/kvm", os.R_OK | os.W_OK):
        raise RuntimeError("Required Linux KVM emulator host is unavailable")
    diagnostics = diagnostics if diagnostics is not None else PreflightDiagnostics()
    def command(site, *args):
        with diagnostics.scope(site):
            return subprocess.check_output([adb, *args], text=True, stderr=subprocess.DEVNULL, timeout=15).strip()
    if (command("android_device_state", "get-state") != "device"
            or command("android_emulator_property", "shell", "getprop", "ro.kernel.qemu") != "1"):
        raise RuntimeError("Required booted Android emulator is unavailable")
    if command("android_abi", "shell", "getprop", "ro.product.cpu.abi") != "x86_64":
        raise RuntimeError("Required staged x86_64 Android host is unavailable")
    return {"emulated": True, "abi": "x86_64", "kvm": True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-source", required=True)
    parser.add_argument("--role", choices=("windows", "android"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--adb", default="adb")
    args = parser.parse_args()
    record = {"v": 1, "passed": False, "role": args.role,
              "scope": "runner/outbound-service preflight only; no transport, pairing or receipt qualification"}
    phase = "source_environment"
    try:
        source, tree = source_identity(args.expected_source)
        if args.role == "windows":
            if sys.platform != "win32":
                raise RuntimeError("Required Windows peer host is unavailable")
            platform = {"windows": True}
        else:
            platform = android_environment(args.adb)
        phase = "production_outbound_services"
        services = outbound_services()
        record.update(passed=True, source_commit=source, source_tree=tree, platform=platform, services=services)
    except Exception as error:
        record.update(failure_type=type(error).__name__, phase=phase)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record))
    return 0 if record["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

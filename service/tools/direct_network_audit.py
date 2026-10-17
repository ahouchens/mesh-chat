"""CI-only Linux syscall provenance for the complete controlled topology.

Trace the test runner and all descendants, including Rust. Payload strings are
suppressed by strace; publish only endpoint-free counts. This observes this
controlled run, not every possible production configuration or physical network.
"""
import argparse
import ipaddress
import json
from pathlib import Path
import re
import subprocess
import tempfile


ADDRESS = re.compile(r'inet_addr\("([^\"]+)"\)|inet_pton\(AF_INET6, "([^\"]+)"')
SOCKADDR = re.compile(r'\{(?:sa_family|sin6_family|sin_family)=AF_INET6?\b[^}]*\}')
SYSCALL = re.compile(r'\b(connect|sendto|sendmsg|sendmmsg|bind|getsockname|getpeername|recvfrom|recvmsg|recvmmsg)\(')


def audit_trace(lines):
    counts = {"loopback_addresses": 0, "wildcard_binds": 0, "network_sends": 0}
    for number, line in enumerate(lines, 1):
        if "AF_PACKET" in line or ("SOCK_RAW" in line and "AF_INET" in line):
            raise ValueError(f"Raw networking at trace line {number}")
        call = SYSCALL.search(line)
        if call and call[1] in {"sendto", "sendmsg", "sendmmsg"}:
            counts["network_sends"] += 1
        if call and call[1] in {"connect", "sendto", "sendmsg", "sendmmsg"} and "sun_path=" in line:
            raise ValueError(f"Named local proxy connection at trace line {number}")
        endpoints = SOCKADDR.findall(line)
        addresses = [address for endpoint in endpoints for address in ADDRESS.findall(endpoint)]
        if ("sa_family=AF_INET" in line or "sin6_family=AF_INET6" in line
                or "sin_family=AF_INET" in line) and not addresses:
            raise ValueError(f"Undecoded Internet address at trace line {number}")
        if any(not ADDRESS.search(endpoint) for endpoint in endpoints):
            raise ValueError(f"Undecoded Internet address at trace line {number}")
        for v4, v6 in addresses:
            address = ipaddress.ip_address(v4 or v6)
            if address.is_loopback:
                counts["loopback_addresses"] += 1
            elif address.is_unspecified and call and call[1] in {"bind", "getsockname"}:
                counts["wildcard_binds"] += 1
            else:
                raise ValueError(f"Non-loopback networking at trace line {number}")
    if not counts["loopback_addresses"] or not counts["network_sends"]:
        raise ValueError("Trace contains no observed loopback packet traffic")
    return {"scope": "controlled topology and all child processes", "external_addresses": 0, **counts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("a test command is required")
    with tempfile.TemporaryDirectory(prefix="mesh-network-audit-") as directory:
        trace = Path(directory) / "network.trace"
        result = subprocess.run(["strace", "-f", "-qq", "-s", "0", "-e", "trace=network",
                                 "-o", str(trace), *command], check=False)
        with trace.open(encoding="utf-8") as stream:
            report = audit_trace(stream)
        if result.returncode:
            raise SystemExit(result.returncode)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report))


if __name__ == "__main__":
    main()

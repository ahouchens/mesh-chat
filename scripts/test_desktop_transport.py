"""Run the separate hidden WebView2 qualification executable; never silently skip."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
CHECKS = {"offer", "answer", "bidirectional_packets", "bidirectional_control", "retirement"}


def verified_report(result, expected_source=None):
    records = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{"')]
    if len(records) != 1 or not isinstance(records[0], dict):
        raise RuntimeError(f"Required browser test did not produce one result (exit {result.returncode})")
    record = records[0]
    if (set(record) != {"v", "source_commit", "evidence_level", "result"}
            or type(record["v"]) is not int or record["v"] != 1
            or record["evidence_level"] != "windows_webview2_private_host_component"):
        raise RuntimeError("Native host report is incompatible")
    if expected_source and record["source_commit"] != expected_source:
        raise RuntimeError("Native host was not built from the required source revision")
    report = record["result"]
    if (result.returncode != 0 or not isinstance(report, dict) or report.get("ok") is not True
            or not isinstance(report.get("checks"), list)
            or len(report["checks"]) != len(CHECKS) or set(report["checks"]) != CHECKS):
        raise RuntimeError("Required browser transport checks did not all pass")
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, default=ROOT / "src-tauri/target/debug/mesh-transport-qualification.exe")
    parser.add_argument("--expected-source")
    parser.add_argument("--output", type=Path, default=ROOT / "dist/reports/desktop-transport.json")
    args = parser.parse_args()
    probe = ROOT / "service/tools/connection_harness/desktop_transport_probe.py"
    evidence = {"v": 1, "passed": False, "evidence_level": "windows_webview2_private_host_component"}
    try:
        if sys.platform != "win32" or not args.binary.is_file():
            raise RuntimeError("Required Windows transport qualification executable is unavailable")
        result = subprocess.run([str(args.binary.resolve()), sys.executable, str(probe)], cwd=ROOT,
            capture_output=True, text=True, timeout=110, creationflags=subprocess.CREATE_NO_WINDOW)
        evidence.update(verified_report(result, args.expected_source))
        evidence["native_binary_sha256"] = hashlib.sha256(args.binary.read_bytes()).hexdigest()
        evidence["python_sources_sha256"] = {
            str(path.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in [probe, *(ROOT / "service/src/mesh_chat" / name for name in
                                ("desktop_transport_host.py", "direct_native.py", "ipc.py", "errors.py"))]}
        evidence["passed"] = True
    except Exception as error:
        evidence["failure"] = str(error)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence))
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

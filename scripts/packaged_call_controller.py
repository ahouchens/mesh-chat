"""Source-bound installed GUI or public SDK peer R5 role; no CI dispatch."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

import packaged_media_preflight as media
from packaged_call_exchange import Exchange, context_from_environment
from packaged_call_flow import Flow
from packaged_call_gui_session import InstalledGui
from packaged_call_peer import BrowserProcess, CallPeerSession


ROOT = Path(__file__).resolve().parents[1]
TOTAL_SECONDS = 1500


def edge_path():
    roots = [os.environ.get("PROGRAMFILES(X86)"), os.environ.get("PROGRAMFILES")]
    paths = [Path(root) / "Microsoft/Edge/Application/msedge.exe" for root in roots if root]
    matches = [path.resolve() for path in paths if path.is_file()]
    if len(set(matches)) != 1: raise ValueError("browser_installation_invalid")
    return matches[0]


def admitted(role, source):
    if (sys.platform != "win32" or role not in {"gui", "peer"}
            or os.environ.get("GITHUB_JOB") != "call_" + role
            or os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("GITHUB_EVENT_NAME") not in {"workflow_dispatch", "push"}
            or os.environ.get("GITHUB_SHA") != source
            or not os.environ.get("GITHUB_TOKEN") or not os.environ.get("ACTIONS_RUNTIME_TOKEN")
            or re.fullmatch(r"[a-f0-9]{40}", source) is None):
        raise ValueError("call_runner_admission")
    tree = subprocess.check_output(["git", "show", "-s", "--format=%T", "HEAD"],
                                   cwd=ROOT, text=True).strip()
    media.source_identity(source, tree)
    os.environ["PACKAGED_CALL_TREE"] = tree
    context = context_from_environment()
    if context["source_commit"] != source or context["source_tree"] != tree:
        raise ValueError("call_source_context")
    parent = Path(os.environ.get("RUNNER_TEMP", ""))
    if (not parent.is_absolute() or not parent.is_dir() or parent.is_symlink()
            or parent.resolve().is_relative_to(ROOT)):
        raise ValueError("call_runner_temp")
    return context, parent.resolve()


def run(role, source):
    started = time.monotonic()
    result = {"v": 1, "passed": False,
              "scope": "installed_windows_gui_public_sdk_peer_real_browser_audio_positive_call",
              "role": role, "source_commit": source, "source_tree": None,
              "run_id": os.environ.get("GITHUB_RUN_ID"),
              "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
              "checks": {}, "cleanup": {}, "phase": "admission"}
    exchange = peer = browser = temporary = None
    failure = None
    try:
        context, parent = admitted(role, source)
        result["source_tree"] = context["source_tree"]
        result["pair_id"] = context["pair_id"]
        result["phase"] = "source_bound_setup"
        temporary = tempfile.TemporaryDirectory(prefix="packaged-call-exchange-", dir=parent)
        if role == "gui":
            peer = InstalledGui(source, context["source_tree"], str(context["run_id"]),
                                context["run_attempt"], Path("node"), started + TOTAL_SECONDS - 30)
            peer.open()
            result["capture_preflight"] = peer.preflight
            result["installed"] = {key: peer.candidate[key] for key in
                ("delivery_report_sha256", "release_manifest_sha256", "installer_sha256",
                 "application_sha256", "sidecar_sha256")}
        else:
            peer = CallPeerSession(source, temporary_root=parent)
            peer.open()
            result["installed"] = {"sidecar_sha256": peer.binding["sidecar_sha256"],
                                   "sdk_sha256": peer.sdk_hash,
                                   "bootstrap_report_sha256": peer.report_hash}
            browser = BrowserProcess(peer.node, edge_path(), parent)
            browser.open(started + TOTAL_SECONDS - 30)
        result["phase"] = "sealed_exchange"
        exchange = Exchange(context, role, Path(temporary.name))
        exchange.connect(min(started + TOTAL_SECONDS - 60, time.monotonic() + 600))
        result["phase"] = "public_gui_call_flow"
        flow = Flow(role, peer, exchange, context["pair_id"], started + TOTAL_SECONDS - 30)
        result["checks"] = flow.run(browser)
        result["phase"] = "cleanup"
    except Exception as error:
        failure = (result["phase"], type(error).__name__)
    finally:
        if browser is not None:
            try: result["cleanup"]["browser_retired"] = browser.close()
            except Exception: result["cleanup"]["browser_retired"] = False
            result["cleanup"].update({"browser_" + key: value for key, value in browser.cleanup.items()})
        if peer is not None:
            if role == "gui":
                try: result["cleanup"]["gui_retired"] = peer.close()
                except Exception: result["cleanup"]["gui_retired"] = False
                result["cleanup"].update(peer.cleanup)
            else:
                try:
                    peer.finish()
                    result["cleanup"]["public_host_retired"] = True
                except Exception: result["cleanup"]["public_host_retired"] = False
                if result["cleanup"]["public_host_retired"]:
                    try:
                        peer.cleanup_workspace()
                        result["cleanup"]["public_workspace_cleaned"] = peer.workspace_cleaned
                    except Exception: result["cleanup"]["public_workspace_cleaned"] = False
        if exchange is not None:
            try: exchange.close(); result["cleanup"]["exchange_closed"] = True
            except Exception: result["cleanup"]["exchange_closed"] = False
        if temporary is not None:
            try: temporary.cleanup(); result["cleanup"]["temporary_removed"] = True
            except Exception: result["cleanup"]["temporary_removed"] = False
        if result["source_tree"] is not None:
            try:
                result["cleanup"]["source_unchanged"] = (
                    media.source_identity(source, result["source_tree"]) ==
                    (source, result["source_tree"]))
            except Exception: result["cleanup"]["source_unchanged"] = False
        result["duration_seconds"] = round(time.monotonic() - started, 3)
        if failure is not None:
            result["failure_phase"], result["failure_type"] = failure
        result["passed"] = (failure is None and result["phase"] == "cleanup"
                            and result["checks"].get("two_way_after") is True
                            and result["cleanup"] and all(value is True for value in result["cleanup"].values())
                            and result["duration_seconds"] <= TOTAL_SECONDS)
        if result["passed"]: result["phase"] = "complete"
        elif failure is None: result["failure_phase"] = "cleanup"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=("gui", "peer"), required=True)
    parser.add_argument("--expected-source", required=True)
    args = parser.parse_args()
    result = run(args.role, args.expected_source)
    output = ROOT / f"dist/reports/packaged-call-{args.role}.json"
    media.write_report(output, result)
    print(f"Packaged call {args.role}: {'passed' if result['passed'] else 'failed'}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

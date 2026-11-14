"""Own one installed public peer and its same-run fresh-pair diagnostic."""

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time

import check_public_core_pair as evidence
from public_core_pair_flow import run_role


ROOT = Path(__file__).resolve().parents[1]
TOTAL_SECONDS = 1200


def producer_inputs(role, context, tree):
    name = "windows-independent-bootstrap.json" if role == "windows" else "android-independent-distribution.json"
    record, identity = evidence.read_report(ROOT / "dist/reports" / name)
    verify = evidence.windows_inputs if role == "windows" else evidence.android_inputs
    return verify(record, context, tree, identity)


def admitted_context(role, expected_source, serial):
    from public_core_pair_rendezvous import JOBS, context_from_environment
    if (role not in JOBS or os.environ.get("GITHUB_JOB") != JOBS[role]
            or os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
            or not os.environ.get("GITHUB_TOKEN") or not os.environ.get("ACTIONS_RUNTIME_TOKEN")
            or os.environ.get("GITHUB_SHA") != expected_source
            or (role == "windows" and (sys.platform != "win32" or serial is not None))
            or (role == "android" and (sys.platform != "linux" or serial != "emulator-5554"))):
        raise ValueError("public_pair_admission")
    context = context_from_environment()
    evidence.checked_context(context)
    return context


def runner_temp():
    raw = os.environ.get("RUNNER_TEMP")
    if not raw:
        raise ValueError("runner_temp_missing")
    path = Path(raw)
    if not path.is_absolute() or not path.is_dir() or path.is_symlink():
        raise ValueError("runner_temp_invalid")
    path = path.resolve(strict=True)
    if path.is_relative_to(ROOT):
        raise ValueError("runner_temp_in_checkout")
    return path


def create_peer(role, expected_source, serial, parent):
    if role == "windows":
        from windows_public_consumer_session import WindowsPublicConsumerSession
        return WindowsPublicConsumerSession(expected_source, temporary_root=parent)
    from check_android_independent_public_session import AndroidPublicSession
    return AndroidPublicSession(expected_source, serial)


def create_exchange(context, role, directory):
    from public_core_pair_artifacts import PublicPairExchange
    return PublicPairExchange(context, role, directory)


def finish_peer(role, peer, requests=None):
    if role == "windows":
        peer.finish()
        if requests is not None and peer.sequence != requests:
            raise ValueError("public_request_count")
        from check_independent_core_consumers import protected_profile
        protected_profile(peer.data)
    else:
        count = peer.finish()
        if requests is not None and count != requests:
            raise ValueError("public_request_count")


def run(role, expected_source, serial=None, *, clock=time.monotonic):
    started = clock()
    deadline = started + TOTAL_SECONDS
    result = {"v": 1, "passed": False, "evidence_level": evidence.LEVEL, "scope": evidence.SCOPE,
        "role": role, "context": None, "source_tree": None, "flow": None, "inputs": None,
        "session": {"finished": False, "cleanup": False}, "duration_seconds": 0}
    phase = "admission"
    peer = exchange = temporary = None
    failure = None
    cleanup = True
    try:
        context = admitted_context(role, expected_source, serial)
        parent = runner_temp()
        phase = "producer_binding"
        _, tree = evidence.source_identity(expected_source)
        inputs = producer_inputs(role, context, tree)
        result.update(context=context, source_tree=tree, inputs=inputs)
        phase = "setup"
        temporary = tempfile.TemporaryDirectory(prefix="mesh-public-pair-setup-", dir=parent)
        exchange = create_exchange(context, role, Path(temporary.name))
        # Exchange keys before starting either application, avoiding an idle
        # Android SDK session while the other platform waits for its CI runner.
        exchange.connect(min(deadline - 120, clock() + 180))
        phase = "startup"
        peer = create_peer(role, expected_source, serial, parent)
        peer.open()
        phase = "public_flow"
        flow = run_role(role, peer, exchange, pair_id=context["pair_id"],
                        deadline=min(deadline - 30, peer.deadline), clock=clock)
        evidence.verify_flow(flow, role, context["pair_id"])
        result["flow"] = flow
        phase = "retirement"
        finish_peer(role, peer, flow["public_request_count"])
        result["session"]["finished"] = True
        phase = "final_binding"
        if (evidence.source_identity(expected_source) != (expected_source, tree)
                or producer_inputs(role, context, tree) != inputs or clock() >= deadline):
            raise ValueError("public_pair_inputs_changed")
    except Exception as error:
        failure = (phase, type(error).__name__)
    finally:
        if peer is not None:
            if role == "windows":
                if not peer.retired and peer.process is not None:
                    try:
                        finish_peer(role, peer)
                        result["session"]["finished"] = True
                    except Exception:
                        cleanup = False
                if failure is None:
                    try:
                        peer.cleanup_workspace()
                        cleanup = cleanup and peer.workspace_cleaned
                    except Exception as error:
                        cleanup = False
                        failure = ("cleanup", type(error).__name__)
                else:
                    # Retain failed Windows app data even after a clean exit.
                    cleanup = False
            else:
                try:
                    cleanup = peer.close() is True and cleanup
                except Exception:
                    cleanup = False
        else:
            cleanup = False
        for owned in (exchange, temporary):
            if owned is not None:
                try:
                    owned.close() if owned is exchange else owned.cleanup()
                except Exception:
                    cleanup = False
        result["session"]["cleanup"] = cleanup
        result["duration_seconds"] = clock() - started
        result["passed"] = (failure is None and cleanup and result["session"]["finished"]
                            and 0 < result["duration_seconds"] <= TOTAL_SECONDS)
        if failure is not None:
            result.update(failure_phase=failure[0], failure_type=failure[1])
        elif not result["passed"]:
            result.update(failure_phase="cleanup", failure_type="IncompleteSession")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=evidence.ROLES, required=True)
    parser.add_argument("--expected-source", required=True)
    parser.add_argument("--disposable-emulator-serial")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.role, args.expected_source, args.disposable_emulator_serial)
    evidence.write_summary(args.output, result)
    print(json.dumps({"passed": result["passed"], "failure_phase": result.get("failure_phase")}))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

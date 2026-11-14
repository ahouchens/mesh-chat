"""Own one installed role in the public Windows owner-restart diagnostic."""

import argparse
import json
import os
from pathlib import Path
import tempfile
import time

import check_public_core_pair as baseline_evidence
import public_core_pair_controller as installed
import public_core_restart_evidence as evidence
from public_core_restart_flow import run_restart_role


def run(role, expected_source, serial=None, *, clock=time.monotonic):
    started = clock()
    deadline = started + installed.TOTAL_SECONDS
    result = {"v": 1, "passed": False, "evidence_level": evidence.LEVEL,
        "scenario": evidence.SCENARIO, "scope": evidence.SCOPE, "role": role,
        "context": None, "source_tree": None, "flow": None, "inputs": None,
        "session": {"finished": False, "cleanup": False, "owner_incarnations_finished": 0},
        "duration_seconds": 0}
    phase = "admission"
    peer = exchange = temporary = None
    failure = None
    cleanup = True
    try:
        if os.environ.get("PUBLIC_PAIR_SCENARIO") != "owner_restart":
            raise ValueError("public_restart_scenario_admission")
        context = installed.admitted_context(role, expected_source, serial)
        parent = installed.runner_temp()
        phase = "producer_binding"
        _, tree = baseline_evidence.source_identity(expected_source)
        inputs = installed.producer_inputs(role, context, tree)
        result.update(context=context, source_tree=tree, inputs=inputs)
        installed.verify_downloads(role, expected_source, tree, inputs)
        phase = "setup"
        temporary = tempfile.TemporaryDirectory(prefix="mesh-public-restart-setup-", dir=parent)
        exchange = installed.create_exchange(context, role, Path(temporary.name))
        exchange.connect(min(deadline - 120, clock() + installed.SETUP_SECONDS))
        phase = "startup"
        peer = installed.create_peer(role, expected_source, serial, parent)
        peer.open()
        phase = "public_restart"
        flow = run_restart_role(role, peer, exchange, pair_id=context["pair_id"],
                                overall_deadline=deadline, clock=clock)
        evidence.verify_restart_flow(flow, role, context["pair_id"])
        result["flow"] = flow
        if role == "windows":
            result["session"]["owner_incarnations_finished"] = 1
        phase = "retirement"
        requests = flow["request_counts"]["after_reopen" if role == "windows" else "total"]
        installed.finish_peer(role, peer, requests)
        result["session"]["finished"] = True
        result["session"]["owner_incarnations_finished"] += 1
        phase = "final_binding"
        if (baseline_evidence.source_identity(expected_source) != (expected_source, tree)
                or installed.producer_inputs(role, context, tree) != inputs or clock() >= deadline):
            raise ValueError("public_restart_inputs_changed")
    except Exception as error:
        failure = (phase, type(error).__name__)
    finally:
        if peer is not None:
            if role == "windows":
                if not peer.retired and peer.process is not None:
                    try:
                        installed.finish_peer(role, peer)
                        result["session"]["finished"] = True
                        result["session"]["owner_incarnations_finished"] += 1
                    except Exception:
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
                            and 0 < result["duration_seconds"] <= installed.TOTAL_SECONDS)
        # Validate the projected successful report and retire setup resources
        # before removing the only retained Windows app data.
        if result["passed"]:
            try:
                evidence.verify_role_report(result, role, context, tree, inputs)
            except Exception as error:
                result["passed"] = False
                failure = ("report", type(error).__name__)
        if role == "windows" and peer is not None:
            if result["passed"]:
                try:
                    peer.cleanup_workspace()
                    cleanup = cleanup and peer.workspace_cleaned
                except Exception as error:
                    cleanup = False
                    failure = ("cleanup", type(error).__name__)
            else:
                cleanup = False
        result["session"]["cleanup"] = cleanup
        result["duration_seconds"] = clock() - started
        result["passed"] = (failure is None and cleanup and result["session"]["finished"]
                            and 0 < result["duration_seconds"] <= installed.TOTAL_SECONDS)
        if result["passed"]:
            try:
                evidence.verify_role_report(result, role, context, tree, inputs)
            except Exception as error:
                result["passed"] = False
                failure = ("report", type(error).__name__)
        if failure is not None:
            result.update(failure_phase=failure[0], failure_type=failure[1])
        elif not result["passed"]:
            result.update(failure_phase="cleanup", failure_type="IncompleteSession")
        if not result["passed"]:
            # A failed flow may have stopped owner 1 before returning its proof.
            # Do not label an incomplete observation as an exact retirement count.
            result["session"]["owner_incarnations_finished"] = None
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=baseline_evidence.ROLES, required=True)
    parser.add_argument("--expected-source", required=True)
    parser.add_argument("--disposable-emulator-serial")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.role, args.expected_source, args.disposable_emulator_serial)
    baseline_evidence.write_summary(args.output, result)
    print(json.dumps({"passed": result["passed"], "failure_phase": result.get("failure_phase")}))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

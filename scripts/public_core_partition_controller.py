"""Own installed public role sessions for the bounded Android route partition.

The Android caller must first boot an owned emulator inside the gateway
namespace and inject an app-UID-scoped fault object. The outer gateway parent
adds its cleanup witness only after the namespace child has exited.
"""

import argparse
import json
import os
from pathlib import Path
import tempfile
import time

import check_public_core_pair as baseline_evidence
import public_core_pair_controller as installed
import public_core_partition_evidence as evidence
from public_core_partition_flow import run_partition_role


def run(role, expected_source, serial=None, *, fault=None, clock=time.monotonic):
    started = clock()
    deadline = started + installed.TOTAL_SECONDS
    result = {"v": 1, "passed": False, "evidence_level": evidence.LEVEL,
        "scenario": evidence.SCENARIO, "scope": evidence.SCOPE, "role": role,
        "context": None, "source_tree": None, "flow": None, "inputs": None,
        "session": {"finished": False, "cleanup": False, "fault_closed": False},
        "gateway": None, "duration_seconds": 0}
    phase = "admission"
    peer = exchange = temporary = None
    failure = None
    cleanup = True
    try:
        if os.environ.get("PUBLIC_PAIR_SCENARIO") != "partition" or (role == "android") != (fault is not None):
            raise ValueError("public_partition_scenario_admission")
        context = installed.admitted_context(role, expected_source, serial)
        parent = installed.runner_temp()
        phase = "producer_binding"
        _, tree = baseline_evidence.source_identity(expected_source)
        inputs = installed.producer_inputs(role, context, tree)
        result.update(context=context, source_tree=tree, inputs=inputs)
        installed.verify_downloads(role, expected_source, tree, inputs)
        phase = "setup"
        temporary = tempfile.TemporaryDirectory(prefix="mesh-public-partition-setup-", dir=parent)
        exchange = installed.create_exchange(context, role, Path(temporary.name))
        exchange.connect(min(deadline - 120, clock() + installed.SETUP_SECONDS))
        phase = "startup"
        peer = installed.create_peer(role, expected_source, serial, parent)
        peer.open()
        if fault is not None:
            # C's gateway adapter binds the admitted installed app package,
            # main-process PID and UID before any loss rule can be armed.
            fault.bind(peer)
        phase = "public_partition"
        flow = run_partition_role(role, peer, exchange, pair_id=context["pair_id"],
            deadline=min(deadline - 60, peer.deadline), fault=fault, clock=clock)
        evidence.verify_partition_flow(flow, role, context["pair_id"])
        result["flow"] = flow
        phase = "retirement"
        requests = flow["baseline"]["public_request_count"] + flow["partition"]["additional_request_count"]
        installed.finish_peer(role, peer, requests)
        result["session"]["finished"] = True
        phase = "final_binding"
        if (baseline_evidence.source_identity(expected_source) != (expected_source, tree)
                or installed.producer_inputs(role, context, tree) != inputs or clock() >= deadline):
            raise ValueError("public_partition_inputs_changed")
    except Exception as error:
        failure = (phase, type(error).__name__)
    finally:
        if fault is not None:
            try: result["session"]["fault_closed"] = fault.close() is True
            except Exception: cleanup = False
            cleanup = cleanup and result["session"]["fault_closed"]
        else:
            result["session"]["fault_closed"] = role == "windows"
        if peer is not None:
            if role == "windows":
                if not peer.retired and peer.process is not None:
                    try:
                        installed.finish_peer(role, peer)
                        result["session"]["finished"] = True
                    except Exception:
                        cleanup = False
                if failure is None and cleanup:
                    try:
                        peer.cleanup_workspace()
                        cleanup = cleanup and peer.workspace_cleaned
                    except Exception as error:
                        cleanup = False
                        failure = ("cleanup", type(error).__name__)
                else:
                    cleanup = False  # Retain failed Windows app data.
            else:
                try: cleanup = peer.close() is True and cleanup
                except Exception: cleanup = False
        else:
            cleanup = False
        for owned in (exchange, temporary):
            if owned is not None:
                try: owned.close() if owned is exchange else owned.cleanup()
                except Exception: cleanup = False
        result["session"]["cleanup"] = cleanup
        result["duration_seconds"] = clock() - started
        result["passed"] = (failure is None and cleanup and result["session"]["finished"]
                            and 0 < result["duration_seconds"] <= installed.TOTAL_SECONDS)
        if failure is not None:
            result.update(failure_phase=failure[0], failure_type=failure[1])
        elif not result["passed"]:
            result.update(failure_phase="cleanup", failure_type="IncompleteSession")
    return result


def main(*, fault=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=baseline_evidence.ROLES, required=True)
    parser.add_argument("--expected-source", required=True)
    parser.add_argument("--disposable-emulator-serial")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.role, args.expected_source, args.disposable_emulator_serial, fault=fault)
    # An Android report is provisional until the gateway parent records exact
    # namespace, process, veth and cleanup evidence; the aggregate checker
    # refuses a missing gateway witness.
    baseline_evidence.write_summary(args.output, result)
    print(json.dumps({"passed": result["passed"], "failure_phase": result.get("failure_phase")}))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

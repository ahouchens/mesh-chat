"""Check same-run installed public pair partition reports after gateway cleanup."""

import argparse
import json
import os
from pathlib import Path

import check_public_core_pair as baseline
import public_core_partition_evidence as evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-source", required=True)
    parser.add_argument("--pair-id")
    for name in ("windows-report", "android-report", "windows-bootstrap", "android-distribution", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    summary = {"v": 1, "passed": False, "evidence_level": evidence.LEVEL,
               "scenario": evidence.SCENARIO, "scope": evidence.SCOPE, "reports": {}}
    phase = "admission"
    try:
        environment = os.environ
        if (environment.get("GITHUB_ACTIONS") != "true"
                or environment.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
                or environment.get("GITHUB_JOB") != "public_pair_check"
                or environment.get("PUBLIC_PAIR_SCENARIO") != "partition"
                or environment.get("GITHUB_SHA") != args.expected_source):
            raise ValueError("manual_public_partition_admission")
        fields = {"repository": environment["GITHUB_REPOSITORY"],
            "repository_id": int(environment["GITHUB_REPOSITORY_ID"]),
            "run_id": int(environment["GITHUB_RUN_ID"]),
            "run_attempt": int(environment["GITHUB_RUN_ATTEMPT"]),
            "source_commit": args.expected_source}
        context = baseline.checked_context({**fields, "pair_id": args.pair_id or baseline.pair_id_for(fields)})
        _, tree = baseline.source_identity(args.expected_source)
        summary.update(context=context, source_tree=tree)
        phase = "reports"
        values = {}
        for name in ("windows_report", "android_report", "windows_bootstrap", "android_distribution"):
            values[name], summary["reports"][name] = baseline.read_report(getattr(args, name))
        phase = "producer_inputs"
        inputs = baseline.prerequisite_inputs(values["windows_bootstrap"], values["android_distribution"],
                                              context, tree, summary["reports"])
        phase = "partition_pair"
        needs = json.loads(environment.get("PUBLIC_PAIR_NEEDS", "null"),
                           object_pairs_hook=baseline.unique_object, parse_constant=baseline.reject_constant)
        evidence.verify_pair_reports(values["windows_report"], values["android_report"],
                                     context, tree, inputs, needs)
        summary["passed"] = True
    except Exception:
        summary["failure_phase"] = phase
    baseline.write_summary(args.output, summary)
    print(json.dumps({"passed": summary["passed"], "failure_phase": summary.get("failure_phase")}))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

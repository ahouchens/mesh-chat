"""Restart reports cannot be confused with fresh-pair or broader acceptance."""

from copy import deepcopy
import hashlib
from pathlib import Path
import sys

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import check_public_core_pair as fresh
import public_core_restart_evidence as restart


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def role_flow(role, pair_id):
    other = "android" if role == "windows" else "windows"
    self_destination = "1" * 32 if role == "windows" else "2" * 32
    peer_destination = "2" * 32 if role == "windows" else "1" * 32
    baseline = {"v": 1, "role": role, "pair_id": pair_id,
                "self_destination_sha256": digest(self_destination),
                "peer_destination_sha256": digest(peer_destination),
                "explicit_decision": "request_approved" if role == "windows" else "invitation_accepted",
                "contact_count": 1, "contact_trust": "approved", "messaging_ready": True,
                "pairing_transferred": True, "cancel_preserved_transferred": True,
                "outbound_text_sha256": fresh.text_digest(pair_id, role),
                "outbound_message_count": 1, "outbound_delivered": True,
                "inbound_text_sha256": fresh.text_digest(pair_id, other),
                "inbound_message_count": 1, "public_request_count": 20}
    return {"v": 1, "role": role, "pair_id": pair_id, "baseline": baseline,
            "checks": dict(restart.WINDOWS_CHECKS if role == "windows" else restart.ANDROID_CHECKS),
            "request_counts": ({"baseline": 20, "before_stop": 23, "after_reopen": 12}
                               if role == "windows" else {"baseline": 20, "additional": 18, "total": 38}),
            "post_outbound_text_sha256": restart.post_text_digest(pair_id, role),
            "post_inbound_text_sha256": restart.post_text_digest(pair_id, other),
            "post_outbound_message_count": 1, "post_inbound_message_count": 1}


def evidence_pair():
    fields = {"repository": "ahouchens/mesh-chat", "repository_id": 123, "run_id": 456,
              "run_attempt": 1, "source_commit": "a" * 40}
    context = {**fields, "pair_id": fresh.pair_id_for(fields)}
    tree = "b" * 40
    inputs = {"windows": {"sdk_sha256": "c" * 64}, "android": {"apk_sha256": "d" * 64}}
    reports = {}
    for role in fresh.ROLES:
        reports[role] = {"v": 1, "passed": True, "evidence_level": restart.LEVEL,
                         "scenario": restart.SCENARIO, "scope": restart.SCOPE,
                         "role": role, "context": context, "source_tree": tree,
                         "flow": role_flow(role, context["pair_id"]), "inputs": inputs[role],
                         "session": {"finished": True, "cleanup": True,
                                     "owner_incarnations_finished": 2 if role == "windows" else 1},
                         "duration_seconds": 220.5}
    needs = {name: {"result": "success"} for name in fresh.JOBS}
    return reports, context, tree, inputs, needs


def test_distinct_restart_reports_cross_match_one_source_and_pair():
    reports, context, tree, inputs, needs = evidence_pair()
    assert restart.verify_pair_reports(reports["windows"], reports["android"],
                                       context, tree, inputs, needs)
    with pytest.raises(ValueError, match="public_pair_role"):
        fresh.verify_role(reports["windows"], "windows", context, tree)


@pytest.mark.parametrize("change", [
    lambda report: report.update(scope=fresh.SCOPE),
    lambda report: report["flow"]["checks"].update(positive_owner_stop=False),
    lambda report: report["flow"]["checks"].update(extra=True),
    lambda report: report["flow"]["request_counts"].update(after_reopen=True),
    lambda report: report["flow"].update(post_inbound_text_sha256="0" * 64),
    lambda report: report["session"].update(owner_incarnations_finished=1),
    lambda report: report.update(raw_profile="private"),
])
def test_windows_report_rejects_wrong_scope_checks_counts_and_extra_fields(change):
    reports, context, tree, inputs, _ = evidence_pair()
    report = deepcopy(reports["windows"])
    change(report)
    with pytest.raises(ValueError):
        restart.verify_role_report(report, "windows", context, tree, inputs["windows"])


@pytest.mark.parametrize("count", [126, 127, True])
def test_android_total_must_leave_finish_frame_and_use_integer_count(count):
    reports, context, tree, inputs, _ = evidence_pair()
    report = deepcopy(reports["android"])
    report["flow"]["request_counts"]["total"] = count
    report["flow"]["request_counts"]["additional"] = count - 20 if type(count) is int else 18
    if count == 126:
        assert restart.verify_role_report(report, "android", context, tree, inputs["android"])
    else:
        with pytest.raises(ValueError):
            restart.verify_role_report(report, "android", context, tree, inputs["android"])


def test_aggregate_rejects_cross_role_identity_or_unsuccessful_prerequisite():
    reports, context, tree, inputs, needs = evidence_pair()
    altered = deepcopy(reports["android"])
    altered["flow"]["baseline"]["peer_destination_sha256"] = "e" * 64
    with pytest.raises(ValueError, match="public_restart_cross_match"):
        restart.verify_pair_reports(reports["windows"], altered, context, tree, inputs, needs)
    needs["android"]["result"] = "skipped"
    with pytest.raises(ValueError, match="public_restart_prerequisites"):
        restart.verify_pair_reports(reports["windows"], reports["android"], context, tree, inputs, needs)

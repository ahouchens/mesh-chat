"""Finite open-gap audit: do not silently omit a remaining mutation family."""
import json
from pathlib import Path


def test_open_mutation_audit_covers_exact_manifest_families_and_splits_reads():
    root = Path(__file__).resolve().parents[3]
    manifest = json.loads((root / "contracts/core-api/operations-v1.json").read_text())
    audit = json.loads((root / "contracts/core-api/non-keyed-mutations-v1.json").read_text())
    expected = {item["operation"]: item["idempotency"] for item in manifest["operations"]
                if item.get("mutation") and item.get("idempotency") != "caller_profile_operation_key"}
    assert {row["operation"] for row in audit["rows"]} == set(expected)
    assert audit["family_count"] == len(expected)
    assert len({(row["operation"], row["action"]) for row in audit["rows"]}) == len(audit["rows"]) == audit["action_row_count"]
    assert audit["public_mutation_action_count"] == sum(row["classification"] == "mutation_without_caller_key" for row in audit["rows"])
    for row in audit["rows"]:
        assert row["manifest_idempotency"] == expected[row["operation"]]
        assert row["state"] in {"open_gap", "excluded_from_public_mutation_extension"}
        assert all((root / path).is_file() for path in row["paths"])
    assert {row["action"] for row in audit["rows"] if row["operation"] == "recovery.transfer" and row["classification"] == "mutation_without_caller_key"} == {"export", "import"}
    assert {(row["operation"], row["action"]) for row in audit["rows"] if row["classification"] == "read_only_action"} == {
        ("connection.support", "help"), ("connection.support", "diagnostics"),
        ("connection.document", "preview_direct"), ("connection.document", "preview_reply")}

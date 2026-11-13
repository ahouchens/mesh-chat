from copy import deepcopy
import json

import pytest

from tools.connection_harness.simulation import replay, scenario


def test_saved_json_trace_replays_the_actual_policy_and_resource_oracle():
    report = json.loads(json.dumps(scenario("fault_sequence", 48)))
    result = replay(report)
    assert result["trace"] == report["trace"]
    assert result["cleanup"] == "passed"
    assert result["replayed"]


def test_in_memory_report_replays_without_json_serialization():
    assert replay(scenario("partition_30s"))["replayed"]


@pytest.mark.parametrize("report", [None, [], "trace"])
def test_replay_requires_an_object(report):
    with pytest.raises(ValueError, match="object"):
        replay(report)


@pytest.mark.parametrize("field,value", [("implementation_digest", "old-implementation"),
    ("trace_version", 2), ("contract_version", 2), ("policy", {}), ("trace", []),
    ("trace", [{"type": "advance", "seconds": -1}]),
    ("trace", [{"type": "advance", "seconds": float("nan")}]),
    ("trace", [{"type": "grant_trust", "authorized": True}]),
    ("trace", [{"type": "complete", "index": 0, "fail": False, "duplicate": False, "adopt": False}]),
    ("trace", [{"type": "intent", "enabled": 1}]),
    ("trace", [{"type": "advance", "seconds": 0, "private": "injection"}])])
def test_replay_rejects_incompatible_or_untrusted_trace_data(field, value):
    report = deepcopy(scenario("stale_completion"))
    report[field] = value
    with pytest.raises(ValueError):
        replay(report)

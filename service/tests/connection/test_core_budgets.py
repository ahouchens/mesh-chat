"""Advertised budgets are the executable bounds, not prose."""

from test_core_messages import client, host, request

BUDGETS = {
    "frame_bytes": 4194304,
    "request_json_depth": 16,
    "request_json_structural_tokens": 1024,
    "text_utf8_bytes": 16384,
    "event_batch_count": 128,
    "event_batch_bytes": 1048576,
    "received_scan_count": 128,
    "received_batch_bytes": 1048576,
    "cursor_bytes": 1024,
    "diagnostic_count": 256,
    "diagnostic_bytes": 262144,
}


def test_capabilities_advertise_the_declared_budgets(host):
    service = host()
    session, _, _, _ = client(service)
    capabilities = session.request(request("runtime.capabilities"))["result"]
    assert {name: capabilities["limits"][name] for name in BUDGETS} == BUDGETS


def test_over_budget_parameters_are_rejected_before_work(host):
    service = host()
    session, _, profile, _ = client(service)
    cursor = "x" * (BUDGETS["cursor_bytes"] + 1)
    rejected = (
        request("events.poll", profile=profile, cursor=None,
                limit=BUDGETS["event_batch_count"] + 1),
        request("message.received", profile=profile, cursor=None,
                limit=BUDGETS["received_scan_count"] + 1),
        request("diagnostics.query", profile=profile, limit=BUDGETS["diagnostic_count"] + 1),
        request("message.list", profile=profile, cursor=cursor),
    )
    for vector in rejected:
        response = session.request(vector)
        assert response["error"]["code"] == "invalid_request", vector


def test_budget_edges_are_accepted(host):
    service = host()
    session, _, profile, _ = client(service)
    accepted = (
        request("events.poll", profile=profile, cursor=None,
                limit=BUDGETS["event_batch_count"]),
        request("message.received", profile=profile, cursor=None,
                limit=BUDGETS["received_scan_count"]),
        request("diagnostics.query", profile=profile, limit=BUDGETS["diagnostic_count"]),
    )
    for vector in accepted:
        response = session.request(vector)
        if not response["ok"]:
            assert response["error"]["code"] != "invalid_request", (vector, response)

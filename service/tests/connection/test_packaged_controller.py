"""Qualification must distinguish an expected service denial from host failure."""
from types import SimpleNamespace

import pytest

from tools.connection_harness import packaged_transport_probe as probe


def controller(monkeypatch, response):
    sent = []
    monkeypatch.setattr(probe, "sys", SimpleNamespace(
        stdin=SimpleNamespace(buffer=None), stdout=SimpleNamespace(buffer=None)))
    monkeypatch.setattr(probe, "FrameWriter", lambda _: SimpleNamespace(write=sent.append))
    monkeypatch.setattr(probe, "read_frame", lambda _: response(sent[-1]))
    return probe.Controller(), sent


def test_expected_denial_is_correlated_and_does_not_poison_later_failure_evidence(monkeypatch):
    value, sent = controller(monkeypatch, lambda request: {
        "id": request["id"], "ok": False, "error": "native_unavailable"})
    value.reject(1, "native_webrtc_stats", "native_unavailable", session_id="retired-session")
    assert len(sent) == 1
    assert sent[0]["action"] == "call" and sent[0]["command"] == "native_webrtc_stats"
    assert value.error_code is None and not any(value.counts.values())


@pytest.mark.parametrize("fault", ["accepted", "wrong_error", "wrong_id", "missing_ok", "non_boolean", "not_object"])
def test_protocol_fault_or_unexpected_success_cannot_count_as_expected_denial(monkeypatch, fault):
    def response(request):
        result = {"id": request["id"], "ok": False, "error": "native_unavailable"}
        if fault == "accepted": result.update(ok=True, result={"attached": True})
        elif fault == "wrong_error": result["error"] = "service_stopped"
        elif fault == "wrong_id": result["id"] = "another-request"
        elif fault == "missing_ok": result.pop("ok")
        elif fault == "non_boolean": result["ok"] = 0
        else: return []
        return result
    value, sent = controller(monkeypatch, response)
    with pytest.raises(RuntimeError):
        value.reject(0, "native_webrtc_stats", "native_unavailable", session_id="retired-session")
    assert len(sent) == 1  # No retry after an unknown or unexpected outcome.


def test_failed_start_does_not_increment_process_count_or_export_raw_error(monkeypatch):
    value, _ = controller(monkeypatch, lambda request: {
        "id": request["id"], "ok": False, "error": "private/path and payload"})
    with pytest.raises(RuntimeError, match="Host command failed"):
        value.action(0, "start")
    assert value.error_code is None and value.counts["processes_started"] == 0

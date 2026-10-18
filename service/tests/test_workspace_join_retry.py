from __future__ import annotations

import os
import time
import unicodedata
import uuid

import pytest
import RNS

from mesh_chat.errors import NetworkUnavailable, ValidationError, WorkspaceAlreadyKnown, WorkspaceLimitReached
from mesh_chat.models import DeliveryState
from mesh_chat.participant import create_access_document, create_email_invitation, email_invitation_formats, verify_email_invitation
from mesh_chat.service import _display_name
from mesh_chat.workspace_protocol import verify_workspace_join
from test_workspace_service import _deliver, _flush, _op, _service


@pytest.fixture
def join_pair(tmp_path):
    owner, owner_network = _service(tmp_path / "owner", RNS.Identity(), "Owner")
    identity, key = RNS.Identity(), os.urandom(32)
    joiner, joiner_network = _service(tmp_path / "joiner", identity, "Joiner", vault_key=key)
    workspace = owner.create_workspace(_op(97000), "Test", "")
    invitation = owner.create_workspace_invitation_command(workspace["id"], _op(97001))
    wrapped = create_email_invitation(owner._identity, "workspace", invitation["value"])
    formats = email_invitation_formats(wrapped, "workspace")
    yield owner, owner_network, joiner, joiner_network, workspace, formats, identity, key
    owner.close()
    joiner.close()


def _saved_join(service):
    return {
        kind: service.store.list(kind)
        for kind in ("workspace", "workspace_invitation", "workspace_delivery")
    }


@pytest.mark.parametrize("state", ["active", "joining", "failed"])
def test_invitation_preview_reports_saved_workspace_without_replacing_join(join_pair, state):
    owner, _onet, joiner, _jnet, workspace, formats, *_ = join_pair
    assert "existing_workspace" not in joiner.preview_workspace_invitation(formats["text"])
    joiner.submit_workspace_join(formats["text"], _op(97002))
    stored = joiner._require_workspace(workspace["id"])
    if state == "active":
        stored["state"] = "active"
        joiner.store.put("workspace", joiner._workspace_record_id(workspace["id"]), stored)
    elif state == "failed":
        delivery = joiner.store.get("workspace_delivery", stored["join_delivery_id"])
        delivery["state"] = "failed"
        joiner.store.put("workspace_delivery", delivery["id"], delivery)
    # A fresh nonce for the same workspace must lead to the saved record too.
    replacement = owner.create_workspace_invitation_command(workspace["id"], _op(97007))
    saved = _saved_join(joiner)
    operations = joiner.store.list("workspace_operation")
    for invitation in (formats["text"], replacement["text"]):
        preview = joiner.preview_workspace_invitation(invitation)
        assert preview["existing_workspace"] == joiner._public_workspace(stored)
        assert preview["can_resume_join"] is (state == "joining" and invitation == formats["text"])
        assert "join_delivery_id" not in preview["existing_workspace"]
        assert "genesis" not in preview["existing_workspace"]
        if state == "failed":
            assert preview["existing_workspace"]["join_delivery_state"] == "failed"
    assert _saved_join(joiner) == saved
    assert joiner.store.list("workspace_operation") == operations


def _with_access(owner, formats):
    invitation = verify_email_invitation(formats["text"], "workspace")
    access = create_access_document(
        owner._identity, [{"host": "93.184.216.34", "port": 4242, "path": "pcp"}],
        network_name="join_retry_network", passphrase="join_retry_passphrase_123456789",
        expires_at=int(time.time()) + 3600,
    )
    return create_email_invitation(owner._identity, "workspace", invitation.inner, access)


@pytest.mark.parametrize("name", ["Jose\u0301", "A\u030angstro\u0308m", "\u1100\u1161"])
def test_valid_profile_name_is_normalized_before_signing_join(join_pair, name):
    _owner, _onet, joiner, _jnet, workspace, formats, *_ = join_pair
    # These names are accepted by profile creation, including older stored profiles.
    assert _display_name(name) == name
    profile = joiner._require_profile()
    profile["display_name"] = name
    joiner.store.put("profile", "local", profile)
    preview = joiner.preview_workspace_invitation(formats["text"])
    assert preview["connection_reply_available"] is True
    assert preview["workspace_id"] == workspace["id"]

    result = joiner.submit_workspace_join(formats["text"], _op(97002))

    assert result["state"] == "joining"
    delivery = joiner.store.list("workspace_delivery")[0]
    signed = verify_workspace_join(delivery["document"])
    assert signed.device.display_name == unicodedata.normalize("NFC", name)
    assert joiner._require_profile()["display_name"] == name


@pytest.mark.parametrize("retry_format", ["text", "link", "value"])
def test_join_recovers_lost_post_commit_result_without_new_request(join_pair, monkeypatch, retry_format):
    _owner, _onet, joiner, _jnet, workspace, formats, *_ = join_pair
    assert joiner.preview_workspace_invitation(formats["text"])["workspace_id"] == workspace["id"]

    def lost_result(*args, **kwargs):
        raise ValidationError("simulated post-commit failure")

    with monkeypatch.context() as patch:
        patch.setattr(joiner, "_workspace_changed", lost_result)
        with pytest.raises(ValidationError, match="post-commit"):
            joiner.submit_workspace_join(formats["text"], _op(97002))
    saved = _saved_join(joiner)

    result = joiner.submit_workspace_join(formats[retry_format], _op(97003))

    assert result["state"] == "joining"
    assert result["local_member_id"] == saved["workspace"][0]["local_member_id"]
    assert result["local_device_id"] == saved["workspace"][0]["local_device_id"]
    assert result["join_delivery_state"] == "queued"
    assert result["join_acknowledged"] is False
    assert _saved_join(joiner) == saved
    current = joiner._public_workspace(joiner._require_workspace(workspace["id"]))
    assert joiner.submit_workspace_join(formats[retry_format], _op(97003)) == current


def test_join_reopens_same_pending_request_after_restart(join_pair, tmp_path):
    _owner, _onet, joiner, _jnet, _workspace, formats, identity, key = join_pair
    first = joiner.submit_workspace_join(formats["text"], _op(97002))
    saved = _saved_join(joiner)
    joiner.close()
    restored, _network = _service(tmp_path / "joiner", identity, "Joiner", vault_key=key)
    try:
        current = restored._public_workspace(restored._require_workspace(first["id"]))
        result = restored.submit_workspace_join(formats["text"], _op(97003))
        assert result == current
        assert result["local_member_id"] == first["local_member_id"]
        assert result["local_device_id"] == first["local_device_id"]
        assert _saved_join(restored) == saved
    finally:
        restored.close()


def test_repeated_join_preserves_verified_receipt_and_returns_current_state(join_pair):
    owner, onet, joiner, jnet, workspace, formats, *_ = join_pair
    initial = joiner.submit_workspace_join(formats["text"], _op(97002))
    assert initial["join_acknowledged"] is False
    request = _flush(joiner, jnet)[0]
    _deliver(owner, request, source_profile=joiner._require_profile(), recipient_profile=owner._require_profile())
    receipt = _flush(owner, onet)[0]
    _deliver(joiner, receipt, source_profile=owner._require_profile(), recipient_profile=joiner._require_profile())
    saved = _saved_join(joiner)
    assert saved["workspace"][0]["join_receipt"]

    result = joiner.submit_workspace_join(formats["text"], _op(97003))

    assert result["id"] == workspace["id"]
    assert result["state"] == "joining"
    assert result["join_acknowledged"] is True
    assert result["join_delivery_state"] == DeliveryState.DELIVERED.value
    assert _saved_join(joiner) == saved
    assert _flush(joiner, jnet) == []


@pytest.mark.parametrize("admitted", [False, True])
def test_same_join_operation_replay_reads_current_state_without_repeating_work(join_pair, monkeypatch, admitted):
    owner, onet, joiner, jnet, workspace, formats, *_ = join_pair
    operation_id = _op(97002)
    initial = joiner.submit_workspace_join(formats["text"], operation_id)
    assert initial["join_acknowledged"] is False
    request = _flush(joiner, jnet)[0]
    _deliver(owner, request, source_profile=joiner._require_profile(), recipient_profile=owner._require_profile())
    if admitted:
        request_id = owner.workspace_snapshot()["workspace_join_requests"][0]["id"]
        owner.approve_workspace_join(workspace["id"], request_id, _op(97006))
    for message in _flush(owner, onet):
        _deliver(joiner, message, source_profile=owner._require_profile(), recipient_profile=joiner._require_profile())
    current = joiner._public_workspace(joiner._require_workspace(workspace["id"]))
    assert current["state"] == ("active" if admitted else "joining")
    if not admitted:
        assert current["join_acknowledged"] is True
        assert current["join_delivery_state"] == DeliveryState.DELIVERED.value
    saved = _saved_join(joiner)
    operations = joiner.store.list("workspace_operation")

    def unexpected_work(*args, **kwargs):
        raise AssertionError("An operation replay must only refresh its public result")

    monkeypatch.setattr(joiner, "_prepare_workspace_join_route", unexpected_work)
    monkeypatch.setattr(jnet, "remember_contact", unexpected_work)
    monkeypatch.setattr(joiner, "_workspace_changed", unexpected_work)

    assert joiner.submit_workspace_join(formats["text"], operation_id) == current
    assert _saved_join(joiner) == saved
    assert joiner.store.list("workspace_operation") == operations
    with pytest.raises(ValidationError, match="different input"):
        joiner.submit_workspace_join(formats["link"], operation_id)


@pytest.mark.parametrize(("failure", "new_operation"), [
    ("interrupted", False), ("exception", False),
    ("candidates", False), ("candidates", True),
])
def test_join_replay_preserves_saved_connection_failure(join_pair, monkeypatch, failure, new_operation):
    owner, _onet, joiner, _jnet, _workspace, formats, *_ = join_pair
    raw = _with_access(owner, formats)
    results = [{"candidate": 1, "path": "pcp", "result": "unreachable"}]

    def failed_setup(*args, **kwargs):
        raise NetworkUnavailable("route setup failed")

    def interrupted_setup(*args, **kwargs):
        raise RuntimeError("process interrupted before route setup")

    with monkeypatch.context() as patch:
        if failure == "interrupted":
            patch.setattr(joiner, "_prepare_workspace_join_route", interrupted_setup)
            with pytest.raises(RuntimeError, match="interrupted"):
                joiner.submit_workspace_join(raw, _op(97002))
        elif failure == "exception":
            patch.setattr(joiner, "approve_participant_access", failed_setup)
            assert joiner.submit_workspace_join(raw, _op(97002))["connection_setup_failed"] is True
        else:
            patch.setattr(joiner, "_resolved_participant_endpoints", lambda access: ([], results))
            patch.setattr(joiner, "_apply_participant_interfaces", lambda: None)
            assert joiner.submit_workspace_join(raw, _op(97002))["connection_results"] == results
    saved = _saved_join(joiner)
    accesses = joiner.store.list("participant_access")

    def unexpected_work(*args, **kwargs):
        raise AssertionError("Retry must read the saved route result")

    monkeypatch.setattr(joiner, "approve_participant_access", unexpected_work)
    if not new_operation:
        monkeypatch.setattr(joiner, "_prepare_workspace_join_route", unexpected_work)
    replay = joiner.submit_workspace_join(raw, _op(97003 if new_operation else 97002))

    assert replay["state"] == "joining"
    if failure == "candidates":
        assert replay["connection_results"] == results
        assert "connection_setup_failed" not in replay
    else:
        assert replay["connection_setup_failed"] is True
    assert _saved_join(joiner) == saved
    assert joiner.store.list("participant_access") == accesses


def test_repeated_inner_invitation_does_not_import_new_wrapper_route(join_pair, monkeypatch):
    owner, _onet, joiner, _jnet, _workspace, formats, *_ = join_pair
    joiner.submit_workspace_join(formats["text"], _op(97002))
    raw = _with_access(owner, formats)
    assert joiner.preview_workspace_invitation(raw)["participant_access"]
    saved = _saved_join(joiner)

    def unexpected_consent(*args, **kwargs):
        raise AssertionError("A resumed join must not approve a different wrapper route")

    monkeypatch.setattr(joiner, "approve_participant_access", unexpected_consent)
    result = joiner.submit_workspace_join(raw, _op(97003))

    assert result["state"] == "joining"
    assert _saved_join(joiner) == saved
    assert joiner.store.list("participant_access") == []


@pytest.mark.parametrize("change", [
    "other_invitation", "identity", "member", "device", "missing_delivery",
    "recipient", "saved_invitation", "revoked_invitation", "join_document",
    "failed", "expired", "cancelled", "elapsed_delivery", "unproved_delivery",
    "active", "declined", "removed", "invalid_receipt",
])
def test_repeated_join_rejects_mismatched_or_terminal_saved_request(join_pair, change):
    owner, _onet, joiner, _jnet, workspace, formats, *_ = join_pair
    joiner.submit_workspace_join(formats["text"], _op(97002))
    record_id = joiner._workspace_record_id(workspace["id"])
    stored = joiner.store.get("workspace", record_id)
    delivery = joiner.store.get("workspace_delivery", stored["join_delivery_id"])
    invitation_id, invitation = joiner.store.items("workspace_invitation")[0]
    raw = formats["text"]
    if change == "other_invitation":
        raw = owner.create_workspace_invitation_command(workspace["id"], _op(97004))["text"]
    elif change == "identity":
        joiner._identity = RNS.Identity()
    elif change == "member":
        stored["local_member_id"] = str(uuid.uuid4())
    elif change == "device":
        stored["local_device_id"] = str(uuid.uuid4())
    elif change == "missing_delivery":
        stored["join_delivery_id"] = str(uuid.uuid4())
    elif change == "recipient":
        delivery["recipient_destination"] = "00" * 16
    elif change == "saved_invitation":
        invitation["document"] = "{}"
    elif change == "revoked_invitation":
        invitation["state"] = "revoked"
    elif change == "join_document":
        invitation["join_document"] = delivery["document"] = "{}"
    elif change in {"failed", "expired", "cancelled"}:
        delivery["state"] = change
    elif change == "elapsed_delivery":
        delivery["expires_at"] = time.time() - 1
    elif change == "unproved_delivery":
        delivery["state"] = "delivered"
    elif change == "invalid_receipt":
        stored["join_receipt"] = "{}"
    else:
        stored["state"] = change
    joiner.store.put_many([
        ("workspace", record_id, stored),
        ("workspace_delivery", delivery["id"], delivery),
        ("workspace_invitation", invitation_id, invitation),
    ])
    saved = _saved_join(joiner)
    operation_count = len(joiner.store.list("workspace_operation"))

    preview = joiner.preview_workspace_invitation(raw)
    assert preview["can_resume_join"] is False
    reason = (
        "invitation_mismatch" if change in {"other_invitation", "saved_invitation"}
        else "request_stopped" if change in {"failed", "expired", "cancelled"}
        else "request_expired" if change == "elapsed_delivery"
        else "identity_mismatch" if change in {"identity", "member", "device"}
        else "saved_request_invalid"
    )
    assert preview["join_resume_reason"] == reason

    with pytest.raises(WorkspaceAlreadyKnown) as error:
        joiner.submit_workspace_join(raw, _op(97003))

    assert error.value.code == "workspace_already_known"
    assert _saved_join(joiner) == saved
    assert len(joiner.store.list("workspace_operation")) == operation_count


def test_self_invitation_and_profile_limit_have_actionable_error_codes(join_pair, monkeypatch):
    owner, _onet, joiner, _jnet, _workspace, formats, *_ = join_pair
    with pytest.raises(WorkspaceAlreadyKnown) as known:
        owner.submit_workspace_join(formats["text"], _op(97002))
    assert known.value.code == "workspace_already_known"
    joiner.create_workspace(_op(97005), "Existing local workspace", "")
    monkeypatch.setattr("mesh_chat.workspace_service.MAX_WORKSPACES", 1)
    with pytest.raises(WorkspaceLimitReached) as limit:
        joiner.submit_workspace_join(formats["text"], _op(97003))
    assert limit.value.code == "workspace_limit_reached"

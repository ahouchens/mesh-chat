"""Group preparation must have no delivery scheduling before atomic commit."""
import sys
from pathlib import Path

import RNS

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_group_service import _contact, _service
from mesh_chat.models import MessageKind


def test_pure_delivery_builder_does_not_schedule_or_persist_before_commit(tmp_path):
    member = _contact(RNS.Identity(), "Synthetic member", "member")
    service, network = _service(tmp_path, RNS.Identity(), "Synthetic owner", member)
    try:
        group = {"id": "synthetic-group", "epoch": 1, "manifest_hash": "a" * 64}
        current = service._group_retry_snapshot()
        prepared = service._delivery_record(group=group, recipient=member,
            kind=MessageKind.GROUP_CHAT, text="Synthetic prepared message", queue_retry=False)
        assert service._group_retry_snapshot() == current
        assert service.store.get("group_delivery", prepared["id"]) is None
        assert not network.sent
        legacy = service._delivery_record(group=group, recipient=member, kind=MessageKind.GROUP_CHAT)
        assert legacy["id"] in service._group_retry_snapshot()
    finally:
        service.close()

from __future__ import annotations

import os
import time
import uuid

import LXMF
import pytest
import RNS

from mesh_chat.app_protocol import build_fields, conversation_id, parse_payload
from mesh_chat.errors import ValidationError
from mesh_chat.models import DeliveryState, MessageKind
from mesh_chat.network import map_native_delivery_state


def _message(kind: MessageKind, text: str = "Hello") -> LXMF.LXMessage:
    return LXMF.LXMessage(
        None,
        None,
        content=text,
        fields=build_fields(
            kind=kind,
            logical_id=str(uuid.uuid4()),
            conversation=str(uuid.uuid4()),
            expires_at=int(time.time()) + 60,
            receipt_for=str(uuid.uuid4()) if kind == MessageKind.RECEIPT else None,
        ),
        desired_method=LXMF.LXMessage.DIRECT,
        destination_hash=os.urandom(16),
        source_hash=os.urandom(16),
    )


def test_chat_payload_uses_standard_content_and_custom_fields() -> None:
    message = _message(MessageKind.CHAT)
    parsed = parse_payload(message)
    assert parsed.kind == MessageKind.CHAT
    assert parsed.text == "Hello"


def test_receipt_must_have_empty_content() -> None:
    with pytest.raises(ValidationError):
        parse_payload(_message(MessageKind.RECEIPT, "not empty"))


def test_conversation_id_is_order_independent() -> None:
    first = os.urandom(16)
    second = os.urandom(16)
    assert conversation_id(first, second) == conversation_id(second, first)


def test_native_status_never_overstates_app_delivery() -> None:
    assert map_native_delivery_state(
        LXMF.LXMessage.PROPAGATED, LXMF.LXMessage.SENT
    ) == DeliveryState.STORED_FOR_DELIVERY
    assert map_native_delivery_state(
        LXMF.LXMessage.DIRECT, LXMF.LXMessage.DELIVERED
    ) == DeliveryState.RECEIVED_BY_ENDPOINT
    assert DeliveryState.DELIVERED not in {
        map_native_delivery_state(LXMF.LXMessage.PROPAGATED, LXMF.LXMessage.SENT),
        map_native_delivery_state(LXMF.LXMessage.DIRECT, LXMF.LXMessage.DELIVERED),
    }

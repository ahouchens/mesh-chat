from __future__ import annotations

import os
import threading
from types import SimpleNamespace

import LXMF
import pytest
import RNS

from mesh_chat.errors import NetworkUnavailable, RecipientKeysUnavailable, ValidationError
from mesh_chat.models import DeliveryState
from mesh_chat.network import ReticulumNetwork
from mesh_chat.reticulum_config import NetworkSettings


@pytest.fixture
def sender(monkeypatch):
    local_identity, recipient = RNS.Identity(), RNS.Identity()
    destination = RNS.Destination.hash(recipient, "lxmf", "delivery")
    ratchet = os.urandom(32)
    monkeypatch.setattr(RNS.Identity, "recall", lambda _destination: recipient)
    monkeypatch.setattr(RNS.Identity, "get_ratchet", lambda _destination: ratchet)
    monkeypatch.setattr(RNS.Transport, "has_path", lambda _destination: False)
    requests, callbacks, outbound = [], [], []
    monkeypatch.setattr(RNS.Transport, "request_path", requests.append)
    network = ReticulumNetwork.__new__(ReticulumNetwork)
    network._send_lock = threading.RLock()
    network._message_lock = threading.RLock()
    network._messages = {}
    network.settings = NetworkSettings()
    network.router = SimpleNamespace(
        direct_links={}, backchannel_links={}, handle_outbound=outbound.append
    )
    network.delivery_destination = RNS.Destination(
        local_identity, RNS.Destination.OUT, RNS.Destination.SINGLE, "lxmf", "delivery"
    )
    network._status_callback = lambda *args: callbacks.append(args)
    values = {
        "logical_id": "logical",
        "recipient_public_key": recipient.get_public_key(),
        "recipient_destination": destination,
        "text": "Waiting for a route",
        "fields": {},
    }
    return network, values, requests, callbacks, outbound


@pytest.mark.parametrize("links,status", [
    (None, None),
    ("direct_links", RNS.Link.CLOSED),
    ("backchannel_links", RNS.Link.CLOSED),
    ("direct_links", RNS.Link.PENDING),
])
def test_cached_keys_without_a_usable_route_do_not_begin_a_native_send(sender, links, status):
    network, values, requests, callbacks, outbound = sender
    if links is not None:
        getattr(network.router, links)[values["recipient_destination"]] = SimpleNamespace(status=status)

    with pytest.raises(NetworkUnavailable, match="No route"):
        network.send_with_fields(**values)

    assert requests == [values["recipient_destination"]]
    assert callbacks == []
    assert outbound == []
    assert network._messages == {}


@pytest.mark.parametrize("links", ["direct_links", "backchannel_links"])
def test_active_cached_link_allows_delivery_without_a_transport_path(sender, links):
    network, values, requests, callbacks, outbound = sender
    getattr(network.router, links)[values["recipient_destination"]] = SimpleNamespace(status=RNS.Link.ACTIVE)

    native_id = network.send_with_fields(**values)

    assert requests == []
    assert callbacks == [("logical", DeliveryState.SENDING, native_id)]
    assert len(outbound) == 1
    assert outbound[0].method == LXMF.LXMessage.DIRECT


def test_route_recovery_allows_the_original_payload_to_be_handed_off(sender, monkeypatch):
    network, values, requests, callbacks, outbound = sender
    with pytest.raises(NetworkUnavailable):
        network.send_with_fields(**values)
    monkeypatch.setattr(RNS.Transport, "has_path", lambda _destination: True)

    native_id = network.send_with_fields(**values)

    assert requests == [values["recipient_destination"]]
    assert callbacks == [("logical", DeliveryState.SENDING, native_id)]
    assert len(outbound) == 1
    assert outbound[0].content.decode() == values["text"]


def test_approved_propagation_does_not_require_a_direct_path(sender):
    network, values, requests, callbacks, outbound = sender
    network.settings.approved_propagation_nodes = ["ab" * 16]

    native_id = network.send_with_fields(**values, propagated=True)

    assert requests == []
    assert callbacks == [("logical", DeliveryState.SENDING, native_id)]
    assert outbound[0].method == LXMF.LXMessage.PROPAGATED
    assert outbound[0].ratchet_id is not None


def test_missing_ratchet_still_reports_keys_unavailable(sender, monkeypatch):
    network, values, requests, callbacks, outbound = sender
    monkeypatch.setattr(RNS.Identity, "get_ratchet", lambda _destination: None)
    with pytest.raises(RecipientKeysUnavailable):
        network.send_with_fields(**values)
    assert requests == [values["recipient_destination"]]
    assert callbacks == outbound == []


def test_invalid_recipient_binding_is_rejected_before_route_discovery(sender):
    network, values, requests, callbacks, outbound = sender
    values["recipient_public_key"] = RNS.Identity().get_public_key()
    with pytest.raises(ValidationError, match="Recalled identity"):
        network.send_with_fields(**values)
    assert requests == callbacks == outbound == []


def test_bootstrap_delegation_does_not_depend_on_the_parent_transport_path(sender):
    network, values, requests, callbacks, outbound = sender
    delegated = []
    network._direct_bootstrap = SimpleNamespace(
        ready=True,
        handles=lambda *_args: True,
        send=lambda **kwargs: delegated.append(kwargs) or "bootstrap-native",
    )

    assert network.send_with_fields(**values) == "bootstrap-native"
    assert delegated == [{**values, "propagated": False}]
    assert requests == callbacks == outbound == []

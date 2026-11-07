"""Validate private transport observations without granting adoption authority."""
from copy import deepcopy
from hashlib import sha256
import re

from .errors import NativeUnavailable


CHANNEL_STATES = {"connecting", "open", "closing", "closed"}
CHANNELS = {"mesh-reticulum", "meshchat-reconnect", "mesh-onboarding"}
RESOURCE_FIELDS = {"resource", "ice_policy", "pending", "ice_connection_state", "signaling_state",
                   "data_channel_state", "channels", "local_type", "remote_type",
                   "local_sdp_sha256", "remote_sdp_sha256"}


def normalized_sdp(sdp):
    return tuple(line for line in sdp.splitlines() if line and line != "a=end-of-candidates")


def description_hash(sdp):
    return sha256("\n".join(normalized_sdp(sdp)).encode("utf-8")).hexdigest()


def matches_binding(binding, epoch, resource):
    return bool(resource is not None and epoch == binding.adapter_epoch
                and resource["resource"] == binding.resource and not resource["pending"]
                and resource["data_channel_state"] == "open" and resource["signaling_state"] == "stable"
                and resource["ice_connection_state"] in {"connected", "completed"}
                and resource["ice_policy"] == binding.ice_policy and resource["local_type"] == binding.local_type
                and resource["remote_type"] == ("answer" if binding.local_type == "offer" else "offer")
                and resource["local_sdp_sha256"] == binding.local_hash
                and resource["remote_sdp_sha256"] == binding.remote_hash)


def _hex(value, length):
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{" + str(length) + r"}", value) is not None


def _resource(value):
    if (not isinstance(value, dict) or set(value) != RESOURCE_FIELDS
            or not isinstance(value["resource"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value["resource"])
            or value["ice_policy"] not in {"all", "relay"} or type(value["pending"]) is not bool
            or value["ice_connection_state"] not in {"new", "checking", "connected", "completed", "disconnected", "failed", "closed"}
            or value["signaling_state"] not in {"stable", "have-local-offer", "have-remote-offer", "have-local-pranswer", "have-remote-pranswer", "closed"}
            or value["data_channel_state"] not in CHANNEL_STATES):
        raise ValueError()
    for side in ("local", "remote"):
        role, digest = value[side + "_type"], value[side + "_sdp_sha256"]
        if not ((role is None and digest is None) or (role in {"offer", "answer"} and _hex(digest, 64))):
            raise ValueError()
    if value["local_type"] is not None and value["local_type"] == value["remote_type"]:
        raise ValueError()
    channels = value["channels"]
    if not isinstance(channels, list) or len(channels) > 3:
        raise ValueError()
    labels = set()
    for channel in channels:
        if (not isinstance(channel, dict) or set(channel) != {"label", "state"}
                or channel["label"] not in CHANNELS or channel["state"] not in CHANNEL_STATES
                or channel["label"] in labels):
            raise ValueError()
        labels.add(channel["label"])
    packet_state = next((channel["state"] for channel in channels if channel["label"] == "mesh-reticulum"), "connecting")
    if packet_state != value["data_channel_state"]:
        raise ValueError()


def validate_inventory(value):
    try:
        if (not isinstance(value, dict) or set(value) != {"v", "adapter_epoch", "resources"}
                or type(value["v"]) is not int or value["v"] != 1 or not _hex(value["adapter_epoch"], 32)
                or not isinstance(value["resources"], list) or len(value["resources"]) > 16):
            raise ValueError()
        resources = set()
        for record in value["resources"]:
            _resource(record)
            if record["resource"] in resources:
                raise ValueError()
            resources.add(record["resource"])
        return deepcopy(value)
    except (KeyError, TypeError, ValueError):
        raise NativeUnavailable("Desktop transport inventory is invalid") from None

"""Encrypted binding evidence; never proof of current carrier or caller authority."""
from dataclasses import asdict, dataclass
import re
from uuid import uuid4

from .errors import ContactNotApproved, NativeUnavailable, StorageUnavailable


@dataclass(frozen=True)
class CarrierBinding:
    resource: str
    adapter_epoch: str
    profile_id: str
    contact_id: str
    scope: str
    workspace_id: str | None
    local_device: str
    remote_device: str
    peer_destination: str
    ice_policy: str
    local_type: str
    local_hash: str
    remote_hash: str

    def __post_init__(self):
        identifiers = (self.profile_id, self.contact_id, self.local_device, self.remote_device)
        if (any(not isinstance(value, str) or not 1 <= len(value) <= 256 for value in identifiers)
                or self.scope not in {"contact", "workspace"}
                or self.ice_policy not in {"all", "relay"} or self.local_type not in {"offer", "answer"}
                or not isinstance(self.resource, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", self.resource)):
            raise ValueError("Invalid carrier binding")
        for value, size in ((self.adapter_epoch, 32), (self.peer_destination, 32),
                            (self.local_hash, 64), (self.remote_hash, 64)):
            if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{" + str(size) + "}", value):
                raise ValueError("Invalid carrier digest or identity")
        if self.scope == "workspace":
            if not isinstance(self.workspace_id, str) or not 1 <= len(self.workspace_id) <= 256:
                raise ValueError("Missing workspace binding")
        elif self.workspace_id is not None:
            raise ValueError("Unexpected workspace binding")

    def matches_authority(self, authority):
        return (authority is None or authority in (self.profile_id, self.contact_id)
                or (self.scope == "workspace" and authority == ("workspace", self.workspace_id)))


class CarrierJournal:
    """One bounded sealed record, updated with the vault's atomic callback API."""

    def __init__(self, store):
        self.store = store

    @staticmethod
    def _decode(value):
        if value is None:
            return {"v": 1, "revision": uuid4().hex, "bindings": []}
        try:
            if (not isinstance(value, dict) or set(value) != {"v", "revision", "bindings"}
                    or type(value["v"]) is not int or value["v"] != 1
                    or not isinstance(value["revision"], str) or not re.fullmatch(r"[a-f0-9]{32}", value["revision"])
                    or not isinstance(value["bindings"], list) or len(value["bindings"]) > 16):
                raise ValueError()
            records = [CarrierBinding(**record) for record in value["bindings"]]
            if len({record.resource for record in records}) != len(records):
                raise ValueError()
            return value
        except (TypeError, ValueError):
            raise StorageUnavailable("Carrier recovery journal is invalid") from None

    def _update(self, change):
        return self.store.update_record("native_carrier_recovery", "current",
                                        lambda value: change(self._decode(value)))

    def revision(self):
        value = self.store.get("native_carrier_recovery", "current")
        return (self._decode(value) if value is not None else self._update(lambda record: record))["revision"]

    def bindings(self):
        value = self._decode(self.store.get("native_carrier_recovery", "current"))
        return tuple(CarrierBinding(**record) for record in value["bindings"])

    def save(self, binding, expected_revision):
        # Reconstruct even private inputs: an arbitrary mapping cannot add live
        # state, credentials or an authorization claim to the sealed record.
        record = asdict(CarrierBinding(**asdict(binding)))
        def change(value):
            if value["revision"] != expected_revision:
                raise ContactNotApproved("Carrier recovery authority changed")
            # The private host pins one adapter incarnation. A newly attested
            # incarnation cannot contain physical resources from its predecessor.
            value = {**value, "bindings": [item for item in value["bindings"]
                                            if item["adapter_epoch"] == binding.adapter_epoch]}
            existing = next((item for item in value["bindings"] if item["resource"] == binding.resource), None)
            if existing is not None:
                if existing != record:
                    raise ContactNotApproved("Carrier recovery resource is already bound")
                return value
            if len(value["bindings"]) >= 16:
                raise NativeUnavailable("Carrier recovery journal is full")
            return {**value, "bindings": [*value["bindings"], record]}
        self._update(change)

    def _remove(self, predicate):
        def change(value):
            return {**value, "revision": uuid4().hex,
                    "bindings": [record for record in value["bindings"] if not predicate(CarrierBinding(**record))]}
        self._update(change)

    def invalidate(self, authority=None):
        self._remove(lambda record: record.matches_authority(authority))

    def reconcile(self, retained, expected_revision):
        records = [asdict(binding) for binding in retained]
        def change(value):
            if value["revision"] != expected_revision or any(record not in value["bindings"] for record in records):
                raise ContactNotApproved("Carrier recovery authority changed")
            if len({record["resource"] for record in records}) != len(records):
                raise ContactNotApproved("Carrier recovery selection is ambiguous")
            return {**value, "revision": uuid4().hex, "bindings": records}
        self._update(change)

    def retire(self, resource):
        self._remove(lambda record: record.resource == resource)

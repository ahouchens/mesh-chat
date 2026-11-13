"""Selected public result types; extra additive minor fields may be ignored."""
from typing import Literal, TypedDict


class Acceptance(TypedDict):
    profile: str
    message: str
    accepted: Literal[True]
    accepted_at: float
    idempotency_expires_at: float


class ProfileEntry(TypedDict):
    profile: str
    display_name: str
    selected: bool
    state: Literal["locked", "unlocked", "retiring"]


class ProfileCatalog(TypedDict):
    profiles: list[ProfileEntry]
    selected_profile: str | None
    revision: int


class Composer(TypedDict):
    profile: str
    peer: str
    revision: str | None
    text: str
    update_key: str
    last_send: dict | None
    send_lookup: dict | None


class ComposerUpdate(TypedDict):
    applied_revision: str
    changed: bool
    composer: Composer


class DraftAcceptance(Acceptance):
    peer: str
    draft_revision: str
    draft_disposition: Literal["cleared", "superseded"]
    composer: Composer

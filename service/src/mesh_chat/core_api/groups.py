"""Typed group summary port."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class GroupObservation:
    group_id: str
    name: str
    posting_policy: str


class Groups(Protocol):
    def list(self, profile: str) -> list[GroupObservation]: ...
    def create(self, profile: str, title: str, member_ids: list[str],
               posting_policy: str) -> GroupObservation: ...

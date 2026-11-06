"""Typed group port."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class GroupObservation:
    group_id: str
    name: str
    posting_policy: str


@dataclass(frozen=True)
class GroupMessageObservation:
    text: str


class Groups(Protocol):
    def list(self, profile: str) -> list[GroupObservation]: ...

    def create(self, profile: str, title: str, member_ids: list[str],
               posting_policy: str) -> GroupObservation: ...

    def send(self, profile: str, group_id: str, text: str) -> GroupMessageObservation: ...

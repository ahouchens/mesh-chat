"""Narrow ports for workspace invitation preview and joining."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class WorkspacePreview:
    name: str
    description: str
    member_count: int
    retention_days: int
    expires_at: float
    requires_i2p_consent: bool


@dataclass(frozen=True)
class WorkspaceJoin:
    workspace: str
    name: str
    state: str


class WorkspaceRelationships(Protocol):
    def preview(self, profile: str, document: str) -> WorkspacePreview: ...

    def join(self, profile: str, document: str, operation_id: str) -> WorkspaceJoin: ...

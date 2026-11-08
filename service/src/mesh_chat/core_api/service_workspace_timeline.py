"""Typed workspace timeline queries and mutations.

The Core facade exposes two use cases rather than one RPC per legacy renderer
command. Both stay workspace-scoped and delegate policy to the service.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class WorkspaceTimeline(Protocol):
    def query(self, profile: str, workspace: str, view: str, params: dict[str, Any]) -> dict: ...

    def mutate(self, profile: str, workspace: str, action: str,
               params: dict[str, Any], operation_id: str) -> dict: ...


@dataclass
class ServiceWorkspaceTimeline:
    service: Any
    store: Any

    def query(self, profile, workspace_id, view, params):
        if view == "channel_messages":
            return self.service.list_workspace_messages(
                workspace_id, params["channel"], params.get("cursor"),
                params.get("limit", 50))
        if view == "direct_messages":
            return self.service.list_workspace_messages(
                workspace_id, params["conversation"], params.get("cursor"),
                params.get("limit", 50))
        if view == "threads":
            return self.service.list_workspace_threads(
                workspace_id, params.get("cursor"), params.get("limit", 50))
        if view == "thread_messages":
            return self.service.list_workspace_thread_messages(
                workspace_id, params["thread_root"], params.get("cursor"),
                params.get("limit", 50))
        if view == "mentions":
            return self.service.list_workspace_mentions(
                workspace_id, params.get("cursor"), params.get("limit", 50))
        if view == "search":
            return self.service.search_workspace(
                workspace_id, params["query"], params.get("scope", "all"),
                params.get("cursor"), params.get("limit", 25))
        raise ValueError("unsupported timeline view")

    def mutate(self, profile, workspace_id, action, params, operation_id):
        if action == "channel_message":
            return self.service.send_workspace_message(
                workspace_id, params["conversation"], params["text"],
                params["event_id"], operation_id, params.get("mention_member_ids"))
        if action == "direct_message":
            return self.service.send_workspace_direct_message(
                workspace_id, params["conversation"], params["text"],
                params["event_id"], operation_id, params.get("mention_member_ids"))
        if action == "thread_reply":
            return self.service.send_workspace_thread_reply(
                workspace_id, params["conversation"], params["thread_root"],
                params["text"], params["event_id"], operation_id)
        if action == "thread_read":
            return self.service.mark_workspace_thread_read(
                workspace_id, params["thread_root"], params["high_water"], operation_id)
        if action == "mentions_read":
            return self.service.mark_workspace_mentions_read(
                workspace_id, params["high_water"], operation_id)
        if action in {"workspace_read", "direct_read"}:
            channel_id = params["conversation"] if action == "direct_read" else params["channel"]
            return self.service.mark_workspace_read(
                workspace_id, channel_id, params["high_water"], operation_id)
        if action == "notification_preference":
            return self.service.set_workspace_notification_preference(
                workspace_id, params["conversation"], params["mode"], operation_id)
        raise ValueError("unsupported timeline action")

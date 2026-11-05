"""Strict synchronous client for the private core API frame contract.

Hosts and tools supply the stream; this module never opens a socket, starts a
runtime or authenticates a caller. It exists so the production CLI and Python
tooling can use the same versioned frames as any other consumer.
"""

from .compatibility import check_capabilities
from .limits import MAX_FRAME_BYTES
from .wire_codec import decode_frame, encode_frame


class CoreClientError(Exception):
    """A typed failure from the facade or from the frame contract."""

    def __init__(self, code, request_id=None, retry_after_ms=None):
        super().__init__(code)
        self.code = code
        self.request_id = request_id
        self.retry_after_ms = retry_after_ms


class CoreClient:
    def __init__(self, readline, write):
        if not callable(readline) or not callable(write):
            raise ValueError("A core client needs stream callbacks")
        self._readline = readline
        self._write = write
        self._sequence = 0
        self._capabilities = None

    @classmethod
    def open(cls, readline, write):
        client = cls(readline, write)
        capabilities = client.request("runtime.capabilities", {})
        try:
            check_capabilities(capabilities)
        except ValueError as error:
            raise CoreClientError("incompatible_version") from error
        client._capabilities = capabilities
        return client

    @property
    def capabilities(self):
        if self._capabilities is None:
            raise CoreClientError("unauthenticated")
        return self._capabilities

    def request(self, operation, params=None, *, idempotency_key=None):
        if not isinstance(operation, str) or not operation:
            raise ValueError("Operation name is required")
        self._sequence += 1
        request_id = f"client:{self._sequence}"
        value = {"api_version": 1, "request_id": request_id, "operation": operation,
                 "params": {} if params is None else params}
        if idempotency_key is not None:
            value["idempotency_key"] = idempotency_key
        self._write(encode_frame(value))
        frame = self._readline(MAX_FRAME_BYTES + 1)
        if not frame:
            raise CoreClientError("transport_closed", request_id)
        try:
            response = decode_frame(frame)
        except (TypeError, ValueError) as error:
            raise CoreClientError("protocol", request_id) from error
        if (not isinstance(response, dict) or response.get("api_version") != 1
                or response.get("request_id") != request_id
                or type(response.get("ok")) is not bool):
            raise CoreClientError("protocol", request_id)
        if response["ok"]:
            if "result" not in response:
                raise CoreClientError("protocol", request_id)
            return response["result"]
        error = response.get("error")
        if not isinstance(error, dict) or not isinstance(error.get("code"), str):
            raise CoreClientError("protocol", request_id)
        raise CoreClientError(error["code"], request_id, error.get("retry_after_ms"))

    def application_command(self, command, payload):
        return self.request("application.command", {"command": command, "payload": payload})

    def application_snapshot(self):
        return self.request("application.snapshot", {})

    def profile(self, handle=None):
        profile = handle or self.capabilities["profiles"][0]
        return self.request("profile.query", {"profile": profile})

    def received(self, handle, cursor=None, limit=128):
        return self.request("message.received", {"profile": handle, "cursor": cursor, "limit": limit})

    def poll(self, handle, cursor=None, limit=128):
        return self.request("events.poll", {"profile": handle, "cursor": cursor, "limit": limit})

    def enqueue(self, handle, recipient, text, key):
        return self.request("message.enqueue",
                            {"profile": handle, "recipient": recipient, "kind": "text", "text": text},
                            idempotency_key=key)

    def acknowledge(self, handle, cursor, key):
        return self.request("events.ack", {"profile": handle, "cursor": cursor}, idempotency_key=key)

    def diagnostics(self, handle, limit=256):
        return self.request("diagnostics.query", {"profile": handle, "limit": limit})

    def message_query(self, handle, message):
        return self.request("message.query", {"profile": handle, "message": message})

    def message_list(self, handle, cursor=None, limit=128):
        if type(limit) is not int or not 1 <= limit <= 128:
            raise ValueError("Message list limit is invalid")
        return self.request("message.list",
                            {"profile": handle, "cursor": cursor, "limit": limit})

    def connection_start(self, handle, peer):
        return self.request("connection.start", {"profile": handle, "peer": peer})

    def connection_stop(self, handle, peer):
        return self.request("connection.stop", {"profile": handle, "peer": peer})

    def connection_snapshot(self, handle, connection):
        return self.request("connection.snapshot",
                            {"profile": handle, "connection": connection})

    def peer_query(self, handle, peer):
        return self.request("peer.query", {"profile": handle, "peer": peer})

    def approve(self, handle, peer):
        return self.request("peer.approve", {"profile": handle, "peer": peer})

    def unblock(self, handle, peer):
        return self.request("peer.unblock", {"profile": handle, "peer": peer})

    def delete_peer(self, handle, peer):
        return self.request("peer.delete", {"profile": handle, "peer": peer})

    def revoke(self, handle, peer):
        return self.request("peer.revoke", {"profile": handle, "peer": peer})

    def pairing_create(self, handle, **options):
        return self.request("peer.pairing_create", {"profile": handle, **options})

    def pairing_request(self, handle, peer):
        return self.request("peer.pairing_request", {"profile": handle, "peer": peer})

    def workspace_preview(self, handle, document):
        if not isinstance(document, str) or not document:
            raise ValueError("Workspace invitation is required")
        return self.request("workspace.invitation_preview",
                            {"profile": handle, "document": document})

    def workspace_channels(self, handle, workspace):
        return self.request("workspace.channels", {"profile": handle, "workspace": workspace})

    def workspace_invitation_create(self, handle, workspace, key,
                                    connection_mode=None, i2p_access_point=None,
                                    i2p_label=None):
        params = {"profile": handle, "workspace": workspace}
        if connection_mode is not None:
            params["connection_mode"] = connection_mode
        if i2p_access_point is not None:
            params["i2p_access_point"] = i2p_access_point
        if i2p_label is not None:
            params["i2p_label"] = i2p_label
        return self.request("workspace.invitation_create", params,
                            idempotency_key=key)

    def workspace_channel_create(self, handle, workspace, name, key, *,
                                 visibility="public", members=None):
        if not isinstance(name, str) or not 1 <= len(name) <= 64:
            raise ValueError("Channel name is invalid")
        if visibility not in {"public", "private"}:
            raise ValueError("Channel visibility is invalid")
        if not isinstance(key, str) or len(key) < 16:
            raise ValueError("Channel creation requires a caller-scoped key")
        params = {"profile": handle, "workspace": workspace, "name": name,
                  "visibility": visibility}
        if visibility == "private":
            if not members or not 1 <= len(members) <= 8:
                raise ValueError("Private channels require one to eight members")
            params["members"] = list(members)
        elif members:
            raise ValueError("Public channels do not take a member list")
        return self.request("workspace.channel_create", params, idempotency_key=key)

    def workspace_device_link_create(self, handle, workspace, key):
        if not isinstance(key, str) or len(key) < 16:
            raise ValueError("Device links require a caller-scoped key")
        return self.request("workspace.device_link_create",
                            {"profile": handle, "workspace": workspace},
                            idempotency_key=key)

    def workspace_device_links(self, handle, workspace):
        return self.request("workspace.device_links",
                            {"profile": handle, "workspace": workspace})

    def workspace_device_link_approve(self, handle, workspace, request_handle, key):
        return self._device_link_decision("workspace.device_link_approve", handle,
                                          workspace, request_handle, key)

    def workspace_device_link_decline(self, handle, workspace, request_handle, key):
        return self._device_link_decision("workspace.device_link_decline", handle,
                                          workspace, request_handle, key)

    def _device_link_decision(self, operation, handle, workspace, request_handle, key):
        if not isinstance(key, str) or len(key) < 16:
            raise ValueError("Device-link decisions require a caller-scoped key")
        return self.request(operation,
                            {"profile": handle, "workspace": workspace,
                             "request": request_handle},
                            idempotency_key=key)

    def workspace_device_link_submit(self, handle, document, key):
        if not isinstance(document, str) or not document:
            raise ValueError("Device link material is required")
        if not isinstance(key, str) or len(key) < 16:
            raise ValueError("Device link submission requires a caller-scoped key")
        return self.request("workspace.device_link_submit",
                            {"profile": handle, "document": document},
                            idempotency_key=key)

    def workspace_device_link_preview(self, handle, document):
        if not isinstance(document, str) or not document:
            raise ValueError("Device link material is required")
        return self.request("workspace.device_link_preview",
                            {"profile": handle, "document": document})

    def workspace_channel_members(self, handle, workspace, channel):
        return self.request("workspace.channel_members",
                            {"profile": handle, "workspace": workspace, "channel": channel})

    def workspace_channel_members_update(self, handle, workspace, channel, members, key):
        if not isinstance(members, list) or not 1 <= len(members) <= 8:
            raise ValueError("Channel membership is invalid")
        if not isinstance(key, str) or len(key) < 16:
            raise ValueError("Channel membership requires a caller-scoped key")
        return self.request("workspace.channel_members_update",
                            {"profile": handle, "workspace": workspace,
                             "channel": channel, "members": members},
                            idempotency_key=key)

    def workspace_devices(self, handle, workspace):
        return self.request("workspace.devices",
                            {"profile": handle, "workspace": workspace})

    def workspace_device_remove(self, handle, workspace, device, key):
        if not isinstance(key, str) or len(key) < 16:
            raise ValueError("Device removal requires a caller-scoped key")
        return self.request("workspace.device_remove",
                            {"profile": handle, "workspace": workspace, "device": device},
                            idempotency_key=key)

    def workspace_policy_update(self, handle, workspace, channel_creation, posting,
                                invitation_requests, key):
        allowed_creation = {"all_members", "owner_and_admins"}
        if channel_creation not in allowed_creation or posting not in allowed_creation:
            raise ValueError("Workspace policy is invalid")
        if invitation_requests not in {"owner_only", "owner_and_admins",
                                       "all_members_request"}:
            raise ValueError("Invitation policy is invalid")
        if not isinstance(key, str) or len(key) < 16:
            raise ValueError("Workspace policies require a caller-scoped key")
        return self.request("workspace.policy_update",
                            {"profile": handle, "workspace": workspace,
                             "channel_creation": channel_creation, "posting": posting,
                             "invitation_requests": invitation_requests},
                            idempotency_key=key)

    def workspace_channel_transfer_offer(self, handle, workspace, channel, member, key):
        if not isinstance(key, str) or len(key) < 16:
            raise ValueError("Channel transfers require a caller-scoped key")
        return self.request("workspace.channel_transfer_offer",
                            {"profile": handle, "workspace": workspace,
                             "channel": channel, "member": member},
                            idempotency_key=key)

    def workspace_channel_transfer_accept(self, handle, workspace, channel, key):
        if not isinstance(key, str) or len(key) < 16:
            raise ValueError("Channel transfers require a caller-scoped key")
        return self.request("workspace.channel_transfer_accept",
                            {"profile": handle, "workspace": workspace,
                             "channel": channel},
                            idempotency_key=key)

    def workspace_channel_archive(self, handle, workspace, channel, key):
        if not isinstance(key, str) or len(key) < 16:
            raise ValueError("Channel archive requires a caller-scoped key")
        return self.request("workspace.channel_archive",
                            {"profile": handle, "workspace": workspace, "channel": channel},
                            idempotency_key=key)

    def workspace_channel_update(self, handle, workspace, channel, name, topic, key,
                                 posting=None):
        if not isinstance(name, str) or not 1 <= len(name) <= 64:
            raise ValueError("Channel name is invalid")
        if not isinstance(topic, str) or len(topic) > 1024:
            raise ValueError("Channel topic is invalid")
        if posting is not None and posting not in {
                "inherit", "all_members", "owner_and_admins"}:
            raise ValueError("Channel posting policy is invalid")
        if not isinstance(key, str) or len(key) < 16:
            raise ValueError("Channel edits require a caller-scoped key")
        params = {"profile": handle, "workspace": workspace, "channel": channel,
                  "name": name, "topic": topic}
        if posting is not None:
            params["posting"] = posting
        return self.request("workspace.channel_update", params, idempotency_key=key)

    def workspace_list(self, handle):
        return self.request("workspace.query", {"profile": handle})

    def workspace_join_requests(self, handle, workspace):
        return self.request("workspace.join_requests",
                            {"profile": handle, "workspace": workspace})

    def workspace_join_approve(self, handle, workspace, request_handle, key):
        if not isinstance(key, str) or len(key) < 16:
            raise ValueError("Workspace approvals require a caller-scoped key")
        return self.request("workspace.join_approve",
                            {"profile": handle, "workspace": workspace,
                             "request": request_handle},
                            idempotency_key=key)

    def workspace_members(self, handle, workspace):
        return self.request("workspace.members", {"profile": handle, "workspace": workspace})

    def workspace_join_decline(self, handle, workspace, request_handle, key):
        if not isinstance(key, str) or len(key) < 16:
            raise ValueError("Workspace declines require a caller-scoped key")
        return self.request("workspace.join_decline",
                            {"profile": handle, "workspace": workspace,
                             "request": request_handle},
                            idempotency_key=key)

    def workspace_member_role(self, handle, workspace, member, role, key):
        if role not in {"admin", "member"}:
            raise ValueError("Workspace role is invalid")
        if not isinstance(key, str) or len(key) < 16:
            raise ValueError("Role changes require a caller-scoped key")
        return self.request("workspace.member_role",
                            {"profile": handle, "workspace": workspace,
                             "member": member, "role": role},
                            idempotency_key=key)

    def workspace_join(self, handle, document):
        if not isinstance(document, str) or not document:
            raise ValueError("Workspace joins require signed material")
        return self.request("workspace.join", {"profile": handle, "document": document})

    def pairing_accept(self, handle, document):
        if not isinstance(document, str) or not document:
            raise ValueError("Signed pairing material is required")
        return self.request("peer.pairing_accept", {"profile": handle, "document": document})

    def stop(self):
        return self.request("runtime.stop", {})

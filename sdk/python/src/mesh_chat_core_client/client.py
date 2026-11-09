"""Strict synchronous client for the private core API frame contract.

Hosts and tools supply the stream; this module never opens a socket, starts a
runtime or authenticates a caller. It exists so the production CLI and Python
tooling can use the same versioned frames as any other consumer.
"""

from .compatibility import check_capabilities
import re
from .limits import MAX_FRAME_BYTES
from .framing import decode_frame, encode_frame


from .errors import CoreClientError
from .protocol import needs_key


class CoreClient:
    """Serial protocol client; callers own authenticated streams and credentials."""

    def __init__(self, readline, write, close=None):
        import threading
        if not callable(readline) or not callable(write):
            raise ValueError("A core client needs stream callbacks")
        self._readline, self._write, self._close_callback = readline, write, close
        self._sequence, self._capabilities, self._closed = 0, None, False
        self._lock = threading.Lock()

    @classmethod
    def open(cls, readline, write, close=None):
        client = cls(readline, write, close)
        capabilities = client.request("runtime.capabilities", {})
        try:
            check_capabilities(capabilities)
        except ValueError as error:
            client.close()
            raise CoreClientError("incompatible_version") from error
        client._capabilities = capabilities
        return client

    @property
    def capabilities(self):
        if self._capabilities is None:
            raise CoreClientError("negotiation_required")
        return self._capabilities

    def close(self):
        if not self._closed:
            self._closed = True
            if self._close_callback is not None:
                self._close_callback()

    def request(self, operation, params=None, *, idempotency_key=None):
        with self._lock:
            return self._request(operation, params, idempotency_key)

    def _request(self, operation, params, key):
        if self._closed:
            raise CoreClientError("transport_closed")
        if not isinstance(operation, str) or not operation:
            raise ValueError("Operation name is required")
        if (key is not None or needs_key(operation, params)) and (not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{16,128}", key)):
            raise ValueError("Operation requires a caller-provided idempotency_key")
        self._sequence += 1
        request_id = f"client:{self._sequence}"
        value = {"api_version": 1, "request_id": request_id, "operation": operation,
                 "params": {} if params is None else params}
        if key is not None:
            value["idempotency_key"] = key
        frame = encode_frame(value)
        try:
            offset = 0
            while offset < len(frame):
                written = self._write(frame[offset:])
                if written is None:
                    offset = len(frame)
                elif type(written) is int and 0 < written <= len(frame) - offset:
                    offset += written
                else:
                    raise OSError("Invalid stream write")
            reply = self._readline(MAX_FRAME_BYTES + 1)
        except (OSError, EOFError, TimeoutError) as error:
            self.close()
            raise CoreClientError("transport_closed", request_id) from error
        if not reply:
            self.close()
            raise CoreClientError("transport_closed", request_id)
        try:
            response = decode_frame(reply)
            if (not isinstance(response, dict) or type(response.get("api_version")) is not int
                    or response["api_version"] != 1 or type(response.get("ok")) is not bool):
                raise ValueError("Invalid response envelope")
            failure = response.get("error")
            if response.get("request_id") != request_id:
                self.close()
                if (response.get("request_id") is None and response["ok"] is False and isinstance(failure, dict)
                        and failure.get("code") in {"forbidden", "invalid_request", "resource_exhausted", "unavailable"}):
                    retry = failure.get("retry_after_ms")
                    if retry is not None and (type(retry) is not int or not 0 <= retry <= 3600000):
                        raise ValueError("Invalid admission retry hint")
                    raise CoreClientError(failure["code"], None, failure.get("retry_after_ms"))
                raise ValueError("Uncorrelated response")
            if response["ok"]:
                if "result" not in response:
                    raise ValueError("Missing result")
                return response["result"]
            if (not isinstance(failure, dict) or not isinstance(failure.get("code"), str)
                    or not 1 <= len(failure["code"]) <= 80):
                raise ValueError("Invalid error")
            retry = failure.get("retry_after_ms")
            if retry is not None and (type(retry) is not int or not 0 <= retry <= 3600000):
                raise ValueError("Invalid retry hint")
        except (TypeError, ValueError) as error:
            self.close()
            raise CoreClientError("protocol", request_id) from error
        error = CoreClientError(failure["code"], request_id, retry)
        error.details = dict(failure)
        raise error

    def _require_composer(self):
        caps = self.capabilities
        names = ("composer_text_utf8_bytes", "composers_per_caller_profile", "composers_per_vault",
                 "composer_update_idempotency_seconds", "composer_update_keys_per_caller_profile",
                 "composer_update_keys_per_vault", "composer_send_idempotency_seconds",
                 "composer_send_keys_per_caller_profile", "composer_send_keys_per_vault")
        limits, operations = caps.get("limits"), caps.get("operations")
        if (type(caps.get("api_minor")) is not int or caps["api_minor"] < 1
                or not isinstance(operations, list) or not isinstance(limits, dict)
                or not {"peer.composer_query", "peer.composer_update", "message.enqueue_draft"} <= set(operations)
                or any(type(limits.get(name)) is not int or not 0 < limits[name] <= 9007199254740991 for name in names)):
            raise CoreClientError("unsupported_operation")

    def application_snapshot(self):
        return self.request("application.snapshot", {})

    def _require_profile_runtime(self):
        operations = {"profile.catalog", "profile.lock", "profile.select", "profile.unlock"}
        limits = ("profile_slots", "profile_lifecycle_keys_per_host", "profile_lifecycle_keys_per_caller_profile", "profile_unlock_credentials")
        caps = self.capabilities
        supported = caps.get("operations")
        if (caps.get("api_minor", 0) < 1 or not isinstance(supported, list)
                or not all(isinstance(name, str) for name in supported)
                or not isinstance(caps.get("limits"), dict) or not operations <= set(supported)
                or any(type(caps.get("limits", {}).get(name)) is not int or not 0 < caps["limits"][name] <= 9007199254740991 for name in limits)):
            raise CoreClientError("unsupported_operation")

    def profile_catalog(self):
        self._require_profile_runtime()
        return self.request("profile.catalog", {})

    def lock_profile(self, profile, key):
        self._require_profile_runtime()
        return self.request("profile.lock", {"profile": profile}, idempotency_key=key)

    def select_profile(self, profile, key):
        self._require_profile_runtime()
        return self.request("profile.select", {"profile": profile}, idempotency_key=key)

    def unlock_profile(self, profile, credential_handle, key):
        self._require_profile_runtime()
        return self.request("profile.unlock", {"profile": profile, "credential_handle": credential_handle}, idempotency_key=key)

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

    def _require_optional_keyed(self, operation):
        caps = self.capabilities
        supported = caps.get('optional_keyed_operations')
        names = ('optional_key_idempotency_seconds', 'optional_keys_per_caller_profile', 'optional_keys_per_vault')
        if (caps.get('api_minor', 0) < 1 or not isinstance(supported, list) or operation not in supported
                or not isinstance(caps.get('operations'), list) or operation not in caps['operations'] or not isinstance(caps.get('limits'), dict)
                or any(type(caps['limits'].get(name)) is not int or not 0 < caps['limits'][name] <= 9007199254740991 for name in names)):
            raise CoreClientError('unsupported_operation')

    def create_group(self, handle, title, posting_policy, members, key=None):
        if key is not None:
            self._require_optional_keyed("group.create")
        return self.request("group.create", {
            "profile": handle, "title": title, "posting_policy": posting_policy,
            "members": members}, idempotency_key=key)

    def retry_group_invitation(self, handle, group, member):
        return self.request("group.invitation_retry", {
            "profile": handle, "group": group, "member": member})

    def group_invitation(self, handle, invitation, accept):
        return self.request(
            "group.invitation_accept" if accept else "group.invitation_decline",
            {"profile": handle, "invitation": invitation})

    def leave_group(self, handle, group):
        return self.request("group.leave", {"profile": handle, "group": group})

    def close_group(self, handle, group):
        return self.request("group.close", {"profile": handle, "group": group})

    def remove_group_member(self, handle, group, member):
        return self.request("group.member_remove", {
            "profile": handle, "group": group, "member": member})

    def send_group(self, handle, group, text, key=None):
        if key is not None:
            self._require_optional_keyed("group.message_enqueue")
        return self.request("group.message_enqueue", {
            "profile": handle, "group": group, "text": text}, idempotency_key=key)

    def groups(self, handle):
        return self.request("group.query", {"profile": handle})

    def reaction_set(self, handle, message, emoji, active):
        return self.request("message.reaction_set", {
            "profile": handle, "message": message, "emoji": emoji, "active": active})

    def network_settings(self, handle):
        return self.request("settings.query", {"profile": handle})

    def update_network_settings(self, handle, settings):
        return self.request("settings.update", {"profile": handle, "settings": settings})

    def call_control(self, handle, action, key, **params):
        return self.request("call.control",
                            {"profile": handle, "action": action, **params},
                            idempotency_key=key)

    def call_media(self, handle, call):
        return self.request("call.media_query", {"profile": handle, "call": call})

    def call_ice_servers(self, handle):
        return self.request("call.ice_servers", {"profile": handle})

    def call_settings_get(self, handle):
        return self.request("call.settings_query", {"profile": handle})

    def call_settings_update(self, handle, settings):
        return self.request("call.settings_update", {"profile": handle, "settings": settings})

    def draft_get(self, handle, peer):
        return self.request("peer.draft_get", {"profile": handle, "peer": peer})

    def composer_query(self, profile, peer, send_revision=None):
        self._require_composer()
        params = {"profile": profile, "peer": peer}
        if send_revision is not None:
            params["send_revision"] = send_revision
        return self.request("peer.composer_query", params)

    def composer_update(self, profile, peer, expected_revision, text, update_key):
        self._require_composer()
        if len(text.encode("utf-8")) > self.capabilities["limits"]["composer_text_utf8_bytes"]:
            raise ValueError("Composer text exceeds negotiated byte limit")
        return self.request("peer.composer_update", {"profile": profile, "peer": peer,
            "expected_revision": expected_revision, "text": text}, idempotency_key=update_key)

    def enqueue_draft(self, profile, recipient, draft_revision):
        self._require_composer()
        return self.request("message.enqueue_draft", {"profile": profile, "recipient": recipient,
            "draft_revision": draft_revision}, idempotency_key=draft_revision)

    def draft_set(self, handle, peer, text):
        return self.request("peer.draft_set", {"profile": handle, "peer": peer, "text": text})

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

    ADMIN_REQUEST_OPERATIONS = {
        "approve": "workspace.admin_request_approve",
        "decline": "workspace.admin_request_decline",
        "cancel": "workspace.admin_request_cancel",
        "dismiss": "workspace.admin_request_dismiss",
    }

    def workspace_connection(self, handle, action, key=None, **params):
        return self.request("workspace.connection",
                            {"profile": handle, "action": action, **params},
                            idempotency_key=key)

    def workspace_history(self, handle, workspace, action, key=None, **params):
        return self.request("workspace.history",
                            {"profile": handle, "workspace": workspace,
                             "action": action, **params}, idempotency_key=key)

    def workspace_access_recommendation(self, handle, workspace, action, key=None, **params):
        return self.request("workspace.access_recommendation",
                            {"profile": handle, "workspace": workspace,
                             "action": action, **params}, idempotency_key=key)

    def runtime_query(self, handle, action):
        return self.request("runtime.query", {"profile": handle, "action": action})

    def runtime_mutate(self, handle, action, key, **params):
        return self.request("runtime.mutate",
                            {"profile": handle, "action": action, **params},
                            idempotency_key=key)

    def peer_decide(self, handle, peer, accept):
        return self.request("peer.decide",
                            {"profile": handle, "peer": peer, "accept": accept})

    def remote_profiles(self, handle):
        return self.request("remote_profile.query", {"profile": handle})

    def create_workspace(self, handle, name, description, key):
        return self.request("workspace.create",
                            {"profile": handle, "name": name, "description": description},
                            idempotency_key=key)

    def create_profile(self, display_name, key=None):
        return self.request("profile.create", {"display_name": display_name}, idempotency_key=key)

    def workspace_join_prompt(self, handle, prompt, key):
        return self.request("workspace.join_prompt",
                            {"profile": handle, "prompt": prompt},
                            idempotency_key=key)

    def pairing_preview(self, handle, document):
        return self.request("peer.pairing_preview",
                            {"profile": handle, "document": document})

    def connection_document(self, handle, action, **params):
        return self.request("connection.document",
                            {"profile": handle, "action": action, **params})

    def connection_support(self, handle, action, **params):
        return self.request("connection.support",
                            {"profile": handle, "action": action, **params})

    def recovery_transfer(self, handle, action, **params):
        return self.request("recovery.transfer",
                            {"profile": handle, "action": action, **params})

    def contact_invitation(self, handle, action, **params):
        return self.request("contact.invitation",
                            {"profile": handle, "action": action, **params})

    def link_preview(self, handle, provider, identifier):
        return self.request("link.preview",
                            {"profile": handle, "provider": provider,
                             "identifier": identifier})

    def conversation(self, handle, action, kind, target_id, **params):
        return self.request("conversation.mutate",
                            {"profile": handle, "action": action, "kind": kind,
                             "target_id": target_id, **params})

    def peer_update(self, handle, peer, action, display_name=None):
        params = {"profile": handle, "peer": peer, "action": action}
        if display_name is not None: params["display_name"] = display_name
        return self.request("peer.update", params)

    def route_update(self, handle, action, key, **params):
        return self.request("route.update",
                            {"profile": handle, "action": action, **params},
                            idempotency_key=key)

    def workspace_direct_open(self, handle, workspace, member, key):
        return self.request("workspace.direct_open",
                            {"profile": handle, "workspace": workspace, "member": member},
                            idempotency_key=key)

    def workspace_display_name_decide(self, handle, workspace, request, approve, key):
        return self.request("workspace.display_name_decide",
                            {"profile": handle, "workspace": workspace,
                             "request": request, "approve": approve},
                            idempotency_key=key)

    def remote_profile(self, handle, action, key, **params):
        return self.request("remote_profile.mutate",
                            {"profile": handle, "action": action, **params},
                            idempotency_key=key)

    def workspace_draft_set(self, handle, workspace, conversation, text, key,
                             thread_root=None, mentions=None):
        params = {"profile": handle, "workspace": workspace,
                  "conversation": conversation, "text": text}
        if thread_root is not None: params["thread_root"] = thread_root
        if mentions: params["mention_member_ids"] = mentions
        return self.request("workspace.draft_set", params, idempotency_key=key)

    def group_draft_set(self, handle, group, text):
        return self.request("group.draft_set",
                            {"profile": handle, "group": group, "text": text})

    def workspace_member_remove(self, handle, workspace, member, key):
        return self.request("workspace.member_remove",
                            {"profile": handle, "workspace": workspace, "member": member},
                            idempotency_key=key)

    def workspace_channel_state(self, handle, workspace, action, key, **params):
        return self.request("workspace.channel_state",
                            {"profile": handle, "workspace": workspace,
                             "action": action, **params}, idempotency_key=key)

    def workspace_channel_recover(self, handle, workspace, channel, key):
        return self.request("workspace.channel_recover",
                            {"profile": handle, "workspace": workspace,
                             "channel": channel}, idempotency_key=key)

    def workspace_snapshot(self, handle):
        return self.request("workspace.snapshot", {"profile": handle})

    def workspace_timeline_query(self, handle, workspace, view, **params):
        return self.request("workspace.timeline_query",
                            {"profile": handle, "workspace": workspace, "view": view, **params})

    def workspace_timeline_mutation(self, handle, workspace, action, key, **params):
        return self.request("workspace.timeline_mutation",
                            {"profile": handle, "workspace": workspace,
                             "action": action, **params}, idempotency_key=key)

    def workspace_invitation_revoke(self, handle, workspace, invitation, key):
        return self.request("workspace.invitation_revoke",
                            {"profile": handle, "workspace": workspace,
                             "invitation": invitation}, idempotency_key=key)

    def workspace_admission_grant_list(self, handle, workspace, key=None):
        return self.request("workspace.admission_grant_list",
                            {"profile": handle, "workspace": workspace}, idempotency_key=key)

    def workspace_admission_grant_create(self, handle, workspace, member, device,
                                         max_admissions, lifetime_days, v2_ready, key):
        return self.request("workspace.admission_grant_create", {
            "profile": handle, "workspace": workspace,
            "admin_member": member, "admin_device": device,
            "max_admissions": max_admissions, "lifetime_days": lifetime_days,
            "v2_ready": v2_ready,
        }, idempotency_key=key)

    def workspace_admission_grant_accept(self, handle, workspace, grant, key):
        return self.request("workspace.admission_grant_accept",
                            {"profile": handle, "workspace": workspace,
                             "grant": grant}, idempotency_key=key)

    def workspace_admission_grant_end(self, handle, workspace, grant, key):
        return self.request("workspace.admission_grant_end",
                            {"profile": handle, "workspace": workspace,
                             "grant": grant}, idempotency_key=key)

    def workspace_authority_offer(self, handle, workspace, transition_kind,
                                  successor_member, successor_device, outgoing_role, key):
        return self.request("workspace.authority_offer", {
            "profile": handle, "workspace": workspace,
            "transition_kind": transition_kind,
            "successor_member": successor_member,
            "successor_device": successor_device,
            "outgoing_owner_role": outgoing_role,
        }, idempotency_key=key)

    def workspace_authority_accept(self, handle, workspace, transition, key):
        return self.request("workspace.authority_accept",
                            {"profile": handle, "workspace": workspace,
                             "transition": transition}, idempotency_key=key)

    def workspace_authority_finalize(self, handle, workspace, transition, key):
        return self.request("workspace.authority_finalize",
                            {"profile": handle, "workspace": workspace,
                             "transition": transition}, idempotency_key=key)

    def workspace_report_authority_loss(self, handle, workspace, key):
        return self.request("workspace.authority_loss_report",
                            {"profile": handle, "workspace": workspace},
                            idempotency_key=key)

    def workspace_close(self, handle, workspace, key):
        return self.request("workspace.close",
                            {"profile": handle, "workspace": workspace},
                            idempotency_key=key)

    def workspace_leave(self, handle, workspace, key):
        return self.request("workspace.leave",
                            {"profile": handle, "workspace": workspace},
                            idempotency_key=key)

    def workspace_remove_data(self, handle, workspace, confirmation, key):
        return self.request("workspace.remove_data",
                            {"profile": handle, "workspace": workspace,
                             "confirmation": confirmation},
                            idempotency_key=key)

    def workspace_admin_request_submit(self, handle, workspace, request_kind,
                                       target_member, requested_role, note, key):
        params = {"profile": handle, "workspace": workspace, "request_kind": request_kind}
        if target_member is not None: params["target_member"] = target_member
        if requested_role is not None: params["requested_role"] = requested_role
        if note: params["note"] = note
        return self.request("workspace.admin_request_submit", params, idempotency_key=key)

    def workspace_display_name_request(self, handle, workspace, display_name, key):
        return self.request("workspace.display_name_request",
                            {"profile": handle, "workspace": workspace,
                             "display_name": display_name}, idempotency_key=key)

    def workspace_read_hint_sync(self, handle, workspace, enabled, key):
        return self.request("workspace.read_hint_sync",
                            {"profile": handle, "workspace": workspace,
                             "enabled": enabled}, idempotency_key=key)

    def workspace_admin_request(self, handle, workspace, request, action, key):
        return self.request(self.ADMIN_REQUEST_OPERATIONS[action],
                            {"profile": handle, "workspace": workspace, "request": request},
                            idempotency_key=key)

    def workspace_metadata(self, handle, workspace, name, description, key):
        return self.request("workspace.metadata_update",
                            {"profile": handle, "workspace": workspace,
                             "name": name, "description": description},
                            idempotency_key=key)

    def workspace_retention(self, handle, workspace, retention_days, key):
        return self.request("workspace.retention_update",
                            {"profile": handle, "workspace": workspace,
                             "retention_days": retention_days},
                            idempotency_key=key)

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

    def workspace_device_removal_request(self, handle, workspace, device, key):
        if not isinstance(key, str) or len(key) < 16:
            raise ValueError("Device removal requires a caller-scoped key")
        return self.request("workspace.device_removal_request",
                            {"profile": handle, "workspace": workspace, "device": device},
                            idempotency_key=key)

    def workspace_device_removal_decide(self, handle, workspace, request_handle, key, approve):
        if not isinstance(key, str) or len(key) < 16:
            raise ValueError("Device removal decisions require a caller-scoped key")
        operation = ("workspace.device_removal_approve" if approve
                     else "workspace.device_removal_decline")
        return self.request(operation,
                            {"profile": handle, "workspace": workspace,
                             "request": request_handle},
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

    def workspace_join(self, handle, document, key=None):
        if not isinstance(document, str) or not document:
            raise ValueError("Workspace joins require signed material")
        return self.request("workspace.join", {"profile": handle, "document": document}, idempotency_key=key)

    def pairing_accept(self, handle, document, *, i2p_consent=False):
        if not isinstance(document, str) or not document:
            raise ValueError("Signed pairing material is required")
        params = {"profile": handle, "document": document}
        if i2p_consent:
            params["i2p_consent"] = True
        return self.request("peer.pairing_accept", params)

    def stop(self):
        return self.request("runtime.stop", {})

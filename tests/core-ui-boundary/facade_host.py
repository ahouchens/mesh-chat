"""Worktree-isolated test host using the real framed session, service and vault."""

from contextlib import redirect_stdout
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from uuid import uuid4
import base64
import RNS

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "service/src"))

from mesh_chat.core_api.composition import bind_service_stream
from mesh_chat.core_api.session import Grant
from mesh_chat.service import MeshChatService
from mesh_chat.vault import VaultStore
from mesh_chat.invitations import readable_fingerprint
from mesh_chat.models import Contact, TrustState


class BoundaryHost:
    def __init__(self, directory, *, fresh_profile=False):
        MeshChatService._start_network = lambda *_: None
        MeshChatService._prepare_lan_fallback = lambda *_: None
        self.directory, self.key = directory, os.urandom(32)
        store = VaultStore(directory, self.key, allow_unprotected_for_tests=True)
        self.service = MeshChatService(store, directory, lambda _: None)
        self.workspace_id = self.channel_id = self.root = None
        if not fresh_profile:
            self.service.create_profile("Boundary Alex")
            peer = RNS.Identity()
            self.peer_identity = peer
            store.put("contact", "boundary-peer", Contact("boundary-peer", "Boundary Blair",
                base64.urlsafe_b64encode(peer.get_public_key()).decode(), peer.hash.hex(),
                RNS.Destination.hash(peer, "lxmf", "delivery").hex(), readable_fingerprint(peer.get_public_key()),
                TrustState.APPROVED, created_at=1, updated_at=1).to_dict())
            workspace = self.service.create_workspace(str(uuid4()), "Boundary Team", "Fixture workspace")
            self.workspace_id = workspace["id"]
            self.channel_id = self.service.workspace_snapshot()["workspace_channels"][0]["id"]
            self.root = self.service.send_workspace_message(
                self.workspace_id, self.channel_id, "Boundary root message", str(uuid4()), str(uuid4()))
        self._bind_session()

    def _bind_session(self):
        permissions = frozenset({"observe", "read", "send", "approve", "pair", "connect",
                                 "diagnose", "runtime_owner", "profile_owner"})
        self.session = bind_service_stream(self.service, lambda: Grant("boundary-ui", permissions, ("local",)),
                                          private_native=True, private_profile_bootstrap=True,
                                          private_composer_legacy=True)
        self.call("runtime.capabilities")

    def call(self, operation, params=None, key=None):
        value = {"api_version": 1, "request_id": "boundary:" + uuid4().hex,
                 "operation": operation, "params": params or {}}
        if key is not None:
            value["idempotency_key"] = key
        frame = json.dumps(value, ensure_ascii=False).encode("utf-8") + b"\n"
        return json.loads(self.session.exchange(frame))

    def profile(self):
        capabilities = self.call("runtime.capabilities")
        if not capabilities["ok"]:
            return capabilities
        return self.call("profile.query", {"profile": capabilities["result"]["profiles"][0]})

    def invoke(self, command, args):
        if command == "fixture_group_accept":
            # In-process domain transport fixture only: real peer signatures,
            # invitation/join/manifest/receipt handlers, no native path claim.
            sys.path.insert(0, str(ROOT / "service/tests"))
            from test_group_service import _contact, _service, _deliver, _sent_values, RecordingGroupNetwork
            groups = self.service.store.list("group")
            assert len(groups) == 1
            group = groups[0]
            peer, peer_network = _service(self.directory / "group-peer", self.peer_identity, "Boundary Blair",
                _contact(self.service._identity, "Boundary Alex", "fixture-group-owner"))
            peer._retry_thread.join(timeout=2)
            assert not peer._retry_thread.is_alive()
            owner_profile, peer_profile = self.service._require_profile(), peer._require_profile()
            owner_network, original_network = RecordingGroupNetwork(), self.service.network
            try:
                with self.service._dispatch_lock:
                    self.service.network = owner_network
                    invitation = next(item for item in self.service.store.list("group_delivery")
                                      if item["kind"] == "group_invite" and item["group_id"] == group["id"])
                    self.service._attempt_group_delivery(invitation["id"])
                    _deliver(peer, _sent_values(owner_network, "group_invite")[-1],
                             source_profile=owner_profile, destination_profile=peer_profile)
                    peer.accept_group_invitation(peer.snapshot()["group_invitations"][0]["id"])
                    _deliver(self.service, _sent_values(peer_network, "group_accept")[-1],
                             source_profile=peer_profile, destination_profile=owner_profile)
                    _deliver(peer, _sent_values(owner_network, "group_manifest", epoch=2)[-1],
                             source_profile=owner_profile, destination_profile=peer_profile)
                    _deliver(self.service, _sent_values(peer_network, "group_receipt", epoch=2)[-1],
                             source_profile=peer_profile, destination_profile=owner_profile)
                    current = self.service.snapshot()["groups"][0]
                    assert not current["membership_update_pending"]
                    assert sum(item["status"] == "active" for item in current["members"]) == 2
                    return {"ok": True, "result": {"signed_acceptance_applied": True, "epoch": current["epoch"]}}
            finally:
                self.service.network = original_network
                peer.close()
        if command == "fixture_reopen":
            self.session.close()
            self.service.close()
            store = VaultStore(self.directory, self.key, allow_unprotected_for_tests=True)
            self.service = MeshChatService(store, self.directory, lambda _: None)
            self._bind_session()
            return {"ok": True, "result": {"reopened": True}}
        if command == "initialize_service":
            return self.call("application.snapshot")
        if command == "core_api_capabilities":
            return self.call("runtime.capabilities")
        if command == "core_api_profile":
            return self.profile()
        if command == "core_api_request":
            return self.call(args["operation"], args.get("params"), args.get("idempotencyKey"))
        if command == "core_api_peer_for_destination":
            profile = self.profile()["result"]
            for peer in profile["peers"]:
                view = self.call("peer.query", {"profile": profile["profile"], "peer": peer})
                if view["ok"] and view["result"]["destination"] == args["destination"]:
                    return {"ok": True, "result": {"profile": profile["profile"], "peer": peer,
                                                    "destination": view["result"]["destination"]}}
            raise ValueError("Unknown fixture peer")
        if command == "core_api_send_message":
            profile = self.profile()["result"]
            for peer in profile["peers"]:
                view = self.call("peer.query", {"profile": profile["profile"], "peer": peer})
                if view["ok"] and view["result"]["destination"] == args["destination"]:
                    return self.call("message.enqueue", {"profile": profile["profile"], "recipient": peer,
                                     "kind": "text", "text": args["text"]}, args["idempotencyKey"])
            raise ValueError("Unknown fixture peer")
        if command in {"core_api_draft_get", "core_api_draft_set"}:
            profile = self.profile()["result"]
            operation = "peer.draft_get" if command.endswith("get") else "peer.draft_set"
            params = {"profile": profile["profile"], "peer": profile["peers"][0]}
            if operation.endswith("set"):
                params["text"] = args["text"]
            return self.call(operation, params)
        if command == "fixture_inspect":
            return {"ok": True, "result": {"messages": self.service.store.list("message"),
                    "workspace": self.workspace_id, "channel": self.channel_id, "root": self.root,
                    "profile_count": len(self.service.store.list("profile")),
                    "identity_count": len(self.service.store.list("identity")),
                    "profile": self.service.store.get("profile", "local"),
                    "groups": [{"id": item["id"], "title": item["title"]} for item in self.service.store.list("group")],
                    "group_messages": [{key: item.get(key) for key in ("id", "group_id", "text", "sequence")}
                                       for item in self.service.store.list("group_message")],
                    "group_delivery_count": self.service.store.record_count("group_delivery"),
                    "group_send_receipt_count": self.service.store.record_count("api_group_composer_send"),
                    "optional_receipt_count": self.service.store.record_count("api_optional_mutation")}}
        raise ValueError(f"Unsupported host command: {command}")

    def close(self):
        self.session.close()
        self.service.close()


def main():
    scratch = ROOT / ".test-tmp/core-ui-boundary"
    scratch.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=scratch) as directory:
        with redirect_stdout(sys.stderr):
            host = BoundaryHost(Path(directory), fresh_profile="--fresh-profile" in sys.argv[1:])
        try:
            for line in sys.stdin:
                request = json.loads(line)
                try:
                    with redirect_stdout(sys.stderr):
                        reply = host.invoke(request["command"], request.get("args", {}))
                except Exception as error:
                    reply = {"ok": False, "error": {"code": "fixture_failure", "detail": repr(error)}}
                print(json.dumps({"id": request["id"], "reply": reply}, ensure_ascii=False), flush=True)
        finally:
            with redirect_stdout(sys.stderr):
                host.close()


if __name__ == "__main__":
    main()

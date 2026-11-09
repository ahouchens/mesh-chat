"""Component host executed with the actual installed pinned service wheel.

No network/platform qualification is inferred: only network startup is suppressed
so actual encrypted storage, parser, session and domain writes can be inspected.
"""
import json
from pathlib import Path
import sys

sys.path.insert(0, sys.argv[1])
import mesh_chat
assert Path(mesh_chat.__file__).resolve().is_relative_to(Path(sys.argv[1]).resolve())
from mesh_chat.core_api.composition import bind_service_stream
from mesh_chat.core_api.session import Grant
from mesh_chat.service import MeshChatService
from mesh_chat.vault import VaultStore, SCHEMA_VERSION
from mesh_chat.errors import StorageUnavailable

config = json.loads(sys.stdin.buffer.readline(16385))
assert SCHEMA_VERSION == 1
key = Path(config["key_file"]).read_bytes()
root = Path(config["profile_dir"])
try:
    store = VaultStore(root, key, allow_unprotected_for_tests=True)
    if config.get("refusal_only"):
        store.get("profile", "local")  # Wrong keys/corrupt records are failures.
except StorageUnavailable as error:
    if str(error) != "Unsupported vault schema":
        raise
    print(json.dumps({"refused_before_service_construction": True}), flush=True)
    raise SystemExit(0)
if config.get("refusal_only"):
    store.close()
    print(json.dumps({"refused_before_service_construction": False}), flush=True)
    raise SystemExit(0)
MeshChatService._start_network = lambda *_: None
MeshChatService._prepare_lan_fallback = lambda *_: None
service = MeshChatService(store, root, lambda _: None)
try:
    if store.get("profile", "local") is None:
        service.create_profile("Upgrade qualification")
        store.put("contact", "internal-peer", {"id": "internal-peer", "display_name": "Synthetic peer",
            "trust": "approved", "destination_hash": "ab" * 16})
        store.put("draft", "internal-peer", {"contact_id": "internal-peer", "text": "Upgrade legacy draft"})
    print(json.dumps({"ready": True}), flush=True)
    session = bind_service_stream(service, lambda: Grant("sdk-distribution-qualification",
        frozenset({"observe", "read", "send"}), ("local",)))
    session.serve(sys.stdin.buffer, sys.stdout.buffer)
finally:
    service.close()

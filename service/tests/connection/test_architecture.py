import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2] / "src" / "mesh_chat" / "connection"


def test_policy_has_only_pure_dependencies_and_no_ambient_clock_or_io():
    allowed = {"dataclasses", "enum", "hashlib", "typing", "model"}
    forbidden_calls = {"open", "print", "sleep", "monotonic", "time", "random",
                       "uuid4", "Thread", "socket", "exec", "eval", "__import__"}
    for name in ("model.py", "reducer.py"):
        tree = ast.parse((ROOT / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(alias.name in allowed for alias in node.names), name
            if isinstance(node, ast.ImportFrom):
                assert node.module in allowed, (name, node.module)
            if isinstance(node, ast.Call):
                function = node.func
                called = function.id if isinstance(function, ast.Name) else getattr(function, "attr", "")
                assert called not in forbidden_calls, (name, called)


def test_supervisor_cannot_import_concrete_service_or_adapters():
    tree = ast.parse((ROOT / "supervisor.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.module not in {"service", "adapters", "composition", "runtime"}
            assert not (node.module or "").startswith(("RNS", "LXMF", "java"))


def test_workspace_writes_cannot_bypass_the_connection_authority_boundary():
    tree = ast.parse((ROOT.parent / "workspace_service.py").read_text(encoding="utf-8"))
    writes = {"put", "put_many", "put_and_delete", "commit_operation", "delete"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in writes:
            target = node.func.value
            assert not (isinstance(target, ast.Attribute) and target.attr == "store"
                        and isinstance(target.value, ast.Name) and target.value.id == "self"), node.lineno


def test_native_adapter_and_policy_cannot_import_the_concrete_service():
    paths = [*(ROOT.parent / name for name in ("native_webrtc_service.py", "native_carrier_checkpoint.py",
                                              "carrier_recovery.py", "carrier_journal.py")), *ROOT.rglob("*.py")]
    for path in paths:
        if path.name == "composition.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                assert all(alias.name != "mesh_chat.service" for alias in node.names), path
            elif isinstance(node, ast.ImportFrom):
                assert node.module not in {"service", "mesh_chat.service"}, path
                if node.module in {None, "mesh_chat"}:
                    assert all(alias.name != "service" for alias in node.names), path


def test_received_message_index_is_pure_and_has_no_ambient_io():
    allowed = {"errors", "models", "record_projection"}
    forbidden_calls = {"open", "print", "sleep", "monotonic", "time", "random",
                       "uuid4", "Thread", "socket", "exec", "eval", "__import__"}
    tree = ast.parse((ROOT.parent / "received_messages.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(alias.name in allowed for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.module in allowed, node.module
        elif isinstance(node, ast.Call):
            function = node.func
            called = function.id if isinstance(function, ast.Name) else getattr(function, "attr", "")
            assert called not in forbidden_calls, called


def test_application_facade_cannot_import_policy_native_or_workspace_services():
    forbidden = {"service", "workspace_service", "native_webrtc_service",
                 "native_webrtc_control", "reducer", "connection"}
    for path in (ROOT.parent / "core_api").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                assert all(alias.name not in forbidden for alias in node.names), path
            elif isinstance(node, ast.ImportFrom):
                assert node.module not in forbidden, (path, node.module)
                assert not (node.module or "").startswith("mesh_chat"), (path, node.module)

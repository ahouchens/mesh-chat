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

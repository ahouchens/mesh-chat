"""Source isolation checks complement the actual installed-wheel consumer."""
import ast
from pathlib import Path
import tomllib


def test_standalone_package_has_no_service_or_third_party_dependencies():
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text())
    assert project["project"]["dependencies"] == []
    for path in (root / "src/mesh_chat_core_client").glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 0:
                assert not (node.module or "").startswith(("mesh_chat.", "RNS", "LXMF", "cryptography"))
            if isinstance(node, ast.Import):
                assert all(not item.name.startswith(("mesh_chat.", "RNS", "LXMF", "cryptography")) for item in node.names)

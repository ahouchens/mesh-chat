# Narrowed-selection fixture: this module only exercises the selector.
import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "connection_ci.py"
sys.path.insert(0, str(SCRIPT.parent))
KOTLIN_CLIENT = "sdk/kotlin/src/main/java/com/meshchat/runtime/core/"
spec = importlib.util.spec_from_file_location("connection_ci", SCRIPT)
ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)


@pytest.mark.parametrize("path", [
    "contracts/connection/observation.schema.json", "contracts/core-api/request.schema.json",
    "service/src/mesh_chat/service.py", "service/src/mesh_chat/workspace_service.py",
    "service/src/mesh_chat/connection/reducer.py", "src-tauri/src/lib.rs",
    "plugins/tauri-plugin-mesh-runtime/android/Host.kt", "src/desktop-transport.ts",
    "pnpm-lock.yaml", "service/requirements.lock", "scripts/frontend-config.mjs",
    ".github/workflows/connection-qualification.yml", "new-runtime/binding.rs",
    "docs/Mesh_Chat_Connection_Runtime_Spec.md", "AGENTS.md",
])
def test_contracts_shared_sources_tooling_and_unknown_paths_require_all_consumers(path):
    assert ci.select([path])["required"] == list(ci.SUITES)


def test_documentation_exclusion_is_explicit_and_does_not_hide_mixed_changes():
    assert ci.select(["docs/guide.md", "README.md"])["required"] == ["policy", "verification"]
    assert ci.select(["docs/guide.md", "contracts/deleted.json"])["required"] == list(ci.SUITES)


@pytest.mark.parametrize("paths", [None, [], ["../README.md"], ["/README.md"], ["docs\\guide.md"]])
def test_missing_empty_or_ambiguous_diff_expands_coverage(paths):
    assert ci.select(paths)["required"] == list(ci.SUITES)
    assert ci.select(paths)["native_workload"] == "full"


@pytest.mark.parametrize("event", ["workflow_dispatch", "merge_group", "release", "schedule", "unknown"])
def test_manual_release_merge_queue_and_unknown_events_cannot_narrow_coverage(event):
    assert ci.select(["README.md"], event=event)["required"] == list(ci.SUITES)
    assert ci.select(["README.md"], event=event)["native_workload"] == "full"


def test_known_affected_pr_keeps_actual_native_smoke_but_push_remains_full():
    path = "service/src/mesh_chat/service.py"
    plan = ci.select([path], event="pull_request")
    assert "native_interop" in plan["required"] and plan["native_workload"] == "quick"
    assert ci.select([path], event="push")["native_workload"] == "full"
    assert ci.select(None, event="pull_request")["native_workload"] == "full"
    plan["native_workload"] = "full"
    with pytest.raises(ValueError):
        ci.validate(plan, {suite: {"result": "success"} for suite in ci.SUITES})


def test_complete_selected_execution_passes_but_omitted_job_does_not():
    plan = ci.select(["README.md"])
    jobs = {suite: {"result": "success" if suite in plan["required"] else "skipped"} for suite in ci.SUITES}
    ci.validate(plan, jobs)
    del jobs["android"]
    with pytest.raises(ValueError):
        ci.validate(plan, jobs)


@pytest.mark.parametrize("status", ["skipped", "cancelled", "failure", "", None])
def test_required_job_must_execute_successfully(status):
    plan = ci.select(["contracts/api.json"])
    jobs = {suite: {"result": "success"} for suite in ci.SUITES}
    jobs["android"]["result"] = status
    with pytest.raises(ValueError):
        ci.validate(plan, jobs)


@pytest.mark.parametrize("alter", [
    lambda plan: plan.update(required=["policy"]),
    lambda plan: plan.update(required=list(ci.SUITES) + ["android"]),
    lambda plan: plan.update(version=2),
    lambda plan: plan.update(version=True),
    lambda plan: plan.update(paths=["README.md"]),
])
def test_gate_recomputes_selection_instead_of_trusting_required_job_list(alter):
    plan = ci.select(["service/src/mesh_chat/service.py"])
    alter(plan)
    with pytest.raises(ValueError):
        ci.validate(plan, {suite: {"result": "success"} for suite in ci.SUITES})


def test_git_rename_from_source_into_documentation_keeps_both_dependency_paths(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    def git(*args):
        return subprocess.check_output(["git", *args], text=True).strip()
    git("init", "-q")
    git("config", "user.name", "Qualification fixture")
    git("config", "user.email", "fixture@example.invalid")
    source = tmp_path / "runtime.py"
    source.write_text("pass\n")
    git("add", ".")
    git("commit", "-qm", "source")
    base = git("rev-parse", "HEAD")
    (tmp_path / "docs").mkdir()
    source.rename(tmp_path / "docs" / "guide.md")
    git("add", "-A")
    git("commit", "-qm", "rename")
    paths = ci.changed_paths("pull_request", {"pull_request": {"base": {"sha": base}}})
    assert paths == ["docs/guide.md", "runtime.py"]
    assert ci.select(paths)["required"] == list(ci.SUITES)
    assert ci.changed_paths("push", {"before": "f" * 40}) is None


def test_failed_optional_workflow_is_not_hidden_by_an_exclusion():
    plan = ci.select(["README.md"])
    jobs = {suite: {"result": "success"} for suite in ci.SUITES}
    jobs["android"]["result"] = "failure"
    with pytest.raises(ValueError):
        ci.validate(plan, jobs)


def test_connection_tests_alone_skip_platform_compilation_suites():
    plan = ci.select(["service/tests/connection/test_core_messages.py",
                      "service/tests/connection/test_workspace_service.py"])
    assert plan["required"] == ["policy", "verification"]
    assert plan["reason"] == "isolated_connection_tests"
    jobs = {suite: {"result": "success" if suite in plan["required"] else "skipped"}
            for suite in ci.SUITES}
    ci.validate(plan, jobs)


@pytest.mark.parametrize("paths", [
    ["service/tests/connection/test_core_messages.py", "service/src/mesh_chat/service.py"],
    ["service/tests/test_workspace_service.py"],
    ["service/tests/connection/conftest.py"],
    ["service/tests/connection/fixture.json"],
    ["service/tests/connection/../test_workspace_service.py"],
    ["docs/guide.md", "service/tests/connection/test_core_messages.py"],
])
def test_mixed_or_non_test_paths_still_require_the_full_matrix(paths):
    assert ci.select(paths)["required"] == list(ci.SUITES)


@pytest.mark.parametrize("event", ["workflow_dispatch", "merge_group", "release", "schedule"])
def test_connection_test_narrowing_is_limited_to_branch_events(event):
    assert ci.select(["service/tests/connection/test_core_messages.py"],
                     event=event)["required"] == list(ci.SUITES)


def test_typescript_sdk_only_changes_skip_platform_recompilation():
    plan = ci.select(["sdk/typescript/src/client.ts", "sdk/typescript/package.json"])
    assert plan["required"] == ["policy", "verification"]
    assert plan["reason"] == "isolated_typescript_sdk"
    jobs = {suite: {"result": "success" if suite in plan["required"] else "skipped"}
            for suite in ci.SUITES}
    ci.validate(plan, jobs)


@pytest.mark.parametrize("paths", [
    ["sdk/typescript/src/client.ts", "src/desktop-transport.ts"],
    ["sdk/typescript/src/client.ts", "docs/guide.md"],
    ["sdk/typescript/src/client.ts", "pnpm-lock.yaml"],
    ["sdk/typescript/../service/src/mesh_chat/service.py"],
])
def test_mixed_or_ambiguous_sdk_paths_keep_the_full_matrix(paths):
    assert ci.select(paths)["required"] == list(ci.SUITES)


@pytest.mark.parametrize("event", ["workflow_dispatch", "merge_group", "release", "schedule"])
def test_sdk_narrowing_is_limited_to_branch_events(event):
    assert ci.select(["sdk/typescript/src/client.ts"], event=event)["required"] == list(ci.SUITES)


def test_frontend_sources_do_not_consume_the_typescript_sdk():
    frontend = Path(__file__).resolve().parents[3] / "src"
    offenders = []
    for path in frontend.rglob("*"):
        if path.suffix not in {".ts", ".tsx", ".js", ".mjs"} or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        if "@mesh-chat/core-client" in text or "sdk/typescript" in text:
            offenders.append(str(path.relative_to(frontend)))
    assert offenders == []


def test_qualification_manifest_exposes_suites_and_the_component_summary():
    plan = ci.select(["README.md"])
    jobs = {suite: "success" for suite in ci.SUITES}
    collected = {
        "policy_tests_executed": 5,
        "suites": [{"suite": "policy", "evidence_level": "local"}],
        "report_sha256": {"policy": "a" * 64},
    }
    result = ci.manifest(plan, collected, jobs)
    assert result["suites"] == collected["suites"]
    assert result["components"] == {"policy_tests_executed": 5}
    assert "suites" not in result["components"]
    assert result["report_sha256"] == collected["report_sha256"]
    assert result["jobs"] == jobs


def test_isolated_pipe_production_changes_skip_platform_recompilation():
    plan = ci.select([
        "service/src/mesh_chat/core_api/pipe_endpoint.py",
        "service/src/mesh_chat/core_api/pipe_policy.py",
    ])
    assert plan["required"] == ["policy", "verification"]
    assert plan["reason"] == "isolated_pipe_production"


@pytest.mark.parametrize("name", ["CoreClient.kt", "CoreTransport.kt", "CoreExchangeTransport.kt"])
def test_isolated_kotlin_client_keeps_android_consumer_and_contract_qualification(name):
    plan = ci.select([KOTLIN_CLIENT + name])
    assert plan["required"] == ["policy", "verification", "android", "native_interop"]
    assert plan["reason"] == "isolated_kotlin_client"
    jobs = {suite: {"result": "success" if suite in plan["required"] else "skipped"}
            for suite in ci.SUITES}
    ci.validate(plan, jobs)
    jobs["android"]["result"] = "skipped"
    with pytest.raises(ValueError):
        ci.validate(plan, jobs)


@pytest.mark.parametrize("path", [
    KOTLIN_CLIENT + "NewClient.kt", KOTLIN_CLIENT + "../MeshCoreApiService.kt",
    "sdk/kotlin/build.gradle.kts", "sdk/kotlin/src/main/AndroidManifest.xml",
    "contracts/core-api/operations-v1.json", "README.md",
])
def test_kotlin_packaging_contract_new_source_or_mixed_changes_keep_full_coverage(path):
    assert ci.select([KOTLIN_CLIENT + "CoreClient.kt", path])["required"] == list(ci.SUITES)


@pytest.mark.parametrize("event", ["workflow_dispatch", "merge_group", "release", "schedule"])
def test_kotlin_client_narrowing_is_limited_to_branch_events(event):
    assert ci.select([KOTLIN_CLIENT + "CoreClient.kt"], event=event)["required"] == list(ci.SUITES)


@pytest.mark.parametrize("paths", [
    ["service/src/mesh_chat/core_api/pipe_endpoint.py",
     "service/src/mesh_chat/core_api/host.py"],
    ["service/src/mesh_chat/core_api/pipe_endpoint.py", "src/desktop-transport.ts"],
    ["service/src/mesh_chat/core_api/pipe_endpoint.py", "README.md"],
])
def test_mixed_pipe_production_paths_keep_the_full_matrix(paths):
    assert ci.select(paths)["required"] == list(ci.SUITES)


@pytest.mark.parametrize("event", ["workflow_dispatch", "merge_group", "release", "schedule"])
def test_pipe_production_narrowing_is_limited_to_branch_events(event):
    assert ci.select(["service/src/mesh_chat/core_api/pipe_endpoint.py"],
                     event=event)["required"] == list(ci.SUITES)


def test_pipe_production_modules_are_not_consumed_by_other_suites():
    root = Path(__file__).resolve().parents[3]
    from check_core_windows_boundary import SELECTION
    assert "service/tests/test_app_owned_windows.py" in SELECTION
    windows_tests = {root / "service/tests/test_core_pipe_windows.py",
                     root / "service/tests/test_app_owned_windows.py"}
    roots = [root / "src",
             root / "plugins" / "tauri-plugin-mesh-runtime" / "android" / "src"]
    offenders = []
    for directory in roots:
        for path in directory.rglob("*"):
            if path.suffix not in {".ts", ".tsx", ".js", ".kt"} or not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            if any(name in text for name in ("pipe_endpoint", "pipe_policy", "pipe_client")):
                offenders.append(str(path.relative_to(root)))
    for path in (root / "service" / "tests").rglob("*.py"):
        if ("connection" in path.parts or path in windows_tests
                or not path.name.startswith("test_")):
            continue
        text = path.read_text(encoding="utf-8")
        if any(name in text for name in ("pipe_endpoint", "pipe_policy", "pipe_client")):
            offenders.append(str(path.relative_to(root)))
    assert offenders == []


def test_isolated_native_windows_production_changes_skip_platform_recompilation():
    plan = ci.select([
        "service/src/mesh_chat/native_windows_webrtc.py",
        "service/src/mesh_chat/desktop_transport_host.py",
    ])
    assert plan["required"] == ["policy", "verification"]
    assert plan["reason"] == "isolated_native_windows_production"


@pytest.mark.parametrize("paths", [
    ["service/src/mesh_chat/native_windows_webrtc.py",
     "service/src/mesh_chat/service.py"],
    ["service/src/mesh_chat/native_windows_webrtc.py", "src/App.tsx"],
    ["service/src/mesh_chat/desktop_transport_host.py", "README.md"],
])
def test_mixed_native_windows_production_paths_keep_the_full_matrix(paths):
    assert ci.select(paths)["required"] == list(ci.SUITES)


@pytest.mark.parametrize("event", ["workflow_dispatch", "merge_group", "release", "schedule"])
def test_native_windows_narrowing_is_limited_to_branch_events(event):
    assert ci.select(["service/src/mesh_chat/native_windows_webrtc.py"],
                     event=event)["required"] == list(ci.SUITES)


def test_native_windows_production_modules_have_only_trusted_consumers():
    root = Path(__file__).resolve().parents[3]
    names = ("native_windows_webrtc", "desktop_transport_host")
    trusted_hosts = {root / "service/src/mesh_chat/__main__.py", root / "service/src/mesh_chat/app_owned_host.py"}
    offenders = []
    for path in (root / "service" / "src").rglob("*.py"):
        if path in trusted_hosts:
            continue
        text = path.read_text(encoding="utf-8")
        if any(f"import {name}" in text or f"from .{name}" in text
               or f"from .core_api.{name}" in text for name in names):
            offenders.append(str(path.relative_to(root)))
    for path in (root / "src").rglob("*"):
        if path.suffix in {".ts", ".tsx", ".js"} and path.is_file():
            text = path.read_text(encoding="utf-8")
            if any(name in text for name in names):
                offenders.append(str(path.relative_to(root)))
    for path in (root / "plugins" / "tauri-plugin-mesh-runtime" / "android" / "src").rglob("*.kt"):
        text = path.read_text(encoding="utf-8")
        if any(name in text for name in names):
            offenders.append(str(path.relative_to(root)))
    allowed = {root / "service" / "tests" / "test_native_webrtc_runtime.py"}
    for path in (root / "service" / "tests").rglob("test_*.py"):
        if "connection" in path.parts or path in allowed:
            continue
        text = path.read_text(encoding="utf-8")
        if any(name in text for name in names):
            offenders.append(str(path.relative_to(root)))
    assert offenders == []


def test_isolated_cli_production_skips_platform_recompilation():
    plan = ci.select(["service/src/mesh_chat/core_api/cli.py"])
    assert plan["required"] == ["policy", "verification"]
    assert plan["reason"] == "isolated_cli_production"


@pytest.mark.parametrize("event", ["workflow_dispatch", "merge_group", "release", "schedule"])
def test_cli_narrowing_is_limited_to_branch_events(event):
    assert ci.select(["service/src/mesh_chat/core_api/cli.py"],
                     event=event)["required"] == list(ci.SUITES)


@pytest.mark.parametrize("status", ["failure", "cancelled", "skipped", None])
def test_android_and_verification_dependency_changes_cannot_hide_missing_native_topology(status):
    plan = ci.select([KOTLIN_CLIENT + "CoreClient.kt"])
    assert {"verification", "android", "native_interop"} <= set(plan["required"])
    jobs = {suite: {"result": "success"} for suite in ci.SUITES}
    jobs["native_interop"]["result"] = status
    with pytest.raises(ValueError, match="native_interop"): ci.validate(plan, jobs)


def test_native_topology_starts_after_both_real_packages_and_is_a_required_final_dependency():
    import yaml
    value = yaml.safe_load((SCRIPT.parents[1] / ".github/workflows/connection-qualification.yml").read_text())
    jobs = value["jobs"]
    assert set(jobs["native_interop"]["needs"]) == {"plan", "verification", "android"}
    assert jobs["native_interop"]["uses"] == "./.github/workflows/native-interop.yml"
    assert "native_interop" in jobs["gate"]["needs"]
    assert jobs["gate"]["if"] == ("${{ always() && !(github.event_name == 'workflow_dispatch' && "
                                    "(inputs.b8_first_cold_diagnostic || inputs.public_pair_diagnostic || inputs.public_restart_diagnostic)) }}")
    downloads = [step.get("with", {}).get("name", "") for step in jobs["gate"]["steps"] if step.get("uses", "").startswith("actions/download-artifact@")]
    assert any(name.startswith("native-interop-windows-") for name in downloads)
    assert any(name.startswith("native-interop-android-") for name in downloads)
    check = next(step for step in jobs["gate"]["steps"]
                 if "--check-plan" in step.get("run", ""))
    assert check["if"] == "always()"

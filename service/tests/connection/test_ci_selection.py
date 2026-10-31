import importlib.util
from pathlib import Path
import subprocess

import pytest


SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "connection_ci.py"
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


@pytest.mark.parametrize("event", ["workflow_dispatch", "merge_group", "release", "schedule", "unknown"])
def test_manual_release_merge_queue_and_unknown_events_cannot_narrow_coverage(event):
    assert ci.select(["README.md"], event=event)["required"] == list(ci.SUITES)


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

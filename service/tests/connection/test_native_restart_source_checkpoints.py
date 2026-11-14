"""Focused build checkpoints expose tracked mutations without source contents."""

import hashlib
import json
import pytest
from pathlib import Path
import subprocess
import sys

import yaml


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
import native_restart_source_checkpoints as checkpoints


def git(repo, *args):
    return subprocess.check_output(["git", *args], cwd=repo, text=True,
                                   stderr=subprocess.DEVNULL).strip()


@pytest.mark.parametrize("filemode", ["false", "true"])
def test_real_git_checkpoints_show_mode_only_and_content_changes(tmp_path, monkeypatch, filemode):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "config", "core.filemode", filemode], cwd=repo, check=True)
    relative = "src-tauri/gen/android/buildSrc/src/main/java/com/meshchat/mobile/kotlin/BuildTask.kt"
    launcher = repo / relative
    launcher.parent.mkdir(parents=True)
    launcher.write_text("original\n", encoding="utf-8")
    subprocess.run(["git", "add", relative], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.name=Diagnostic", "-c", "user.email=diagnostic@example.invalid",
                    "commit", "-qm", "baseline"], cwd=repo, check=True)
    source = git(repo, "rev-parse", "HEAD")
    monkeypatch.setattr(checkpoints, "ROOT", repo)
    output = tmp_path / "checkpoints.json"
    before = checkpoints.checkpoint(output, source, "before_app")
    assert before["status"] == "captured" and before["tracked_clean"] is True
    original_sha = hashlib.sha256(launcher.read_bytes()).hexdigest()
    subprocess.run(["git", "update-index", "--chmod=+x", relative], cwd=repo, check=True)
    after = checkpoints.checkpoint(output, source, "after_app")
    assert after["status"] == "captured" and after["tracked_clean"] is False
    assert after["changed_count"] == 1 and after["entries_truncated"] is False
    assert after["entries"] == [{"status": "M", "path": relative,
                                  "index_status": "M", "worktree_status": "M" if filemode == "true" else None,
                                  "head_mode": "100644", "index_mode": "100755",
                                  "worktree_mode": checkpoints.worktree_mode(launcher),
                                  "sha256": original_sha}]
    launcher.write_text("changed content stays private\n", encoding="utf-8")
    changed = checkpoints.checkpoint(output, source, "before_test")
    assert changed["entries"][0]["sha256"] == hashlib.sha256(launcher.read_bytes()).hexdigest()
    assert changed["entries"][0]["sha256"] != original_sha
    report = output.read_text(encoding="utf-8")
    assert "changed content stays private" not in report
    assert [item["stage"] for item in json.loads(report)["checkpoints"]] == [
        "before_app", "after_app", "before_test"]


def test_staged_content_then_worktree_revert_remains_visible(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    file = repo / "tracked.txt"
    file.write_text("original\n")
    git(repo, "add", "tracked.txt")
    git(repo, "-c", "user.name=Diagnostic", "-c", "user.email=diagnostic@example.invalid",
        "commit", "-qm", "baseline")
    source = git(repo, "rev-parse", "HEAD")
    file.write_text("staged content stays private\n")
    git(repo, "add", "tracked.txt")
    file.write_text("original\n")
    assert git(repo, "diff", "HEAD", "--") == ""
    monkeypatch.setattr(checkpoints, "ROOT", repo)
    record = checkpoints.snapshot(source)
    assert record["tracked_clean"] is False and record["changed_count"] == 1
    assert record["entries"][0]["path"] == "tracked.txt"
    assert record["entries"][0]["index_status"] == "M"
    assert record["entries"][0]["worktree_status"] == "M"
    assert "staged content" not in json.dumps(record)


def test_unsafe_or_many_changed_paths_are_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(checkpoints, "ROOT", tmp_path)
    monkeypatch.setattr(checkpoints, "tracked_mode", lambda *args: None)
    raw = b"M\0private name.txt\0" + b"".join(
        b"M\0safe/path" + str(index).encode() + b"\0" for index in range(40))
    entries, count, truncated = checkpoints.entries_from_diff(raw)
    assert count == 41 and truncated is True and len(entries) == checkpoints.MAX_ENTRIES
    assert entries[0]["status"] == "M" and "path" not in entries[0]
    assert len(entries[0]["path_sha256"]) == 64


def test_two_diff_layers_share_the_inventory_and_size_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(checkpoints, "ROOT", tmp_path)
    monkeypatch.setattr(checkpoints, "tracked_mode", lambda *args: None)
    entries, count, truncated = checkpoints.entries_from_diff(
        b"A\0staged.txt\0M\0both.txt\0", b"D\0staged.txt\0M\0both.txt\0M\0working.txt\0")
    assert count == 3 and truncated is False
    assert [(row["path"], row["index_status"], row["worktree_status"]) for row in entries] == [
        ("staged.txt", "A", "D"), ("both.txt", "M", "M"), ("working.txt", None, "M")]
    assert checkpoints.entries_from_diff(b"x" * checkpoints.MAX_DIFF_BYTES, b"x") == ([], None, True)


def test_workflow_checkpoints_bracket_builds_and_rust_cache_is_restore_only():
    workflow = yaml.safe_load((ROOT / ".github/workflows/native-restart-diagnostic.yml").read_text())
    steps = workflow["jobs"]["android_restart_diagnostic"]["steps"]
    by_name = {step["name"]: index for index, step in enumerate(steps) if "name" in step}
    assert (by_name["Record tracked source before app build"]
            < by_name["Build the same-source Android app"]
            < by_name["Record tracked source after app build"])
    assert (by_name["Record tracked source before instrumentation build"]
            < by_name["Build the existing instrumentation host"]
            < by_name["Record tracked source after instrumentation build"])
    assert (by_name["Record tracked source after instrumentation build"]
            < by_name["Record tracked source before reopen probe"]
            < by_name["Run bounded reopen observations"])
    rust = next(step for step in steps if step.get("uses") == "Swatinem/rust-cache@v2")
    assert rust["with"]["save-if"] == "false"
    assert "cache-on-failure" not in rust["with"]
    upload = next(step for step in steps if step.get("name") == "Retain every diagnostic result")
    assert "dist/reports/native-restart-source-checkpoints.json" in upload["with"]["path"]
    assert "dist/reports/native-restart-diagnostic.json" in upload["with"]["path"]

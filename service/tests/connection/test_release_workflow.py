"""Release publication must consume qualified bytes, not just a green build."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = ROOT / ".github" / "workflows"
TAG_GUARD = "startsWith(github.ref, 'refs/tags/v')"


def load(name):
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def triggers(document):
    return document.get(True) or document.get("on")


def test_qualification_workflow_is_callable_and_publication_requires_it():
    assert "workflow_call" in triggers(load("connection-qualification.yml"))
    release = load("release.yml")
    assert release["jobs"]["qualification"]["uses"] == \
        "./.github/workflows/connection-qualification.yml"
    needs = release["jobs"]["publish"]["needs"]
    assert "qualification" in needs and "qualify" in needs


def test_publication_rehashes_staged_assets_against_the_manifest():
    release = load("release.yml")
    qualify = release["jobs"]["qualify"]
    commands = " ".join(step.get("run", "") for step in qualify["steps"])
    assert "scripts/release_qualification.py" in commands
    upload = next(step for step in qualify["steps"] if step.get("uses", "").startswith("actions/upload-artifact"))
    assert upload["with"]["name"] == "release-qualification-${{ github.sha }}"

    publish_steps = release["jobs"]["publish"]["steps"]
    verify = next(step for step in publish_steps
                  if step.get("name") == "Require the qualified bytes before publishing")
    assert "scripts/verify_release_assets.py" in verify["run"]
    assert "--manifest release-evidence/dist/reports/release-qualification.json" in verify["run"]
    assert "--assets release-assets" in verify["run"]


def test_qualification_jobs_are_tag_gated():
    release = load("release.yml")
    for job in ("qualification", "qualify"):
        assert release["jobs"][job]["if"] == TAG_GUARD
    assert "startsWith(github.ref, 'refs/tags/v')" in release["jobs"]["publish"]["if"]

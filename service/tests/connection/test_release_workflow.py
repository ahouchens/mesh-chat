"""Release publication must consume qualified bytes, not just a green build."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = ROOT / ".github" / "workflows"


def release():
    return (WORKFLOWS / "release.yml").read_text(encoding="utf-8")


def test_publication_requires_the_connection_qualification_workflow():
    text = release()
    assert "  workflow_call:" in (WORKFLOWS / "connection-qualification.yml").read_text(encoding="utf-8")
    assert "uses: ./.github/workflows/connection-qualification.yml" in text
    needs = text[text.index("  publish:"):]
    needs = needs[: needs.index("runs-on:")]
    assert "- qualification" in needs and "- qualify" in needs


def test_publication_rehashes_staged_assets_against_the_manifest():
    text = release()
    assert "release-qualification-${{ github.sha }}" in text
    assert "scripts/release_qualification.py" in text
    assert "scripts/verify_release_assets.py" in text
    section = text[text.index("Require the qualified bytes before publishing"):]
    assert "--manifest release-evidence/dist/reports/release-qualification.json" in section
    assert "--assets release-assets" in section
    assert (ROOT / "scripts" / "verify_release_assets.py").is_file()


def test_qualification_is_only_required_for_release_tags():
    text = release()
    for job in ("  qualification:", "  qualify:"):
        section = text[text.index(job):]
        assert "if: startsWith(github.ref, 'refs/tags/v')" in section[: section.index("runs-on:")]

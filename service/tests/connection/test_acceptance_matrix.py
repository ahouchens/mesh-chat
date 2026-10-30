"""The acceptance reconciliation must stay complete and honestly labelled."""

import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
DOCUMENT = ROOT / "docs" / "Mesh_Chat_Connection_Runtime_Acceptance.md"
ROADMAP = ROOT / "docs" / "Mesh_Chat_Connection_Runtime_Roadmap.md"
STATUSES = {"local", "component", "workflow", "partial", "open", "unavailable"}
ROW = re.compile(r"^\| (INV\d{2}|SC\d{2}) \| `([a-z]+)` \| (.+) \|$", re.MULTILINE)


def rows():
    text = DOCUMENT.read_text(encoding="utf-8")
    return {identifier: (status, note) for identifier, status, note in ROW.findall(text)}


def test_every_invariant_and_required_scenario_has_one_status_row():
    found = rows()
    expected = {f"INV{index:02d}" for index in range(1, 27)} | {f"SC{index:02d}" for index in range(1, 27)}
    assert set(found) == expected
    assert len(found) == 52


@pytest.mark.parametrize("identifier", sorted(rows()))
def test_each_row_uses_the_declared_vocabulary_and_cites_evidence(identifier):
    status, note = rows()[identifier]
    assert status in STATUSES
    assert len(note.strip()) >= 10
    assert "complete" != status


def test_physical_only_acceptance_is_marked_unavailable_and_never_implied():
    found = rows()
    assert found["SC21"][0] == "unavailable"
    text = DOCUMENT.read_text(encoding="utf-8")
    assert "## Physical checklist" in text
    assert "Unavailable in this environment" in text
    unavailable = {identifier for identifier, (status, _) in found.items() if status == "unavailable"}
    assert unavailable == {"SC21"}


def test_the_roadmap_links_to_the_reconciliation():
    assert "Mesh_Chat_Connection_Runtime_Acceptance.md" in ROADMAP.read_text(encoding="utf-8")

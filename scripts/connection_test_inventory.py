"""Pytest evidence binding for the required connection qualification selection."""

import json
from pathlib import Path
from uuid import uuid4


REQUIRED_SUITES = (
    "service/tests/connection",
    "service/tests/test_background_reconnect.py",
    "service/tests/test_native_webrtc_runtime.py",
    "service/tests/test_native_event_inbox.py",
    "service/tests/test_native_resource_registry.py",
    "service/tests/test_native_startup_packets.py",
    "service/tests/test_native_webrtc_events.py",
    "service/tests/test_reconnect_scope.py",
    "service/tests/test_reconnect_service.py",
    "service/tests/test_connection_diagnostics.py",
)


class TestInventory:
    def __init__(self, path: Path, source: str):
        self.path = path
        self.source = source
        self.run_id = uuid4().hex
        self.deselected = False

    def pytest_deselected(self, items):
        self.deselected = self.deselected or bool(items)

    def pytest_collection_finish(self, session):
        options = session.config.option
        if self.deselected or any(getattr(options, name, None)
                                 for name in ("keyword", "markexpr", "deselect", "ignore", "ignore_glob", "lf")):
            raise ValueError("Required qualification cannot deselect tests")
        if session.testsfailed or not session.items:
            raise ValueError("Required qualification collection failed or was empty")
        nodeids = [item.nodeid for item in session.items]
        for suite in REQUIRED_SUITES:
            # Pytest's rootdir is service/, so nodeids omit that prefix.
            prefix = suite.removeprefix("service/")
            if not any(nodeid.startswith(prefix + ("::" if prefix.endswith(".py") else "/"))
                       for nodeid in nodeids):
                raise ValueError("Required qualification suite was not collected: " + suite)
        for item in session.items:
            item.user_properties.extend((("qualification_nodeid", item.nodeid),
                                         ("qualification_run", self.run_id)))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({
            "v": 1, "source_commit": self.source, "run_id": self.run_id,
            "selection": list(REQUIRED_SUITES), "nodeids": sorted(nodeids),
        }, indent=2) + "\n", encoding="utf-8")

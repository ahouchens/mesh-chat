"""Fail-closed input checks for the packaged WebView2 capture preflight."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import packaged_media_preflight as preflight


class PublishedCandidateTests(unittest.TestCase):
    def test_git_40_character_source_and_tree_are_required(self):
        source = "a" * 40
        tree = "b" * 40
        with patch.object(preflight.subprocess, "check_output", side_effect=[source, tree, b""]):
            self.assertEqual(preflight.source_identity(source), (source, tree))
        with self.assertRaisesRegex(preflight.PreflightFailure, "expected_source_invalid"):
            preflight.source_identity("a" * 64)

    def test_installed_bytes_must_match_the_bound_release_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = root / "mesh-chat.exe"
            sidecar = root / "mesh-chat-service.exe"
            app.write_bytes(b"application candidate")
            sidecar.write_bytes(b"sidecar candidate")
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({
                "schema_version": 1, "product": "Mesh Chat", "platform": "windows",
                "artifacts": [
                    {"role": "application", "path": app.name, "sha256": preflight.digest(app), "size": app.stat().st_size},
                    {"role": "sidecar", "path": sidecar.name, "sha256": preflight.digest(sidecar), "size": sidecar.stat().st_size},
                ],
            }), encoding="utf-8")
            expected = preflight.digest(manifest)
            bound = preflight.published_bytes(manifest, expected, app)
            self.assertEqual(bound["application_sha256"], preflight.digest(app))
            sidecar.write_bytes(b"changed sidecar candidate")
            with self.assertRaisesRegex(preflight.PreflightFailure, "installed_bytes_mismatch"):
                preflight.published_bytes(manifest, expected, app)
            with self.assertRaisesRegex(preflight.PreflightFailure, "manifest_mismatch"):
                preflight.published_bytes(manifest, "0" * 64, app)

    def test_existing_app_data_refuses_launch_without_deleting_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            roaming = root / "roaming"
            local = root / "local"
            roaming.mkdir()
            local.mkdir()
            preflight.require_fresh_app_data("com.meshchat.desktop", roaming, local)
            marker = roaming / "com.meshchat.desktop"
            marker.mkdir()
            with self.assertRaisesRegex(preflight.PreflightFailure, "app_data_not_fresh"):
                preflight.require_fresh_app_data("com.meshchat.desktop", roaming, local)
            self.assertTrue(marker.is_dir())


if __name__ == "__main__":
    unittest.main()

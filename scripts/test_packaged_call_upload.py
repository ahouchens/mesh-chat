"""Run the real sealed uploader against an isolated artifact-client boundary."""

import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parent / "native-interop-artifact/packaged-call-upload.mjs"


class PackagedCallUploadTest(unittest.TestCase):
    def test_push_and_dispatch_upload_but_other_events_cannot(self):
        fields = {"repository": "example/mesh", "repository_id": 11, "run_id": 22,
                  "run_attempt": 1, "source_commit": "a" * 40, "source_tree": "b" * 40}
        canonical = json.dumps(fields, sort_keys=True, separators=(",", ":")).encode("ascii")
        pair_id = hashlib.sha256(b"packaged-call:v1:" + canonical).hexdigest()[:32]
        context = {**fields, "pair_id": pair_id}
        name = f"packaged-call-v1-22-1-{'a' * 12}-{pair_id}-peer-key"
        value = {"v": 1, "context": context, "producer_job": "call_peer",
                 "created_at": 1000, "expires_at": 2800, "role": "peer",
                 "public_key": base64.urlsafe_b64encode(b"\x07" * 32).decode().rstrip("=")}
        environment = {**os.environ, "GITHUB_JOB": "call_peer", "GITHUB_ACTIONS": "true",
                       "GITHUB_REPOSITORY": fields["repository"], "GITHUB_REPOSITORY_ID": "11",
                       "GITHUB_RUN_ID": "22", "GITHUB_RUN_ATTEMPT": "1",
                       "GITHUB_SHA": fields["source_commit"],
                       "PACKAGED_CALL_TREE": fields["source_tree"],
                       "ACTIONS_RUNTIME_TOKEN": "test-runtime",
                       "ACTIONS_RESULTS_URL": "https://results.invalid/test",
                       "EXPECTED_ARTIFACT_NAME": name}
        with tempfile.TemporaryDirectory(prefix="packaged-call-upload-test-") as temporary:
            root = Path(temporary)
            package = root / "node_modules/@actions/artifact"
            package.mkdir(parents=True)
            (package / "package.json").write_text(json.dumps({
                "name": "@actions/artifact", "type": "module", "main": "index.mjs"}),
                encoding="utf-8")
            (package / "index.mjs").write_text("""
export class DefaultArtifactClient {
  async uploadArtifact(name, files, directory, options) {
    if (name !== process.env.EXPECTED_ARTIFACT_NAME || files.length !== 1
        || directory !== process.env.EXPECTED_ARTIFACT_DIR
        || options.retentionDays !== 1 || options.compressionLevel !== 0
        || !process.env.ACTIONS_RUNTIME_TOKEN || !process.env.ACTIONS_RESULTS_URL) throw new Error();
    return { id: 7, size: 128 };
  }
}
""", encoding="utf-8")
            uploader = root / SCRIPT.name
            shutil.copyfile(SCRIPT, uploader)
            for event, expected in (("push", 0), ("workflow_dispatch", 0),
                                    ("pull_request", 1)):
                with self.subTest(event=event):
                    directory = root / event
                    directory.mkdir()
                    bundle = directory / "bundle.json"
                    identity = directory / "identity.json"
                    bundle.write_text(json.dumps(value), encoding="utf-8")
                    result = subprocess.run(["node", str(uploader), name, str(bundle), str(identity)],
                                            env={**environment, "GITHUB_EVENT_NAME": event,
                                                 "EXPECTED_ARTIFACT_DIR": str(directory)},
                                            capture_output=True, text=True, check=False)
                    self.assertEqual(result.returncode, expected, result.stderr)
                    self.assertEqual((result.stdout, result.stderr), ("", ""))
                    if expected == 0:
                        self.assertEqual(json.loads(identity.read_text(encoding="utf-8")),
                                         {"passed": True, "id": 7, "size": 128})
                    else:
                        self.assertFalse(identity.exists())


if __name__ == "__main__":
    unittest.main()

"""Bounded same-run REST downloads and official Actions-SDK setup uploads."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

from native_interop_rendezvous import (MAX_ARCHIVE, MAX_BLOB, PRODUCER_JOBS, artifact_name,
                                        canonical, checked_context, verify_artifact)

API = "https://api.github.com"
API_VERSION = "2026-03-10"
MAX_API_RESPONSE = 512 * 1024


class RendezvousUnavailable(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def context_from_environment(environment=os.environ):
    try:
        return checked_context({"repository": environment["GITHUB_REPOSITORY"],
                                "repository_id": int(environment["GITHUB_REPOSITORY_ID"]),
                                "run_id": int(environment["GITHUB_RUN_ID"]),
                                "run_attempt": int(environment["GITHUB_RUN_ATTEMPT"]),
                                "source_commit": environment["GITHUB_SHA"]})
    except (KeyError, ValueError) as error:
        raise RendezvousUnavailable("Authenticated GitHub run context is unavailable") from error


class GithubArtifacts:
    def __init__(self, context, role, directory, *, node="node", token=None, environment=os.environ,
                 clock=time.monotonic, sleep=time.sleep):
        self.context = checked_context(context)
        self.role = role
        self.directory = Path(directory)
        self.node, self.clock, self.sleep = node, clock, sleep
        self._token = token if token is not None else environment.get("GITHUB_TOKEN")
        if (role not in PRODUCER_JOBS or environment.get("GITHUB_JOB") != PRODUCER_JOBS[role]
                or context_from_environment(environment) != context or not self._token):
            raise RendezvousUnavailable("Unexpected publishing job, role or authenticated run")
        self.directory.mkdir(parents=True, exist_ok=True)
        self._published = set()

    def _live(self):
        if self._token is None:
            raise RendezvousUnavailable("Bootstrap artifact transport is closed")

    def _request(self, path, *, binary=False):
        self._live()
        url = API + path
        request = urllib.request.Request(url, headers={"Authorization": "Bearer " + self._token,
            "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": "mesh-native-qualification/1"})
        opener = urllib.request.build_opener(NoRedirect())
        try:
            try:
                response = opener.open(request, timeout=10)
            except urllib.error.HTTPError as redirect:
                if not binary or redirect.code != 302:
                    raise RendezvousUnavailable("GitHub artifact request rejected") from None
                location = redirect.headers.get("Location", "")
                target = urllib.parse.urlsplit(location)
                if target.scheme != "https" or not target.hostname or target.username or target.password or target.fragment:
                    raise RendezvousUnavailable("Invalid artifact download location")
                # The repository token is NEVER forwarded to signed blob storage.
                response = opener.open(urllib.request.Request(location), timeout=10)
            limit = MAX_ARCHIVE if binary else MAX_API_RESPONSE
            with response:
                data = response.read(limit + 1)
            if not data or len(data) > limit:
                raise RendezvousUnavailable("GitHub response exceeds its qualification budget")
            return data if binary else json.loads(data)
        except RendezvousUnavailable:
            raise
        except Exception:
            # Do not include request URLs, signed URLs, bearer headers or raw bodies.
            raise RendezvousUnavailable("GitHub artifact transport is unavailable") from None

    def publish(self, phase, bundle):
        self._live()
        name = artifact_name(self.context, self.role, phase)
        if phase in self._published or not isinstance(bundle, dict) or len(canonical(bundle)) > MAX_BLOB:
            raise ValueError("Duplicate or oversized bootstrap artifact")
        if bundle.get("producer_job") != PRODUCER_JOBS[self.role] or bundle.get("context") != self.context:
            raise ValueError("Unexpected bootstrap publisher context")
        with tempfile.TemporaryDirectory(prefix="upload-", dir=self.directory) as directory:
            path = Path(directory) / "bundle.json"
            path.write_bytes(canonical(bundle))
            helper = Path(__file__).resolve().parent / "native-interop-artifact/upload.mjs"
            try:
                process = subprocess.run([self.node, str(helper), name, str(path)],
                                         capture_output=True, timeout=60, text=True)
            except Exception:
                raise RendezvousUnavailable("Bounded artifact upload is unavailable") from None
            if process.returncode:
                raise RendezvousUnavailable("Bounded artifact upload failed")
            try:
                result = json.loads(process.stdout.splitlines()[-1])
            except (ValueError, IndexError):
                raise RendezvousUnavailable("Artifact upload returned no identity") from None
            if (result.get("passed") is not True or type(result.get("id")) is not int
                    or result["id"] <= 0 or type(result.get("size")) is not int
                    or not 0 < result["size"] <= MAX_ARCHIVE):
                raise RendezvousUnavailable("Artifact upload returned an invalid identity")
        self._published.add(phase)
        return {"id": result["id"], "size": result["size"], "name": name}

    def wait(self, role, phase, *, timeout=900):
        self._live()
        if type(timeout) not in {int, float} or not 0 < timeout <= 900:
            raise ValueError("Artifact wait deadline is out of bounds")
        name = artifact_name(self.context, role, phase)
        endpoint = f"/repos/{self.context['repository']}/actions/runs/{self.context['run_id']}"
        deadline = self.clock() + timeout
        while self.clock() < deadline:
            inventory = self._request(endpoint + "/artifacts?per_page=100")
            entries = inventory.get("artifacts") if isinstance(inventory, dict) else None
            if (not isinstance(entries, list) or len(entries) > 100 or not all(isinstance(item, dict) for item in entries)
                    or type(inventory.get("total_count")) is not int or inventory["total_count"] > 100):
                raise RendezvousUnavailable("Artifact inventory exceeds its bounded run budget")
            matching = [value for value in entries if value.get("name") == name]
            if len(matching) > 1:
                raise RendezvousUnavailable("Duplicate bootstrap artifact identity")
            if matching:
                metadata = matching[0]
                identifier = metadata.get("id")
                if type(identifier) is not int or identifier <= 0:
                    raise RendezvousUnavailable("Missing bootstrap artifact identity")
                archive = self._request(f"/repos/{self.context['repository']}/actions/artifacts/{identifier}/zip", binary=True)
                return verify_artifact(metadata, archive, self.context, role, phase)
            self.sleep(min(3, max(0, deadline - self.clock())))
        raise RendezvousUnavailable("Required partner bootstrap artifact did not arrive before deadline")

    def close(self):
        # Official artifact retention is one day. Private keys and decoded
        # shareables never enter this transport; temporary bundles are removed.
        self._token = None

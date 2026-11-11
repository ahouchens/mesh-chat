"""Bounded same-run REST downloads and official Actions-SDK setup uploads."""

import json
from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

from native_interop_rendezvous import (MAX_ARCHIVE, MAX_BLOB, PRODUCER_JOBS, artifact_name,
                                        canonical, checked_context, validate_upload, verify_artifact)

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
        self._receiving = False
        self._receive_failure = None
        self._retryable_read_503 = None

    @contextmanager
    def _receive_scope(self):
        self._receive_failure = None
        self._retryable_read_503 = None
        self._receiving = True
        try:
            yield
        except Exception as error:
            if self._receive_failure is not None and self._receive_failure[0] is not error:
                self._receive_failure = None
            raise
        else:
            self._receive_failure = None
        finally:
            self._receiving = False
            self._retryable_read_503 = None

    def _unavailable(self, stage, reason, message, http_error=None):
        error = RendezvousUnavailable(message)
        if self._receiving:
            selected = {"rendezvous_stage": stage, "rendezvous_reason": reason}
            if type(http_error) is urllib.error.HTTPError:
                try: status = http_error.code
                except Exception: status = None
                if type(status) is int and 100 <= status <= 599:
                    selected["rendezvous_http_status"] = status
                    if (status == 503 and reason == "http_rejected" and stage in
                            {"inventory_request", "archive_request", "blob_request"}):
                        self._retryable_read_503 = error
            self._receive_failure = error, selected
        return error

    def failure_observation(self, error):
        observed = self._receive_failure
        return dict(observed[1]) if observed is not None and observed[0] is error else {}

    def _live(self):
        if self._token is None:
            raise self._unavailable("transport_state", "closed", "Bootstrap artifact transport is closed")

    def _request(self, path, *, binary=False, deadline=None):
        self._receive_failure = None
        self._retryable_read_503 = None
        self._live()
        url = API + path
        request = urllib.request.Request(url, headers={"Authorization": "Bearer " + self._token,
            "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": "mesh-native-qualification/1"})
        opener = urllib.request.build_opener(NoRedirect())
        stage = "archive_request" if binary else "inventory_request"
        reason = "transport_failed"
        def open_timeout():
            if deadline is None:
                return 10
            remaining = deadline - self.clock()
            if remaining <= 0:
                raise self._unavailable("partner_wait", "deadline_exhausted",
                                        "Required partner bootstrap artifact did not arrive before deadline")
            return min(10, remaining)
        try:
            try:
                response = opener.open(request, timeout=open_timeout())
            except urllib.error.HTTPError as redirect:
                if not binary or redirect.code != 302:
                    raise self._unavailable(stage, "http_rejected", "GitHub artifact request rejected", redirect) from None
                reason = "redirect_invalid"
                location = redirect.headers.get("Location", "")
                target = urllib.parse.urlsplit(location)
                if target.scheme != "https" or not target.hostname or target.username or target.password or target.fragment:
                    raise self._unavailable(stage, "redirect_invalid", "Invalid artifact download location")
                # The repository token is NEVER forwarded to signed blob storage.
                stage, reason = "blob_request", "transport_failed"
                try:
                    response = opener.open(urllib.request.Request(location), timeout=open_timeout())
                except urllib.error.HTTPError as error:
                    raise self._unavailable(stage, "http_rejected", "GitHub artifact transport is unavailable", error) from None
            limit = MAX_ARCHIVE if binary else MAX_API_RESPONSE
            reason = "read_failed"
            with response:
                data = response.read(limit + 1)
            if deadline is not None and self.clock() >= deadline:
                raise self._unavailable("partner_wait", "deadline_exhausted",
                                        "Required partner bootstrap artifact did not arrive before deadline")
            if not data or len(data) > limit:
                raise self._unavailable(stage, "response_empty" if not data else "response_oversized",
                                        "GitHub response exceeds its qualification budget")
            if binary: return data
            # The response context/read has completed; other decoder failures
            # retain the existing generic wrapper rather than a read label.
            reason = "transport_failed"
            try:
                return json.loads(data)
            except (json.JSONDecodeError, UnicodeDecodeError):
                raise self._unavailable(stage, "json_invalid", "GitHub artifact transport is unavailable") from None
        except RendezvousUnavailable:
            raise
        except Exception:
            # Do not include request URLs, signed URLs, bearer headers or raw bodies.
            raise self._unavailable(stage, reason, "GitHub artifact transport is unavailable") from None

    def publish(self, phase, bundle):
        self._receive_failure = None
        self._live()
        name = artifact_name(self.context, self.role, phase)
        if phase in self._published or not isinstance(bundle, dict) or len(canonical(bundle)) > MAX_BLOB:
            raise ValueError("Duplicate or oversized bootstrap artifact")
        validate_upload(self.context, self.role, phase, bundle)
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
        with self._receive_scope():
            return self._wait(role, phase, timeout)

    def _wait(self, role, phase, timeout):
        self._live()
        if type(timeout) not in {int, float} or not 0 < timeout <= 900:
            raise ValueError("Artifact wait deadline is out of bounds")
        name = artifact_name(self.context, role, phase)
        endpoint = f"/repos/{self.context['repository']}/actions/runs/{self.context['run_id']}"
        deadline = self.clock() + timeout
        transient_503s = 0
        while self.clock() < deadline:
            try:
                inventory = self._request(endpoint + "/artifacts?per_page=100", deadline=deadline)
                entries = inventory.get("artifacts") if isinstance(inventory, dict) else None
                if (not isinstance(entries, list) or len(entries) > 100 or not all(isinstance(item, dict) for item in entries)
                        or type(inventory.get("total_count")) is not int or inventory["total_count"] > 100):
                    raise self._unavailable("inventory_check", "inventory_invalid", "Artifact inventory exceeds its bounded run budget")
                matching = [value for value in entries if value.get("name") == name]
                if len(matching) > 1:
                    raise self._unavailable("inventory_check", "duplicate_identity", "Duplicate bootstrap artifact identity")
                if matching:
                    metadata = matching[0]
                    identifier = metadata.get("id")
                    if type(identifier) is not int or identifier <= 0:
                        raise self._unavailable("inventory_check", "missing_identity", "Missing bootstrap artifact identity")
                    archive = self._request(f"/repos/{self.context['repository']}/actions/artifacts/{identifier}/zip",
                                            binary=True, deadline=deadline)
                    verified = verify_artifact(metadata, archive, self.context, role, phase)
                    if self.clock() >= deadline:
                        raise self._unavailable("partner_wait", "deadline_exhausted",
                                                "Required partner bootstrap artifact did not arrive before deadline")
                    return verified
            except RendezvousUnavailable as error:
                if (transient_503s >= 2 or self._retryable_read_503 is not error
                        or deadline - self.clock() <= 3):
                    raise
                transient_503s += 1
                self.sleep(3)
                continue
            self.sleep(min(3, max(0, deadline - self.clock())))
        raise self._unavailable("partner_wait", "deadline_exhausted", "Required partner bootstrap artifact did not arrive before deadline")

    def close(self):
        # Official artifact retention is one day. Private keys and decoded
        # shareables never enter this transport; temporary bundles are removed.
        self._token = None
        self._receive_failure = None

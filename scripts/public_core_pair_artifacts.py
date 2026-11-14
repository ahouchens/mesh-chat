"""Same-run GitHub artifact transport for sealed public Core pair setup."""

import json
import os
from pathlib import Path
import queue
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from public_core_pair_rendezvous import (JOBS, MAX_ARCHIVE, MAX_BLOB, Rendezvous, artifact_name,
    canonical, checked_context, context_from_environment, partner, validate_upload,
    validated_artifact_metadata, verify_artifact)


API = "https://api.github.com"
API_VERSION = "2026-03-10"
MAX_INVENTORY = 512 * 1024
MAX_ARTIFACTS = 100
UPLOAD = Path(__file__).resolve().parent / "native-interop-artifact/public-pair-upload.mjs"


class PublicPairUnavailable(RuntimeError):
    def __init__(self, message, *, status=None):
        super().__init__(message)
        self.status = status


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GithubArtifacts:
    """Publish one bundle per phase and verify exact same-run partner artifacts."""

    def __init__(self, context, role, directory, *, node="node", token=None,
                 environment=os.environ, clock=time.monotonic, sleep=time.sleep, opener=None):
        self.context = checked_context(context)
        if (role not in JOBS or environment.get("GITHUB_JOB") != JOBS[role]
                or environment.get("GITHUB_ACTIONS") != "true"
                or environment.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
                or context_from_environment(environment) != self.context):
            raise PublicPairUnavailable("Unexpected public pair job or run")
        self.token = token if token is not None else environment.get("GITHUB_TOKEN")
        if not self.token:
            raise PublicPairUnavailable("Public pair artifact read authority is unavailable")
        self.role, self.directory = role, Path(directory)
        self.node, self.clock, self.sleep = node, clock, sleep
        self.opener = opener or urllib.request.build_opener(NoRedirect())
        self.directory.mkdir(parents=True, exist_ok=True)
        self._published = set()

    def _read_response(self, response, limit, deadline):
        """Enforce the phase deadline across a trickling HTTP body."""
        outcome = queue.Queue(maxsize=1)

        def read_body():
            try:
                with response:
                    data = response.read(limit + 1)
                outcome.put_nowait((data, None))
            except Exception as error:
                outcome.put_nowait((None, error))

        reader = threading.Thread(target=read_body, daemon=True)
        reader.start()

        def abort_read():
            try: response.close()
            except Exception: pass

        remaining = deadline - self.clock()
        if remaining <= 0:
            threading.Thread(target=abort_read, daemon=True).start()
            raise PublicPairUnavailable("Public pair partner wait expired")
        try:
            data, error = outcome.get(timeout=remaining)
        except queue.Empty:
            threading.Thread(target=abort_read, daemon=True).start()
            raise PublicPairUnavailable("Public pair partner wait expired") from None
        if error is not None:
            raise PublicPairUnavailable("Public pair artifact read failed") from None
        return data

    def _request(self, path, *, archive=False, deadline):
        if self.token is None or not path.startswith("/repos/" + self.context["repository"] + "/actions/"):
            raise PublicPairUnavailable("Public pair artifact transport is closed or invalid")
        timeout = min(10, deadline - self.clock())
        if timeout <= 0:
            raise PublicPairUnavailable("Public pair partner wait expired")
        request = urllib.request.Request(API + path, headers={
            "Authorization": "Bearer " + self.token, "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION, "User-Agent": "mesh-public-core-pair/1"})
        try:
            try:
                response = self.opener.open(request, timeout=timeout)
            except urllib.error.HTTPError as error:
                if not archive or error.code != 302:
                    raise PublicPairUnavailable("Public pair artifact request was rejected",
                                                status=error.code) from None
                target = urllib.parse.urlsplit(error.headers.get("Location", ""))
                if (target.scheme != "https" or not target.hostname or target.username or target.password
                        or target.fragment):
                    raise PublicPairUnavailable("Public pair artifact redirect is invalid") from None
                # The repository token never crosses to signed blob storage.
                remaining = deadline - self.clock()
                if remaining <= 0:
                    raise PublicPairUnavailable("Public pair partner wait expired") from None
                try:
                    response = self.opener.open(urllib.request.Request(target.geturl()),
                                                timeout=min(10, remaining))
                except urllib.error.HTTPError as error:
                    raise PublicPairUnavailable("Public pair artifact blob is unavailable",
                                                status=error.code) from None
            limit = MAX_ARCHIVE if archive else MAX_INVENTORY
            data = self._read_response(response, limit, deadline)
            if self.clock() >= deadline or not data or len(data) > limit:
                raise PublicPairUnavailable("Public pair artifact response is unavailable")
            return data if archive else json.loads(data)
        except PublicPairUnavailable:
            raise
        except Exception:
            raise PublicPairUnavailable("Public pair artifact transport is unavailable") from None

    def publish(self, phase, value, deadline):
        name = artifact_name(self.context, self.role, phase)
        validate_upload(self.context, self.role, phase, value)
        if self.token is None or phase in self._published:
            raise ValueError("Public pair setup artifact was already published or transport closed")
        if type(deadline) not in {int, float} or deadline - self.clock() <= 0:
            raise PublicPairUnavailable("Public pair setup deadline expired")
        with tempfile.TemporaryDirectory(prefix="public-pair-upload-", dir=self.directory) as temporary:
            bundle = Path(temporary) / "bundle.json"
            bundle.write_bytes(canonical(value))
            if bundle.stat().st_size > MAX_BLOB:
                raise ValueError("Public pair upload exceeds its budget")
            remaining = deadline - self.clock()
            if remaining <= 0:
                raise PublicPairUnavailable("Public pair setup deadline expired")
            try:
                process = subprocess.run([self.node, str(UPLOAD), name, str(bundle)],
                                         capture_output=True, text=True, timeout=min(60, remaining))
            except Exception:
                raise PublicPairUnavailable("Public pair setup upload is unavailable") from None
            if self.clock() >= deadline:
                raise PublicPairUnavailable("Public pair setup deadline expired")
            if process.returncode:
                raise PublicPairUnavailable("Public pair setup upload failed")
            try:
                response = json.loads(process.stdout.splitlines()[-1])
            except (ValueError, IndexError):
                raise PublicPairUnavailable("Public pair upload returned no identity") from None
            if (type(response) is not dict or response.get("passed") is not True
                    or type(response.get("id")) is not int or response["id"] <= 0
                    or type(response.get("size")) is not int or not 0 < response["size"] <= MAX_ARCHIVE):
                raise PublicPairUnavailable("Public pair upload identity is invalid")
        self._published.add(phase)
        return {"id": response["id"], "size": response["size"], "name": name}

    def wait(self, role, phase, deadline):
        name = artifact_name(self.context, role, phase)
        if role != partner(self.role) or type(deadline) not in {int, float} or not self.clock() < deadline <= self.clock() + 900:
            raise ValueError("Public pair partner or deadline is invalid")
        endpoint = f"/repos/{self.context['repository']}/actions/runs/{self.context['run_id']}"
        transient_reads = 0
        pinned_identity = None
        while self.clock() < deadline:
            try:
                inventory = self._request(endpoint + "/artifacts?per_page=100", deadline=deadline)
            except PublicPairUnavailable as error:
                if error.status != 503 or transient_reads >= 2 or deadline - self.clock() <= 3:
                    raise
                transient_reads += 1
                self.sleep(3)
                continue
            entries = inventory.get("artifacts") if type(inventory) is dict else None
            if (type(entries) is not list or len(entries) > MAX_ARTIFACTS
                    or any(type(item) is not dict for item in entries)
                    or type(inventory.get("total_count")) is not int
                    or inventory["total_count"] > MAX_ARTIFACTS):
                raise PublicPairUnavailable("Public pair artifact inventory is invalid")
            matches = [item for item in entries if item.get("name") == name]
            if len(matches) > 1:
                raise PublicPairUnavailable("Duplicate public pair artifact identity")
            if pinned_identity is not None and not matches:
                raise ValueError("Public pair artifact disappeared during retry")
            if matches:
                metadata = matches[0]
                identity = validated_artifact_metadata(metadata, self.context, role, phase)
                if pinned_identity is not None and identity != pinned_identity:
                    raise ValueError("Public pair artifact changed during retry")
                try:
                    archive = self._request(
                        f"/repos/{self.context['repository']}/actions/artifacts/{identity[0]}/zip",
                        archive=True, deadline=deadline)
                except PublicPairUnavailable as error:
                    if (error.status not in {404, 503} or transient_reads >= 2
                            or deadline - self.clock() <= 3):
                        raise
                    pinned_identity = identity
                    transient_reads += 1
                    self.sleep(3)
                    continue
                if self.clock() >= deadline:
                    raise PublicPairUnavailable("Public pair partner wait expired")
                return verify_artifact(metadata, archive, self.context, role, phase)
            self.sleep(min(3, max(0, deadline - self.clock())))
        raise PublicPairUnavailable("Public pair partner wait expired")

    def close(self):
        self.token = None


class PublicPairExchange:
    """Flow-facing interface: connect, publish, receive, close."""

    def __init__(self, context, role, directory, *, transport=None, rendezvous=None):
        self.rendezvous = rendezvous or Rendezvous(context, role)
        self.transport = transport or GithubArtifacts(context, role, directory)
        self.connected = False

    def connect(self, deadline):
        if self.connected:
            raise ValueError("Public pair exchange is already connected")
        if time.monotonic() >= deadline:
            raise PublicPairUnavailable("Public pair setup deadline expired")
        self.transport.publish("key", self.rendezvous.public_manifest(), deadline)
        if time.monotonic() >= deadline:
            raise PublicPairUnavailable("Public pair setup deadline expired")
        peer = self.transport.wait(self.rendezvous.partner_role, "key", deadline)
        if time.monotonic() >= deadline:
            raise PublicPairUnavailable("Public pair setup deadline expired")
        self.rendezvous.bind_partner(peer)
        self.connected = True

    def publish(self, phase, payload, deadline):
        if not self.connected or time.monotonic() >= deadline:
            raise PublicPairUnavailable("Public pair setup deadline expired")
        bundle = self.rendezvous.seal(phase, payload)
        result = self.transport.publish(phase, bundle, deadline)
        if time.monotonic() >= deadline:
            raise PublicPairUnavailable("Public pair setup deadline expired")
        return result

    def receive(self, phase, deadline):
        if not self.connected or time.monotonic() >= deadline:
            raise PublicPairUnavailable("Public pair setup deadline expired")
        bundle = self.transport.wait(self.rendezvous.partner_role, phase, deadline)
        if time.monotonic() >= deadline:
            raise PublicPairUnavailable("Public pair setup deadline expired")
        return self.rendezvous.open(phase, bundle)

    def close(self):
        self.rendezvous.close()
        self.transport.close()
        self.connected = False

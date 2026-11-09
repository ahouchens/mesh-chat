"""Outside-checkout application staging is component evidence, not SC21 traffic."""

import json
import io
import copy
import os
from pathlib import Path
import sys
import tempfile
import subprocess
import tarfile
import zipfile
from threading import Event, RLock
from types import SimpleNamespace

import pytest

from mesh_chat.core_api.composition import bind_service_stream
from mesh_chat.core_api.session import Grant
from mesh_chat.core_api.wire_codec import decode_frame, encode_frame
from test_core_messages import host

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import stage_independent_core_consumers as staging
import check_independent_core_consumers as bootstrap
import check_independent_core_pairing as pairing
import verify_android_independent_consumer as android_distribution
import stage_android_independent_consumer as android_staging


def test_installed_node_sdk_readiness_reaches_actual_framed_connection_projection(tmp_path):
    from mesh_chat.connection.projection import snapshot
    from tools.connection_harness.simulation import Simulation
    simulation = Simulation()
    simulation.recover()
    service = SimpleNamespace(_shutdown=Event(), _dispatch_lock=RLock(), _identity=object(),
        store=SimpleNamespace(opaque_id=lambda *_: "ab" * 32, items=lambda *_, **__: [],
            get=lambda *_: {"display_name": "Alex", "destination_hash": "cd" * 16}),
        _require_profile=lambda: {"display_name": "Alex", "destination_hash": "cd" * 16},
        _connection_runtime=SimpleNamespace(snapshots=lambda: {
            simulation.key.profile_id: snapshot(simulation.owner.snapshot(simulation.key), simulation.now)}))
    stream = bind_service_stream(service, lambda: Grant("readiness-consumer", frozenset({"observe"}), ("local",)))
    # Install the actual public package bytes, not a fake connectionSnapshot method.
    artifact = Path(os.environ.get("MESH_CORE_SDK_ARTIFACTS", staging.ROOT / "dist/sdk")) / "typescript" / staging.ARTIFACTS["typescript"]
    assert artifact.is_file(), "Stage the real public TypeScript SDK first"
    with tarfile.open(artifact) as archive: archive.extractall(tmp_path / "installed", filter="data")
    sdk = tmp_path / "installed/package/dist/index.js"
    helper = staging.APPLICATION / "connection-readiness.mjs"
    script = f"import {{CoreClient}} from {json.dumps(sdk.as_uri())};\n" + \
             f"import {{connectionMessagingReady}} from {json.dumps(helper.as_uri())};\n" + """
import {createInterface} from 'node:readline';
const input = createInterface({input:process.stdin});
const lines = input[Symbol.asyncIterator]();
const client = await CoreClient.open({
  async writeLine(line) { process.stdout.write(line); },
  async readLine() { const value = await lines.next(); return value.done ? null : value.value + '\\n'; },
  close() { input.close(); },
}, {requestTimeoutMs:3000});
const profile = client.capabilities.profiles[0];
const connection = (await client.request('profile.query', {profile})).connections[0];
const before = await connectionMessagingReady(client, profile, connection);
const after = await connectionMessagingReady(client, profile, connection);
let obsolete;
try { await client.request('connection.query', {profile,connection}); } catch (error) { obsolete = error.code; }
client.close();
console.log(JSON.stringify({before,after,obsolete}));
"""
    node, _ = staging.tools()
    process = subprocess.Popen([node, "--input-type=module", "-e", script], cwd=tmp_path,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        for index, expected in enumerate(("runtime.capabilities", "profile.query", "connection.snapshot", "connection.snapshot", "connection.query")):
            line = process.stdout.readline()
            assert line, process.stderr.read()
            assert json.loads(line)["operation"] == expected
            response = stream.exchange(line.encode())
            decoded = json.loads(response)
            if expected == "connection.snapshot":
                assert decoded["ok"], decoded
                assert decoded["result"]["observation"]["messaging_ready"] is (index == 2)
            elif expected == "connection.query":
                assert decoded["error"]["code"] == "unsupported_operation"
            process.stdin.write(response.decode())
            process.stdin.flush()
            if index == 2: simulation.close()
        assert json.loads(process.stdout.readline()) == {"before": True, "after": False, "obsolete": "unsupported_operation"}
        assert process.wait(timeout=5) == 0, process.stderr.read()
    finally:
        if process.poll() is None: process.kill()
        process.wait(timeout=5)
        stream.close()


@pytest.mark.parametrize("fault", ["invitation_wait", "invitation_accept", "pending_request_wait",
    "offerer_relationship_wait", "offerer_ready_wait", "answerer_ready_wait", "unsafe_error"])
def test_actual_node_pairing_producer_reports_safe_specific_failure_observations(fault):
    # Actual producer control flow; synthetic SDK/host boundary, no native claim.
    node, _ = staging.tools()
    completed = subprocess.run([node, "--import", (staging.ROOT /
        "tests/core-ui-boundary/pairing_diagnostic_fixture.mjs").as_uri(),
        str(staging.APPLICATION / "pairing-check.mjs"), "--runtime", "unused", "--data-directory", "unused"],
        cwd=staging.ROOT, env={**os.environ, "PAIRING_DIAGNOSTIC_FAULT": fault},
        capture_output=True, text=True, timeout=15)
    assert completed.returncode == 1, completed.stdout + completed.stderr
    assert len(completed.stdout.encode()) <= 4096
    observed = json.loads(completed.stdout)
    details = pairing.failure_details(observed)
    expected = "invitation_accept" if fault == "unsafe_error" else fault
    assert details["application_phase"] == "explicit_approval"
    assert details["diagnostics"]["subphase"] == expected
    assert details["diagnostics"]["deadline_exhausted"] is (fault not in {"invitation_accept", "unsafe_error"})
    assert details["error_code"] == ("forbidden" if fault == "invitation_accept" else "unavailable")
    assert "private" not in (completed.stdout + completed.stderr).lower()
    peers = details["diagnostics"]["peers"]
    assert peers["answerer"]["last_pairing"] == {"state": "awaiting_approval", "code_present": False}
    if fault == "invitation_wait":
        assert peers["answerer"]["last_snapshot"]["pending_invitations"] == 0
    elif fault == "pending_request_wait":
        assert peers["offerer"]["last_snapshot"]["pending_requests"] == 1
        assert peers["offerer"]["last_snapshot"]["matching_pending_request"] is False
    elif fault == "offerer_relationship_wait":
        assert peers["offerer"]["last_snapshot"]["approved_contacts"] == 1
        assert peers["offerer"]["last_snapshot"]["matching_approved_contact"] is False
    elif fault.endswith("ready_wait"):
        role = fault.removesuffix("_ready_wait")
        assert peers[role]["last_connections"] == {"total": 1, "checked": 1, "ready": 0, "counts_capped": False}


def test_node_diagnostic_projection_caps_counts_and_selects_no_private_payloads():
    node, _ = staging.tools()
    script = """
import {pairingDiagnostics, SUBPHASES, ERROR_CODES} from './examples/typescript-independent-consumer/pairing-diagnostics.mjs';
const diagnostics = pairingDiagnostics();
diagnostics.enter('invitation_wait');
diagnostics.snapshot('answerer', {contacts: Array(300).fill({trust:'pending_request',destination_hash:'PRIVATE_DESTINATION'}),
  contact_invitations: Array(300).fill({state:'pending',sdp:'PRIVATE_SDP'})}, 'PRIVATE_DESTINATION');
diagnostics.pairing('answerer', {state:'PRIVATE_STATE',pairing_code:'PRIVATE_PAIRING_CODE',token:'PRIVATE_TOKEN'});
diagnostics.connections('answerer',300,299,298);
console.log(JSON.stringify({diagnostics:diagnostics.failure(),subphases:[...SUBPHASES],errors:[...ERROR_CODES]}));
"""
    completed = subprocess.run([node, "--input-type=module", "-e", script], cwd=staging.ROOT,
        capture_output=True, text=True, check=True, timeout=15)
    assert "PRIVATE" not in completed.stdout
    value = json.loads(completed.stdout)
    assert set(value["subphases"]) == set().union(*pairing.SUBPHASES.values())
    contract = json.loads((staging.ROOT / "contracts/core-api/error-v1.schema.json").read_text())
    assert set(value["errors"]) == pairing.ERROR_CODES == set(contract["properties"]["error"]["properties"]["code"]["enum"])
    observed = {"passed": False, "phase": "explicit_approval", "error_code": "unavailable", "diagnostics": value["diagnostics"]}
    pairing.failure_details(observed)
    peer = observed["diagnostics"]["peers"]["answerer"]
    assert peer["last_snapshot"]["contacts"] == peer["last_snapshot"]["pending_invitations"] == 256
    assert peer["last_snapshot"]["counts_capped"] is True
    assert peer["last_pairing"] == {"state": "unknown", "code_present": True}
    assert peer["last_connections"] == {"total": 256, "checked": 256, "ready": 256, "counts_capped": True}


@pytest.mark.parametrize("fault", ["subphase", "phase_mismatch", "role", "state", "pairing_code", "private_field",
    "envelope_field", "error_code", "negative", "oversized", "boolean_count", "string_flag", "inconsistent"])
def test_pairing_failure_report_rejects_unselected_private_or_unbounded_fields(fault):
    observed = {"passed": False, "phase": "explicit_approval", "error_code": "unavailable",
        "diagnostics": {"subphase": "offerer_ready_wait", "deadline_exhausted": True, "peers": {"offerer": {
            "last_pairing": {"state": "awaiting_approval", "code_present": False},
            "last_connections": {"total": 1, "checked": 1, "ready": 0, "counts_capped": False}}}}}
    pairing.failure_details(copy.deepcopy(observed))
    diagnostics = observed["diagnostics"]
    peer = diagnostics["peers"]["offerer"]
    if fault == "subphase": diagnostics["subphase"] = "PRIVATE_TOKEN"
    elif fault == "phase_mismatch": diagnostics["subphase"] = "offer_begin"
    elif fault == "role": diagnostics["peers"]["PRIVATE_IDENTITY"] = diagnostics["peers"].pop("offerer")
    elif fault == "state": peer["last_pairing"]["state"] = "PRIVATE_SDP"
    elif fault == "pairing_code": peer["last_pairing"]["pairing_code"] = "PRIVATE_PAIRING_CODE"
    elif fault == "private_field": peer["sdp"] = "PRIVATE_SDP"
    elif fault == "envelope_field": observed["token"] = "PRIVATE_TOKEN"
    elif fault == "error_code": observed["error_code"] = "private_token"
    elif fault == "negative": peer["last_connections"]["total"] = -1
    elif fault == "oversized": peer["last_connections"]["total"] = 257
    elif fault == "boolean_count": peer["last_connections"]["total"] = True
    elif fault == "string_flag": peer["last_connections"]["counts_capped"] = "PRIVATE_TOKEN"
    else: peer["last_connections"]["ready"] = 2
    with pytest.raises(ValueError): pairing.failure_details(observed)


def test_pairing_relay_settings_serialize_real_public_query_into_accepted_core_update(host):
    service = host()
    stream = bind_service_stream(service, lambda: Grant(
        "independent-settings", frozenset({"observe", "read", "send"}), ("local",)))

    def invoke(operation, **params):
        return decode_frame(stream.exchange(encode_frame({"api_version": 1,
            "request_id": "independent:relay-settings", "operation": operation, "params": params})))

    try:
        capabilities = invoke("runtime.capabilities")
        assert capabilities["ok"], capabilities
        profile = capabilities["result"]["profiles"][0]
        queried = invoke("call.settings_query", profile=profile)
        assert queried["ok"], queried
        settings = queried["result"]["settings"]
        assert settings["turn_configured"] is False
        # Replaying a public query as an update was the actual producer defect.
        rejected = invoke("call.settings_update", profile=profile,
                          settings={**settings, "turn_broker_consent": True, "relay_only": True})
        assert not rejected["ok"] and rejected["error"]["code"] == "invalid_request"
        node, _ = staging.tools()
        script = """
import { freshRelaySettings } from './examples/typescript-independent-consumer/relay-settings.mjs';
let input = '';
for await (const chunk of process.stdin) input += chunk;
process.stdout.write(JSON.stringify(freshRelaySettings(JSON.parse(input))));
"""
        completed = subprocess.run([node, "--input-type=module", "-e", script], cwd=staging.ROOT,
            input=json.dumps(settings), capture_output=True, text=True, check=True, timeout=15)
        update = json.loads(completed.stdout)
        assert set(update) == {"stun_urls", "turn_url", "turn_username", "turn_broker_url",
            "signal_mailbox_url", "store_call_signaling", "turn_broker_consent", "relay_only"}
        accepted = invoke("call.settings_update", profile=profile, settings=update)
        assert accepted["ok"], accepted
        applied = invoke("call.settings_query", profile=profile)
        assert applied["ok"], applied
        assert applied["result"]["settings"]["turn_broker_consent"] is True
        assert applied["result"]["settings"]["relay_only"] is True
    finally:
        stream.close()


def test_application_owned_runtime_framing_and_retirement_use_real_subprocesses():
    node, _ = staging.tools()
    result = subprocess.run([node, "--test", "--test-reporter=tap",
                             str(staging.ROOT / "tests/core-ui-boundary/app_owned_runtime.test.mjs")],
                            cwd=staging.ROOT, capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-1000:]
    assert "# tests 11" in result.stdout
    assert "# pass 11" in result.stdout and "# fail 0" in result.stdout and "# skipped 0" in result.stdout


@pytest.mark.parametrize("fault", ["source", "tree", "failed", "scope", "inside_checkout", "integer_check",
    "application_missing", "application_hash", "host_pom_missing", "host_aar_changed", "sdk_module_missing", "apk_missing"])
def test_android_distribution_requires_both_publications_apks_and_exact_scope(fault):
    identity = {"source_commit": "a" * 40, "source_tree": "b" * 40}
    artifacts = {path.relative_to(staging.ROOT).as_posix(): "c" * 64 for path in android_distribution.ARTIFACTS}
    record = {"v": 1, "passed": True, **identity, "checks": dict(android_distribution.CHECKS),
        "scope": android_distribution.SCOPE, "artifacts": dict(artifacts),
        "application_files": {name: "d" * 64 for name in android_distribution.APPLICATION_FILES}}
    android_distribution.verify_record(record, identity, artifacts)
    if fault == "source": record["source_commit"] = "e" * 40
    elif fault == "tree": record["source_tree"] = "e" * 40
    elif fault == "failed": record["passed"] = False
    elif fault == "scope": record["scope"] = "Successful OS confirmation and peer receipts"
    elif fault == "inside_checkout": record["checks"]["outside_checkout"] = False
    elif fault == "integer_check": record["checks"]["outside_checkout"] = 1
    elif fault == "application_missing": record["application_files"].pop("app/build.gradle.kts")
    elif fault == "application_hash": record["application_files"]["app/build.gradle.kts"] = "missing"
    else:
        name = next(name for name in artifacts if
            (fault == "host_pom_missing" and "core-runtime-host" in name and name.endswith(".pom")) or
            (fault == "host_aar_changed" and "core-runtime-host" in name and name.endswith(".aar")) or
            (fault == "sdk_module_missing" and "core-client" in name and name.endswith(".module")) or
            (fault == "apk_missing" and name.endswith("consumer.apk")))
        if fault == "host_aar_changed": record["artifacts"][name] = "e" * 64
        else: record["artifacts"].pop(name)
    with pytest.raises(ValueError): android_distribution.verify_record(record, identity, artifacts)


def test_android_staging_cannot_resolve_producer_checkout_as_application():
    with pytest.raises(ValueError, match="outside checkout"):
        android_staging.stage(staging.ROOT)


def android_publication_fixture(directory):
    """Synthetic archives test packaging admission only, never Android execution."""
    for artifact in ("core-client", "core-runtime-host"):
        aar = android_distribution.publication_path(directory, artifact, "aar")
        aar.parent.mkdir(parents=True)
        classes = io.BytesIO()
        with zipfile.ZipFile(classes, "w") as jar:
            jar.writestr("META-INF/LICENSE", (staging.ROOT / "LICENSE").read_bytes())
            names = ("core/CoreClient", "IMeshCoreApi") if artifact == "core-client" else (
                "MeshCoreRuntime", "MeshCoreApiService", "BootstrapService", "NativeWebRtcBridge")
            for name in names: jar.writestr("com/meshchat/runtime/" + name + ".class", b"fixture class name only")
        python = io.BytesIO()
        with zipfile.ZipFile(python, "w") as package:
            package.writestr("mesh_chat/mobile_bridge.pyc", b"fixture source name only")
        with zipfile.ZipFile(aar, "w") as archive:
            archive.writestr("AndroidManifest.xml", b"fixture manifest")
            archive.writestr("classes.jar", classes.getvalue())
            if artifact == "core-runtime-host": archive.writestr("assets/chaquopy/app.imy", python.getvalue())
        dependencies = [] if artifact == "core-client" else [
            ("com.meshchat", "core-client", android_distribution.VERSION, "compile"),
            ("androidx.activity", "activity-ktx", "1.10.1", "compile"),
            ("io.github.webrtc-sdk", "android", "150.7871.01", "runtime")]
        pom = '<project xmlns="http://maven.apache.org/POM/4.0.0"><groupId>com.meshchat</groupId>' + \
            f'<artifactId>{artifact}</artifactId><version>{android_distribution.VERSION}</version><dependencies>'
        pom += "".join("<dependency>" + "".join(f"<{key}>{value}</{key}>" for key, value in
            zip(("groupId", "artifactId", "version", "scope"), dependency)) + "</dependency>" for dependency in dependencies)
        android_distribution.publication_path(directory, artifact, "pom").write_text(pom + "</dependencies></project>")
        sources = aar.with_name(f"{artifact}-{android_distribution.VERSION}-sources.jar")
        with zipfile.ZipFile(sources, "w") as archive:
            archive.writestr("CoreClient.kt" if artifact == "core-client" else "MeshCoreRuntime.kt", b"fixture source only")
        android_distribution.publication_path(directory, artifact, "module").write_text(json.dumps({
            "component": {"group": "com.meshchat", "module": artifact, "version": android_distribution.VERSION},
            "variants": [{"attributes": {"org.gradle.usage": usage, "org.gradle.category": "library",
                                        "org.gradle.libraryelements": "aar"},
                "dependencies": [{"group": group, "module": name, "version": {"requires": version}}
                    for group, name, version, scope in dependencies if usage == "java-runtime" or scope == "compile"],
                "files": [{"name": aar.name, "url": aar.name, "sha256": staging.digest(aar),
                           "size": aar.stat().st_size}]} for usage in ("java-api", "java-runtime")] +
                [{"attributes": {"org.gradle.usage": "java-runtime", "org.gradle.category": "documentation",
                                  "org.gradle.docstype": "sources"},
                  "files": [{"name": sources.name, "url": sources.name, "sha256": staging.digest(sources),
                              "size": sources.stat().st_size}]}]}))


@pytest.mark.parametrize("fault", ["none", "old_version", "activity_not_exported", "sdk_not_exported",
    "module_aar_hash", "module_aar_size", "module_absolute_url", "runtime_missing",
    "variant_sdk_missing", "variant_runtime_missing", "variant_redirect", "sources_changed", "sources_missing"])
def test_android_maven_metadata_binds_exact_runtime_and_public_api(tmp_path, fault):
    android_publication_fixture(tmp_path)
    android_distribution.verify_publications(tmp_path)
    pom = android_distribution.publication_path(tmp_path, "core-runtime-host", "pom")
    module = android_distribution.publication_path(tmp_path, "core-runtime-host", "module")
    if fault == "old_version": pom.write_text(pom.read_text().replace(android_distribution.VERSION, "0.2.0"))
    elif fault in {"activity_not_exported", "sdk_not_exported"}:
        needle = "activity-ktx" if fault == "activity_not_exported" else "core-client"
        pom.write_text(pom.read_text().replace(f"<artifactId>{needle}</artifactId><version>" +
            ("1.10.1" if fault == "activity_not_exported" else android_distribution.VERSION) +
            "</version><scope>compile</scope>", f"<artifactId>{needle}</artifactId><version>0.0.0</version><scope>runtime</scope>"))
    elif fault.startswith("module_"):
        value = json.loads(module.read_text())
        item = value["variants"][0]["files"][0]
        item[{"module_aar_hash": "sha256", "module_aar_size": "size", "module_absolute_url": "url"}[fault]] = {
            "module_aar_hash": "e" * 64, "module_aar_size": 1, "module_absolute_url": "https://unqualified.invalid/runtime.aar"}[fault]
        module.write_text(json.dumps(value))
    elif fault == "runtime_missing":
        pom.write_text(pom.read_text().replace("150.7871.01", "0.0.0"))
    elif fault.startswith("variant_"):
        value = json.loads(module.read_text())
        if fault == "variant_redirect": value["variants"][0]["available-at"] = {"url": "other.module"}
        else:
            variant = value["variants"][1 if fault == "variant_runtime_missing" else 0]
            missing = "android" if fault == "variant_runtime_missing" else "core-client"
            variant["dependencies"] = [item for item in variant["dependencies"] if item["module"] != missing]
        module.write_text(json.dumps(value))
    elif fault.startswith("sources_"):
        sources = android_distribution.publication_path(tmp_path, "core-runtime-host", "aar").with_name(
            f"core-runtime-host-{android_distribution.VERSION}-sources.jar")
        if fault == "sources_missing": sources.unlink()
        else: sources.write_bytes(sources.read_bytes() + b"changed")
    if fault != "none":
        with pytest.raises((ValueError, FileNotFoundError)): android_distribution.verify_publications(tmp_path)


def staged_input(tmp_path):
    directory = tmp_path / "sdk"
    (directory / "typescript").mkdir(parents=True)
    artifact = directory / "typescript" / staging.ARTIFACTS["typescript"]
    artifact.write_bytes(b"component fixture bytes; not a real SDK archive")
    value = {"v": 1, "passed": True, "evidence_level": "public_sdk_archive_and_isolated_import_staging",
             "source_commit": "a" * 40, "source_tree": "b" * 40,
             "artifacts": {"typescript": {"artifact": "typescript/" + artifact.name,
                "sha256": staging.digest(artifact), "size_bytes": artifact.stat().st_size}}}
    report = tmp_path / "sdk-staging.json"
    report.write_text(json.dumps(value))
    return directory, artifact, report, value


def bootstrap_record(source="a" * 40, tree="b" * 40):
    """Synthetic complete declaration for rejection checks; never execution proof."""
    return {"v": 1, "passed": True, "source_commit": source, "source_tree": tree,
            "evidence_level": bootstrap.LEVEL, "scope": bootstrap.SCOPE,
            "checks": dict(bootstrap.CHECKS), "run_id": "6" * 32, "duration_seconds": 1,
            "sidecar_sha256": "d" * 64, "build_input_sha256": "e" * 64, "build_manifest_sha256": "f" * 64,
            "sdk_sha256": "a" * 64, "runtime_installed_outside_checkout": True, "cleanup": "passed",
            "sdk_artifact": bootstrap.SDK_ARTIFACT,
            "application": {"installed_outside_checkout": True, "imports_public_package": True,
                "application_files": {name: "c" * 64 for name in staging.FILES}}}


def pairing_record(source="a" * 40, tree="b" * 40):
    return {**bootstrap_record(source, tree), "evidence_level": pairing.LEVEL, "scope": pairing.SCOPE,
            "checks": dict(pairing.CHECKS), "run_id": "7" * 32, "bootstrap_report_sha256": "b" * 64}


@pytest.mark.parametrize("fault", ["bootstrap_scope", "SC21_scope", "implicit_approval", "missing_receipt",
    "duplicate_records", "missing_transfer", "missing_cancel", "unready", "efs", "receipt_boolean", "cleanup", "missing_bootstrap_binding",
    "direct_disclosure", "relay_not_requested", "broker_consent"])
def test_public_pairing_report_requires_exact_receipts_consent_and_normal_host_provenance(fault):
    record = pairing_record()
    pairing.verify_report(record, "a" * 40, "b" * 40)
    if fault == "bootstrap_scope": record["evidence_level"] = bootstrap.LEVEL
    elif fault == "SC21_scope": record["scope"] = "Windows-Android SC21 qualification"
    elif fault == "implicit_approval": record["checks"]["explicit_contact_decisions"] = 0
    elif fault == "missing_receipt": record["checks"]["authenticated_receipts"] = 1
    elif fault == "duplicate_records": record["checks"]["single_inbound_and_outbound_records"] = False
    elif fault == "missing_transfer": record["checks"]["supervisor_transfers"] = 1
    elif fault == "missing_cancel": record["checks"]["transferred_cancel_preserves_delivery"] = False
    elif fault == "unready": record["checks"]["public_messaging_ready"] = 0
    elif fault == "efs": record["checks"]["efs_vault_files"] = 0
    elif fault == "receipt_boolean": record["checks"]["original_message_key_replay"] = 1
    elif fault == "cleanup": record["cleanup"] = "pending"
    elif fault == "direct_disclosure": record["checks"]["direct_disclosure_consented"] = True
    elif fault == "relay_not_requested": record["checks"]["relay_only_requested"] = False
    elif fault == "broker_consent": record["checks"]["broker_consent"] = False
    else: record.pop("bootstrap_report_sha256")
    with pytest.raises(ValueError): pairing.verify_report(record, "a" * 40, "b" * 40)


@pytest.mark.parametrize("fault", ["source", "tree", "scope", "component_scope", "failed", "efs",
    "efs_integer", "sdk_hash", "runtime_hash", "inside_checkout", "runtime_inside", "file_missing",
    "file_hash", "cleanup", "single_exit", "run", "duration"])
def test_normal_bootstrap_evidence_cannot_substitute_components_or_unprotected_storage(fault):
    record = bootstrap_record()
    bootstrap.verify_report(record, "a" * 40, "b" * 40)
    if fault == "source": record["source_commit"] = "c" * 40
    elif fault == "tree": record["source_tree"] = "c" * 40
    elif fault == "scope": record["scope"] = "SC21 public peer receipt qualification"
    elif fault == "component_scope": record["evidence_level"] = "windows_named_pipe_and_inprocess_domain"
    elif fault == "failed": record["passed"] = False
    elif fault == "efs": record["checks"]["efs_vault_file"] = False
    elif fault == "efs_integer": record["checks"]["efs_profile_directory"] = 1
    elif fault == "sdk_hash": record["sdk_sha256"] = "missing"
    elif fault == "runtime_hash": record.pop("sidecar_sha256")
    elif fault == "inside_checkout": record["application"]["installed_outside_checkout"] = False
    elif fault == "runtime_inside": record["runtime_installed_outside_checkout"] = False
    elif fault == "file_missing": record["application"]["application_files"].pop("bootstrap-check.mjs")
    elif fault == "file_hash": record["application"]["application_files"]["runtime.mjs"] = "bad"
    elif fault == "cleanup": record["cleanup"] = "pending"
    elif fault == "single_exit": record["checks"]["clean_host_exits"] = 1
    elif fault == "run": record["run_id"] = ""
    else: record["duration_seconds"] = float("nan")
    with pytest.raises(ValueError): bootstrap.verify_report(record, "a" * 40, "b" * 40)


def test_installed_application_does_not_inherit_checkout_import_paths_or_artifact_bearers():
    assert bootstrap.application_environment({"Path": "tools", "SYSTEMROOT": "system",
        "PythonPath": "checkout", "PYTHONHOME": "checkout", "NODE_PATH": "checkout", "NODE_OPTIONS": "checkout-preload",
        "mesh_private_key": "secret", "GITHUB_TOKEN": "secret", "Actions_Runtime_Token": "secret",
        "INPUT_ROLE": "secret"}) == {"Path": "tools", "SYSTEMROOT": "system"}


def test_normal_profile_protection_requires_an_existing_protected_profile_and_vault(tmp_path):
    directory = tmp_path / "mesh-core-runtime/profile-v1"
    directory.mkdir(parents=True)
    # The parent may itself be encrypted on a developer machine; missing Vault
    # storage must fail in either case, without asserting local EFS support.
    with pytest.raises((ValueError, FileNotFoundError)):
        bootstrap.protected_profile(tmp_path)


@pytest.mark.parametrize("fault", ["source", "tree", "bytes", "size", "path", "failed", "component_scope"])
def test_independent_stage_refuses_sdk_source_hash_and_scope_substitution(tmp_path, fault):
    directory, artifact, report, value = staged_input(tmp_path)
    assert staging.sdk_input(directory, report, "a" * 40, "b" * 40) == artifact
    if fault == "source": value["source_commit"] = "c" * 40
    elif fault == "tree": value["source_tree"] = "c" * 40
    elif fault == "bytes": artifact.write_bytes(artifact.read_bytes() + b"changed")
    elif fault == "size": value["artifacts"]["typescript"]["size_bytes"] += 1
    elif fault == "path": value["artifacts"]["typescript"]["artifact"] = "../different.tgz"
    elif fault == "failed": value["passed"] = False
    else: value["evidence_level"] = "simulated_and_in_process"
    report.write_text(json.dumps(value))
    with pytest.raises(ValueError): staging.sdk_input(directory, report, "a" * 40, "b" * 40)


def test_independent_install_cannot_use_checkout_or_delete_unowned_directory(tmp_path):
    with pytest.raises(ValueError, match="outside the checkout"):
        staging.outside_directory(staging.ROOT)
    with pytest.raises(ValueError, match="checkout dependencies"):
        staging.install_typescript(staging.ROOT, Path("missing-sdk"), "missing-node", "missing-npm")
    with pytest.raises(ValueError, match="ownership changed"):
        staging.cleanup(tmp_path, tmp_path.parent)
    assert tmp_path.is_dir()


def test_actual_independent_app_installs_from_sdk_archive_outside_checkout(record_property):
    # Actual SDK bytes are a mandatory staging prerequisite. This exercises
    # installation/import only, with no substitute host or fabricated receipt.
    artifact = Path(os.environ.get("MESH_CORE_SDK_ARTIFACTS", staging.ROOT / "dist/sdk")) / "typescript" / staging.ARTIFACTS["typescript"]
    assert artifact.is_file(), "Stage the actual public TypeScript SDK first"
    node, npm = staging.tools()
    parent = Path(os.environ.get("MESH_CORE_CONSUMER_TMP") or tempfile.gettempdir())
    directory = staging.outside_directory(parent)
    try:
        report = staging.install_typescript(directory, artifact, node, npm)
        record_property("sdk_sha256", staging.digest(artifact))
        assert report["imports_public_package"] and report["installed_outside_checkout"]
        assert report["installed_sdk_entry"].startswith("node_modules/@mesh-chat/core-client/")
        assert set(report["application_files"]) == set(staging.FILES)
        rejected = subprocess.run([node, "bootstrap-check.mjs"], cwd=directory,
                                  capture_output=True, text=True, timeout=15)
        assert rejected.returncode == 1
        assert json.loads(rejected.stdout) == {"passed": False, "phase": "arguments", "error_code": "unavailable"}
        rejected = subprocess.run([node, "pairing-check.mjs"], cwd=directory,
                                  capture_output=True, text=True, timeout=15)
        assert rejected.returncode == 1
        assert json.loads(rejected.stdout) == {"passed": False, "phase": "arguments", "error_code": "unavailable",
            "diagnostics": {"subphase": "arguments", "deadline_exhausted": False, "peers": {}}}
        assert pairing.failure_details(json.loads(rejected.stdout))["application_phase"] == "arguments"
    finally:
        staging.cleanup(directory, parent)
    assert not directory.exists()

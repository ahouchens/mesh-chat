"""Conservative CI selection and an always-running gate for required workflows."""

import argparse
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess


SUITES = ("policy", "verification", "android", "direct", "layout")

# Component evidence each required suite must contribute to the uniform manifest.
COMPONENTS = {
    "policy": {"policy"},
    "verification": {"windows_transport", "windows_packaged_lifecycle",
                     "windows_packaged_transport", "windows_packaged_pairing",
                     "core_ui_boundary_python", "core_ui_boundary_rendered", "core_windows_boundary",
                     "windows_native_control", "windows_native_lifecycle"},
    "android": {"android_webrtc", "android_signaling", "android_core_api", "android_core_consumer"},
    "direct": {"direct_Linux_recovery", "direct_Linux_setup", "direct_Linux_fabric",
               "direct_Windows_recovery", "direct_Windows_setup", "direct_Windows_fabric"},
    "layout": set(),
}
PROTECTED_DOCS = {"AGENTS.md", "SKILL.md", "Mesh_Chat_Connection_Runtime_Spec.md"}
CONNECTION_TESTS = "service/tests/connection/"
UI_CORE_BOUNDARY_TESTS = "tests/core-ui-boundary/"
TYPESCRIPT_SDK = "sdk/typescript/"
PIPE_PRODUCTION = frozenset({
    "service/src/mesh_chat/core_api/pipe_endpoint.py",
    "service/src/mesh_chat/core_api/pipe_policy.py",
    "service/src/mesh_chat/core_api/pipe_client.py",
})
NATIVE_WINDOWS_PRODUCTION = frozenset({
    "service/src/mesh_chat/native_windows_webrtc.py",
    "service/src/mesh_chat/desktop_transport_host.py",
})
CLI_PRODUCTION = frozenset({
    "service/src/mesh_chat/core_api/cli.py",
})
KOTLIN_CLIENT_PRODUCTION = frozenset(
    "plugins/tauri-plugin-mesh-runtime/android/src/main/java/com/meshchat/runtime/core/" + name
    for name in ("CoreClient.kt", "CoreTransport.kt", "CoreExchangeTransport.kt")
)


def documentation(path):
    if not isinstance(path, str) or not path or "\\" in path:
        return False
    value = PurePosixPath(path)
    if value.is_absolute() or ".." in value.parts or value.name in PROTECTED_DOCS:
        return False
    return (path in {"README.md", "CHANGELOG.md", "LICENSE"}
            or (path.startswith("docs/") and value.suffix in {".md", ".png", ".svg"}))


def connection_test(path):
    if not isinstance(path, str) or not path or "\\" in path:
        return False
    value = PurePosixPath(path)
    if value.is_absolute() or ".." in value.parts:
        return False
    return (path.startswith(CONNECTION_TESTS) and value.suffix == ".py"
            and value.name.startswith("test_"))


def typescript_sdk(path):
    if not isinstance(path, str) or not path or "\\" in path:
        return False
    value = PurePosixPath(path)
    if value.is_absolute() or ".." in value.parts:
        return False
    return path.startswith(TYPESCRIPT_SDK)


def ui_core_boundary_test(path):
    if not isinstance(path, str) or not path or "\\" in path:
        return False
    value = PurePosixPath(path)
    if value.is_absolute() or ".." in value.parts:
        return False
    return path.startswith(UI_CORE_BOUNDARY_TESTS) and value.suffix in {".py", ".ts", ".tsx", ".json", ".md"}


def pipe_production(path):
    if not isinstance(path, str) or not path or "\\" in path:
        return False
    value = PurePosixPath(path)
    if value.is_absolute() or ".." in value.parts:
        return False
    return path in PIPE_PRODUCTION


def native_windows_production(path):
    if not isinstance(path, str) or not path or "\\" in path:
        return False
    value = PurePosixPath(path)
    if value.is_absolute() or ".." in value.parts:
        return False
    return path in NATIVE_WINDOWS_PRODUCTION


def cli_production(path):
    if not isinstance(path, str) or not path or "\\" in path:
        return False
    value = PurePosixPath(path)
    if value.is_absolute() or ".." in value.parts:
        return False
    return path in CLI_PRODUCTION


def select(paths, *, event="pull_request"):
    eligible = event in {"pull_request", "push"} and bool(paths)
    documentation_only = eligible and all(documentation(path) for path in paths)
    connection_tests_only = (eligible and not documentation_only
                             and all(connection_test(path) for path in paths))
    sdk_only = (eligible and not documentation_only and not connection_tests_only
                and all(typescript_sdk(path) for path in paths))
    pipe_only = (eligible and not documentation_only and not connection_tests_only
                 and not sdk_only and all(pipe_production(path) for path in paths))
    cli_only = (eligible and not documentation_only and not connection_tests_only
                and not sdk_only and not pipe_only
                and all(cli_production(path) for path in paths))
    native_windows_only = (eligible and not documentation_only
                           and not connection_tests_only and not sdk_only
                           and not pipe_only and not cli_only
                           and all(native_windows_production(path) for path in paths))
    kotlin_only = eligible and all(isinstance(path, str) and path in KOTLIN_CLIENT_PRODUCTION for path in paths)
    ui_boundary_only = (eligible and any(ui_core_boundary_test(path) for path in paths)
                        and all(ui_core_boundary_test(path) or connection_test(path) for path in paths))
    if documentation_only:
        required, reason = ["policy", "verification"], "isolated_documentation"
    elif connection_tests_only:
        required, reason = ["policy", "verification"], "isolated_connection_tests"
    elif ui_boundary_only:
        # The verification workflow executes these rendered UI/Python tests.
        # Neither Android/native production nor packaged consumers import them.
        required, reason = ["policy", "verification"], "isolated_ui_core_boundary_tests"
    elif sdk_only:
        required, reason = ["policy", "verification"], "isolated_typescript_sdk"
    elif pipe_only:
        required, reason = ["policy", "verification"], "isolated_pipe_production"
    elif cli_only:
        required, reason = ["policy", "verification"], "isolated_cli_production"
    elif native_windows_only:
        required, reason = ["policy", "verification"], "isolated_native_windows_production"
    elif kotlin_only:
        # The separate AAR compiles only these public sources. Android executes
        # the client JVM corpus and an independent APK built from that AAR;
        # verification retains public contract and cross-language checks.
        required, reason = ["policy", "verification", "android"], "isolated_kotlin_client"
    else:
        required, reason = list(SUITES), "conservative_full_matrix"
    return {
        "version": 1, "event": event, "paths": paths,
        "required": required, "reason": reason,
    }


def validate(plan, jobs):
    if not isinstance(plan, dict) or type(plan.get("version")) is not int:
        raise ValueError("Required selection manifest is missing")
    expected = select(plan.get("paths"), event=plan.get("event"))
    if any(plan.get(key) != value for key, value in expected.items()):
        raise ValueError("Selection manifest does not match the dependency policy")
    if not isinstance(jobs, dict) or set(jobs) != set(SUITES):
        raise ValueError("Required workflow result inventory is incomplete")
    for suite, job in jobs.items():
        result = job.get("result") if isinstance(job, dict) else None
        allowed = {"success"} if suite in expected["required"] else {"success", "skipped"}
        if result not in allowed:
            raise ValueError(f"Workflow {suite} did not satisfy its selection: {result}")


def git(*arguments):
    return subprocess.check_output(["git", *arguments], stderr=subprocess.DEVNULL)


def changed_paths(event, payload):
    if event == "pull_request":
        base = payload.get("pull_request", {}).get("base", {}).get("sha")
    elif event == "push":
        base = payload.get("before")
    else:
        return None
    if not isinstance(base, str) or not re.fullmatch(r"[a-fA-F0-9]{40}", base) or base == "0" * 40:
        return None
    try:
        # Disabling rename detection includes both deleted and added names, so
        # moving source into docs cannot hide the removed producer/consumer.
        names = git("diff", "--no-renames", "--name-only", "-z", base, "HEAD", "--")
        return sorted(set(name.decode("utf-8") for name in names.split(b"\0") if name))
    except (subprocess.CalledProcessError, UnicodeDecodeError):
        return None


def current_plan():
    event = os.environ.get("GITHUB_EVENT_NAME", "unknown")
    try:
        payload = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
        paths = changed_paths(event, payload)
    except (KeyError, OSError, ValueError, AttributeError):
        paths = None
    source = git("rev-parse", "HEAD").decode().strip()
    if source != os.environ.get("GITHUB_SHA"):
        raise ValueError("Workflow checkout does not match the required source")
    return {**select(paths, event=event), "source_commit": source,
            "source_tree": git("rev-parse", "HEAD^{tree}").decode().strip()}


def manifest(plan, collected, jobs):
    suites = collected.get("suites")
    if not isinstance(suites, list) or not suites:
        raise ValueError("Collected qualification has no uniform suite evidence")
    components = {key: value for key, value in collected.items()
                  if key not in {"suites", "report_sha256"}}
    if "policy_tests_executed" not in components:
        raise ValueError("Collected qualification has no component summary")
    return {**plan, "passed": True,
            "scope": "Selected workflow execution and component reports; not an exact-artifact release qualification",
            "components": components, "suites": suites,
            "report_sha256": collected.get("report_sha256"), "jobs": jobs}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--check-plan", type=Path)
    parser.add_argument("--evidence-dir", type=Path)
    args = parser.parse_args()
    plan = current_plan()
    if args.check_plan:
        recorded = json.loads(args.check_plan.read_text(encoding="utf-8"))
        if recorded != plan:
            raise ValueError("Selected workflow manifest does not match the current source and event")
        needs = json.loads(os.environ["QUALIFICATION_NEEDS"])
        if needs.get("plan", {}).get("result") != "success":
            raise ValueError("Selection job did not succeed")
        jobs = {name: value for name, value in needs.items() if name != "plan"}
        validate(plan, jobs)
        if args.evidence_dir is None:
            raise ValueError("Required component evidence directory is missing")
        from connection_matrix import collect
        collected = collect(args.evidence_dir, plan["source_commit"], plan["source_tree"], plan["required"])
        result = manifest(plan, collected,
                          {name: value["result"] for name, value in jobs.items()})
    else:
        result = plan
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
            for suite in SUITES:
                output.write(f"{suite}={str(suite in plan['required']).lower()}\n")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()

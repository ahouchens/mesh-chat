"""Conservative CI selection and an always-running gate for required workflows."""

import argparse
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess


SUITES = ("policy", "verification", "android", "direct", "layout")
PROTECTED_DOCS = {"AGENTS.md", "SKILL.md", "Mesh_Chat_Connection_Runtime_Spec.md"}


def documentation(path):
    if not isinstance(path, str) or not path or "\\" in path:
        return False
    value = PurePosixPath(path)
    if value.is_absolute() or ".." in value.parts or value.name in PROTECTED_DOCS:
        return False
    return (path in {"README.md", "CHANGELOG.md", "LICENSE"}
            or (path.startswith("docs/") and value.suffix in {".md", ".png", ".svg"}))


def select(paths, *, event="pull_request"):
    documentation_only = (event in {"pull_request", "push"} and bool(paths)
                          and all(documentation(path) for path in paths))
    return {
        "version": 1, "event": event, "paths": paths,
        "required": ["policy", "verification"] if documentation_only else list(SUITES),
        "reason": "isolated_documentation" if documentation_only else "conservative_full_matrix",
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
        components = collect(args.evidence_dir, plan["source_commit"], plan["source_tree"], plan["required"])
        result = {**plan, "passed": True,
                  "scope": "Selected workflow execution and component reports; not an exact-artifact release qualification",
                  "components": components,
                  "jobs": {name: value["result"] for name, value in jobs.items()}}
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

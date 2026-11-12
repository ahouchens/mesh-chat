"""Bounded, evidence-producing WebRTC socket patch C++ prototype runner.

This builds only the pinned fork's Linux rtc_p2p_unittests. It never builds an
Android AAR or changes the application's WebRTC dependency.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET


SOURCE_REPO = "https://github.com/webrtc-sdk/webrtc.git"
SOURCE_REVISION = "73cb8180f7258ee292878d6edd05177f41883962"
DEPOT_REPO = "https://chromium.googlesource.com/chromium/tools/depot_tools.git"
DEPOT_REVISION = "2f9bc10799af5aeb4a0ed903742ad69bb1d0ef75"
DEPS_SHA256 = "dcf605b64a79a0ea7808b13bd9373a57d3bb441cb00436292ab865485a5ffdd3"
PATCH_RELATIVE = Path("third_party/webrtc/patches/selected-turn-socket.patch")
GN_ARGS = (
    'target_os="linux" target_cpu="x64" is_debug=false '
    "rtc_include_tests=true rtc_build_examples=false rtc_build_tools=false "
    "use_remoteexec=false"
)
MIN_INITIAL_FREE_BYTES = 10 * 1024**3
MIN_POST_SYNC_FREE_BYTES = 3 * 1024**3
MIN_AVAILABLE_MEMORY_KIB = 3 * 1024**2
MAX_BUILD_JOBS = 2
TEST_MACRO = re.compile(r"^\+\s*TEST(_F)?\s*\(\s*(\w+)\s*,\s*(\w+)\s*\)")
CONTEXT_TEST = re.compile(r"(?:TEST|TEST_F)\s*\(\s*(\w+)\s*,\s*(\w+)\s*\)")
UNSUPPORTED_TEST_MACRO = re.compile(r"^\+\s*(?:TEST_P|TYPED_TEST|TYPED_TEST_P)\s*\(")
DIFF_PATH = re.compile(r"^diff --git a/(\S+) b/(\S+)$")


class PrototypeError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def patch_inventory(patch: Path) -> dict:
    if not patch.is_file():
        raise PrototypeError(f"required patch absent: {patch}")
    content = patch.read_text(encoding="utf-8")
    paths: list[str] = []
    tests: list[str] = []
    current_path = ""
    current_test = ""
    for line in content.splitlines():
        header = DIFF_PATH.match(line)
        if header:
            if header.group(1) != header.group(2):
                raise PrototypeError("patch rename/copy is outside prototype scope")
            candidate = PurePosixPath(header.group(1))
            if candidate.is_absolute() or ".." in candidate.parts or not candidate.parts or candidate.parts[0] != "p2p":
                raise PrototypeError(f"patch path outside p2p: {candidate}")
            current_path = str(candidate)
            current_test = ""
            paths.append(current_path)
        if line.startswith("@@") and current_path.endswith("_unittest.cc"):
            match = CONTEXT_TEST.search(line)
            current_test = f"{match.group(1)}.{match.group(2)}" if match else ""
        elif current_path.endswith("_unittest.cc") and line.startswith(" "):
            match = CONTEXT_TEST.search(line)
            if match:
                current_test = f"{match.group(1)}.{match.group(2)}"
        match = TEST_MACRO.match(line)
        if UNSUPPORTED_TEST_MACRO.match(line):
            raise PrototypeError("parameterized or typed new tests need an explicit inventory")
        if match and current_path.endswith("_unittest.cc"):
            current_test = f"{match.group(2)}.{match.group(3)}"
        if current_test and line.startswith("+") and not line.startswith("+++") and current_path.endswith("_unittest.cc"):
            tests.append(current_test)
    if not paths:
        raise PrototypeError("patch has no p2p diff headers")
    tests = list(dict.fromkeys(tests))
    if not tests:
        raise PrototypeError("patch must modify at least one TEST or TEST_F in a p2p unit test file")
    return {"path": str(patch), "sha256": sha256(patch), "bytes": patch.stat().st_size,
            "changedPaths": paths, "selectedTests": tests}


def disk_snapshot(path: Path) -> dict:
    usage = shutil.disk_usage(path)
    return {"totalBytes": usage.total, "usedBytes": usage.used, "freeBytes": usage.free}


def memory_snapshot() -> dict:
    meminfo = Path("/proc/meminfo")
    if not meminfo.exists():
        return {}
    values = {}
    for line in meminfo.read_text(encoding="utf-8").splitlines():
        if line.startswith(("MemTotal:", "MemAvailable:")):
            key, number, _ = line.split()
            values[key.rstrip(":") + "KiB"] = int(number)
    return values


def verify_checkout_file(path: Path, expected: str, label: str) -> str:
    actual = sha256(path)
    if actual != expected:
        raise PrototypeError(f"{label} SHA256 mismatch: expected {expected}, got {actual}")
    return actual


def verify_test_target(source: Path) -> dict:
    root = source / "BUILD.gn"
    p2p = source / "p2p" / "BUILD.gn"
    root_text = root.read_text(encoding="utf-8")
    p2p_text = p2p.read_text(encoding="utf-8")
    if 'rtc_test("rtc_p2p_unittests")' not in root_text:
        raise PrototypeError("root runnable rtc_p2p_unittests target absent")
    if 'rtc_library("rtc_p2p_unittests")' not in p2p_text:
        raise PrototypeError("p2p test library target absent")
    if 'deps = [ "p2p:rtc_p2p_unittests" ]' not in root_text:
        raise PrototypeError("root test does not depend on p2p test library")
    return {"rootBuildGnSha256": sha256(root), "p2pBuildGnSha256": sha256(p2p),
            "runnableTarget": "//:rtc_p2p_unittests",
            "testLibrary": "//p2p:rtc_p2p_unittests"}


def extract_listed_tests(output: str) -> set[str]:
    suite = ""
    found: set[str] = set()
    for line in output.splitlines():
        if line and not line.startswith(" ") and line.endswith("."):
            suite = line.strip()
        elif suite and line.startswith("  "):
            name = line.strip().split(" #", 1)[0]
            if name:
                found.add(suite + name)
    return found


def verify_listed_tests(listed: set[str], required: list[str]) -> None:
    missing = sorted(set(required) - listed)
    if missing:
        raise PrototypeError(f"selected patch tests absent from binary: {missing}")


def validate_test_xml(path: Path, required: list[str]) -> dict:
    if not path.is_file():
        raise PrototypeError("test runner produced no XML")
    root = ET.parse(path).getroot()
    cases = {f"{case.get('classname')}.{case.get('name')}": case
             for case in root.iter("testcase")}
    missing = sorted(set(required) - cases.keys())
    if missing:
        raise PrototypeError(f"test XML omitted selected cases: {missing}")
    bad = [name for name in required if cases[name].find("failure") is not None
           or cases[name].find("error") is not None
           or cases[name].find("skipped") is not None]
    if bad:
        raise PrototypeError(f"selected test cases did not pass: {bad}")
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size,
            "selectedCases": required, "allCaseCount": len(cases)}


def verify_resolved_revisions(path: Path) -> dict:
    """Require actual Git commits or CIPD instances; retain GCS DEPS pins."""
    entries = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(entries, dict) or "src" not in entries:
        raise PrototypeError("gclient revision inventory lacks src")
    if not isinstance(entries["src"], dict):
        raise PrototypeError("gclient source revision entry malformed")
    unresolved = []
    kinds = {"git": 0, "cipdInstance": 0, "gcsDepsPinned": 0, "inactive": 0}
    for name, entry in entries.items():
        if not isinstance(entry, dict):
            unresolved.append(name)
            continue
        revision = entry.get("rev")
        url = entry.get("url")
        if not url and not revision:
            kinds["inactive"] += 1
        elif revision and re.fullmatch(r"[0-9a-f]{40}", revision):
            kinds["git"] += 1
        elif url and re.search(r"/p/[^\s]+/\+/[A-Za-z0-9_-]{40,}$", url):
            kinds["cipdInstance"] += 1
        elif url and str(url).startswith("gs://") and not revision:
            # GCS object names, SHA256, size and generation are in exact DEPS.
            kinds["gcsDepsPinned"] += 1
        else:
            unresolved.append(name)
    if entries["src"].get("rev") != SOURCE_REVISION:
        raise PrototypeError("gclient actual source revision differs from pinned fork revision")
    if unresolved:
        raise PrototypeError(f"gclient actual revisions unresolved or moving: {unresolved[:20]}")
    return {"path": str(path), "sha256": sha256(path), "entries": len(entries),
            "kinds": kinds}


def run_command(name: str, command: list[str], cwd: Path, env: dict,
                evidence: dict, evidence_dir: Path, timeout: int = 1200) -> str:
    log = evidence_dir / f"{name}.log"
    print(f"[{name}] {' '.join(command)}", flush=True)
    start = time.monotonic()
    with log.open("w", encoding="utf-8") as output:
        try:
            result = subprocess.run(command, cwd=cwd, env=env, stdout=output,
                                    stderr=subprocess.STDOUT, text=True, timeout=timeout,
                                    check=False)
            code = result.returncode
        except subprocess.TimeoutExpired:
            code = "timeout"
    stage = {"name": name, "command": command, "cwd": str(cwd), "exitCode": code,
             "seconds": round(time.monotonic() - start, 1), "log": str(log),
             "logSha256": sha256(log),
             "disk": disk_snapshot(evidence_dir), "memory": memory_snapshot()}
    evidence["stages"].append(stage)
    if code != 0:
        tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-25:]
        print("\n".join(tail), file=sys.stderr)
        raise PrototypeError(f"{name} failed ({code}); see {log}")
    if name in ("test-list", "depot-revision", "depot-post-sync-revision",
                "source-revision", "source-post-sync-revision"):
        return log.read_text(encoding="utf-8", errors="replace")
    return ""


def git_pinned_checkout(name: str, url: str, revision: str, path: Path,
                        env: dict, evidence: dict, evidence_dir: Path) -> None:
    path.mkdir()
    for suffix, command in (
        ("init", ["git", "init", "-q"]),
        ("remote", ["git", "remote", "add", "origin", url]),
        ("fetch", ["git", "fetch", "--depth=1", "origin", revision]),
        ("checkout", ["git", "checkout", "--detach", "FETCH_HEAD"]),
    ):
        run_command(f"{name}-{suffix}", command, path, env, evidence, evidence_dir)
    actual = run_command(f"{name}-revision", ["git", "rev-parse", "HEAD"],
                         path, env, evidence, evidence_dir).strip()
    if actual != revision:
        raise PrototypeError(f"{name} revision mismatch: {actual}")


def run_prototype(repo: Path, work_dir: Path, evidence_dir: Path) -> None:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    evidence = {"status": "running", "source": {"url": SOURCE_REPO, "revision": SOURCE_REVISION},
                "depotTools": {"url": DEPOT_REPO, "revision": DEPOT_REVISION},
                "depsSha256": DEPS_SHA256, "gnArgs": GN_ARGS,
                "buildJobs": MAX_BUILD_JOBS, "stages": [], "appIntegrationPerformed": False,
                "githubRunId": os.environ.get("GITHUB_RUN_ID"),
                "githubSha": os.environ.get("GITHUB_SHA"),
                "pythonVersion": sys.version,
                "runnerPlatform": sys.platform,
                "scriptSha256": sha256(Path(__file__)),
                "nativeAcceptanceClaim": False}
    manifest = evidence_dir / "manifest.json"
    try:
        if sys.platform != "linux":
            raise PrototypeError("native prototype runner requires Linux")
        evidence["patch"] = patch_inventory(repo / PATCH_RELATIVE)
        if work_dir.exists():
            raise PrototypeError(f"work directory must be absent: {work_dir}")
        if disk_snapshot(work_dir.parent)["freeBytes"] < MIN_INITIAL_FREE_BYTES:
            raise PrototypeError("initial free disk below 10 GiB preflight")
        initial_memory = memory_snapshot()
        if initial_memory.get("MemAvailableKiB", 0) < MIN_AVAILABLE_MEMORY_KIB:
            raise PrototypeError("initial available memory below 3 GiB preflight")
        work_dir.mkdir(parents=True)
        evidence["initialDisk"] = disk_snapshot(work_dir)
        evidence["initialMemory"] = initial_memory
        env = os.environ.copy()
        env["DEPOT_TOOLS_UPDATE"] = "0"
        depot = work_dir / "depot_tools"
        git_pinned_checkout("depot", DEPOT_REPO, DEPOT_REVISION, depot,
                            env, evidence, evidence_dir)
        env["PATH"] = f"{depot}{os.pathsep}{env.get('PATH', '')}"
        checkout = work_dir / "checkout"
        checkout.mkdir()
        (checkout / ".gclient").write_text(
            'solutions = [{"name": "src", "url": "' + SOURCE_REPO + '", '
            '"deps_file": "DEPS", "managed": False, "custom_deps": {}}]\n'
            'target_os = []\n', encoding="utf-8")
        evidence["gclientConfigSha256"] = sha256(checkout / ".gclient")
        source = checkout / "src"
        git_pinned_checkout("source", SOURCE_REPO, SOURCE_REVISION, source,
                            env, evidence, evidence_dir)
        evidence["source"]["depsVerifiedSha256"] = verify_checkout_file(
            source / "DEPS", DEPS_SHA256, "DEPS")
        evidence["testTarget"] = verify_test_target(source)
        run_command("gclient-sync", ["gclient", "sync", "--no-history", "--jobs=2",
                                     "--revision", f"src@{SOURCE_REVISION}"],
                    checkout, env, evidence, evidence_dir, timeout=3600)
        evidence["source"]["depsPostSyncSha256"] = verify_checkout_file(
            source / "DEPS", DEPS_SHA256, "DEPS after sync")
        pinned_depot_after_sync = run_command(
            "depot-post-sync-revision", ["git", "rev-parse", "HEAD"],
            depot, env, evidence, evidence_dir).strip()
        if pinned_depot_after_sync != DEPOT_REVISION:
            raise PrototypeError(f"bootstrap depot_tools moved during sync: {pinned_depot_after_sync}")
        actual_source = run_command("source-post-sync-revision", ["git", "rev-parse", "HEAD"],
                                    source, env, evidence, evidence_dir).strip()
        if actual_source != SOURCE_REVISION:
            raise PrototypeError(f"post-sync source revision mismatch: {actual_source}")
        if disk_snapshot(work_dir)["freeBytes"] < MIN_POST_SYNC_FREE_BYTES:
            raise PrototypeError("post-sync free disk below 3 GiB build preflight")
        if memory_snapshot().get("MemAvailableKiB", 0) < MIN_AVAILABLE_MEMORY_KIB:
            raise PrototypeError("post-sync available memory below 3 GiB build preflight")
        resolved = evidence_dir / "gclient-actual-revisions.json"
        run_command("gclient-revinfo", ["gclient", "revinfo", "--actual",
                                         "--output-json", str(resolved)], checkout,
                    env, evidence, evidence_dir)
        evidence["resolvedRevisions"] = verify_resolved_revisions(resolved)
        patch = repo / PATCH_RELATIVE
        run_command("patch-check", ["git", "apply", "--check", str(patch)], source,
                    env, evidence, evidence_dir)
        run_command("patch-apply", ["git", "apply", str(patch)], source,
                    env, evidence, evidence_dir)
        run_command("patch-diff-check", ["git", "diff", "--check"], source,
                    env, evidence, evidence_dir)
        output_dir = source / "out" / "socket_prototype"
        run_command("gn-gen", ["gn", "gen", str(output_dir), f"--args={GN_ARGS}"],
                    source, env, evidence, evidence_dir)
        evidence["argsGnSha256"] = sha256(output_dir / "args.gn")
        run_command("native-build", ["autoninja", "-C", str(output_dir),
                                      "-j", str(MAX_BUILD_JOBS), "rtc_p2p_unittests"],
                    source, env, evidence, evidence_dir, timeout=3600)
        binary = output_dir / "rtc_p2p_unittests"
        if not binary.is_file():
            raise PrototypeError("rtc_p2p_unittests binary absent")
        evidence["testBinary"] = {"path": str(binary), "sha256": sha256(binary),
                                  "bytes": binary.stat().st_size}
        listed = extract_listed_tests(run_command("test-list", [str(binary), "--gtest_list_tests"],
                                                  source, env, evidence, evidence_dir))
        required = evidence["patch"]["selectedTests"]
        verify_listed_tests(listed, required)
        xml = evidence_dir / "selected-tests.xml"
        run_command("focused-tests", [str(binary), f"--gtest_filter={':'.join(required)}",
                                      f"--gtest_output=xml:{xml}"],
                    source, env, evidence, evidence_dir, timeout=1200)
        evidence["testXml"] = validate_test_xml(xml, required)
        evidence["status"] = "focused C++ tests passed; Android AAR and app acceptance untested"
    except (PrototypeError, OSError, ValueError, subprocess.SubprocessError, ET.ParseError) as exc:
        evidence["status"] = "failed or blocked; no native acceptance claim"
        evidence["error"] = str(exc)
        raise
    finally:
        xml_artifact = evidence_dir / "selected-tests.xml"
        if xml_artifact.is_file() and "testXml" not in evidence:
            evidence["testXmlArtifact"] = {
                "path": str(xml_artifact), "sha256": sha256(xml_artifact),
                "bytes": xml_artifact.stat().st_size,
                "validatedPassingCases": False,
            }
        evidence["finalDisk"] = disk_snapshot(evidence_dir)
        manifest.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        print(f"evidence: {manifest}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate", "run"))
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--evidence-dir", type=Path)
    args = parser.parse_args()
    try:
        repo = args.repo.resolve()
        if args.command == "validate":
            print(json.dumps(patch_inventory(repo / PATCH_RELATIVE), indent=2))
        else:
            if not args.work_dir or not args.evidence_dir:
                parser.error("run requires --work-dir and --evidence-dir")
            run_prototype(repo, args.work_dir.resolve(), args.evidence_dir.resolve())
    except (PrototypeError, OSError, ValueError, subprocess.SubprocessError, ET.ParseError) as exc:
        print(f"prototype validation: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Run-bound evidence for the isolated optimized Android instrumentation host."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "dist/reports"
APK_DIRECTORY = ROOT / "plugins/tauri-plugin-mesh-runtime/android/webrtc-smoke/build/outputs/apk"
APKS = (APK_DIRECTORY / "release/webrtc-smoke-release.apk",
        APK_DIRECTORY / "androidTest/release/webrtc-smoke-release-androidTest.apk")
APP_ID = "com.meshchat.runtime.smoke"
WEBRTC = {
    "NativeCallbackQueueTest": ("saturatedMetadataQueueStillAdmitsExactDisposal",),
    "NativeSessionReservationsTest": (
        "cancellationRetainsCapacityUntilCreationAndDisposalFinish",
        "cancelledCreationCannotRetryOrReplaceItsReservation",
        "replacementWaitsForExactPhysicalDisposal",
        "concurrentCreatorsCannotOverbookOrReplaceAnId"),
    "NativeWebRtcInteropTest": (
        "chromiumOfferCanBeAcceptedThroughTheRealPythonBridge",
        "chromiumOfferSurvivesEarlyIceFailureDuringManualAnswerExchange",
        "nativeOfferCanConnectToChromiumWithReconnectControl",
        "repeatedChromiumMediaCallsPreserveNativeMessaging",
        "repeatedChromiumMediaCallsPreserveNativeOfferedMessaging",
        "backgroundRuntimeCanInitializeNativeWebRtc",
        "backgroundDefaultResumesAfterUnlockAndPreservesAnExplicitOffChoice",
        "queuedAvailabilityStartHonorsStopWithoutCrashingOrOpeningTheRuntime",
        "optedInServiceRestoresAndKeepsNativeTrafficWhileActivityIsStopped",
        "productionDesktopTransportOffersToNative", "productionDesktopTransportAnswersNative"),
}
SIGNALING = (
    ("embeddedDefaultAndChoicesSurviveProcessRestart", "seed"),
    ("embeddedDefaultAndChoicesSurviveProcessRestart", "verify"),
    ("packagedAndroidCryptoExchangesCiphertextWithWorker", "none"),
    ("personalMailboxRecoversAfterLossRestartAndLifecycleChanges", "none"),
    ("workspaceMailboxRecoversAfterLossRestartAndLifecycleChanges", "none"),
    ("sharedRuntimeOwnsNativeRecoveryAcrossLifecycle", "none"),
    ("sharedRuntimeAdoptsVerifiedManualNativeCarrierWithoutMailbox", "none"),
    ("sharedRuntimeAdoptsManualCarrierWithAutomaticReconnectDisabled", "none"),
)


def cases(suite):
    entries = ((name, method, "none") for name, methods in WEBRTC.items() for method in methods)
    if suite == "signaling":
        entries = (("SignalMailboxAndroidTest", method, phase) for method, phase in SIGNALING)
    elif suite != "webrtc":
        raise ValueError("Unknown qualification suite")
    return [{"id": f"{name}.{method}.{phase}", "class": name, "method": method, "phase": phase,
             "report": method + (f"-{phase}" if suite == "signaling" else "") + ".txt"}
            for name, method, phase in entries]


def verify_case(text, run, test_class, method):
    lines = [line.strip() for line in text.splitlines()]
    prefix = "INSTRUMENTATION_STATUS: "
    def values(name):
        return [line[len(prefix + name + "="):] for line in lines if line.startswith(prefix + name + "=")]
    codes = [line.split(":", 1)[1].strip() for line in lines if line.startswith("INSTRUMENTATION_STATUS_CODE:")]
    if (lines.count(f"MESH_QUALIFICATION_RUN={run}") != 1
            or not lines or lines[0] != f"MESH_QUALIFICATION_RUN={run}"
            or lines.count("OK (1 test)") != 1
            or set(values("class")) != {f"com.meshchat.runtime.{test_class}"}
            or set(values("test")) != {method} or set(values("numtests")) != {"1"}
            or codes.count("1") != 1 or codes.count("0") != 1 or set(codes) - {"0", "1", "2"}
            or lines.count("INSTRUMENTATION_CODE: -1") != 1
            or any(re.search(r"INSTRUMENTATION_FAILED|FAILURES!!!|Process crashed|shortMsg=", line)
                   for line in lines)):
        raise ValueError("Required instrumentation case did not execute once successfully")


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def artifacts():
    return {str(path.relative_to(ROOT)).replace("\\", "/"): digest(path) for path in APKS}


def source():
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if commit != os.environ.get("GITHUB_SHA", commit):
        raise ValueError("Android checkout does not match the required source")
    tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, text=True).strip()
    return {"source_commit": commit, "source_tree": tree}


def prepare(suite):
    directory = REPORTS / f"android-{suite}"
    directory.mkdir(parents=True, exist_ok=True)
    inventory = {"v": 1, **source(), "run_id": uuid4().hex, "scenarios": cases(suite),
                 "artifacts": artifacts(), "started_at": time.time()}
    (directory / "inventory.json").write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    print(inventory["run_id"])


def verify_suite(directory, suite, expected_source, expected_artifacts):
    inventory = json.loads((directory / "inventory.json").read_text(encoding="utf-8"))
    if (type(inventory.get("v")) is not int or inventory["v"] != 1
            or any(inventory.get(key) != value for key, value in expected_source.items())
            or inventory.get("artifacts") != expected_artifacts or inventory.get("scenarios") != cases(suite)
            or not isinstance(inventory.get("run_id"), str)
            or not re.fullmatch(r"[a-f0-9]{32}", inventory["run_id"])):
        raise ValueError("Android inventory does not match the source, artifacts or required selection")
    results = []
    for case in cases(suite):
        report = directory / case["report"]
        verify_case(report.read_text(encoding="utf-8"), inventory["run_id"], case["class"], case["method"])
        results.append({"scenario_id": case["id"], "report_sha256": digest(report), "passed": True})
    return {"suite": suite, "run_id": inventory["run_id"], "scenarios": results,
            "tests_collected": len(results), "tests_executed": len(results), "tests_passed": len(results),
            "tests_failed": 0, "tests_skipped": 0,
            "duration_seconds": max(0, time.time() - inventory["started_at"])}


def adb(*arguments):
    return subprocess.check_output(["adb", *arguments], text=True, timeout=20, stderr=subprocess.DEVNULL).strip()


def emulator_and_cleanup():
    if adb("shell", "getprop", "ro.kernel.qemu") != "1":
        raise ValueError("Required emulator qualification environment is unavailable")
    for package in (APP_ID, APP_ID + ".test"):
        adb("shell", "am", "force-stop", package)
    processes = adb("shell", "ps", "-A").splitlines()
    if not processes or not {"NAME", "CMD"}.intersection(processes[0].split()):
        raise ValueError("Android process cleanup could not be inspected")
    names = {line.split()[-1] for line in processes[1:] if line.split()}
    if any(name == APP_ID or name.startswith((APP_ID + ":", APP_ID + ".test")) for name in names):
        raise ValueError("Isolated Android test host still has a live process")
    return {"emulated": True, "api_level": adb("shell", "getprop", "ro.build.version.sdk"),
            "abi": adb("shell", "getprop", "ro.product.cpu.abi"), "test_host_cleanup": "passed"}


def report(status):
    result = {"v": 1, "passed": False,
              "evidence_level": "android_emulator_optimized_native_and_python_components", "phase": "runner"}
    try:
        if status != 0:
            raise ValueError("Android qualification runner failed")
        result["phase"] = "source_and_artifacts"
        identity, binaries = source(), artifacts()
        suites = []
        for suite in ("webrtc", "signaling"):
            result["phase"] = suite
            suites.append(verify_suite(REPORTS / f"android-{suite}", suite, identity, binaries))
        result["phase"] = "cleanup"
        result.update(identity, artifacts=binaries, suites=suites, platform=emulator_and_cleanup(), passed=True)
        del result["phase"]
    except Exception as error:
        # Instrumentation text can contain private documents. Keep it in the test
        # log artifacts; the machine result exposes only a bounded failure class.
        result["failure_type"] = type(error).__name__
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "android-qualification.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))
    return 0 if result["passed"] else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "list", "report"))
    parser.add_argument("--suite", choices=("webrtc", "signaling"))
    parser.add_argument("--status", type=int, default=1)
    args = parser.parse_args()
    if args.command == "report":
        return report(args.status)
    if args.suite is None:
        parser.error("--suite is required")
    if args.command == "prepare":
        prepare(args.suite)
    else:
        for case in cases(args.suite):
            print("\t".join(case[key] for key in ("method", "class", "phase")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

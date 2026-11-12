"""Manual, read-only inventory of a fresh API-35 KVM emulator.

This report diagnoses command availability and parsing. It is not native
interoperability evidence and never installs an app or changes network policy.
"""

import argparse
import json
import os
from pathlib import Path
import re
import selectors
import shlex
import shutil
import signal
import subprocess
import sys
import time
from uuid import uuid4

from native_interop_link_scope import LinkScopeError, covered_links, link_metadata, snapshot


IMAGE = "system-images;android-35;google_apis;x86_64"
SERIAL = "emulator-5554"
NAME = re.compile(r"[A-Za-z0-9_.-]{1,15}\Z")
MAX_LINKS = 32
MAX_COMMANDS = 256
MAX_STDOUT = 32 * 1024
MAX_STDERR = 4 * 1024
MAX_CAPTURE = 256 * 1024
MAX_REPORT = 512 * 1024
READ_SECONDS = 10
READ_BUDGET_SECONDS = 180
BOOT_SECONDS = 600
BEGIN = "MESH_NETWORK_INVENTORY_JSON_BEGIN"
END = "MESH_NETWORK_INVENTORY_JSON_END"


class ProbeFailure(RuntimeError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def _source_identity():
    root = Path(__file__).resolve().parents[1]
    values = []
    for revision in ("HEAD", "HEAD^{tree}"):
        value = subprocess.check_output(["git", "rev-parse", revision], cwd=root, timeout=10,
                                        stderr=subprocess.DEVNULL).decode().strip()
        if not re.fullmatch(r"[0-9a-f]{40}", value):
            raise ProbeFailure("source_identity_unavailable")
        values.append(value)
    return values


def _image_revision(sdk):
    source = sdk / "system-images/android-35/google_apis/x86_64/source.properties"
    try:
        lines = source.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    values = [line.split("=", 1)[1].strip() for line in lines if line.startswith("Pkg.Revision=")]
    return values[0][:64] if len(values) == 1 else None


def _collect_process(argv, *, timeout, stdout_limit, stderr_limit, env=None):
    """Drain both pipes while retaining no more than the supplied byte limits."""
    process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    selector = None
    try:
        selector = selectors.DefaultSelector()
        kept = {"stdout": bytearray(), "stderr": bytearray()}
        limits = {"stdout": stdout_limit, "stderr": stderr_limit}
        truncated = {"stdout": False, "stderr": False}
        deadline = time.monotonic() + timeout
        timed_out = False
        for name, pipe in (("stdout", process.stdout), ("stderr", process.stderr)):
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_READ, name)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            for key, _ in selector.select(timeout=remaining):
                data = os.read(key.fileobj.fileno(), 4096)
                if not data:
                    selector.unregister(key.fileobj)
                    continue
                name = key.data
                room = max(0, limits[name] - len(kept[name]))
                kept[name].extend(data[:room])
                if len(data) > room:
                    truncated[name] = True
        if timed_out:
            process.kill()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
            timed_out = True
    except BaseException:
        # A local read/selector failure must not orphan the exact child.
        try:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass
        raise
    finally:
        for resource in (selector, process.stdout, process.stderr):
            if resource is None:
                continue
            try:
                resource.close()
            except Exception:
                pass
    return {"exit_code": process.returncode, "timed_out": timed_out,
            "stdout": kept["stdout"].decode("utf-8", "replace"),
            "stderr": kept["stderr"].decode("utf-8", "replace"),
            "stdout_truncated": truncated["stdout"],
            "stderr_truncated": truncated["stderr"]}


class Emulator:
    def __init__(self):
        if (sys.platform != "linux" or os.environ.get("GITHUB_ACTIONS") != "true"
                or not os.access("/dev/kvm", os.R_OK | os.W_OK)):
            raise ProbeFailure("linux_kvm_ci_required")
        try:
            self.sdk = Path(os.environ.get("ANDROID_SDK_ROOT") or os.environ["ANDROID_HOME"]).resolve(strict=True)
            self.runner_temp = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
        except (KeyError, OSError) as error:
            raise ProbeFailure("android_sdk_or_runner_temp_unavailable") from error
        self.adb = self.sdk / "platform-tools/adb"
        self.binary = self.sdk / "emulator/emulator"
        self.name = "mesh-inventory-" + uuid4().hex[:12]
        self.avd_home = self.runner_temp / self.name
        self.process = None
        self.env = dict(os.environ, ANDROID_AVD_HOME=str(self.avd_home), ANDROID_SERIAL=SERIAL)

    def _short(self, *args, timeout=READ_SECONDS):
        try:
            return subprocess.run([str(self.adb), *args], capture_output=True, timeout=timeout,
                                  env=self.env, check=False)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ProbeFailure("adb_boot_command_unavailable") from error

    def start(self):
        devices = self._short("devices")
        device_lines = devices.stdout.decode("utf-8", "replace").splitlines()
        if (devices.returncode or not device_lines or device_lines[0].strip() != "List of devices attached"
                or any(line.strip() for line in device_lines[1:])):
            raise ProbeFailure("unowned_android_device_present")
        avdmanager = shutil.which("avdmanager")
        if avdmanager is None or not self.adb.is_file() or not self.binary.is_file():
            raise ProbeFailure("android_tools_unavailable")
        self.avd_home.mkdir(exist_ok=False)
        try:
            created = subprocess.run([avdmanager, "create", "avd", "--name", self.name,
                                      "--package", IMAGE], input=b"no\n", capture_output=True,
                                     timeout=120, env=self.env, check=False)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ProbeFailure("avd_creation_unavailable") from error
        if created.returncode:
            raise ProbeFailure("avd_creation_unavailable")
        self.process = subprocess.Popen([str(self.binary), "-avd", self.name, "-port", "5554",
            "-no-window", "-gpu", "swiftshader_indirect", "-accel", "on", "-no-snapshot",
            "-noaudio", "-no-boot-anim", "-camera-back", "none", "-camera-front", "none"],
            env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)
        deadline = time.monotonic() + BOOT_SECONDS
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise ProbeFailure("emulator_exited_during_boot")
            try:
                boot = self._short("-s", SERIAL, "shell", "getprop", "sys.boot_completed", timeout=5)
                if boot.returncode == 0 and boot.stdout.strip() == b"1":
                    break
            except ProbeFailure:
                pass
            time.sleep(1)
        else:
            raise ProbeFailure("emulator_boot_deadline")
        if self._short("-s", SERIAL, "root", timeout=30).returncode:
            raise ProbeFailure("android_root_unavailable")
        if self._short("-s", SERIAL, "wait-for-device", timeout=30).returncode:
            raise ProbeFailure("android_root_unavailable")
        uid = self._short("-s", SERIAL, "shell", "id", "-u")
        if uid.returncode or uid.stdout.strip() != b"0":
            raise ProbeFailure("android_root_identity_unavailable")

    def close(self):
        failed = False
        if self.process is not None:
            if self.process.poll() is None:
                try:
                    self._short("-s", SERIAL, "emu", "kill", timeout=10)
                    self.process.wait(timeout=30)
                except (ProbeFailure, subprocess.TimeoutExpired):
                    try:
                        os.killpg(self.process.pid, signal.SIGKILL)
                        self.process.wait(timeout=15)
                    except (OSError, subprocess.TimeoutExpired):
                        failed = True
            else:
                self.process.wait(timeout=5)
            if self.process.poll() is None:
                failed = True
        if failed:
            raise ProbeFailure("emulator_cleanup_incomplete")
        if (self.avd_home.parent != self.runner_temp or self.avd_home.name != self.name
                or self.avd_home.is_symlink()):
            raise ProbeFailure("avd_cleanup_path_changed")
        if self.avd_home.exists():
            try:
                shutil.rmtree(self.avd_home)
            except OSError:
                failed = True
        if self.avd_home.exists() or failed:
            raise ProbeFailure("emulator_cleanup_incomplete")


class Inventory:
    def __init__(self, emulator, report):
        self.emulator = emulator
        self.report = report
        self.records = {}
        self.bytes_kept = 0
        self.deadline = time.monotonic() + READ_BUDGET_SECONDS

    def capture(self, *argv):
        if len(self.report["commands"]) >= MAX_COMMANDS:
            raise ProbeFailure("command_limit_exceeded")
        key = tuple(str(value) for value in argv)
        if key in self.records:
            return self.records[key]
        room = max(0, MAX_CAPTURE - self.bytes_kept)
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            value = {"exit_code": None, "timed_out": True, "stdout": "", "stderr": "",
                     "stdout_truncated": False, "stderr_truncated": False}
        else:
            stderr_limit = min(MAX_STDERR, room)
            value = _collect_process([str(self.emulator.adb), "-s", SERIAL, "shell", *key],
                timeout=min(READ_SECONDS, remaining), stdout_limit=min(MAX_STDOUT, room - stderr_limit),
                stderr_limit=stderr_limit,
                env=self.emulator.env)
        value = {"argv": list(key), **value}
        self.bytes_kept += len(value["stdout"].encode("utf-8")) + len(value["stderr"].encode("utf-8"))
        self.records[key] = value
        self.report["commands"].append(value)
        return value

    def cached(self, *argv):
        record = self.records.get(tuple(argv))
        if (record is None or record["exit_code"] != 0 or record["timed_out"]
                or record["stdout_truncated"] or record["stderr_truncated"]):
            raise ProbeFailure("captured_command_unavailable")
        return record["stdout"].strip()

    def collect(self):
        self.capture("ip", "-V")
        self.capture("ip", "-j", "-d", "link", "show")
        old = self.capture("ip", "-o", "link", "show")
        for args in (("ip", "-4", "route", "show", "table", "all"),
                     ("ip", "-6", "route", "show", "table", "all"),
                     ("ip", "-4", "rule", "show"), ("ip", "-6", "rule", "show")):
            self.capture(*args)
        if old["exit_code"] == 0 and not old["timed_out"] and not old["stdout_truncated"]:
            names = []
            for line in old["stdout"].splitlines():
                match = re.fullmatch(r"\s*[0-9]+:\s+([A-Za-z0-9_.-]{1,15})(?:@[^:]+)?:\s+<[^>]*>.*", line)
                if match is None or match[1] in names or len(names) >= MAX_LINKS:
                    self.report["name_inventory"] = "unavailable"
                    break
                names.append(match[1])
            else:
                self.report["name_inventory"] = "validated"
                for name in names:
                    root = "/sys/class/net/" + name
                    for field in ("type", "ifindex", "iflink", "netdev_group"):
                        self.capture("cat", root + "/" + field)
                    script = ("for p in " + root + "/master " + root + "/lower_* "
                              + root + "/upper_*; do if [ -e \"$p\" ]; then echo 1; exit; fi; done; echo 0")
                    self.capture("sh", "-c", shlex.quote(script))
                    self.capture("ip", "-d", "link", "show", "dev", name)
                    self.capture("tc", "qdisc", "show", "dev", name)
        else:
            self.report["name_inventory"] = "unavailable"
        for args in (("getprop", "ro.build.fingerprint"), ("iptables-save",),
                     ("ip6tables-save",),
                     ("sh", "-c", shlex.quote("command -v nft >/dev/null 2>&1")),
                     ("sh", "-c", shlex.quote(
                         "if [ -r /proc/config.gz ] && command -v zcat >/dev/null 2>&1; "
                         "then zcat /proc/config.gz 2>/dev/null | "
                         "grep -E '^(CONFIG_NF_TABLES=(y|m|n)|# CONFIG_NF_TABLES is not set)$' "
                         "|| echo unknown; "
                         "else echo unknown; fi"))):
            self.capture(*args)
        nft = self.records[("sh", "-c", shlex.quote("command -v nft >/dev/null 2>&1"))]
        if nft["exit_code"] == 0 and not nft["timed_out"]:
            self.capture("nft", "list", "ruleset")
        self.classify()

    def classify(self):
        try:
            links, route4, route6, rule4, rule6 = snapshot(self.cached)
        except ProbeFailure:
            self.report["classification"] = {"stage": "snapshot_command", "result": "unavailable"}
            return
        try:
            parsed = json.loads(links)
        except (TypeError, ValueError):
            self.report["classification"] = {"stage": "json_decode", "result": "rejected"}
            return
        if type(parsed) is not list:
            self.report["classification"] = {"stage": "json_shape", "result": "rejected"}
            return
        try:
            metadata = link_metadata(self.cached, links)
        except (LinkScopeError, ProbeFailure) as error:
            reason = error.reason if type(error) is LinkScopeError else "captured_command_unavailable"
            self.report["classification"] = {"stage": "link_metadata", "result": "rejected", "reason": reason}
            return
        try:
            plan = covered_links(links, route4, route6, rule4, rule6, metadata)
        except LinkScopeError as error:
            self.report["classification"] = {"stage": "covered_links", "result": "rejected",
                                             "reason": error.reason}
            return
        self.report["classification"] = {"stage": "covered_links", "result": "accepted",
                                         "admitted_count": len(plan["external"]),
                                         "denied_sink_count": len(plan["sinks"])}


def _bounded_json(report):
    for _ in range(20):
        encoded = json.dumps(report, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        if len(encoded) <= MAX_REPORT:
            return encoded
        for record in reversed(report["commands"]):
            field = "stdout" if len(record["stdout"]) >= len(record["stderr"]) else "stderr"
            if record[field]:
                record[field] = record[field][:len(record[field]) // 2]
                record[field + "_truncated"] = True
                report["classification"] = {"stage": "report_limit", "result": "unavailable"}
                break
        else:
            raise ProbeFailure("report_limit_unavailable")
    raise ProbeFailure("report_limit_unavailable")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output != Path("dist/reports/android-network-inventory.json"):
        parser.error("--output must be dist/reports/android-network-inventory.json")
    report = {"kind": "android_network_inventory_probe_v1",
              "evidence_level": "diagnostic_only_not_qualification", "qualification": False,
              "network_mutations": False, "image_package": IMAGE,
              "github_run_id": os.environ.get("GITHUB_RUN_ID"),
              "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
              "source_commit": None, "source_tree": None, "image_revision": None,
              "image_fingerprint": None, "commands": [], "name_inventory": "unavailable",
              "classification": {"stage": "bootstrap", "result": "unavailable"},
              "bootstrap": "unavailable", "cleanup": "not_needed"}
    failure = False
    emulator = None
    try:
        if not (re.fullmatch(r"[1-9][0-9]*", report["github_run_id"] or "")
                and re.fullmatch(r"[1-9][0-9]*", report["github_run_attempt"] or "")):
            raise ProbeFailure("run_binding_unavailable")
        report["source_commit"], report["source_tree"] = _source_identity()
        if os.environ.get("GITHUB_SHA") != report["source_commit"]:
            raise ProbeFailure("source_binding_mismatch")
        emulator = Emulator()
        report["image_revision"] = _image_revision(emulator.sdk)
        emulator.start()
        report["bootstrap"] = "passed"
        inventory = Inventory(emulator, report)
        inventory.collect()
        fingerprint = inventory.records.get(("getprop", "ro.build.fingerprint"))
        if fingerprint and fingerprint["exit_code"] == 0 and not fingerprint["stdout_truncated"]:
            report["image_fingerprint"] = fingerprint["stdout"].strip()[:512]
    except ProbeFailure as error:
        failure = True
        report["bootstrap"] = "failed" if report["bootstrap"] != "passed" else "passed"
        report["probe_failure"] = error.reason
    except Exception:
        failure = True
        report["probe_failure"] = "unexpected_probe_failure"
    finally:
        if emulator is not None:
            try:
                emulator.close()
                report["cleanup"] = "passed"
            except ProbeFailure as error:
                report["cleanup"] = "failed"
                report["cleanup_failure"] = error.reason
                failure = True
            except Exception:
                report["cleanup"] = "failed"
                report["cleanup_failure"] = "unexpected_cleanup_failure"
                failure = True
    try:
        encoded = _bounded_json(report)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(encoded + b"\n")
        print(BEGIN)
        print(json.dumps(json.loads(encoded), ensure_ascii=True, indent=2))
        print(END)
    except (OSError, ProbeFailure):
        return 1
    return 1 if failure else 0


if __name__ == "__main__":
    raise SystemExit(main())

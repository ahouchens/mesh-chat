"""Record bounded tracked-source checkpoints for the focused Android build."""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
STAGES = ("before_app", "after_app", "before_test", "after_test", "before_probe")
MAX_ENTRIES = 32
MAX_DIFF_BYTES = 256 * 1024
SAFE_PATH = re.compile(r"[A-Za-z0-9._/+@-]{1,180}\Z")


def git(*arguments):
    return subprocess.check_output(["git", *arguments], cwd=ROOT, stderr=subprocess.DEVNULL,
                                   timeout=15)


def sha256(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def safe_path(raw):
    name = raw.decode("utf-8", "surrogateescape")
    if (SAFE_PATH.fullmatch(name) and not PurePosixPath(name).is_absolute()
            and ".." not in PurePosixPath(name).parts):
        return {"path": name}
    return {"path_sha256": hashlib.sha256(raw).hexdigest()}


def tracked_mode(command, name):
    raw = git(*command, "--", name)
    if not raw:
        return None
    mode = raw.split(b" ", 1)[0].decode("ascii")
    if mode not in {"100644", "100755", "120000", "160000"}:
        raise ValueError("Invalid tracked file mode")
    return mode


def worktree_mode(path):
    if path.is_symlink():
        return "120000"
    if path.is_file():
        return "100755" if path.stat().st_mode & stat.S_IXUSR else "100644"
    if path.is_dir():
        return "160000"
    return None


def entries_from_diff(raw):
    if len(raw) > MAX_DIFF_BYTES:
        return [], None, True
    if not raw:
        return [], 0, False
    fields = raw.split(b"\0")
    if fields.pop() != b"":
        raise ValueError("Incomplete tracked name-status inventory")
    entries = []
    index = 0
    total = 0
    while index < len(fields):
        status = fields[index].decode("ascii")
        if not re.fullmatch(r"[ACDMRTUXB][0-9]*", status):
            raise ValueError("Invalid tracked change status")
        count = 2 if status.startswith(("R", "C")) else 1
        names = fields[index + 1:index + 1 + count]
        if len(names) != count or any(not name for name in names):
            raise ValueError("Incomplete tracked change path")
        if len(entries) < MAX_ENTRIES:
            item = {"status": status, **safe_path(names[-1])}
            if count == 2:
                item["previous"] = safe_path(names[0])
            if "path" in item:
                name = item["path"]
                path = ROOT.joinpath(*name.split("/"))
                item["head_mode"] = tracked_mode(("ls-tree", "HEAD"), name)
                item["index_mode"] = tracked_mode(("ls-files", "--stage"), name)
                item["worktree_mode"] = worktree_mode(path)
                item["sha256"] = (sha256(path) if path.is_file() and not path.is_symlink()
                                  and path.resolve().is_relative_to(ROOT) else None)
            else:
                item.update(head_mode=None, index_mode=None, worktree_mode=None, sha256=None)
            entries.append(item)
        index += count + 1
        total += 1
    if index != len(fields):
        raise ValueError("Incomplete tracked change inventory")
    return entries, total, total > MAX_ENTRIES


def snapshot(expected):
    source = git("rev-parse", "HEAD").decode("ascii").strip()
    tree = git("rev-parse", "HEAD^{tree}").decode("ascii").strip()
    dirty = bool(git("status", "--porcelain", "--untracked-files=no"))
    entries, count, truncated = entries_from_diff(git("diff", "--name-status", "-z", "HEAD", "--"))
    return {"source_commit": source, "source_tree": tree, "source_matches_expected": source == expected,
            "tracked_clean": not dirty, "changed_count": count, "entries_truncated": truncated,
            "entries": entries}


def write_report(path, value):
    encoded = (json.dumps(value, indent=2, allow_nan=False) + "\n").encode("utf-8")
    if len(encoded) > 16 * 1024:
        raise ValueError("Source checkpoint report exceeds its bound")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def checkpoint(path, expected, stage):
    if stage not in STAGES or re.fullmatch(r"[a-f0-9]{40}", expected) is None:
        raise ValueError("Invalid source checkpoint identity")
    if path.exists():
        report = json.loads(path.read_text(encoding="utf-8"))
        if (report.get("expected_source") != expected or report.get("v") != 1
                or report.get("scope") != "tracked_names_status_and_sha_only"):
            raise ValueError("Source checkpoint report identity changed")
    else:
        report = {"v": 1, "expected_source": expected,
                  "scope": "tracked_names_status_and_sha_only", "checkpoints": []}
    prior = [STAGES.index(item["stage"]) for item in report["checkpoints"]]
    if prior and max(prior) >= STAGES.index(stage):
        raise ValueError("Source checkpoint order changed")
    try:
        record = {"stage": stage, "status": "captured", **snapshot(expected)}
    except Exception as error:
        record = {"stage": stage, "status": "unavailable", "exception_kind": type(error).__name__}
    report["checkpoints"].append(record)
    write_report(path, report)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-source", required=True)
    parser.add_argument("--stage", choices=STAGES, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    record = checkpoint(args.output, args.expected_source, args.stage)
    print(json.dumps({"stage": record["stage"], "status": record["status"],
                      "tracked_clean": record.get("tracked_clean")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

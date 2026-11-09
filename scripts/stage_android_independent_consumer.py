"""Stage an ordinary Android application and versioned Maven artifacts outside the checkout."""
import argparse
import json
from pathlib import Path
import shutil

from android_qualification import ROOT, source
from verify_android_independent_consumer import APPLICATION_FILES, PUBLICATIONS, digest, verify_publications


def stage(directory):
    directory = directory.resolve(strict=True)
    if directory.is_relative_to(ROOT) or not directory.is_dir() or any(directory.iterdir()):
        raise ValueError("Independent Android staging requires an empty directory outside checkout")
    identity = source()
    output = ROOT / "dist/android-independent-consumer"
    output.mkdir(parents=True, exist_ok=True)
    for relative, producer in PUBLICATIONS.items():
        if producer.is_symlink() or not producer.is_file():
            raise ValueError("Published Android Maven artifact is missing")
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(producer, destination)
        staged = directory / relative
        staged.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(producer, staged)
        if digest(producer) != digest(staged) or digest(staged) != digest(destination):
            raise ValueError("Published Maven artifact changed during staging")
    verify_publications(output)
    application = {}
    for name in APPLICATION_FILES:
        original = ROOT / "examples/android-independent-consumer" / name
        if original.is_symlink() or not original.is_file():
            raise ValueError("Independent application source is invalid")
        target = directory / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, target)
        application[name] = digest(original)
    if source() != identity:
        raise ValueError("Android source changed during staging")
    return {**identity, "application_files": application,
            "publications": {name: digest(output / name) for name in PUBLICATIONS}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    args = parser.parse_args()
    record = stage(args.stage)
    (args.stage / "staging.json").write_text(json.dumps(record), encoding="utf-8")

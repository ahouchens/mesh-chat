from __future__ import annotations

import json
import os
import re
import tomllib
import uuid
from dataclasses import dataclass
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]
SEMVER_PATTERN = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)")


class VersionError(RuntimeError):
    """Release metadata is missing, malformed, or inconsistent."""


@dataclass(frozen=True)
class VersionState:
    version: str
    android_version_code: int
    configured: dict[str, str]


def validate_version(value: str) -> str:
    """Validate the stable release format shared by npm, Cargo, and Android."""
    match = SEMVER_PATTERN.fullmatch(value)
    if match is None:
        raise VersionError("version must use the stable MAJOR.MINOR.PATCH format")
    major, minor, patch = (int(part) for part in match.groups())
    if minor > 999 or patch > 999:
        raise VersionError("Android version mapping requires MINOR and PATCH to be <= 999")
    code = major * 1_000_000 + minor * 1_000 + patch
    if code > 2_100_000_000:
        raise VersionError("derived Android versionCode exceeds the Play Store limit")
    return value


def android_version_code(version: str) -> int:
    validate_version(version)
    major, minor, patch = (int(part) for part in version.split("."))
    return major * 1_000_000 + minor * 1_000 + patch


def _root_cargo_lock_version(lock: dict[str, object]) -> str:
    packages = lock.get("package")
    if not isinstance(packages, list):
        raise VersionError("src-tauri/Cargo.lock has no package list")
    matches = [
        item
        for item in packages
        if isinstance(item, dict)
        and item.get("name") == "mesh-chat"
        and "source" not in item
    ]
    if len(matches) != 1 or not isinstance(matches[0].get("version"), str):
        raise VersionError("Cargo.lock must contain exactly one local mesh-chat package")
    return str(matches[0]["version"])


def configured_versions(repository: Path = REPOSITORY) -> dict[str, str]:
    repository = repository.resolve()
    try:
        package = json.loads((repository / "package.json").read_text(encoding="utf-8"))
        tauri = json.loads(
            (repository / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8")
        )
        cargo = tomllib.loads(
            (repository / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8")
        )
        cargo_lock = tomllib.loads(
            (repository / "src-tauri" / "Cargo.lock").read_text(encoding="utf-8")
        )
        service = tomllib.loads(
            (repository / "service" / "pyproject.toml").read_text(encoding="utf-8")
        )
        versions = {
            "package.json": package["version"],
            "src-tauri/tauri.conf.json": tauri["version"],
            "src-tauri/Cargo.toml": cargo["package"]["version"],
            "src-tauri/Cargo.lock": _root_cargo_lock_version(cargo_lock),
            "service/pyproject.toml": service["project"]["version"],
        }
    except (FileNotFoundError, KeyError, TypeError, json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
        raise VersionError(f"could not read release version metadata: {exc}") from exc
    if not all(isinstance(value, str) for value in versions.values()):
        raise VersionError("all configured release versions must be strings")
    return versions


def check_versions(
    repository: Path = REPOSITORY,
    *,
    expected: str | None = None,
) -> VersionState:
    versions = configured_versions(repository)
    canonical = validate_version(versions["package.json"])
    inconsistent = {path: value for path, value in versions.items() if value != canonical}
    if inconsistent:
        details = ", ".join(f"{path}={value}" for path, value in inconsistent.items())
        raise VersionError(f"release metadata does not match package.json {canonical}: {details}")
    if expected is not None:
        normalized = expected.removeprefix("v")
        validate_version(normalized)
        if normalized != canonical:
            raise VersionError(f"requested release {normalized} does not match source version {canonical}")
    return VersionState(canonical, android_version_code(canonical), versions)


def _replace_section_version(
    text: str,
    *,
    section: str,
    expected_name: str,
    version: str,
) -> str:
    section_match = re.search(
        rf"(?ms)^\[{re.escape(section)}\][^\n]*\n(?P<body>.*?)(?=^\[|\Z)",
        text,
    )
    if section_match is None:
        raise VersionError(f"missing [{section}] section")
    body = section_match.group("body")
    name_matches = re.findall(r'(?m)^name\s*=\s*"([^"]+)"\s*$', body)
    if name_matches != [expected_name]:
        raise VersionError(f"[{section}] must describe {expected_name}")
    version_matches = list(re.finditer(r'(?m)^(version\s*=\s*")([^"]+)("\s*)$', body))
    if len(version_matches) != 1:
        raise VersionError(f"[{section}] must contain exactly one version")
    match = version_matches[0]
    updated_body = body[: match.start()] + match.group(1) + version + match.group(3) + body[match.end() :]
    return text[: section_match.start("body")] + updated_body + text[section_match.end("body") :]


def _replace_cargo_lock_version(text: str, version: str) -> str:
    starts = [match.start() for match in re.finditer(r"(?m)^\[\[package\]\]\s*$", text)]
    starts.append(len(text))
    matches: list[tuple[int, int, str]] = []
    for start, end in zip(starts, starts[1:]):
        block = text[start:end]
        name = re.search(r'(?m)^name\s*=\s*"([^"]+)"\s*$', block)
        if name is None or name.group(1) != "mesh-chat":
            continue
        source = re.search(r"(?m)^source\s*=", block)
        if source is not None:
            continue
        version_match = re.search(r'(?m)^(version\s*=\s*")([^"]+)("\s*)$', block)
        if version_match is None:
            raise VersionError("local mesh-chat Cargo.lock package has no version")
        matches.append((start, end, block))
    if len(matches) != 1:
        raise VersionError("Cargo.lock must contain exactly one local mesh-chat package")
    start, end, block = matches[0]
    updated = re.sub(
        r'(?m)^(version\s*=\s*")([^"]+)("\s*)$',
        rf"\g<1>{version}\g<3>",
        block,
        count=1,
    )
    return text[:start] + updated + text[end:]


def _json_with_version(path: Path, version: str) -> str:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VersionError(f"could not parse {path}: {exc}") from exc
    if not isinstance(value, dict) or not isinstance(value.get("version"), str):
        raise VersionError(f"{path} has no top-level string version")
    value["version"] = version
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def _atomic_replace_many(contents: dict[Path, str]) -> None:
    originals = {path: path.read_bytes() for path in contents}
    temporary: dict[Path, Path] = {}
    replaced: list[Path] = []
    try:
        for path, value in contents.items():
            candidate = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
            candidate.write_text(value, encoding="utf-8", newline="\n")
            temporary[path] = candidate
        for path, candidate in temporary.items():
            os.replace(candidate, path)
            replaced.append(path)
    except Exception:
        for path in replaced:
            candidate = path.with_name(f".{path.name}.{uuid.uuid4().hex}.rollback")
            candidate.write_bytes(originals[path])
            os.replace(candidate, path)
        raise
    finally:
        for candidate in temporary.values():
            candidate.unlink(missing_ok=True)


def set_version(version: str, repository: Path = REPOSITORY) -> VersionState:
    """Synchronize every build metadata file as one validated transaction."""
    version = validate_version(version)
    repository = repository.resolve()
    package = repository / "package.json"
    tauri = repository / "src-tauri" / "tauri.conf.json"
    cargo = repository / "src-tauri" / "Cargo.toml"
    cargo_lock = repository / "src-tauri" / "Cargo.lock"
    service = repository / "service" / "pyproject.toml"

    cargo_text = cargo.read_text(encoding="utf-8")
    service_text = service.read_text(encoding="utf-8")
    lock_text = cargo_lock.read_text(encoding="utf-8")
    updates = {
        package: _json_with_version(package, version),
        tauri: _json_with_version(tauri, version),
        cargo: _replace_section_version(
            cargo_text,
            section="package",
            expected_name="mesh-chat",
            version=version,
        ),
        cargo_lock: _replace_cargo_lock_version(lock_text, version),
        service: _replace_section_version(
            service_text,
            section="project",
            expected_name="mesh-chat-service",
            version=version,
        ),
    }
    _atomic_replace_many(updates)
    return check_versions(repository, expected=version)

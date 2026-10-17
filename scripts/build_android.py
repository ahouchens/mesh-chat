"""Build the maintained debug APK or an externally signed Android release.

The default artifact targets current physical Android phones (arm64-v8a). The
APK uses Android's standard debug signing key and is intended for direct device
testing, not Play Store publication.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

try:
    from .publish_android_release import AndroidReleaseError, publish_android_release
except ImportError:  # Direct execution: python scripts/build_android.py
    from publish_android_release import AndroidReleaseError, publish_android_release


ROOT = Path(__file__).resolve().parents[1]
ANDROID = ROOT / "src-tauri" / "gen" / "android"
PENDING_INVITATION_TEMPLATE = (
    ROOT / "scripts" / "templates" / "android" / "PendingInvitation.kt"
)
NATIVE_LIBRARY = (
    ROOT
    / "src-tauri"
    / "target"
    / "aarch64-linux-android"
    / "debug"
    / "libmesh_chat_lib.so"
)
RELEASE_NATIVE_LIBRARY = (
    ROOT
    / "src-tauri"
    / "target"
    / "aarch64-linux-android"
    / "release"
    / "libmesh_chat_lib.so"
)
APK = ANDROID / "app" / "build" / "outputs" / "apk" / "arm64" / "debug" / "app-arm64-debug.apk"


def native_input_files() -> list[Path]:
    inputs = [
        ROOT / "index.html",
        ROOT / "package.json",
        ROOT / "pnpm-lock.yaml",
        ROOT / "THIRD_PARTY_NOTICES.md",
        ROOT / "vite.config.ts",
        ROOT / "src-tauri" / "Cargo.lock",
        ROOT / "src-tauri" / "Cargo.toml",
        ROOT / "experiments" / "direct-fabric" / "Cargo.toml",
        ROOT / "src-tauri" / "tauri.conf.json",
        ROOT / "src-tauri" / "tauri.android.conf.json",
        ROOT / "service" / "requirements-mobile.lock",
        ROOT / "plugins" / "tauri-plugin-mesh-runtime" / "Cargo.toml",
        ROOT / "plugins" / "tauri-plugin-mesh-runtime" / "build.rs",
        ROOT / "plugins" / "tauri-plugin-mesh-runtime" / "android" / "build.gradle.kts",
        ROOT / "plugins" / "tauri-plugin-mesh-runtime" / "android" / "settings.gradle",
    ]
    for directory, patterns in (
        (ROOT / "src", ("*.ts", "*.tsx", "*.css")),
        (ROOT / "public", ("*",)),
        (ROOT / "service" / "src", ("*.py",)),
        (ROOT / "src-tauri" / "src", ("*.rs",)),
        (ROOT / "experiments" / "direct-fabric" / "src", ("*.rs",)),
        (ROOT / "src-tauri" / "capabilities", ("*.json",)),
        (ROOT / "src-tauri" / "icons", ("*",)),
        (ROOT / "plugins" / "tauri-plugin-mesh-runtime" / "src", ("*.rs",)),
        (
            ROOT / "plugins" / "tauri-plugin-mesh-runtime" / "android" / "src",
            ("*.kt", "*.java", "*.xml"),
        ),
    ):
        for pattern in patterns:
            inputs.extend(path for path in directory.rglob(pattern) if path.is_file())
    return sorted({path.resolve() for path in inputs if path.is_file()})


def native_input_digest() -> str:
    digest = hashlib.sha256()
    for path in native_input_files():
        digest.update(path.relative_to(ROOT).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _native_library_newer_than_inputs(native_library: Path = NATIVE_LIBRARY) -> bool:
    if not native_library.is_file():
        return False
    library_mtime = native_library.stat().st_mtime
    return all(path.stat().st_mtime <= library_mtime for path in native_input_files())


def native_library_is_current(native_library: Path = NATIVE_LIBRARY) -> bool:
    """Return true only for a content-addressed, untampered native library."""
    native_stamp = native_library.with_name(".mesh-chat-native-input.json")
    if not native_library.is_file() or not native_stamp.is_file():
        return False
    try:
        stamp = json.loads(native_stamp.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    library_digest = hashlib.sha256(native_library.read_bytes()).hexdigest()
    return (
        stamp.get("schema_version") == 1
        and stamp.get("input_sha256") == native_input_digest()
        and stamp.get("library_sha256") == library_digest
    )


def record_native_library(native_library: Path = NATIVE_LIBRARY) -> None:
    if not native_library.is_file():
        return
    native_stamp = native_library.with_name(".mesh-chat-native-input.json")
    value = {
        "schema_version": 1,
        "input_sha256": native_input_digest(),
        "library_sha256": hashlib.sha256(native_library.read_bytes()).hexdigest(),
    }
    temporary = native_stamp.with_name(f".{native_stamp.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, native_stamp)


def stage_native_library(native_library: Path, destination: Path) -> Path:
    """Copy a native library unless Tauri already staged the same file."""
    destination.mkdir(parents=True, exist_ok=True)
    staged = destination / native_library.name
    try:
        if staged.exists() and native_library.samefile(staged):
            return staged
    except OSError:
        pass
    shutil.copy2(native_library, staged)
    return staged


def symlinks_available() -> bool:
    if os.name != "nt":
        return True
    target_root = ROOT / "src-tauri" / "target"
    target_root.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix="mesh-chat-symlink-", dir=target_root) as folder:
            directory = Path(folder)
            source = directory / "source"
            link = directory / "link"
            source.write_text("probe", encoding="ascii")
            os.symlink(source, link)
            return link.is_file()
    except OSError:
        return False


def write_if_changed(path: Path, value: str) -> None:
    if path.is_file() and path.read_text(encoding="utf-8") == value:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")


def build_android_frontend(pnpm: str, env: dict[str, str], *, debug: bool = True) -> int:
    """Refresh WebView assets with the same platform hints Tauri supplies."""
    frontend_env = env.copy()
    frontend_env.update(
        {
            "TAURI_ENV_PLATFORM": "android",
            "TAURI_ENV_ARCH": "aarch64",
            "TAURI_ENV_FAMILY": "unix",
            "TAURI_ENV_TARGET_TRIPLE": "aarch64-linux-android",
            "TAURI_ENV_DEBUG": "true" if debug else "false",
        }
    )
    return run([pnpm, "build"], env=frontend_env)


def run(command: list[str], *, cwd: Path = ROOT, env: dict[str, str]) -> int:
    print("+", subprocess.list2cmdline(command), flush=True)
    checked = command
    if (
        os.name == "nt"
        and Path(command[0]).suffix.lower() in {".bat", ".cmd"}
    ):
        checked = [env.get("COMSPEC", "cmd.exe"), "/d", "/c", *command]
    return subprocess.run(checked, cwd=cwd, env=env, check=False).returncode


def python_313() -> Path:
    candidates: list[Path] = []
    configured = os.environ.get("MESH_CHAT_BUILD_PYTHON")
    if configured:
        candidates.append(Path(configured))
    candidates.append(Path(sys.executable))
    for name in ("python3.13", "python3"):
        located = shutil.which(name)
        if located:
            candidates.append(Path(located))
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(Path(local_app_data) / "Programs" / "Python" / "Python313" / "python.exe")

    for candidate in candidates:
        if not candidate.is_file():
            continue
        probe = subprocess.run(
            [str(candidate), "-c", "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')"],
            capture_output=True,
            text=True,
            check=False,
        )
        if probe.returncode == 0 and probe.stdout.strip() == "3.13":
            return candidate.resolve()
    raise SystemExit(
        "Python 3.13 is required to package the embedded Android runtime. "
        "Install it or set MESH_CHAT_BUILD_PYTHON to its executable."
    )


def android_sdk() -> Path:
    """Locate an existing Android SDK without requiring shell-global setup."""
    candidates: list[Path] = []
    for variable in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        if configured := os.environ.get(variable):
            candidates.append(Path(configured))
    if local_app_data := os.environ.get("LOCALAPPDATA"):
        candidates.append(Path(local_app_data) / "Android" / "Sdk")
    candidates.extend(
        [
            Path.home() / "Library" / "Android" / "sdk",
            Path.home() / "Android" / "Sdk",
        ]
    )
    for candidate in candidates:
        if (candidate / "platform-tools").is_dir() and (candidate / "build-tools").is_dir():
            return candidate.resolve()
    raise SystemExit(
        "Android SDK not found. Install it with Android Studio or set ANDROID_HOME."
    )


def java_home() -> Path:
    """Locate the JDK used by Gradle, preferring Android Studio's bundled JBR."""
    candidates: list[Path] = []
    if configured := os.environ.get("JAVA_HOME"):
        candidates.append(Path(configured))
    for variable in ("ProgramFiles", "ProgramFiles(x86)"):
        if base := os.environ.get(variable):
            candidates.append(Path(base) / "Android" / "Android Studio" / "jbr")
    candidates.extend(
        [
            Path("/Applications/Android Studio.app/Contents/jbr/Contents/Home"),
            Path("/Applications/Android Studio.app/Contents/jre/Contents/Home"),
            Path("/opt/android-studio/jbr"),
            Path.home() / "android-studio" / "jbr",
        ]
    )
    if located := shutil.which("java"):
        candidates.append(Path(located).resolve().parent.parent)
    executable = "java.exe" if os.name == "nt" else "java"
    for candidate in candidates:
        if (candidate / "bin" / executable).is_file():
            return candidate.resolve()
    raise SystemExit(
        "Java runtime not found. Install Android Studio or set JAVA_HOME to a JDK."
    )


def patch_generated_project() -> None:
    build_file = ANDROID / "app" / "build.gradle.kts"
    text = build_file.read_text(encoding="utf-8")
    text = re.sub(r"compileSdk\s*=\s*\d+", "compileSdk = 36", text, count=1)
    text = re.sub(r"targetSdk\s*=\s*\d+", "targetSdk = 36", text, count=1)
    text = re.sub(
        r'\n\s*manifestPlaceholders\["usesCleartextTraffic"\]\s*=\s*"true"',
        "",
        text,
        count=1,
    )
    text = re.sub(
        r"\n\s*packaging\s*\{\s*\n(?:\s*jniLibs\.keepDebugSymbols\.add\([^\n]+\)\s*\n)+\s*\}",
        "",
        text,
        count=1,
    )
    write_if_changed(build_file, text)

    properties = ANDROID / "gradle.properties"
    value = properties.read_text(encoding="utf-8")
    value = value.replace("org.gradle.configuration-cache=true", "org.gradle.configuration-cache=false")
    if "org.gradle.caching=" not in value:
        value = value.rstrip() + "\norg.gradle.caching=true\n"
    write_if_changed(properties, value)

    # Tauri's generated Gradle task launches `tauri` as a package-manager
    # command. Keep that launcher portable across developer machines and CI
    # runners while still honoring the explicit release-tool override.
    build_task = (
        ANDROID
        / "buildSrc"
        / "src"
        / "main"
        / "java"
        / "com"
        / "meshchat"
        / "mobile"
        / "kotlin"
        / "BuildTask.kt"
    )
    build_task_text = build_task.read_text(encoding="utf-8")
    build_task_text, replacements = re.subn(
        r'val executable = (?:""".*?"""|System\.getenv\("MESH_CHAT_(?:NODE|PNPM)"\) \?: "(?:node|pnpm)");?',
        'val executable = System.getenv("MESH_CHAT_PNPM") ?: "pnpm"',
        build_task_text,
        count=1,
    )
    if replacements != 1:
        raise SystemExit("Could not make the generated Android Node launcher portable")
    write_if_changed(build_task, build_task_text)

    version = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["version"]
    major, minor, patch = (int(part) for part in version.split("."))
    version_code = major * 1_000_000 + minor * 1_000 + patch
    write_if_changed(
        ANDROID / "app" / "tauri.properties",
        "// THIS IS AN AUTOGENERATED FILE. DO NOT EDIT THIS FILE DIRECTLY.\n"
        f"tauri.android.versionName={version}\n"
        f"tauri.android.versionCode={version_code}\n",
    )

    # Tauri's generated activity enables edge-to-edge rendering by default.
    # Android WebView does not consistently surface those system-bar insets to
    # CSS, so keep the WebView inside the usable window on phones and tablets.
    activity = (
        ANDROID
        / "app"
        / "src"
        / "main"
        / "java"
        / "com"
        / "meshchat"
        / "mobile"
        / "MainActivity.kt"
    )
    write_if_changed(
        activity,
        """package com.meshchat.mobile

import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import androidx.core.graphics.Insets
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import com.meshchat.runtime.InvitationDocumentHost
import com.meshchat.runtime.InvitationDocumentResult

class MainActivity : TauriActivity(), InvitationDocumentHost {
  companion object {
    private const val THEME_PREFERENCES = "mesh-chat-vault"
    private const val UI_THEME = "ui-theme"
  }

  private fun applyStoredTheme() {
    val theme = getSharedPreferences(THEME_PREFERENCES, MODE_PRIVATE)
      .getString(UI_THEME, "dark")
    setTheme(if (theme == "light") R.style.Theme_mesh_chat_Light else R.style.Theme_mesh_chat)
  }

  private fun captureLaunch(intent: Intent?) {
    if (PendingInvitation.isNotification(intent)) return
    if (PendingInvitation.capture(this, intent)) {
      // Do not let activity recreation or the deep-link plugin replay a value
      // which is now durably owned by the bounded pending slot.
      setIntent(Intent(Intent.ACTION_MAIN).setPackage(packageName))
    }
  }

  override fun readInvitationDocument(uri: Uri): InvitationDocumentResult =
    PendingInvitation.readDocument(this, uri)

  override fun onCreate(savedInstanceState: Bundle?) {
    captureLaunch(intent)
    // Select the persisted native palette before Android inflates the activity
    // so the launch window and native surfaces match the WebView from frame one.
    applyStoredTheme()
    super.onCreate(savedInstanceState)

    // Android 15+ forces edge-to-edge for our target SDK. Some supported
    // WebViews predate reliable CSS safe-area values, so inset the root view
    // natively and pass only the remaining (for example, IME) insets through.
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.VANILLA_ICE_CREAM) {
      val safeTypes =
        WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout()
      ViewCompat.setOnApplyWindowInsetsListener(window.decorView) { view, windowInsets ->
        val safeInsets = windowInsets.getInsets(safeTypes)
        view.setPadding(safeInsets.left, safeInsets.top, safeInsets.right, safeInsets.bottom)
        WindowInsetsCompat.Builder(windowInsets)
          .setInsets(safeTypes, Insets.NONE)
          .build()
      }
      ViewCompat.requestApplyInsets(window.decorView)
    }
  }

  override fun onNewIntent(intent: Intent) {
    if (PendingInvitation.isNotification(intent)) {
      super.onNewIntent(intent)
      setIntent(intent)
      return
    }
    PendingInvitation.capture(this, intent)
    val sanitized = Intent(Intent.ACTION_MAIN).setPackage(packageName)
    super.onNewIntent(sanitized)
    setIntent(sanitized)
  }
}
""",
    )
    pending_invitation = activity.with_name("PendingInvitation.kt")
    write_if_changed(
        pending_invitation,
        PENDING_INVITATION_TEMPLATE.read_text(encoding="utf-8"),
    )

    # Mobile bundles do not currently copy Tauri's desktop-style `resources`
    # list into the APK. Keep the Unicode data license inside the single-file
    # sideload artifact instead of relying on a separate download.
    assets = ANDROID / "app" / "src" / "main" / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    source_notice = ROOT / "THIRD_PARTY_NOTICES.md"
    packaged_notice = assets / "THIRD_PARTY_NOTICES.md"
    if not packaged_notice.is_file() or packaged_notice.read_bytes() != source_notice.read_bytes():
        shutil.copy2(source_notice, packaged_notice)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Build Mesh Chat's Android debug APK or externally signed release artifact"
    )
    parser.add_argument(
        "--release",
        action="store_true",
        help="build a release variant; all external signing inputs are required",
    )
    parser.add_argument(
        "--aab",
        action="store_true",
        help="build an Android App Bundle (implies --release)",
    )
    args = parser.parse_args()
    release = args.release or args.aab
    artifact_format = "aab" if args.aab else "apk"
    pnpm = os.environ.get("MESH_CHAT_PNPM") or shutil.which("pnpm")
    if pnpm is None:
        raise SystemExit("pnpm is required. Install pnpm 11 and run pnpm install first.")
    build_python = python_313()
    env = os.environ.copy()
    env["MESH_CHAT_BUILD_PYTHON"] = str(build_python)
    # Tauri can locate these while compiling Rust, but the portable Windows
    # fallback invokes Gradle directly and therefore needs explicit paths.
    sdk = android_sdk()
    jdk = java_home()
    env["ANDROID_HOME"] = str(sdk)
    env["ANDROID_SDK_ROOT"] = str(sdk)
    env["JAVA_HOME"] = str(jdk)
    env["ORG_GRADLE_PROJECT_meshRuntimeAbis"] = "arm64-v8a"
    # Rust's default development profile emits large PDB/debug and incremental
    # caches even when the final artifact is an Android APK. They are not used
    # for on-device Java/Kotlin debugging and can require several extra GiB on
    # Windows, so keep the sideload build compact and reproducible.
    env.setdefault("CARGO_INCREMENTAL", "0")
    env.setdefault("CARGO_PROFILE_DEV_DEBUG", "0")
    tool_paths = [str(build_python.parent)]
    configured_node = env.get("MESH_CHAT_NODE")
    if configured_node:
        tool_paths.append(str(Path(configured_node).resolve().parent))
    for variable in ("CARGO", "RUSTC"):
        configured_tool = env.get(variable)
        if configured_tool:
            tool_paths.append(str(Path(configured_tool).resolve().parent))
    env["PATH"] = os.pathsep.join([*tool_paths, env.get("PATH", "")])

    if not (ANDROID / "gradlew").exists() and not (ANDROID / "gradlew.bat").exists():
        if run([pnpm, "tauri", "android", "init", "--ci"], env=env) != 0:
            return 1
    patch_generated_project()

    force_native = os.environ.get("MESH_CHAT_FORCE_ANDROID_NATIVE") == "1"
    requested_reuse = os.environ.get("MESH_CHAT_REUSE_ANDROID_NATIVE") == "1"
    reuse_native = not release and not force_native and native_library_is_current() and (
        requested_reuse or not symlinks_available()
    )
    result = 1
    native_library = RELEASE_NATIVE_LIBRARY if release else NATIVE_LIBRARY
    if not reuse_native:
        build_started = time.time()
        command = [pnpm, "tauri", "android", "build"]
        if not release:
            command.append("--debug")
        command.extend([f"--{artifact_format}", "--target", "aarch64"])
        if artifact_format == "apk":
            command.append("--split-per-abi")
        command.append("--ci")
        result = run(command, env=env)
        # On Windows Tauri may finish Cargo and then fail while creating its
        # convenience symlink. Capture that freshly built library so the direct
        # Gradle fallback and later builds can safely reuse it.
        if native_library.is_file() and (
            result == 0
            or native_library.stat().st_mtime >= build_started
            or _native_library_newer_than_inputs(native_library)
        ):
            record_native_library(native_library)
    else:
        print("Reusing the content-verified Android Rust library.")
    if result != 0:
        # Windows requires Developer Mode for Tauri's convenience symlink. Keep
        # the build portable by copying the completed library and invoking the
        # equivalent Gradle packaging task when symlinks are unavailable.
        if not native_library_is_current(native_library):
            print(
                "The reusable Android Rust library is missing or older than its source inputs; "
                "refusing to package a stale APK.",
                file=sys.stderr,
            )
            return result
        if build_android_frontend(pnpm, env, debug=not release) != 0:
            return 1
        destination = ANDROID / "app" / "src" / "main" / "jniLibs" / "arm64-v8a"
        stage_native_library(native_library, destination)
        wrapper = ANDROID / ("gradlew.bat" if os.name == "nt" else "gradlew")
        variant = "Release" if release else "Debug"
        result = run(
            [
                str(wrapper),
                f":app:assembleArm64{variant}",
                "-x",
                f"rustBuildArm64{variant}",
                "--no-configuration-cache",
            ],
            cwd=ANDROID,
            env=env,
        )
    if release:
        pattern = (
            "app-arm64-release.aab" if artifact_format == "aab" else "app-arm64-release.apk"
        )
        candidates = sorted((ANDROID / "app" / "build" / "outputs").rglob(pattern))
        built_artifact = candidates[-1] if candidates else None
    else:
        built_artifact = APK
    if result != 0 or built_artifact is None or not built_artifact.is_file():
        return result or 1

    try:
        manifest = publish_android_release(
            built_artifact,
            variant="release" if release else "debug",
            artifact_format=artifact_format,
        )
    except (OSError, ValueError, AndroidReleaseError) as exc:
        print(f"Android release verification failed: {exc}", file=sys.stderr)
        return 1
    version = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["version"]
    variant = "release" if release else "debug"
    output = ROOT / "dist" / "mobile" / f"mesh-chat-{version}-android-arm64-{variant}.{artifact_format}"
    print(f"{artifact_format.upper()}: {output}")
    print(f"Manifest: {manifest}")
    print(f"SHA-256: {hashlib.sha256(output.read_bytes()).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

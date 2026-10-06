from __future__ import annotations

import json
import re
from pathlib import Path


STYLES = Path(__file__).resolve().parents[2] / "src" / "styles.css"
DESKTOP_HOST = Path(__file__).resolve().parents[2] / "src-tauri" / "src" / "lib.rs"
TAURI_CONFIG = Path(__file__).resolve().parents[2] / "src-tauri" / "tauri.conf.json"
ANDROID_ACTIVITY = (
    Path(__file__).resolve().parents[2]
    / "src-tauri"
    / "gen"
    / "android"
    / "app"
    / "src"
    / "main"
    / "java"
    / "com"
    / "meshchat"
    / "mobile"
    / "MainActivity.kt"
)


def _rule(css: str, selector: str) -> str:
    match = re.search(rf"{re.escape(selector)}\s*\{{([^}}]*)\}}", css)
    assert match is not None, f"Missing {selector} rule"
    return match.group(1)


def test_conversation_layout_keeps_messages_flexible_without_optional_banner() -> None:
    css = STYLES.read_text(encoding="utf-8")
    conversation = _rule(css, ".conversation")
    assert 'grid-template-areas: "header" "banner" "messages" "composer"' in conversation
    assert "grid-template-rows: auto auto minmax(0, 1fr) auto" in conversation
    assert "grid-area: header" in _rule(css, ".conversation__header")
    assert "grid-area: banner" in _rule(css, ".connection-banner")
    assert "grid-area: messages" in _rule(css, ".message-list")
    assert "min-height: 0" in _rule(css, ".message-list")
    assert "grid-area: composer" in _rule(css, ".composer")


def test_shell_bounds_independent_conversation_and_message_scrollers() -> None:
    css = STYLES.read_text(encoding="utf-8")

    assert "min-height: 0" in _rule(css, ".app-shell")
    assert "overflow: hidden" in _rule(css, ".app-shell")
    assert "min-height: 0" in _rule(css, ".sidebar")
    assert "overflow: hidden" in _rule(css, ".sidebar")
    assert "min-height: 0" in _rule(css, ".contact-list")
    assert "overflow-y: auto" in _rule(css, ".contact-list")
    assert "overflow-y: auto" in _rule(css, ".message-list")
    assert "height: 100dvh" in css
    assert "max-height: 100dvh" in css


def test_android_webview_stays_inside_system_bars() -> None:
    source = ANDROID_ACTIVITY.read_text(encoding="utf-8")

    assert "Build.VERSION_CODES.VANILLA_ICE_CREAM" in source
    assert "WindowInsetsCompat.Type.systemBars()" in source
    assert "WindowInsetsCompat.Type.displayCutout()" in source
    assert "view.setPadding(" in source
    assert ".setInsets(safeTypes, Insets.NONE)" in source
    assert "enableEdgeToEdge" not in source


def test_desktop_window_can_reach_the_compact_layout() -> None:
    config = json.loads(TAURI_CONFIG.read_text(encoding="utf-8"))
    window = config["app"]["windows"][0]

    assert window["width"] <= 1100
    assert window["height"] <= 720
    assert window["minWidth"] <= 640
    assert window["minHeight"] <= 480


def test_desktop_close_exits_and_second_launch_restores_main_window() -> None:
    source = DESKTOP_HOST.read_text(encoding="utf-8")

    assert '.on_window_event(move |window, event|' in source
    assert 'tauri::WindowEvent::CloseRequested { api, .. }' in source
    assert 'api.prevent_close();' in source
    assert 'tauri::async_runtime::spawn(async move {' in source
    deadline = re.search(
        r"std::thread::spawn\(move \|\| \{"
        r".*?std::thread::sleep\(Duration::from_secs\(2\)\);"
        r".*?retire_service_child\(&deadline_state\);"
        r".*?deadline_app\.exit\(0\);"
        r".*?\}\);",
        source,
        flags=re.DOTALL,
    )
    assert deadline is not None
    assert "request(" not in deadline.group(0)
    assert 'let _ = request(' in source
    assert '.child\n        .try_lock()' in source
    assert 'sidecar_pid: Arc<Mutex<Option<u32>>>' in source
    assert 'terminate_windows_process_tree(pid);' in source
    assert '.join("taskkill.exe")' in source
    assert '.arg("/PID")' in source
    assert '.arg("/T")' in source
    assert '.arg("/F")' in source
    assert '.creation_flags(CREATE_NO_WINDOW)' in source
    assert 'let deadline = Instant::now() + Duration::from_secs(1);' in source
    assert 'match helper.try_wait()' in source
    assert 'let _ = helper.kill();' in source
    assert '"parent_pid": std::process::id()' in source
    assert 'app.get_webview_window("main")' in source
    assert 'tauri::WebviewWindowBuilder::from_config' in source
    assert 'let _ = window.hide();' in source
    assert 'window.show();' in source
    assert 'window.unminimize();' in source
    assert 'window.set_focus();' in source
    assert 'if matches!(event, tauri::RunEvent::Exit)' in source
    assert 'retire_service_child(&state);' in source
    assert 'std::process::exit(0);' not in source

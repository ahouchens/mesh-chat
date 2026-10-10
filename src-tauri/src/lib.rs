#[cfg(desktop)]
use base64::{engine::general_purpose::STANDARD as BASE64, Engine as _};
#[cfg(desktop)]
use rand::{rngs::OsRng, RngCore};
#[cfg(desktop)]
use serde_json::json;
use serde_json::Value;
#[cfg(desktop)]
use std::{
    collections::HashMap,
    fs,
    path::Path,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex,
    },
    time::Duration,
};
#[cfg(windows)]
use std::{
    os::windows::process::CommandExt,
    path::PathBuf,
    process::{Command, Stdio},
    time::Instant,
};
use tauri::AppHandle;
#[cfg(desktop)]
use tauri::{Emitter, Manager, State};
#[cfg(desktop)]
use tauri_plugin_shell::{
    process::{CommandChild, CommandEvent},
    ShellExt,
};
#[cfg(desktop)]
use tokio::sync::{oneshot, Mutex as AsyncMutex};

#[cfg(mobile)]
use tauri_plugin_mesh_runtime::{
    CommandRequest, InitializeRequest, MeshRuntimeExt, NativeResponse,
};

#[cfg(desktop)]
const IPC_VERSION: u64 = 1;
#[cfg(desktop)]
// Keep this limit in sync with service/src/mesh_chat/ipc.py. Responses can be
// substantially larger than renderer requests because snapshots carry message
// history and per-recipient group delivery state. The bound still prevents an
// invalid sidecar length prefix from causing an unbounded allocation.
const MAX_FRAME_BYTES: usize = 4 * 1024 * 1024;
const MAX_RENDERER_PAYLOAD_BYTES: usize = 32 * 1024;

type PendingResult = Result<Value, String>;

#[cfg(desktop)]
#[derive(Clone, Default)]
struct ServiceState {
    child: Arc<Mutex<Option<CommandChild>>>,
    sidecar_pid: Arc<Mutex<Option<u32>>>,
    pending: Arc<Mutex<HashMap<String, oneshot::Sender<PendingResult>>>>,
    start_lock: Arc<AsyncMutex<()>>,
    pending_invitation: Arc<Mutex<Option<String>>>,
    closing: Arc<AtomicBool>,
}

#[cfg(desktop)]
fn frame(value: &Value) -> Result<Vec<u8>, String> {
    let body = serde_json::to_vec(value).map_err(|_| "ipc_encode_failed".to_string())?;
    if body.is_empty() || body.len() > MAX_FRAME_BYTES {
        return Err("ipc_frame_too_large".into());
    }
    let mut framed = Vec::with_capacity(4 + body.len());
    framed.extend_from_slice(&(body.len() as u32).to_be_bytes());
    framed.extend_from_slice(&body);
    Ok(framed)
}

#[cfg(desktop)]
fn send_frame(state: &ServiceState, value: &Value) -> Result<(), String> {
    let framed = frame(value)?;
    let mut guard = state
        .child
        .lock()
        .map_err(|_| "service_lock_failed".to_string())?;
    let child = guard
        .as_mut()
        .ok_or_else(|| "service_not_running".to_string())?;
    child
        .write(&framed)
        .map_err(|_| "service_write_failed".to_string())
}

#[cfg(desktop)]
async fn request(
    state: &ServiceState,
    command: &str,
    payload: Value,
    timeout: Duration,
) -> PendingResult {
    let id = uuid::Uuid::new_v4().to_string();
    let value = json!({"v": IPC_VERSION, "id": id, "command": command, "payload": payload});
    let (sender, receiver) = oneshot::channel();
    state
        .pending
        .lock()
        .map_err(|_| "service_lock_failed".to_string())?
        .insert(id.clone(), sender);
    if let Err(error) = send_frame(state, &value) {
        if let Ok(mut pending) = state.pending.lock() {
            pending.remove(&id);
        }
        return Err(error);
    }
    match tokio::time::timeout(timeout, receiver).await {
        Ok(Ok(result)) => result,
        Ok(Err(_)) => Err("service_stopped".into()),
        Err(_) => {
            if let Ok(mut pending) = state.pending.lock() {
                pending.remove(&id);
            }
            Err("service_timeout".into())
        }
    }
}

#[cfg(desktop)]
fn handle_sidecar_value(app: &AppHandle, state: &ServiceState, value: Value) {
    if value.get("type").and_then(Value::as_str) == Some("response") {
        if let Some(id) = value.get("id").and_then(Value::as_str) {
            let sender = state.pending.lock().ok().and_then(|mut map| map.remove(id));
            if let Some(sender) = sender {
                let result = if value.get("ok").and_then(Value::as_bool) == Some(true) {
                    Ok(value.get("result").cloned().unwrap_or(Value::Null))
                } else {
                    let code = value
                        .pointer("/error/code")
                        .and_then(Value::as_str)
                        .unwrap_or("service_error");
                    Err(code.to_string())
                };
                let _ = sender.send(result);
            }
        }
    } else if value.get("type").and_then(Value::as_str) == Some("event") {
        let _ = app.emit("mesh-chat://service-event", value);
    }
}

#[cfg(desktop)]
fn consume_stdout(app: &AppHandle, state: &ServiceState, buffer: &mut Vec<u8>) -> Result<(), ()> {
    loop {
        if buffer.len() < 4 {
            return Ok(());
        }
        let size = u32::from_be_bytes(buffer[0..4].try_into().map_err(|_| ())?) as usize;
        if size < 2 || size > MAX_FRAME_BYTES {
            return Err(());
        }
        if buffer.len() < 4 + size {
            return Ok(());
        }
        let body = buffer[4..4 + size].to_vec();
        buffer.drain(0..4 + size);
        let value: Value = serde_json::from_slice(&body).map_err(|_| ())?;
        handle_sidecar_value(app, state, value);
    }
}

#[cfg(desktop)]
fn fail_all_pending(state: &ServiceState, code: &str) {
    if let Ok(mut pending) = state.pending.lock() {
        for (_, sender) in pending.drain() {
            let _ = sender.send(Err(code.to_string()));
        }
    }
}

#[cfg(desktop)]
fn take_sidecar_pid(state: &ServiceState) -> Option<u32> {
    state.sidecar_pid.lock().ok().and_then(|mut pid| pid.take())
}

#[cfg(windows)]
fn terminate_windows_process_tree(pid: u32) {
    // Use the operating-system binary directly, without cmd.exe, and target
    // only the PID recorded from CommandChild. `/T` is required because a
    // packaged Python sidecar has a PyInstaller supervisor and worker process.
    let Some(system_root) = std::env::var_os("SystemRoot") else {
        return;
    };
    let taskkill = PathBuf::from(system_root)
        .join("System32")
        .join("taskkill.exe");
    const CREATE_NO_WINDOW: u32 = 0x0800_0000;
    // Give taskkill a short, bounded opportunity to enumerate and stop the
    // complete PyInstaller tree before the direct-child fallback runs. Without
    // this ordering, killing the supervisor first can orphan its worker before
    // taskkill has enumerated the tree. The parent watchdog remains the final
    // backstop if Windows cannot start or complete this helper.
    let Ok(mut helper) = Command::new(taskkill)
        .arg("/PID")
        .arg(pid.to_string())
        .arg("/T")
        .arg("/F")
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .creation_flags(CREATE_NO_WINDOW)
        .spawn()
    else {
        return;
    };
    let deadline = Instant::now() + Duration::from_secs(1);
    loop {
        match helper.try_wait() {
            Ok(Some(_)) => break,
            Ok(None) if Instant::now() < deadline => {
                std::thread::sleep(Duration::from_millis(25));
            }
            _ => {
                let _ = helper.kill();
                break;
            }
        }
    }
}

#[cfg(desktop)]
fn retire_service_child(state: &ServiceState) {
    // PID tracking is deliberately independent from the stdin writer mutex.
    // A blocked writer must not prevent the host from retiring the exact
    // sidecar process tree during shutdown.
    let pid = take_sidecar_pid(state);
    #[cfg(windows)]
    if let Some(pid) = pid {
        terminate_windows_process_tree(pid);
    }
    #[cfg(not(windows))]
    let _ = pid;

    // Never let a synchronous pipe writer turn the retirement deadline into
    // another hang. Windows has already received an exact PID-tree kill; on
    // other desktops this remains a best-effort direct-child kill fallback.
    let child = state
        .child
        .try_lock()
        .ok()
        .and_then(|mut child| child.take());
    if let Some(child) = child {
        // This is the process-handle fallback on non-Windows desktops and also
        // covers a Windows host where taskkill could not be started.
        let _ = child.kill();
    }
    fail_all_pending(state, "service_stopped");
}

#[cfg(desktop)]
fn stored_vault_key() -> Result<String, String> {
    let entry = keyring::Entry::new("com.meshchat.desktop", "vault-key-v1")
        .map_err(|_| "credential_store_unavailable".to_string())?;
    match entry.get_password() {
        Ok(encoded) => {
            let decoded = BASE64
                .decode(encoded.as_bytes())
                .map_err(|_| "credential_store_corrupt".to_string())?;
            if decoded.len() != 32 {
                return Err("credential_store_corrupt".into());
            }
            Ok(encoded)
        }
        Err(keyring::Error::NoEntry) => {
            let mut key = [0u8; 32];
            OsRng.fill_bytes(&mut key);
            let encoded = BASE64.encode(key);
            entry
                .set_password(&encoded)
                .map_err(|_| "credential_store_unavailable".to_string())?;
            Ok(encoded)
        }
        Err(_) => Err("credential_store_unavailable".into()),
    }
}

#[cfg(desktop)]
fn spawn_service(app: &AppHandle, state: &ServiceState) -> Result<(), String> {
    let command = app
        .shell()
        .sidecar("mesh-chat-service")
        .map_err(|_| "service_binary_unavailable".to_string())?
        .set_raw_out(true);
    let (mut receiver, child) = command
        .spawn()
        .map_err(|_| "service_start_failed".to_string())?;
    let sidecar_pid = child.pid();
    *state
        .child
        .lock()
        .map_err(|_| "service_lock_failed".to_string())? = Some(child);
    *state
        .sidecar_pid
        .lock()
        .map_err(|_| "service_lock_failed".to_string())? = Some(sidecar_pid);

    let app_handle = app.clone();
    let event_state = state.clone();
    tauri::async_runtime::spawn(async move {
        let mut buffer = Vec::new();
        while let Some(event) = receiver.recv().await {
            match event {
                CommandEvent::Stdout(bytes) => {
                    buffer.extend_from_slice(&bytes);
                    if consume_stdout(&app_handle, &event_state, &mut buffer).is_err() {
                        fail_all_pending(&event_state, "service_protocol_error");
                        let _ = app_handle.emit(
                            "mesh-chat://service-event",
                            json!({"type":"event", "event":"service_error"}),
                        );
                        break;
                    }
                }
                CommandEvent::Stderr(_) => {
                    // Diagnostics are intentionally not forwarded to the renderer.
                }
                CommandEvent::Error(_) => {
                    let is_current = event_state
                        .sidecar_pid
                        .lock()
                        .ok()
                        .map(|current| *current == Some(sidecar_pid))
                        .unwrap_or(false);
                    if is_current {
                        retire_service_child(&event_state);
                        let _ = app_handle.emit(
                            "mesh-chat://service-event",
                            json!({"type":"event", "event":"service_error"}),
                        );
                    }
                    break;
                }
                CommandEvent::Terminated(_) => {
                    let is_current = event_state
                        .sidecar_pid
                        .lock()
                        .ok()
                        .map(|mut current| {
                            if *current == Some(sidecar_pid) {
                                current.take();
                                true
                            } else {
                                false
                            }
                        })
                        .unwrap_or(false);
                    if is_current {
                        fail_all_pending(&event_state, "service_stopped");
                        if let Ok(mut child) = event_state.child.lock() {
                            if child.as_ref().map(CommandChild::pid) == Some(sidecar_pid) {
                                child.take();
                            }
                        }
                        let _ = app_handle.emit(
                            "mesh-chat://service-event",
                            json!({"type":"event", "event":"service_error"}),
                        );
                    }
                    break;
                }
                _ => {}
            }
        }
    });
    Ok(())
}

fn contains_forbidden_key(value: &Value) -> bool {
    match value {
        Value::Object(map) => map.iter().any(|(key, child)| {
            matches!(
                key.as_str(),
                "path" | "profile_dir" | "vault_key" | "executable"
            ) || contains_forbidden_key(child)
        }),
        Value::Array(values) => values.iter().any(contains_forbidden_key),
        _ => false,
    }
}

fn allowed_renderer_command(command: &str) -> bool {
    matches!(
        command,
        "snapshot"
            | "workspace_snapshot"
            | "create_profile"
            | "create_invitation"
            | "preview_invitation"
            | "accept_invitation"
            | "approve_request"
            | "decline_request"
            | "send_message"
            | "set_message_reaction"
            | "save_draft"
            | "delete_conversation"
            | "restore_conversation"
            | "retry_message"
            | "verify_contact"
            | "block_contact"
            | "connection_help"
            | "search"
            | "update_settings"
            | "create_group"
            | "send_group_message"
            | "save_group_draft"
            | "accept_group_invitation"
            | "decline_group_invitation"
            | "retry_group_invitation"
            | "remove_group_member"
            | "leave_group"
            | "close_group"
            | "create_workspace"
            | "create_workspace_invitation"
            | "preview_workspace_invitation"
            | "revoke_workspace_invitation"
            | "submit_workspace_join"
            | "approve_workspace_join"
            | "decline_workspace_join"
            | "update_workspace_metadata"
            | "update_workspace_policies"
            | "update_workspace_retention"
            | "prune_workspace_history"
            | "get_workspace_history_status"
            | "start_workspace_history"
            | "cancel_workspace_history"
            | "list_workspace_history_gaps"
            | "remove_workspace_member"
            | "request_workspace_display_name"
            | "decide_workspace_display_name"
            | "create_workspace_channel"
            | "update_workspace_channel"
            | "update_workspace_private_channel_members"
            | "leave_workspace_private_channel"
            | "set_workspace_channel_subscription"
            | "offer_workspace_channel_transfer"
            | "accept_workspace_channel_transfer"
            | "recover_workspace_channel"
            | "sync_workspace_channels"
            | "send_workspace_message"
            | "open_workspace_direct"
            | "hide_workspace_direct"
            | "send_workspace_direct_message"
            | "send_workspace_thread_reply"
            | "edit_workspace_message"
            | "delete_workspace_message"
            | "set_workspace_reaction"
            | "search_workspace"
            | "list_workspace_messages"
            | "list_workspace_direct_messages"
            | "mark_workspace_read"
            | "mark_workspace_direct_read"
            | "list_workspace_mentions"
            | "list_workspace_threads"
            | "list_workspace_thread_messages"
            | "list_workspace_message_revisions"
            | "list_workspace_tombstones"
            | "mark_workspace_mentions_read"
            | "mark_workspace_thread_read"
            | "set_workspace_channel_mentions_muted"
            | "hide_workspace_message"
            | "save_workspace_draft"
            | "save_workspace_direct_draft"
            | "save_workspace_thread_draft"
            | "leave_workspace"
            | "close_workspace"
            | "remove_workspace_data"
    )
}

fn workspace_renderer_command(command: &str) -> bool {
    matches!(
        command,
        "workspace_snapshot"
            | "create_workspace"
            | "create_workspace_invitation"
            | "preview_workspace_invitation"
            | "revoke_workspace_invitation"
            | "submit_workspace_join"
            | "approve_workspace_join"
            | "decline_workspace_join"
            | "update_workspace_metadata"
            | "update_workspace_policies"
            | "update_workspace_retention"
            | "prune_workspace_history"
            | "get_workspace_history_status"
            | "start_workspace_history"
            | "cancel_workspace_history"
            | "list_workspace_history_gaps"
            | "remove_workspace_member"
            | "request_workspace_display_name"
            | "decide_workspace_display_name"
            | "create_workspace_channel"
            | "update_workspace_channel"
            | "update_workspace_private_channel_members"
            | "leave_workspace_private_channel"
            | "set_workspace_channel_subscription"
            | "offer_workspace_channel_transfer"
            | "accept_workspace_channel_transfer"
            | "recover_workspace_channel"
            | "sync_workspace_channels"
            | "send_workspace_message"
            | "open_workspace_direct"
            | "hide_workspace_direct"
            | "send_workspace_direct_message"
            | "send_workspace_thread_reply"
            | "edit_workspace_message"
            | "delete_workspace_message"
            | "set_workspace_reaction"
            | "search_workspace"
            | "list_workspace_messages"
            | "list_workspace_direct_messages"
            | "mark_workspace_read"
            | "mark_workspace_direct_read"
            | "list_workspace_mentions"
            | "list_workspace_threads"
            | "list_workspace_thread_messages"
            | "list_workspace_message_revisions"
            | "list_workspace_tombstones"
            | "mark_workspace_mentions_read"
            | "mark_workspace_thread_read"
            | "set_workspace_channel_mentions_muted"
            | "hide_workspace_message"
            | "save_workspace_draft"
            | "save_workspace_direct_draft"
            | "save_workspace_thread_draft"
            | "leave_workspace"
            | "close_workspace"
            | "remove_workspace_data"
    )
}

#[cfg(desktop)]
fn invitation_from_argument(argument: &str) -> Option<String> {
    if (argument.starts_with("meshchat://invite/") || argument.starts_with("meshchat://workspace/"))
        && argument.len() <= 24 * 1024
    {
        return Some(argument.to_string());
    }
    let path = Path::new(argument);
    if path.extension().and_then(|value| value.to_str()) != Some("meshchat") {
        return None;
    }
    let metadata = fs::metadata(path).ok()?;
    if !metadata.is_file() || metadata.len() > 16 * 1024 {
        return None;
    }
    let contents = fs::read_to_string(path).ok()?;
    if contents.len() <= 16 * 1024 {
        Some(contents)
    } else {
        None
    }
}

#[cfg(desktop)]
fn remember_invitation(state: &ServiceState, argument: &str) -> Option<String> {
    let invitation = invitation_from_argument(argument)?;
    if let Ok(mut pending) = state.pending_invitation.lock() {
        *pending = Some(invitation.clone());
    }
    Some(invitation)
}

#[cfg(desktop)]
fn restore_main_window(app: &AppHandle) {
    let window = app.get_webview_window("main").or_else(|| {
        let config = app
            .config()
            .app
            .windows
            .iter()
            .find(|config| config.label == "main")?
            .clone();
        tauri::WebviewWindowBuilder::from_config(app, &config)
            .ok()?
            .build()
            .ok()
    });
    if let Some(window) = window {
        // Force the native window through a known visible state. This also
        // recovers a Windows HWND hidden outside Tauri's cached visibility
        // state, while the builder above recreates a window that was destroyed.
        let _ = window.hide();
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

#[cfg(desktop)]
#[tauri::command]
async fn initialize_service(
    app: AppHandle,
    state: State<'_, ServiceState>,
    display_name: Option<String>,
) -> PendingResult {
    let _guard = state.start_lock.lock().await;
    if state
        .child
        .lock()
        .map_err(|_| "service_lock_failed".to_string())?
        .is_none()
    {
        let vault_key = stored_vault_key()?;
        let profile_dir = app
            .path()
            .app_data_dir()
            .map_err(|_| "profile_path_unavailable".to_string())?
            .join("profile-v1");
        spawn_service(&app, &state)?;
        let initialized = request(
            &state,
            "initialize",
            json!({
                "profile_dir": profile_dir.to_string_lossy(),
                "vault_key": vault_key,
                "display_name": display_name,
                "parent_pid": std::process::id(),
            }),
            Duration::from_secs(30),
        )
        .await;
        if initialized.is_err() {
            retire_service_child(&state);
        }
        initialized
    } else {
        request(&state, "snapshot", json!({}), Duration::from_secs(10)).await
    }
}

#[cfg(desktop)]
#[tauri::command]
async fn service_command(
    state: State<'_, ServiceState>,
    command: String,
    payload: Value,
) -> PendingResult {
    if !allowed_renderer_command(&command) {
        return Err("command_not_allowed".into());
    }
    let size = serde_json::to_vec(&payload)
        .map_err(|_| "invalid_request".to_string())?
        .len();
    if size > MAX_RENDERER_PAYLOAD_BYTES || contains_forbidden_key(&payload) {
        return Err("invalid_request".into());
    }
    request(&state, &command, payload, Duration::from_secs(20)).await
}

#[cfg(desktop)]
#[tauri::command]
async fn lock_service(state: State<'_, ServiceState>) -> Result<(), String> {
    let shutdown = request(&state, "shutdown", json!({}), Duration::from_secs(2)).await;
    tokio::time::sleep(Duration::from_millis(250)).await;
    retire_service_child(&state);
    shutdown.map(|_| ())
}

#[cfg(desktop)]
#[tauri::command]
fn take_pending_invitation(state: State<'_, ServiceState>) -> Result<Option<String>, String> {
    state
        .pending_invitation
        .lock()
        .map_err(|_| "service_lock_failed".to_string())
        .map(|mut pending| pending.take())
}

#[cfg(mobile)]
fn mobile_result(response: NativeResponse) -> PendingResult {
    let value: Value =
        serde_json::from_str(&response.json).map_err(|_| "service_protocol_error".to_string())?;
    if value.get("ok").and_then(Value::as_bool) == Some(true) {
        Ok(value.get("result").cloned().unwrap_or(Value::Null))
    } else {
        Err(value
            .pointer("/error/code")
            .and_then(Value::as_str)
            .unwrap_or("service_error")
            .to_string())
    }
}

#[cfg(mobile)]
#[tauri::command]
async fn initialize_service(app: AppHandle, display_name: Option<String>) -> PendingResult {
    let response = app
        .mesh_runtime()
        .initialize(InitializeRequest { display_name })
        .map_err(|_| "service_start_failed".to_string())?;
    mobile_result(response)
}

#[cfg(mobile)]
#[tauri::command]
async fn service_command(app: AppHandle, command: String, payload: Value) -> PendingResult {
    if !allowed_renderer_command(&command) {
        return Err("command_not_allowed".into());
    }
    if workspace_renderer_command(&command) {
        return Err("workspace_desktop_only".into());
    }
    let size = serde_json::to_vec(&payload)
        .map_err(|_| "invalid_request".to_string())?
        .len();
    if size > MAX_RENDERER_PAYLOAD_BYTES || contains_forbidden_key(&payload) {
        return Err("invalid_request".into());
    }
    let response = app
        .mesh_runtime()
        .command(CommandRequest { command, payload })
        .map_err(|_| "service_write_failed".to_string())?;
    mobile_result(response)
}

#[cfg(mobile)]
#[tauri::command]
async fn lock_service(app: AppHandle) -> Result<(), String> {
    let response = app
        .mesh_runtime()
        .shutdown()
        .map_err(|_| "service_stopped".to_string())?;
    mobile_result(response).map(|_| ())
}

#[cfg(mobile)]
#[tauri::command]
fn take_pending_invitation() -> Result<Option<String>, String> {
    Ok(None)
}

#[cfg(mobile)]
#[tauri::command]
fn poll_mobile_events(app: AppHandle) -> Result<Vec<Value>, String> {
    let response = app
        .mesh_runtime()
        .drain_events()
        .map_err(|_| "service_stopped".to_string())?;
    let value = mobile_result(response)?;
    serde_json::from_value(value).map_err(|_| "service_protocol_error".to_string())
}

#[cfg(desktop)]
#[tauri::command]
fn poll_mobile_events() -> Result<Vec<Value>, String> {
    Ok(Vec::new())
}

#[tauri::command]
fn runtime_platform() -> &'static str {
    #[cfg(target_os = "android")]
    return "android";
    #[cfg(target_os = "ios")]
    return "ios";
    #[cfg(desktop)]
    return "desktop";
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    #[cfg(desktop)]
    let state = ServiceState::default();
    #[cfg(desktop)]
    for argument in std::env::args().skip(1) {
        remember_invitation(&state, &argument);
    }
    #[cfg(desktop)]
    let instance_state = state.clone();

    let builder = tauri::Builder::default();
    #[cfg(desktop)]
    let builder = builder
        // Must be first so a second desktop launch forwards deep links.
        .plugin(tauri_plugin_single_instance::init(
            move |app, argv, _cwd| {
                for argument in argv {
                    if let Some(invitation) = remember_invitation(&instance_state, &argument) {
                        let _ = app.emit("mesh-chat://invitation", invitation);
                    }
                }
                restore_main_window(app);
            },
        ));
    let builder = builder.plugin(tauri_plugin_deep_link::init());
    #[cfg(desktop)]
    let builder = builder
        .plugin(tauri_plugin_shell::init())
        .manage(state.clone());
    #[cfg(desktop)]
    let close_state = state.clone();
    #[cfg(desktop)]
    let builder = builder.on_window_event(move |window, event| {
        if window.label() == "main" {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
                if close_state.closing.swap(true, Ordering::AcqRel) {
                    return;
                }

                // This operating-system thread is the definitive deadline. It
                // is independent of request(), whose synchronous stdin write
                // could itself be blocked by an unhealthy sidecar.
                let deadline_app = window.app_handle().clone();
                let deadline_state = close_state.clone();
                std::thread::spawn(move || {
                    std::thread::sleep(Duration::from_secs(2));
                    retire_service_child(&deadline_state);
                    deadline_app.exit(0);
                });

                // Ask for a clean service shutdown separately. Success is not
                // required for the deadline thread above to retire the PID.
                let shutdown_state = close_state.clone();
                tauri::async_runtime::spawn(async move {
                    let _ = request(
                        &shutdown_state,
                        "shutdown",
                        json!({}),
                        Duration::from_millis(1_250),
                    )
                    .await;
                });
            }
        }
    });
    #[cfg(mobile)]
    let builder = builder
        .plugin(tauri_plugin_barcode_scanner::init())
        .plugin(tauri_plugin_mesh_runtime::init());

    builder
        .invoke_handler(tauri::generate_handler![
            initialize_service,
            service_command,
            lock_service,
            take_pending_invitation,
            poll_mobile_events,
            runtime_platform
        ])
        .setup(|_app| {
            #[cfg(any(target_os = "linux", all(debug_assertions, windows)))]
            {
                use tauri_plugin_deep_link::DeepLinkExt;
                _app.deep_link().register_all()?;
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to build Mesh Chat")
        .run(move |_app, event| {
            #[cfg(desktop)]
            if matches!(event, tauri::RunEvent::Exit) {
                // The normal window-close path retires the sidecar before
                // requesting app exit. Keep this idempotent fallback for other
                // platform exit paths such as operating-system shutdown.
                retire_service_child(&state);
            }
            #[cfg(mobile)]
            let _ = event;
        });
}

#[cfg(all(test, desktop))]
mod tests {
    use super::*;

    #[test]
    fn frame_supports_snapshot_larger_than_legacy_limit() {
        let value = json!({
            "type": "response",
            "result": {"messages": [{"text": "x".repeat(128 * 1024)}]},
        });

        let encoded = frame(&value).expect("large bounded snapshot should encode");
        assert!(encoded.len() > 64 * 1024);
        let declared = u32::from_be_bytes(encoded[0..4].try_into().unwrap()) as usize;
        assert_eq!(declared, encoded.len() - 4);
    }

    #[test]
    fn frame_rejects_values_above_the_explicit_upper_bound() {
        let value = json!({"payload": "x".repeat(MAX_FRAME_BYTES)});
        assert_eq!(frame(&value), Err("ipc_frame_too_large".to_string()));
    }

    #[test]
    fn sidecar_pid_tracking_does_not_depend_on_the_writer_mutex() {
        let state = ServiceState::default();
        *state.sidecar_pid.lock().unwrap() = Some(4_242);
        let guard = state.child.lock().unwrap();
        assert_eq!(take_sidecar_pid(&state), Some(4_242));
        assert_eq!(take_sidecar_pid(&state), None);
        drop(guard);
    }

    #[test]
    fn renderer_can_delete_and_restore_local_conversations() {
        assert!(allowed_renderer_command("delete_conversation"));
        assert!(allowed_renderer_command("restore_conversation"));
        assert!(allowed_renderer_command("set_message_reaction"));
        assert!(!allowed_renderer_command("delete_contact_identity"));
    }

    #[test]
    fn renderer_workspace_commands_are_desktop_scoped() {
        let commands = [
            "workspace_snapshot",
            "create_workspace",
            "create_workspace_invitation",
            "preview_workspace_invitation",
            "revoke_workspace_invitation",
            "submit_workspace_join",
            "approve_workspace_join",
            "decline_workspace_join",
            "update_workspace_metadata",
            "update_workspace_policies",
            "update_workspace_retention",
            "prune_workspace_history",
            "get_workspace_history_status",
            "start_workspace_history",
            "cancel_workspace_history",
            "list_workspace_history_gaps",
            "remove_workspace_member",
            "request_workspace_display_name",
            "decide_workspace_display_name",
            "create_workspace_channel",
            "update_workspace_channel",
            "update_workspace_private_channel_members",
            "leave_workspace_private_channel",
            "set_workspace_channel_subscription",
            "offer_workspace_channel_transfer",
            "accept_workspace_channel_transfer",
            "recover_workspace_channel",
            "sync_workspace_channels",
            "send_workspace_message",
            "open_workspace_direct",
            "hide_workspace_direct",
            "send_workspace_direct_message",
            "send_workspace_thread_reply",
            "edit_workspace_message",
            "delete_workspace_message",
            "set_workspace_reaction",
            "search_workspace",
            "list_workspace_messages",
            "list_workspace_direct_messages",
            "mark_workspace_read",
            "mark_workspace_direct_read",
            "list_workspace_mentions",
            "list_workspace_threads",
            "list_workspace_thread_messages",
            "list_workspace_message_revisions",
            "list_workspace_tombstones",
            "mark_workspace_mentions_read",
            "mark_workspace_thread_read",
            "set_workspace_channel_mentions_muted",
            "hide_workspace_message",
            "save_workspace_draft",
            "save_workspace_direct_draft",
            "save_workspace_thread_draft",
            "leave_workspace",
            "close_workspace",
            "remove_workspace_data",
        ];
        for command in commands {
            assert!(allowed_renderer_command(command));
            assert!(workspace_renderer_command(command));
        }
        assert!(!workspace_renderer_command("send_message"));
    }

    #[test]
    fn desktop_accepts_workspace_deep_links() {
        let link = "meshchat://workspace/fixture-token";
        assert_eq!(invitation_from_argument(link), Some(link.to_string()));
    }
}

#[cfg(desktop)]
use base64::{engine::general_purpose::STANDARD as BASE64, Engine as _};
#[cfg(desktop)]
use rand::{rngs::OsRng, RngCore};
#[cfg(desktop)]
use serde_json::json;
use serde_json::Value;
mod direct_native;
#[cfg(desktop)]
mod desktop_transport;
#[cfg(desktop)]
mod desktop_transport_broker;
#[cfg(all(windows, feature = "transport-qualification"))]
mod desktop_transport_qualification;
#[cfg(all(windows, feature = "transport-qualification"))]
mod packaged_transport_qualification;
#[cfg(all(windows, feature = "transport-qualification"))]
pub use desktop_transport_qualification::run as run_desktop_transport_qualification;
#[cfg(desktop)]
mod service_diagnostics;
#[cfg(target_os = "android")]
mod mobile_direct;
#[cfg(desktop)]
use std::{
    collections::HashMap,
    fs,
    path::Path,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex,
    },
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};
#[cfg(windows)]
use std::{
    os::windows::process::CommandExt,
    path::PathBuf,
    process::{Command, Stdio},
};
use tauri::AppHandle;
#[cfg(desktop)]
use tauri::{Emitter, Manager, State};
use tauri::path::BaseDirectory;
#[cfg(desktop)]
use tauri_plugin_shell::{
    process::{CommandChild, CommandEvent},
    ShellExt,
};
#[cfg(desktop)]
use tokio::sync::{oneshot, Mutex as AsyncMutex};

#[cfg(mobile)]
use tauri_plugin_mesh_runtime::{
    CommandRequest, InitializeRequest, MeshRuntimeExt, NativeResponse, ThemeRequest,
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
// Answer verification carries both signed documents, and answer creation
// carries the offer plus a 32 KiB SDP. Include nested JSON escaping while
// keeping the service's per-document and SDP validation bounds in force.
const MAX_WEBRTC_SIGNALING_PAYLOAD_BYTES: usize = 128 * 1024;
const MAX_DIRECT_DOCUMENT_PAYLOAD_BYTES: usize = 2 * 1024 * 1024;
const MAX_CONNECTION_RESPONSE_PAYLOAD_BYTES: usize = 40 * 1024;
const MAX_ROUTE_UPDATE_PAYLOAD_BYTES: usize = 24 * 1024;
const MAX_WORKSPACE_INVITATION_PAYLOAD_BYTES: usize = 600 * 1024;
const MAX_WORKSPACE_DEVICE_LINK_PAYLOAD_BYTES: usize = 700 * 1024;

type PendingResult = Result<Value, String>;

fn renderer_payload_maximum(command: &str) -> usize {
    if command == "receive_contact_invitation" {
        64 * 1024
    } else if matches!(
        command,
        "preview_direct_connection"
            | "prepare_direct_answer"
            | "prepare_direct_ready"
            | "accept_direct_ready"
            | "connect_direct_setup"
    ) {
        MAX_DIRECT_DOCUMENT_PAYLOAD_BYTES
    } else if matches!(
        command,
        "preview_workspace_device_link" | "submit_workspace_device_link"
    ) {
        MAX_WORKSPACE_DEVICE_LINK_PAYLOAD_BYTES
    } else if matches!(
        command,
        "preview_workspace_invitation" | "submit_workspace_join" | "create_connection_reply"
    ) {
        MAX_WORKSPACE_INVITATION_PAYLOAD_BYTES
    } else if matches!(command, "preview_connection_reply" | "connect_using_reply") {
        MAX_CONNECTION_RESPONSE_PAYLOAD_BYTES + 1024
    } else if matches!(command, "preview_route_update" | "apply_route_update") {
        MAX_ROUTE_UPDATE_PAYLOAD_BYTES + 1024
    } else if matches!(
        command,
        "webrtc_onboarding_offer"
            | "verify_webrtc_onboarding_offer"
            | "webrtc_onboarding_answer"
            | "verify_webrtc_onboarding_answer"
            | "native_webrtc_offer"
            | "native_webrtc_accept"
            | "native_webrtc_apply_answer"
            | "native_webrtc_bind_onboarding"
            | "signal_publish"
            | "reconnect_offer_create"
            | "reconnect_answer_create"
            | "verify_reconnect_offer"
            | "verify_reconnect_answer"
            | "reconnect_publish"
            | "start_call"
            | "answer_call"
            | "restart_call"
            | "answer_call_restart"
    ) {
        MAX_WEBRTC_SIGNALING_PAYLOAD_BYTES
    } else {
        MAX_RENDERER_PAYLOAD_BYTES
    }
}

#[cfg(desktop)]
#[derive(Clone, Default)]
struct ServiceState {
    desktop_transport: Arc<Mutex<Option<desktop_transport::RegisteredHost>>>,
    direct_native: Arc<Mutex<Option<direct_native::NativeHost>>>,
    child: Arc<Mutex<Option<CommandChild>>>,
    sidecar_pid: Arc<Mutex<Option<u32>>>,
    pending: Arc<Mutex<HashMap<String, oneshot::Sender<PendingResult>>>>,
    start_lock: Arc<AsyncMutex<()>>,
    pending_invitation: Arc<Mutex<Option<String>>>,
    closing: Arc<AtomicBool>,
    locked: Arc<AtomicBool>,
    last_unexpected_exit: Arc<Mutex<Option<Value>>>,
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
fn handle_sidecar_value(
    app: &AppHandle,
    state: &ServiceState,
    native: &direct_native::NativeHost,
    pid: u32,
    value: Value,
) {
    if route_sidecar_value(app, state, native, pid, value).is_err() {
        retire_service_process(state, Some(pid));
    }
}

#[cfg(desktop)]
fn route_sidecar_value(
    app: &AppHandle,
    state: &ServiceState,
    native: &direct_native::NativeHost,
    pid: u32,
    value: Value,
) -> Result<(), String> {
    if value.get("type").and_then(Value::as_str) == Some("desktop_transport") {
        return desktop_transport::admit(state, pid, value);
    }
    if value.get("type").and_then(Value::as_str) == Some("direct_native") {
        let response = native.handle(value);
        if let Ok(frame) = frame(&response) {
            if let Ok(mut child) = state.child.lock() {
                if let Some(child) = child.as_mut().filter(|child| child.pid() == pid) {
                    if child.write(&frame).is_ok() {
                        return Ok(());
                    }
                }
            }
        }
        native.close();
        return Ok(());
    }
    if value.get("type").and_then(Value::as_str) == Some("response") {
        if let Some(id) = value.get("id").and_then(Value::as_str) {
            let sender = state.pending.lock().ok().and_then(|mut map| map.remove(id));
            if let Some(sender) = sender {
                let result = if value.get("ok").and_then(Value::as_bool) == Some(true) {
                    Ok(value.get("result").cloned().unwrap_or(Value::Null))
                } else {
                    let error = value
                        .get("error")
                        .cloned()
                        .unwrap_or_else(|| serde_json::json!({"code": "service_error"}));
                    if error.get("details").is_some() {
                        Err(error.to_string())
                    } else {
                        Err(error
                            .get("code")
                            .and_then(Value::as_str)
                            .unwrap_or("service_error")
                            .to_string())
                    }
                };
                let _ = sender.send(result);
            }
        }
    } else if value.get("type").and_then(Value::as_str) == Some("event") {
        let _ = app.emit("mesh-chat://service-event", value);
    }
    Ok(())
}

#[cfg(desktop)]
fn consume_stdout(
    app: &AppHandle,
    state: &ServiceState,
    native: &direct_native::NativeHost,
    pid: u32,
    buffer: &mut Vec<u8>,
) -> Result<(), ()> {
    consume_frames(buffer, |value| handle_sidecar_value(app, state, native, pid, value))
}

#[cfg(desktop)]
fn consume_frames(buffer: &mut Vec<u8>, mut consume: impl FnMut(Value)) -> Result<(), ()> {
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
        consume(value);
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
fn record_unexpected_service_exit(
    app: &AppHandle,
    state: &ServiceState,
    reason: &str,
    exit_code: Option<i32>,
    signal: Option<i32>,
    evidence: Value,
    uptime_ms: u64,
) {
    if state.closing.load(Ordering::Acquire) || state.locked.load(Ordering::Acquire) {
        return;
    }
    let recorded_at = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .ok()
        .map(|elapsed| elapsed.as_secs());
    let mut record = json!({
            "reason": reason,
            "exit_code": exit_code,
            "signal": signal,
            "recorded_at": recorded_at,
            "native_version": env!("CARGO_PKG_VERSION"),
            "build_commit": env!("MESH_BUILD_COMMIT"),
            "uptime_ms": uptime_ms,
            "pending_requests": state.pending.lock().ok().map(|pending| pending.len()),
            "from_previous_app_run": false,
        });
    if let (Some(record), Some(evidence)) = (record.as_object_mut(), evidence.as_object()) {
        record.extend(evidence.clone());
    }
    if let Ok(mut last) = state.last_unexpected_exit.lock() {
        *last = Some(record.clone());
    }
    // Persist only the last sanitized exit, so closing/reopening the app does
    // not erase the evidence. No stderr text, request bodies or paths are saved.
    if let Ok(directory) = app.path().app_data_dir() {
        if fs::create_dir_all(&directory).is_ok() {
            if let Ok(bytes) = serde_json::to_vec(&record) {
                if bytes.len() <= 16_384 { let _ = fs::write(directory.join("service-exit-diagnostics.json"), bytes); }
            }
        }
    }
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
struct DetachedService {
    pid: u32,
    process_present: bool,
    child: Option<CommandChild>,
    native: Option<direct_native::NativeHost>,
    transport: Option<desktop_transport::RegisteredHost>,
}

#[cfg(desktop)]
impl DetachedService {
    fn dispose(self, terminate: bool) {
        if let Some(host) = self.transport {
            host.close();
        }
        if let Some(native) = self.native {
            native.close();
        }
        if terminate && self.process_present {
            #[cfg(windows)]
            terminate_windows_process_tree(self.pid);
            if let Some(child) = self.child {
                let _ = child.kill();
            }
        }
    }
}

#[cfg(desktop)]
fn detach_service(state: &ServiceState, expected_pid: Option<u32>) -> Option<DetachedService> {
    detach_service_with_transport(state, expected_pid, false)
}

#[cfg(desktop)]
fn detach_service_with_transport(state: &ServiceState, expected_pid: Option<u32>, preserve_transport: bool) -> Option<DetachedService> {
    // This guard also protects publication in spawn_service. Detach everything
    // before permitting a replacement, then dispose only the captured resources.
    // Never wait for the stdin writer while holding the lifecycle guard.
    let mut current = state.sidecar_pid.lock().ok()?;
    let pid = match (*current).filter(|pid| expected_pid.is_none_or(|expected| *pid == expected)) {
        Some(pid) => pid,
        None if current.is_none() && expected_pid.is_none() => {
            // Explicit lock/exit must also dispose a host retained after a crash.
            // Never terminate a recycled OS PID belonging to that dead service.
            let transport = desktop_transport::detach(state, None)?;
            return Some(DetachedService { pid: transport.pid(), process_present: false,
                child: None, native: None, transport: Some(transport) });
        }
        None => return None,
    };
    current.take();
    let transport = if preserve_transport && desktop_transport::suspend(state, pid) { None }
                    else { desktop_transport::detach(state, Some(pid)) };
    let native = state.direct_native.lock().ok().and_then(|mut host| host.take());
    let child = state
        .child
        .try_lock()
        .ok()
        .and_then(|mut child| {
            if child.as_ref().is_some_and(|child| child.pid() == pid) { child.take() }
            else { None }
        });
    fail_all_pending(state, "service_stopped");
    Some(DetachedService { pid, process_present: true, child, native, transport })
}

#[cfg(desktop)]
fn retire_service_process(state: &ServiceState, expected_pid: Option<u32>) {
    if let Some(retired) = detach_service(state, expected_pid) {
        let pid = retired.pid;
        let process_present = retired.process_present;
        retired.dispose(true);
        if !process_present { return; }
        // A writer may have held the child handle during detachment. Reap only
        // that handle after process termination releases its pipe; never hold up
        // the shutdown deadline or take a replacement's handle.
        let child = state.child.clone();
        std::thread::spawn(move || {
            if let Ok(mut child) = child.lock() {
                if child.as_ref().is_some_and(|child| child.pid() == pid) {
                    child.take();
                }
            }
        });
    }
}

#[cfg(desktop)]
fn retire_service_child(state: &ServiceState) {
    retire_service_process(state, None);
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
    let mut command = command;
    #[cfg(all(windows, feature = "experimental-shared-webview"))]
    { command = command.args(["--shared-webview"]); }
    let i2pd = [
        "i2pd.exe",
        "vendor/i2pd.exe",
        "_up_/vendor/i2pd.exe",
    ]
    .iter()
    .find_map(|name| {
        app.path()
            .resolve(name, BaseDirectory::Resource)
            .ok()
            .filter(|path| path.is_file())
    });
    if let Some(i2pd) = i2pd {
        command = command.env("MESH_CHAT_I2PD_PATH", i2pd.to_string_lossy().to_string());
    }
    let (mut receiver, child) = command
        .spawn()
        .map_err(|_| "service_start_failed".to_string())?;
    let sidecar_pid = child.pid();
    let native = direct_native::NativeHost::default();
    // Acquire the potentially busy writer before the lifecycle guard. Retirement
    // uses try_lock for this handle and can always reach the exact PID-tree kill.
    let mut writer = state.child.lock().map_err(|_| "service_lock_failed".to_string())?;
    let mut process = state.sidecar_pid.lock().map_err(|_| "service_lock_failed".to_string())?;
    let previous_native = state.direct_native.lock().ok().and_then(|mut current| current.replace(native.clone()));
    *writer = Some(child);
    *process = Some(sidecar_pid);
    drop(process);
    drop(writer);
    if let Some(old) = previous_native { old.close(); }

    #[cfg(all(windows, feature = "experimental-shared-webview"))]
    if let Err(error) = desktop_transport::register(app, state, sidecar_pid) {
        retire_service_process(state, Some(sidecar_pid));
        return Err(error);
    }

    let app_handle = app.clone();
    let event_state = state.clone();
    tauri::async_runtime::spawn(async move {
        let mut buffer = Vec::new();
        let mut stderr = service_diagnostics::Capture::default();
        let started = Instant::now();
        while let Some(event) = receiver.recv().await {
            match event {
                CommandEvent::Stdout(bytes) => {
                    if event_state
                        .sidecar_pid
                        .lock()
                        .ok()
                        .is_none_or(|pid| *pid != Some(sidecar_pid))
                    {
                        break;
                    }
                    buffer.extend_from_slice(&bytes);
                    if consume_stdout(&app_handle, &event_state, &native, sidecar_pid, &mut buffer)
                        .is_err()
                    {
                        let is_current = event_state
                            .sidecar_pid
                            .lock()
                            .ok()
                            .is_some_and(|pid| *pid == Some(sidecar_pid));
                        if is_current {
                            record_unexpected_service_exit(&app_handle, &event_state, "protocol_error", None, None, stderr.finish(), started.elapsed().as_millis() as u64);
                            retire_service_process(&event_state, Some(sidecar_pid));
                            let _ = app_handle.emit(
                                "mesh-chat://service-event",
                                json!({"type":"event", "event":"service_error"}),
                            );
                        }
                        break;
                    }
                }
                CommandEvent::Stderr(bytes) => stderr.push(&bytes),
                CommandEvent::Error(_) => {
                    let is_current = event_state
                        .sidecar_pid
                        .lock()
                        .ok()
                        .map(|current| *current == Some(sidecar_pid))
                        .unwrap_or(false);
                    if is_current {
                        record_unexpected_service_exit(&app_handle, &event_state, "process_event_error", None, None, stderr.finish(), started.elapsed().as_millis() as u64);
                        retire_service_process(&event_state, Some(sidecar_pid));
                        let _ = app_handle.emit(
                            "mesh-chat://service-event",
                            json!({"type":"event", "event":"service_error"}),
                        );
                    }
                    break;
                }
                CommandEvent::Terminated(exit) => {
                    if let Some(retired) = detach_service_with_transport(&event_state, Some(sidecar_pid), true) {
                        retired.dispose(false);
                        record_unexpected_service_exit(&app_handle, &event_state, "terminated", exit.code, exit.signal, stderr.finish(), started.elapsed().as_millis() as u64);
                        let _ = app_handle.emit(
                            "mesh-chat://service-event",
                            json!({"type":"event", "event":"service_error"}),
                        );
                    }
                    native.close();
                    return;
                }
                _ => {}
            }
        }
        native.close();
        desktop_transport::retire(&event_state, Some(sidecar_pid), false);
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
            | "i2p_status"
            | "workspace_snapshot"
            | "create_profile"
            | "create_invitation"
            | "preview_invitation"
            | "accept_invitation"
            | "receive_contact_invitation"
            | "decide_contact_invitation"
            | "create_connection_reply"
            | "preview_connection_reply"
            | "connect_using_reply"
            | "create_route_update"
            | "preview_route_update"
            | "apply_route_update"
            | "preview_remote_profile"
            | "create_manual_remote_profile"
            | "approve_remote_profile"
            | "test_remote_profile"
            | "list_remote_profiles"
            | "retry_remote_profile"
            | "remove_remote_profile"
            | "approve_remote_propagation"
            | "remove_remote_propagation"
            | "check_direct_connection"
            | "prepare_manual_participant_host"
            | "configure_participant_firewall"
            | "stop_participant_host"
            | "approve_request"
            | "decline_request"
            | "send_message"
            | "start_call"
            | "answer_call"
            | "add_call_candidate"
            | "end_call"
            | "call_media"
            | "restart_call"
            | "answer_call_restart"
            | "call_settings"
            | "update_call_settings"
            | "call_ice_servers"
            | "link_preview"
            | "signal_publish"
            | "signal_fetch"
            | "reconnect_profiles"
            | "reconnect_consent_set"
            | "reconnect_capabilities_create"
            | "reconnect_capabilities_store"
            | "reconnect_capabilities_get"
            | "reconnect_replay_check"
            | "reconnect_status"
            | "reconnect_start"
            | "reconnect_stop"
            | "reconnect_request_create"
            | "reconnect_offer_create"
            | "reconnect_answer_create"
            | "reconnect_publish"
            | "reconnect_fetch"
            | "reconnect_path_status"
            | "verify_reconnect_request"
            | "verify_reconnect_offer"
            | "verify_reconnect_answer"
            | "webrtc_attach"
            | "webrtc_packet"
            | "webrtc_detach"
            | "native_webrtc_offer"
            | "native_webrtc_accept"
            | "native_webrtc_apply_answer"
            | "native_webrtc_control"
            | "native_webrtc_close"
            | "native_webrtc_stats"
            | "native_webrtc_bind_onboarding"
            | "webrtc_onboarding_offer"
            | "webrtc_onboarding_answer"
            | "verify_webrtc_onboarding_offer"
            | "verify_webrtc_onboarding_answer"
            | "set_message_reaction"
            | "save_draft"
            | "delete_conversation"
            | "restore_conversation"
            | "retry_message"
            | "verify_contact"
            | "unverify_contact"
            | "unblock_contact"
            | "block_contact"
            | "update_contact"
            | "rename_contact"
            | "delete_contact"
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
            | "invite_contact_to_workspace"
            | "dismiss_workspace_invitation_prompt"
            | "preview_workspace_invitation_prompt"
            | "submit_workspace_invitation_prompt"
            | "preview_workspace_invitation"
            | "preview_direct_connection"
            | "prepare_direct_offer"
            | "prepare_direct_answer"
            | "prepare_direct_ready"
            | "accept_direct_ready"
            | "connect_direct_setup"
            | "configure_direct_firewall"
            | "direct_recovery_status"
            | "export_recovery_update"
            | "import_recovery_update"
            | "pause_direct_recovery"
            | "resume_direct_recovery"
            | "direct_setup_status"
            | "resume_direct_setup"
            | "check_direct_setup"
            | "retry_direct_setup"
            | "connection_diagnostics"
            | "clear_connection_diagnostics"
            | "cancel_direct_setup"
            | "revoke_workspace_invitation"
            | "submit_workspace_join"
            | "approve_workspace_join"
            | "decline_workspace_join"
            | "create_workspace_device_link"
            | "preview_workspace_device_link"
            | "submit_workspace_device_link"
            | "approve_workspace_device_link"
            | "decline_workspace_device_link"
            | "request_workspace_device_removal"
            | "approve_workspace_device_removal"
            | "decline_workspace_device_removal"
            | "update_workspace_metadata"
            | "update_workspace_policies"
            | "update_workspace_retention"
            | "prune_workspace_history"
            | "get_workspace_history_status"
            | "start_workspace_history"
            | "cancel_workspace_history"
            | "list_workspace_history_gaps"
            | "remove_workspace_member"
            | "change_workspace_role"
            | "submit_workspace_admin_request"
            | "submit_workspace_invitation_request"
            | "submit_workspace_member_removal_request"
            | "submit_workspace_role_change_request"
            | "list_workspace_members"
            | "workspace_connectivity"
            | "workspace_reconnect_status"
            | "workspace_reconnect_consent_set"
            | "workspace_helper_status"
            | "workspace_helper_consent_set"
            | "relay_workspace_connection_update"
            | "create_workspace_admission_grant"
            | "accept_workspace_admission_grant"
            | "list_workspace_admission_grants"
            | "end_workspace_admission_grant"
            | "workspace_request_paths"
            | "create_workspace_access_recommendation"
            | "preview_workspace_access_recommendation"
            | "apply_workspace_access_recommendation"
            | "send_workspace_access_recommendation"
            | "list_workspace_access_recommendations"
            | "preview_workspace_access_recommendation_by_id"
            | "apply_workspace_access_recommendation_by_id"
            | "list_workspace_admin_requests"
            | "list_workspace_admin_history"
            | "get_workspace_admin_request"
            | "approve_workspace_admin_request"
            | "decline_workspace_admin_request"
            | "cancel_workspace_admin_request"
            | "dismiss_workspace_admin_request"
            | "offer_workspace_authority_transition"
            | "accept_workspace_authority_transition"
            | "finalize_workspace_authority_transition"
            | "list_workspace_authority_transitions"
            | "report_workspace_authority_loss"
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
            | "set_workspace_read_hint_sync"
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
            | "get_notification_state"
            | "set_hide_notification_previews"
            | "set_workspace_notification_preference"
            | "open_notification_target"
            | "reconcile_mobile_lifecycle"
            | "set_background_availability"
            | "background_status"
    )
}

#[cfg(desktop)]
fn validated_invitation_value(raw: &str) -> Option<String> {
    let value = raw.trim();
    if value.is_empty() || value.contains('\0') {
        return None;
    }
    let compact: String = value
        .chars()
        .filter(|character| !character.is_whitespace())
        .collect();
    let (prefix, maximum) = if compact.starts_with("mesh-direct:") {
        ("mesh-direct:", MAX_DIRECT_DOCUMENT_PAYLOAD_BYTES)
    } else if compact.starts_with("meshchat://invite/") {
        ("meshchat://invite/", MAX_RENDERER_PAYLOAD_BYTES)
    } else if compact.starts_with("meshchat://workspace/") {
        (
            "meshchat://workspace/",
            MAX_WORKSPACE_INVITATION_PAYLOAD_BYTES,
        )
    } else if compact.starts_with("meshchat://workspace-device/") {
        (
            "meshchat://workspace-device/",
            MAX_WORKSPACE_DEVICE_LINK_PAYLOAD_BYTES,
        )
    } else if compact.starts_with("meshchat://pair/") {
        ("meshchat://pair/", MAX_CONNECTION_RESPONSE_PAYLOAD_BYTES)
    } else if compact.starts_with("meshchat://connect/") {
        ("meshchat://connect/", MAX_CONNECTION_RESPONSE_PAYLOAD_BYTES)
    } else if compact.starts_with("meshchat://route/") {
        ("meshchat://route/", MAX_ROUTE_UPDATE_PAYLOAD_BYTES)
    } else if compact.starts_with("MESHCHAT1:") {
        ("MESHCHAT1:", MAX_RENDERER_PAYLOAD_BYTES)
    } else if compact.starts_with("MESHCHAT2:") {
        ("MESHCHAT2:", MAX_RENDERER_PAYLOAD_BYTES)
    } else if compact.starts_with("MESHCHAT3:") {
        ("MESHCHAT3:", MAX_RENDERER_PAYLOAD_BYTES)
    } else if compact.starts_with("MESHCHAT4:") {
        ("MESHCHAT4:", MAX_RENDERER_PAYLOAD_BYTES)
    } else if compact.starts_with("MESHWORKSPACE1:") {
        ("MESHWORKSPACE1:", MAX_WORKSPACE_INVITATION_PAYLOAD_BYTES)
    } else if compact.starts_with("MESHWORKSPACE2:") {
        ("MESHWORKSPACE2:", MAX_WORKSPACE_INVITATION_PAYLOAD_BYTES)
    } else if compact.starts_with("MESHWORKSPACE3:") {
        ("MESHWORKSPACE3:", MAX_WORKSPACE_INVITATION_PAYLOAD_BYTES)
    } else if compact.starts_with("MESHWORKSPACE4:") {
        ("MESHWORKSPACE4:", MAX_WORKSPACE_INVITATION_PAYLOAD_BYTES)
    } else if compact.starts_with("MESHCONNECT1:") {
        ("MESHCONNECT1:", MAX_CONNECTION_RESPONSE_PAYLOAD_BYTES)
    } else if compact.starts_with("MESHROUTE1:") {
        ("MESHROUTE1:", MAX_ROUTE_UPDATE_PAYLOAD_BYTES)
    } else if compact.starts_with("MESHWORKSPACEDEVICE1:") {
        (
            "MESHWORKSPACEDEVICE1:",
            MAX_WORKSPACE_DEVICE_LINK_PAYLOAD_BYTES,
        )
    } else {
        // A .meshchat export is canonical signed JSON. Workspace envelopes can
        // contain a bounded manifest, while personal envelopes retain the
        // smaller renderer limit. Full validation remains in the service.
        let raw_bytes = value.len();
        if raw_bytes > MAX_DIRECT_DOCUMENT_PAYLOAD_BYTES {
            return None;
        }
        let document = serde_json::from_str::<Value>(value).ok()?;
        let fields = document.as_object()?;
        let direct_fields = ["v", "type", "invitation", "offer", "answer", "ready"];
        if raw_bytes <= 768 * 1024
            && fields.len() == direct_fields.len()
            && direct_fields.iter().all(|key| fields.contains_key(*key))
            && fields.get("v").and_then(Value::as_i64) == Some(2)
            && fields.get("type").and_then(Value::as_str) == Some("direct_connection")
            && fields.get("invitation").is_some_and(Value::is_string)
            && fields.get("offer").is_some_and(Value::is_object)
            && ["answer", "ready"].iter().all(|key| {
                fields
                    .get(*key)
                    .is_some_and(|value| value.is_null() || value.is_object())
            })
        {
            return Some(value.to_string());
        }
        if raw_bytes > MAX_WORKSPACE_DEVICE_LINK_PAYLOAD_BYTES {
            return None;
        }
        let expected = [
            "v",
            "label",
            "public_identity",
            "destination",
            "created_at",
            "expires_at",
            "hints",
            "signature",
        ];
        if raw_bytes <= MAX_RENDERER_PAYLOAD_BYTES
            && fields.len() == expected.len()
            && expected.iter().all(|field| fields.contains_key(*field))
            && fields.get("v").and_then(Value::as_i64) == Some(1)
            && ["label", "public_identity", "destination", "signature"]
                .iter()
                .all(|field| {
                    fields
                        .get(*field)
                        .and_then(Value::as_str)
                        .is_some_and(|item| !item.is_empty())
                })
            && fields.get("created_at").and_then(Value::as_i64).is_some()
            && fields.get("expires_at").and_then(Value::as_i64).is_some()
            && fields.get("hints").is_some_and(Value::is_array)
        {
            return Some(value.to_string());
        }
        let remote_expected = [
            "v",
            "type",
            "purpose",
            "inner",
            "inner_digest",
            "profile",
            "created_at",
            "expires_at",
            "signer_destination",
            "signature",
        ];
        let purpose = fields.get("purpose").and_then(Value::as_str);
        let purpose_size_valid = match purpose {
            Some("personal") => raw_bytes <= MAX_RENDERER_PAYLOAD_BYTES,
            Some("workspace") => raw_bytes <= MAX_WORKSPACE_INVITATION_PAYLOAD_BYTES,
            _ => false,
        };
        if purpose_size_valid
            && fields.len() == remote_expected.len()
            && remote_expected
                .iter()
                .all(|field| fields.contains_key(*field))
            && fields.get("v").and_then(Value::as_i64) == Some(2)
            && fields.get("type").and_then(Value::as_str) == Some("remote_invitation")
            && fields.get("profile").is_some_and(Value::is_object)
            && ["inner", "inner_digest", "signer_destination", "signature"]
                .iter()
                .all(|field| fields.get(*field).and_then(Value::as_str).is_some())
            && fields.get("created_at").and_then(Value::as_i64).is_some()
            && fields.get("expires_at").and_then(Value::as_i64).is_some()
        {
            return Some(value.to_string());
        }
        let participant_expected = [
            "v",
            "type",
            "purpose",
            "inner",
            "inner_digest",
            "access",
            "created_at",
            "expires_at",
            "signer_destination",
            "signature",
        ];
        if purpose_size_valid
            && fields.len() == participant_expected.len()
            && participant_expected
                .iter()
                .all(|field| fields.contains_key(*field))
            && fields.get("v").and_then(Value::as_i64) == Some(3)
            && fields.get("type").and_then(Value::as_str) == Some("participant_invitation")
            && fields.get("access").is_some_and(Value::is_object)
            && ["inner", "inner_digest", "signer_destination", "signature"]
                .iter()
                .all(|field| fields.get(*field).and_then(Value::as_str).is_some())
            && fields.get("created_at").and_then(Value::as_i64).is_some()
            && fields.get("expires_at").and_then(Value::as_i64).is_some()
        {
            return Some(value.to_string());
        }
        let email_expected = [
            "v",
            "type",
            "purpose",
            "inner",
            "inner_digest",
            "inviter_access",
            "reply_challenge",
            "created_at",
            "expires_at",
            "signer_destination",
            "signature",
        ];
        if purpose_size_valid
            && fields.len() == email_expected.len()
            && email_expected
                .iter()
                .all(|field| fields.contains_key(*field))
            && fields.get("v").and_then(Value::as_i64) == Some(4)
            && fields.get("type").and_then(Value::as_str) == Some("email_invitation")
            && (fields.get("inviter_access").is_some_and(Value::is_null)
                || fields.get("inviter_access").is_some_and(Value::is_object))
            && [
                "inner",
                "inner_digest",
                "reply_challenge",
                "signer_destination",
                "signature",
            ]
            .iter()
            .all(|field| fields.get(*field).and_then(Value::as_str).is_some())
            && fields.get("created_at").and_then(Value::as_i64).is_some()
            && fields.get("expires_at").and_then(Value::as_i64).is_some()
        {
            return Some(value.to_string());
        }
        let response_expected = [
            "v",
            "type",
            "purpose",
            "invitation_digest",
            "reply_challenge",
            "signer_destination",
            "responder_public_identity",
            "responder_destination",
            "access",
            "created_at",
            "expires_at",
            "signature",
        ];
        if raw_bytes <= MAX_CONNECTION_RESPONSE_PAYLOAD_BYTES
            && fields.len() == response_expected.len()
            && response_expected
                .iter()
                .all(|field| fields.contains_key(*field))
            && fields.get("v").and_then(Value::as_i64) == Some(1)
            && fields.get("type").and_then(Value::as_str) == Some("connection_response")
            && matches!(purpose, Some("personal") | Some("workspace"))
            && fields.get("access").is_some_and(Value::is_object)
            && [
                "invitation_digest",
                "reply_challenge",
                "signer_destination",
                "responder_public_identity",
                "responder_destination",
                "signature",
            ]
            .iter()
            .all(|field| fields.get(*field).and_then(Value::as_str).is_some())
            && fields.get("created_at").and_then(Value::as_i64).is_some()
            && fields.get("expires_at").and_then(Value::as_i64).is_some()
        {
            return Some(value.to_string());
        }
        let route_expected = [
            "v",
            "type",
            "scope_kind",
            "scope_id",
            "audience_destination",
            "issuer_public_identity",
            "issuer_destination",
            "generation",
            "access",
            "created_at",
            "expires_at",
            "signature",
        ];
        if raw_bytes <= MAX_ROUTE_UPDATE_PAYLOAD_BYTES
            && fields.len() == route_expected.len()
            && route_expected
                .iter()
                .all(|field| fields.contains_key(*field))
            && fields.get("v").and_then(Value::as_i64) == Some(1)
            && fields.get("type").and_then(Value::as_str) == Some("route_update")
            && matches!(
                fields.get("scope_kind").and_then(Value::as_str),
                Some("contact") | Some("workspace_device")
            )
            && fields.get("access").is_some_and(Value::is_object)
            && [
                "scope_id",
                "audience_destination",
                "issuer_public_identity",
                "issuer_destination",
                "signature",
            ]
            .iter()
            .all(|field| fields.get(*field).and_then(Value::as_str).is_some())
            && fields.get("generation").and_then(Value::as_i64).is_some()
            && fields.get("created_at").and_then(Value::as_i64).is_some()
            && fields.get("expires_at").and_then(Value::as_i64).is_some()
        {
            return Some(value.to_string());
        }
        return None;
    };
    let token = compact.strip_prefix(prefix)?;
    if compact.len() <= maximum
        && !token.is_empty()
        && token
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || byte == b'_' || byte == b'-')
    {
        Some(if prefix.starts_with("meshchat://") {
            compact
        } else {
            value.to_string()
        })
    } else {
        None
    }
}

#[cfg(desktop)]
fn invitation_from_argument(argument: &str) -> Option<String> {
    if argument.starts_with("meshchat://") {
        return validated_invitation_value(argument);
    }
    let path = Path::new(argument);
    if !path
        .extension()
        .and_then(|value| value.to_str())
        .is_some_and(|value| {
            value.eq_ignore_ascii_case("meshchat")
                || value.eq_ignore_ascii_case("meshchat-invite")
                || value.eq_ignore_ascii_case("meshchat-connect")
                || value.eq_ignore_ascii_case("meshchat-route")
        })
    {
        return None;
    }
    let metadata = fs::metadata(path).ok()?;
    if !metadata.is_file() || metadata.len() > MAX_DIRECT_DOCUMENT_PAYLOAD_BYTES as u64 {
        return None;
    }
    let contents = fs::read_to_string(path).ok()?;
    validated_invitation_value(&contents)
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
async fn start_or_snapshot_service(
    app: &AppHandle,
    state: &ServiceState,
    display_name: Option<String>,
) -> PendingResult {
    let _guard = state.start_lock.lock().await;
    if state.closing.load(Ordering::Acquire) || state.locked.load(Ordering::Acquire) {
        return Err("service_not_running".into());
    }
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
        spawn_service(app, state)?;
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
async fn initialize_service(
    app: AppHandle,
    state: State<'_, ServiceState>,
    display_name: Option<String>,
) -> PendingResult {
    // Explicit Unlock is the only path that re-enables a deliberately locked
    // service. Ordinary commands may recover an unexpected exit below.
    state.locked.store(false, Ordering::Release);
    start_or_snapshot_service(&app, &state, display_name).await
}

#[cfg(desktop)]
#[tauri::command]
async fn service_command(
    app: AppHandle,
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
    let maximum = renderer_payload_maximum(&command);
    if size > maximum || contains_forbidden_key(&payload) {
        return Err("invalid_request".into());
    }
    let result = request(&state, &command, payload.clone(), Duration::from_secs(20)).await;
    if result.as_ref().err().is_some_and(|error| error == "service_not_running")
        && !matches!(command.as_str(), "snapshot" | "workspace_snapshot" | "background_status")
        && !state.closing.load(Ordering::Acquire)
        && !state.locked.load(Ordering::Acquire)
    {
        // The command was not written, so a single retry is safe even for a
        // mutation. The start lock coalesces concurrent recovery attempts.
        start_or_snapshot_service(&app, &state, None).await?;
        return request(&state, &command, payload, Duration::from_secs(20)).await;
    }
    result
}

#[cfg(desktop)]
#[tauri::command]
async fn lock_service(state: State<'_, ServiceState>) -> Result<(), String> {
    state.locked.store(true, Ordering::Release);
    let _ = request(&state, "shutdown", json!({}), Duration::from_secs(2)).await;
    tokio::time::sleep(Duration::from_millis(250)).await;
    retire_service_child(&state);
    // The exact sidecar PID has been retired even if it could not acknowledge
    // shutdown. Keep the renderer on the locked screen in that case.
    Ok(())
}

#[cfg(desktop)]
#[tauri::command]
fn desktop_service_health(app: AppHandle, state: State<'_, ServiceState>) -> Value {
    let running = state.child.lock().ok().is_some_and(|child| child.is_some());
    let last_exit = state.last_unexpected_exit.lock().ok().and_then(|last| last.clone()).or_else(|| {
        let path = app.path().app_data_dir().ok()?.join("service-exit-diagnostics.json");
        if fs::metadata(&path).ok()?.len() > 16_384 { return None; }
        service_diagnostics::saved_exit(&fs::read(path).ok()?)
    });
    json!({"running":running, "last_unexpected_exit":last_exit})
}

#[cfg(mobile)]
#[tauri::command]
fn desktop_service_health() -> Value {
    serde_json::json!({"running":null, "last_unexpected_exit":null})
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
        let error = value
            .get("error")
            .cloned()
            .unwrap_or_else(|| serde_json::json!({"code": "service_error"}));
        if error.get("details").is_some() {
            Err(error.to_string())
        } else {
            Err(error
                .get("code")
                .and_then(Value::as_str)
                .unwrap_or("service_error")
                .to_string())
        }
    }
}

#[cfg(mobile)]
#[tauri::command]
async fn initialize_service(app: AppHandle, display_name: Option<String>) -> PendingResult {
    let response = app
        .mesh_runtime()
        .initialize(InitializeRequest { display_name })
        .map_err(|_| "service_start_failed".to_string())?;
    let result = mobile_result(response)?;
    #[cfg(target_os = "android")]
    mobile_direct::start(&app);
    Ok(result)
}

#[cfg(mobile)]
#[tauri::command]
async fn service_command(app: AppHandle, command: String, payload: Value) -> PendingResult {
    if !allowed_renderer_command(&command) {
        return Err("command_not_allowed".into());
    }
    let size = serde_json::to_vec(&payload)
        .map_err(|_| "invalid_request".to_string())?
        .len();
    let maximum = renderer_payload_maximum(&command);
    if size > maximum || contains_forbidden_key(&payload) {
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
    #[cfg(target_os = "android")]
    mobile_direct::stop(&app);
    mobile_result(response).map(|_| ())
}

#[cfg(mobile)]
#[tauri::command]
fn set_background_availability(app: AppHandle, enabled: bool) -> PendingResult {
    let response = app
        .mesh_runtime()
        .set_background_availability(enabled)
        .map_err(|_| "background_availability_unavailable".to_string())?;
    mobile_result(response)
}

#[cfg(desktop)]
#[tauri::command]
fn set_background_availability(_enabled: bool) -> PendingResult {
    Err("background_availability_unsupported".into())
}

#[cfg(mobile)]
#[tauri::command]
fn take_pending_invitation(app: AppHandle) -> Result<Option<String>, String> {
    let response = app
        .mesh_runtime()
        .take_pending_invitation()
        .map_err(|_| "service_stopped".to_string())?;
    let value = mobile_result(response)?;
    serde_json::from_value(value).map_err(|_| "service_protocol_error".to_string())
}

#[cfg(mobile)]
#[tauri::command]
async fn pick_invitation_file(app: AppHandle) -> Result<Option<String>, String> {
    let response = app
        .mesh_runtime()
        .pick_invitation_file()
        .await
        .map_err(|_| "invitation_file_unavailable".to_string())?;
    let value = mobile_result(response)?;
    serde_json::from_value(value).map_err(|_| "service_protocol_error".to_string())
}

#[cfg(desktop)]
#[tauri::command]
fn pick_invitation_file() -> Result<Option<String>, String> {
    Err("unsupported_platform".to_string())
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

#[tauri::command]
fn set_native_theme(app: AppHandle, theme: String) -> Result<(), String> {
    if theme != "dark" && theme != "light" {
        return Err("invalid_theme".to_string());
    }
    #[cfg(desktop)]
    {
        let window = app
            .get_webview_window("main")
            .ok_or_else(|| "window_unavailable".to_string())?;
        let native_theme = if theme == "light" {
            tauri::Theme::Light
        } else {
            tauri::Theme::Dark
        };
        window
            .set_theme(Some(native_theme))
            .map_err(|_| "theme_unavailable".to_string())
    }
    #[cfg(target_os = "android")]
    {
        let response = app
            .mesh_runtime()
            .set_theme(ThemeRequest { theme })
            .map_err(|_| "theme_unavailable".to_string())?;
        mobile_result(response).map(|_| ())
    }
    #[cfg(target_os = "ios")]
    {
        let _ = (app, theme);
        Ok(())
    }
}

#[cfg(desktop)]
#[tauri::command]
fn notification_capability() -> PendingResult {
    Ok(serde_json::json!({
        "supported": false,
        "platform": "desktop",
        "permission_state": "unsupported"
    }))
}

#[cfg(mobile)]
#[tauri::command]
fn notification_capability(app: AppHandle) -> PendingResult {
    mobile_result(
        app.mesh_runtime()
            .notification_capability()
            .map_err(|_| "notification_unavailable".to_string())?,
    )
}

#[cfg(desktop)]
#[tauri::command]
fn request_notification_permission() -> PendingResult {
    notification_capability()
}

#[cfg(mobile)]
#[tauri::command]
fn request_notification_permission(app: AppHandle) -> PendingResult {
    mobile_result(
        app.mesh_runtime()
            .request_notification_permission()
            .map_err(|_| "notification_unavailable".to_string())?,
    )
}

#[cfg(desktop)]
#[tauri::command]
fn request_media_permission(media: String) -> serde_json::Value {
    let _ = media;
    serde_json::json!({"audio": false, "camera": false})
}

#[cfg(mobile)]
#[tauri::command]
fn request_media_permission(app: AppHandle, media: String) -> PendingResult {
    if !matches!(media.as_str(), "audio" | "video") {
        return Err("invalid_request".into());
    }
    mobile_result(
        app.mesh_runtime()
            .request_media_permission(&media)
            .map_err(|_| "media_permission_unavailable".to_string())?,
    )
}

#[cfg(desktop)]
#[tauri::command]
fn begin_call_audio(media: String) -> serde_json::Value {
    let _ = media;
    serde_json::json!({"granted": true})
}

#[cfg(mobile)]
#[tauri::command]
fn begin_call_audio(app: AppHandle, media: String) -> PendingResult {
    if !matches!(media.as_str(), "audio" | "video") {
        return Err("invalid_request".into());
    }
    mobile_result(
        app.mesh_runtime()
            .begin_call_audio(&media)
            .map_err(|_| "call_audio_unavailable".to_string())?,
    )
}

#[cfg(desktop)]
#[tauri::command]
fn end_call_audio() -> serde_json::Value {
    serde_json::json!({"active": false})
}

#[cfg(mobile)]
#[tauri::command]
fn end_call_audio(app: AppHandle) -> PendingResult {
    mobile_result(
        app.mesh_runtime()
            .end_call_audio()
            .map_err(|_| "call_audio_unavailable".to_string())?,
    )
}

#[cfg(desktop)]
#[tauri::command]
fn open_notification_settings() -> PendingResult {
    notification_capability()
}

#[cfg(mobile)]
#[tauri::command]
fn open_notification_settings(app: AppHandle) -> PendingResult {
    mobile_result(
        app.mesh_runtime()
            .open_notification_settings()
            .map_err(|_| "notification_unavailable".to_string())?,
    )
}

#[cfg(desktop)]
#[tauri::command]
fn open_battery_settings() -> PendingResult {
    Err("battery_settings_unavailable".to_string())
}

#[cfg(mobile)]
#[tauri::command]
fn open_battery_settings(app: AppHandle) -> PendingResult {
    mobile_result(
        app.mesh_runtime()
            .open_battery_settings()
            .map_err(|_| "battery_settings_unavailable".to_string())?,
    )
}

fn external_link_url(url: &str) -> Result<tauri::Url, String> {
    let parsed = tauri::Url::parse(url).map_err(|_| "invalid_url".to_string())?;
    if url.len() > 4096 || url.chars().any(|c| c.is_control()) ||
        !matches!(parsed.scheme(), "https" | "http") || parsed.host_str().is_none() ||
        !parsed.username().is_empty() || parsed.password().is_some() {
        return Err("invalid_url".into());
    }
    Ok(parsed)
}

#[tauri::command]
fn open_external_link(app: AppHandle, url: String) -> Result<(), String> {
    let parsed = external_link_url(&url)?;
    #[cfg(desktop)]
    {
        #[allow(deprecated)]
        app.shell().open(parsed.as_str(), None).map_err(|_| "browser_unavailable".to_string())?;
    }
    #[cfg(mobile)]
    {
        mobile_result(app.mesh_runtime().open_external_link(parsed.as_str())
            .map_err(|_| "browser_unavailable".to_string())?)?;
    }
    Ok(())
}

#[tauri::command]
fn app_build_info(app: AppHandle) -> serde_json::Value {
    let mut info = serde_json::json!({
        "installed_version": app.package_info().version.to_string(),
        "native_version": env!("CARGO_PKG_VERSION"),
        "build_commit": env!("MESH_BUILD_COMMIT"),
        "platform": std::env::consts::OS,
        "os_version": "unavailable",
        "android_version_code": null
    });
    #[cfg(target_os = "android")]
    if let Ok(response) = app.mesh_runtime().build_info() {
        if let Ok(android) = mobile_result(response) {
            for key in ["installed_version", "android_version_code", "os_version"] {
                if let Some(value) = android.get(key) {
                    info[key] = value.clone();
                }
            }
        }
    }
    // No service, identity, network, or filesystem path is needed for this call.
    let _ = &mut info;
    info
}

#[cfg(desktop)]
#[tauri::command]
async fn desktop_transport_exchange(window: tauri::WebviewWindow, state: State<'_, ServiceState>,
                                    token: String, frames: Vec<Value>, fault: bool) -> Result<Vec<Value>, String> {
    desktop_transport::exchange(&window, &state, &token, frames, fault)
}

#[cfg(mobile)]
#[tauri::command]
fn desktop_transport_exchange() -> Result<Vec<Value>, String> {
    Err("transport_host_unavailable".into())
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
    #[cfg(all(windows, feature = "experimental-shared-webview"))]
    let builder = builder.append_invoke_initialization_script(
        "Object.defineProperty(window, '__MESH_SERVICE_TRANSPORT__', {value:true});",
    );
    #[cfg(target_os = "android")]
    let builder = builder.manage(mobile_direct::MobileDirect::default());
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
            desktop_transport_exchange,
            initialize_service,
            service_command,
            lock_service,
            desktop_service_health,
            set_background_availability,
            take_pending_invitation,
            pick_invitation_file,
            poll_mobile_events,
            runtime_platform,
            app_build_info,
            set_native_theme,
            notification_capability,
            request_notification_permission,
            request_media_permission,
            begin_call_audio,
            end_call_audio,
            open_notification_settings,
            open_external_link,
            open_battery_settings
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
    fn external_links_cannot_launch_non_web_handlers_or_include_credentials() {
        for url in ["javascript:alert(1)", "file:///secret", "data:text/html,hi", "meshchat://connect", "https://user:secret@example.com", "https://example.com/\nsecret"] {
            assert!(external_link_url(url).is_err(), "accepted {url}");
        }
        assert!(external_link_url("https://www.youtube.com/watch?v=aqz-KE-bpKQ").is_ok());
        assert!(external_link_url("http://example.com/page").is_ok());
        assert!(external_link_url(&format!("https://example.com/{}", "x".repeat(4096))).is_err());
    }

    #[test]
    fn signed_webrtc_exchange_has_room_for_a_full_sdp_document() {
        for command in [
            "webrtc_onboarding_offer",
            "verify_webrtc_onboarding_offer",
            "webrtc_onboarding_answer",
            "verify_webrtc_onboarding_answer",
            "native_webrtc_accept",
            "native_webrtc_bind_onboarding",
            "signal_publish",
            "reconnect_offer_create",
            "reconnect_answer_create",
            "verify_reconnect_offer",
            "verify_reconnect_answer",
            "reconnect_publish",
            "start_call",
            "answer_call",
            "restart_call",
            "answer_call_restart",
        ] {
            assert_eq!(renderer_payload_maximum(command), 128 * 1024, "{command}");
        }
        assert_eq!(renderer_payload_maximum("snapshot"), 32 * 1024);
        let answer_exchange = serde_json::to_vec(&json!({
            "offer_document": "x".repeat(36 * 1024),
            "answer_document": "y".repeat(36 * 1024),
        })).unwrap();
        assert!(answer_exchange.len() > 64 * 1024);
        assert!(answer_exchange.len() <= renderer_payload_maximum("verify_webrtc_onboarding_answer"));
    }

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
    fn stale_process_retirement_preserves_the_replacement_and_its_requests() {
        let state = ServiceState::default();
        *state.sidecar_pid.lock().unwrap() = Some(200);
        *state.direct_native.lock().unwrap() = Some(direct_native::NativeHost::default());
        let (sender, mut receiver) = oneshot::channel();
        state.pending.lock().unwrap().insert("replacement".into(), sender);

        assert!(detach_service(&state, Some(100)).is_none());

        assert_eq!(*state.sidecar_pid.lock().unwrap(), Some(200));
        assert!(state.direct_native.lock().unwrap().is_some());
        assert!(matches!(receiver.try_recv(), Err(oneshot::error::TryRecvError::Empty)));
    }

    #[test]
    fn exact_process_detachment_wakes_requests_even_when_the_writer_is_blocked() {
        let state = ServiceState::default();
        *state.sidecar_pid.lock().unwrap() = Some(100);
        let (sender, mut receiver) = oneshot::channel();
        state.pending.lock().unwrap().insert("old".into(), sender);
        let writer = state.child.lock().unwrap();

        let retired = detach_service(&state, Some(100)).unwrap();

        assert_eq!(retired.pid, 100);
        assert_eq!(*state.sidecar_pid.lock().unwrap(), None);
        assert_eq!(receiver.try_recv().unwrap(), Err("service_stopped".into()));
        assert!(detach_service(&state, Some(100)).is_none());
        drop(writer);
    }

    #[test]
    fn delayed_disposal_cannot_close_a_replacement_host_or_cancel_its_requests() {
        let state = ServiceState::default();
        *state.sidecar_pid.lock().unwrap() = Some(100);
        *state.direct_native.lock().unwrap() = Some(direct_native::NativeHost::default());
        let retired = detach_service(&state, Some(100)).unwrap();
        *state.sidecar_pid.lock().unwrap() = Some(200);
        *state.direct_native.lock().unwrap() = Some(direct_native::NativeHost::default());
        let (sender, mut receiver) = oneshot::channel();
        state.pending.lock().unwrap().insert("replacement".into(), sender);

        retired.dispose(false);

        assert_eq!(*state.sidecar_pid.lock().unwrap(), Some(200));
        assert!(state.direct_native.lock().unwrap().is_some());
        assert!(matches!(receiver.try_recv(), Err(oneshot::error::TryRecvError::Empty)));
    }

    #[test]
    fn renderer_can_delete_and_restore_local_conversations() {
        for command in [
            "direct_native",
            "direct_native_reply",
            "directExchange",
            "direct_exchange",
            "prepare",
            "activate",
            "poll",
            "send",
            "reset",
        ] {
            assert!(!allowed_renderer_command(command));
        }
        assert!(allowed_renderer_command("delete_conversation"));
        assert!(allowed_renderer_command("i2p_status"));
        assert!(allowed_renderer_command("restore_conversation"));
        assert!(allowed_renderer_command("set_message_reaction"));
        assert!(!allowed_renderer_command("delete_contact_identity"));
        for command in [
            "preview_remote_profile",
            "create_manual_remote_profile",
            "test_remote_profile",
            "list_remote_profiles",
            "retry_remote_profile",
            "remove_remote_profile",
            "approve_remote_propagation",
            "remove_remote_propagation",
            "stop_participant_host",
        ] {
            assert!(allowed_renderer_command(command));
        }
    }

    #[test]
    fn renderer_workspace_commands_are_cross_platform_and_native_work_is_private() {
        let commands = [
            "preview_direct_connection",
            "prepare_direct_offer",
            "prepare_direct_answer",
            "prepare_direct_ready",
            "accept_direct_ready",
            "connect_direct_setup",
            "configure_direct_firewall",
            "direct_recovery_status",
            "export_recovery_update",
            "import_recovery_update",
            "pause_direct_recovery",
            "resume_direct_recovery",
            "direct_setup_status",
            "resume_direct_setup",
            "check_direct_setup",
            "retry_direct_setup",
            "connection_diagnostics",
            "clear_connection_diagnostics",
            "cancel_direct_setup",
            "workspace_snapshot",
            "create_workspace",
            "create_workspace_invitation",
            "invite_contact_to_workspace",
            "dismiss_workspace_invitation_prompt",
            "offer_workspace_authority_transition",
            "accept_workspace_authority_transition",
            "finalize_workspace_authority_transition",
            "list_workspace_authority_transitions",
            "report_workspace_authority_loss",
            "preview_workspace_invitation",
            "revoke_workspace_invitation",
            "submit_workspace_join",
            "approve_workspace_join",
            "decline_workspace_join",
            "create_workspace_device_link",
            "preview_workspace_device_link",
            "submit_workspace_device_link",
            "approve_workspace_device_link",
            "decline_workspace_device_link",
            "request_workspace_device_removal",
            "approve_workspace_device_removal",
            "decline_workspace_device_removal",
            "update_workspace_metadata",
            "update_workspace_policies",
            "update_workspace_retention",
            "prune_workspace_history",
            "get_workspace_history_status",
            "start_workspace_history",
            "cancel_workspace_history",
            "list_workspace_history_gaps",
            "remove_workspace_member",
            "change_workspace_role",
            "submit_workspace_admin_request",
            "submit_workspace_invitation_request",
            "submit_workspace_member_removal_request",
            "submit_workspace_role_change_request",
            "list_workspace_members",
            "workspace_connectivity",
            "workspace_reconnect_status",
            "workspace_reconnect_consent_set",
            "workspace_helper_status",
            "workspace_helper_consent_set",
            "relay_workspace_connection_update",
            "create_workspace_admission_grant",
            "accept_workspace_admission_grant",
            "list_workspace_admission_grants",
            "end_workspace_admission_grant",
            "workspace_request_paths",
            "create_workspace_access_recommendation",
            "preview_workspace_access_recommendation",
            "apply_workspace_access_recommendation",
            "send_workspace_access_recommendation",
            "list_workspace_access_recommendations",
            "preview_workspace_access_recommendation_by_id",
            "apply_workspace_access_recommendation_by_id",
            "list_workspace_admin_requests",
            "list_workspace_admin_history",
            "get_workspace_admin_request",
            "approve_workspace_admin_request",
            "decline_workspace_admin_request",
            "cancel_workspace_admin_request",
            "dismiss_workspace_admin_request",
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
            "set_workspace_read_hint_sync",
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
            "get_notification_state",
            "set_hide_notification_previews",
            "set_workspace_notification_preference",
            "open_notification_target",
            "reconcile_mobile_lifecycle",
            "set_background_availability",
            "background_status",
        ];
        for command in commands {
            assert!(allowed_renderer_command(command));
        }
        assert!(!allowed_renderer_command("native_notification_state"));
        assert!(!allowed_renderer_command("mobile_lifecycle_transition"));
        assert!(!allowed_renderer_command("drain_native_notification_work"));
        assert!(!allowed_renderer_command("acknowledge_native_notification"));
    }

    #[test]
    fn desktop_accepts_workspace_deep_links() {
        assert_eq!(
            validated_invitation_value("mesh-direct:abc_DEF-123"),
            Some("mesh-direct:abc_DEF-123".to_string())
        );
        let direct = json!({"v":2,"type":"direct_connection","invitation":"signed","offer":{},"answer":null,"ready":null});
        assert_eq!(
            validated_invitation_value(&direct.to_string()),
            Some(direct.to_string())
        );
        let mut wrong_direct = direct.clone();
        wrong_direct["v"] = json!(1);
        assert!(validated_invitation_value(&wrong_direct.to_string()).is_none());
        let link = "meshchat://workspace/fixture-token";
        assert_eq!(invitation_from_argument(link), Some(link.to_string()));
        assert_eq!(
            validated_invitation_value("MESHCHAT2:abc_DEF-123"),
            Some("MESHCHAT2:abc_DEF-123".to_string())
        );
        assert_eq!(
            validated_invitation_value("MESHCHAT3:abc_DEF-123"),
            Some("MESHCHAT3:abc_DEF-123".to_string())
        );
        assert_eq!(
            validated_invitation_value("MESHCHAT4:abc_DEF-123"),
            Some("MESHCHAT4:abc_DEF-123".to_string())
        );
        assert_eq!(
            validated_invitation_value("MESHWORKSPACE2:abc_DEF-123"),
            Some("MESHWORKSPACE2:abc_DEF-123".to_string())
        );
        assert_eq!(
            validated_invitation_value("MESHWORKSPACE3:abc_DEF-123"),
            Some("MESHWORKSPACE3:abc_DEF-123".to_string())
        );
        assert_eq!(
            validated_invitation_value("MESHCONNECT1:abc_DEF-123"),
            Some("MESHCONNECT1:abc_DEF-123".to_string())
        );
        assert_eq!(
            validated_invitation_value("MESHROUTE1:abc_DEF-123"),
            Some("MESHROUTE1:abc_DEF-123".to_string())
        );
        let workspace_document = "{\"v\":2,\"type\":\"remote_invitation\",\"purpose\":\"workspace\",\"inner\":\"signed\",\"inner_digest\":\"digest\",\"profile\":{},\"created_at\":1,\"expires_at\":2,\"signer_destination\":\"destination\",\"signature\":\"signature\"}";
        assert_eq!(
            validated_invitation_value(workspace_document),
            Some(workspace_document.to_string())
        );
        let participant_document = "{\"v\":3,\"type\":\"participant_invitation\",\"purpose\":\"personal\",\"inner\":\"signed\",\"inner_digest\":\"digest\",\"access\":{},\"created_at\":1,\"expires_at\":2,\"signer_destination\":\"destination\",\"signature\":\"signature\"}";
        assert_eq!(
            validated_invitation_value(participant_document),
            Some(participant_document.to_string())
        );
        let device = "meshchat://workspace-device/fixture-token";
        assert_eq!(invitation_from_argument(device), Some(device.to_string()));
    }

    #[test]
    fn desktop_rejects_malformed_unrelated_and_oversized_launch_values() {
        assert_eq!(
            invitation_from_argument("meshchat://notification/abc"),
            None
        );
        assert_eq!(
            invitation_from_argument("meshchat://invite/abc?leak=1"),
            None
        );
        assert_eq!(
            invitation_from_argument("meshchat://invite/abc/extra"),
            None
        );
        let oversized = format!(
            "meshchat://invite/{}",
            "a".repeat(MAX_RENDERER_PAYLOAD_BYTES)
        );
        assert_eq!(invitation_from_argument(&oversized), None);
        assert_eq!(validated_invitation_value("{\"v\":1}"), None);
        assert_eq!(
            validated_invitation_value(
                "{\"v\":1,\"label\":\"Peer\",\"public_identity\":\"a\",\"destination\":\"b\",\"created_at\":1,\"expires_at\":2,\"hints\":[],\"signature\":\"c\",\"path\":\"private\"}"
            ),
            None
        );
    }
}

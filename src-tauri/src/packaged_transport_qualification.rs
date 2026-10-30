//! Test-only orchestration. Each frozen service uses the production private host.
use crate::{desktop_transport, direct_native, ServiceState};
use serde_json::{json, Value};
use std::{
    collections::BTreeMap,
    sync::{Arc, Mutex},
    time::Duration,
};
use tauri::{AppHandle, State, WebviewWindow};
use tauri_plugin_shell::{
    process::{CommandChild, CommandEvent},
    ShellExt,
};

#[derive(Clone)]
struct Fixture {
    peers: [ServiceState; 2],
    binary: String,
    controller: Arc<Mutex<Option<CommandChild>>>,
    operations: Arc<Mutex<[BTreeMap<String, u64>; 2]>>,
    exits: Arc<Mutex<[Option<Value>; 2]>>,
}

#[tauri::command]
async fn desktop_transport_exchange(
    window: WebviewWindow,
    state: State<'_, Fixture>,
    token: String,
    frames: Vec<Value>,
    fault: bool,
) -> Result<Vec<Value>, String> {
    for (index, peer) in state.peers.iter().enumerate() {
        match desktop_transport::exchange(&window, peer, &token, frames.clone(), fault) {
            Err(error)
                if matches!(
                    error.as_str(),
                    "transport_caller_denied" | "transport_retired"
                ) =>
            {
                continue
            }
            result => {
                if let Ok(requests) = &result {
                    let mut counts = state.operations.lock().map_err(|_| "fixture_lock")?;
                    for request in requests {
                        if let Some(op) = request["request"]["op"].as_str() {
                            *counts[index].entry(op.to_owned()).or_default() += 1;
                        }
                    }
                }
                return result;
            }
        }
    }
    Err("transport_caller_denied".into())
}

fn launch(app: &AppHandle, fixture: &Fixture, index: usize) -> Result<Value, String> {
    let state = fixture.peers[index].clone();
    let mut current = state.sidecar_pid.lock().map_err(|_| "fixture_lock")?;
    if current.is_some() {
        return Err("fixture_peer_running".into());
    }
    let (mut events, child) = app
        .shell()
        .command(&fixture.binary)
        .arg("--shared-webview")
        .set_raw_out(true)
        .spawn()
        .map_err(|_| "fixture_spawn_failed")?;
    let pid = child.pid();
    *state.child.lock().map_err(|_| "fixture_lock")? = Some(child);
    *current = Some(pid);
    drop(current);
    desktop_transport::register(app, &state, pid)?;
    fixture.exits.lock().map_err(|_| "fixture_lock")?[index] = None;
    let exits = fixture.exits.clone();
    let app = app.clone();
    tauri::async_runtime::spawn(async move {
        let native = direct_native::NativeHost::default();
        let mut buffer = Vec::new();
        let mut stderr = crate::service_diagnostics::Capture::default();
        let mut reason = "event_stream_closed";
        let mut exit_code = None;
        let mut transport_error = None;
        while let Some(event) = events.recv().await {
            match event {
                CommandEvent::Stdout(bytes) => {
                    buffer.extend(bytes);
                    if crate::consume_frames(&mut buffer, |value| {
                        if transport_error.is_none() {
                            transport_error = crate::route_sidecar_value(&app, &state, &native, pid, value).err();
                        }
                    })
                    .is_err()
                    {
                        reason = "protocol_error";
                        break;
                    }
                    if transport_error.is_some() {
                        reason = "transport_admission";
                        break;
                    }
                }
                CommandEvent::Stderr(bytes) => stderr.push(&bytes),
                CommandEvent::Terminated(exit) => {
                    reason = "terminated";
                    exit_code = exit.code;
                    break;
                }
                CommandEvent::Error(_) => { reason = "process_event_error"; break; }
                _ => {}
            }
        }
        let mut evidence = stderr.finish();
        evidence["slot"] = json!(index);
        evidence["reason"] = json!(reason);
        evidence["exit_code"] = json!(exit_code);
        evidence["transport_error"] = json!(transport_error);
        // Publish before detachment wakes a failed pending initialization.
        exits.lock().unwrap()[index] = Some(evidence);
        native.close();
        if reason == "terminated" {
            if let Some(retired) = crate::detach_service_with_transport(&state, Some(pid), true) {
                retired.dispose(false);
            }
        } else {
            crate::retire_service_process(&state, Some(pid));
        }
    });
    Ok(json!({"started":true}))
}

async fn request(state: &ServiceState, value: &Value) -> Result<Value, String> {
    crate::request(
        state,
        value["command"].as_str().ok_or("fixture_command")?,
        value["payload"].clone(),
        Duration::from_secs(35),
    )
    .await
}

async fn command(app: &AppHandle, fixture: &Fixture, value: &Value) -> Result<Value, String> {
    let index = value["slot"]
        .as_u64()
        .filter(|index| *index < 2)
        .ok_or("fixture_slot")? as usize;
    let state = &fixture.peers[index];
    match value["action"].as_str() {
        Some("start") => launch(app, fixture, index),
        Some("call") => request(state, value).await,
        Some("stop") => {
            crate::retire_service_child(state);
            Ok(json!({"stopped":true}))
        }
        Some("crash") => {
            let pid = state
                .sidecar_pid
                .lock()
                .map_err(|_| "fixture_lock")?
                .ok_or("fixture_peer_missing")?;
            crate::terminate_windows_process_tree(pid);
            for _ in 0..100 {
                if state.sidecar_pid.lock().unwrap().is_none() {
                    return Ok(json!({"crashed":true}));
                }
                tokio::time::sleep(Duration::from_millis(50)).await;
            }
            Err("fixture_crash_timeout".into())
        }
        Some("counts") => Ok(json!(
            fixture.operations.lock().map_err(|_| "fixture_lock")?[index]
        )),
        _ => Err("fixture_action".into()),
    }
}

fn reply(fixture: &Fixture, value: Value) -> Result<(), ()> {
    let encoded = crate::frame(&value).map_err(|_| ())?;
    fixture
        .controller
        .lock()
        .map_err(|_| ())?
        .as_mut()
        .ok_or(())?
        .write(&encoded)
        .map_err(|_| ())
}

fn cleanup(fixture: &Fixture) {
    for peer in &fixture.peers {
        crate::retire_service_child(peer);
    }
    if let Some(controller) = fixture.controller.lock().unwrap().take() {
        let _ = controller.kill();
    }
}

pub fn run(arguments: &[String]) -> i32 {
    let fixture = Fixture {
        peers: [ServiceState::default(), ServiceState::default()],
        binary: arguments[2].clone(),
        controller: Default::default(),
        operations: Default::default(),
        exits: Default::default(),
    };
    let setup = fixture.clone();
    let python = arguments[0].clone();
    let probe = arguments[1].clone();
    let mut context = tauri::generate_context!();
    context.config_mut().app.windows.clear();
    context.config_mut().build.dev_url = None;
    context.config_mut().identifier = format!(
        "com.meshchat.packagedqualification.{}",
        uuid::Uuid::new_v4().simple()
    );
    let application = tauri::Builder::default().plugin(tauri_plugin_shell::init()).manage(fixture.clone())
        .invoke_handler(tauri::generate_handler![desktop_transport_exchange])
        .setup(move |app| {
            let (mut events, controller) = app.shell().command(python).arg(probe)
                .arg(std::process::id().to_string()).set_raw_out(true).spawn()?;
            *setup.controller.lock().unwrap() = Some(controller);
            let app = app.handle().clone();
            let deadline_app = app.clone();
            let deadline_fixture = setup.clone();
            std::thread::spawn(move || {
                std::thread::sleep(Duration::from_secs(240));
                cleanup(&deadline_fixture);
                deadline_app.exit(2);
            });
            tauri::async_runtime::spawn(async move {
                let mut buffer = Vec::new();
                while let Some(event) = events.recv().await {
                    match event {
                        CommandEvent::Stdout(bytes) => {
                            buffer.extend(bytes);
                            let mut messages = Vec::new();
                            if crate::consume_frames(&mut buffer, |value| messages.push(value)).is_err() { break; }
                            for value in messages {
                                if value["action"] == "finish" {
                                    let passed = value["ok"] == true;
                                    let level = if value["scenario"] == "explicit_pairing" {
                                        "windows_packaged_webview2_explicit_pairing"
                                    } else { "windows_packaged_webview2_preapproved_peers" };
                                    println!("{}", json!({"v":1,"source_commit":env!("MESH_BUILD_COMMIT"),
                                        "evidence_level":level,
                                        "result":{"ok":passed,"checks":value["checks"],"counts":value["counts"],
                                            "phase":value["phase"],"error_type":value["error_type"],
                                            "process_exits":setup.exits.lock().unwrap().iter().flatten().cloned().collect::<Vec<_>>()}}));
                                    app.exit(if passed {0} else {1});
                                    return;
                                }
                                let result = command(&app, &setup, &value).await;
                                let response = match result {
                                    Ok(result) => json!({"id":value["id"],"ok":true,"result":result}),
                                    Err(error) => json!({"id":value["id"],"ok":false,"error":error}),
                                };
                                if reply(&setup, response).is_err() { app.exit(2); return; }
                            }
                        }
                        CommandEvent::Terminated(_) | CommandEvent::Error(_) => break,
                        _ => {}
                    }
                }
                app.exit(2);
            });
            Ok(())
        }).build(context);
    match application {
        Ok(app) => app.run_return(move |_, event| {
            if let tauri::RunEvent::ExitRequested {
                code: None, api, ..
            } = &event
            {
                api.prevent_exit();
            }
            if matches!(event, tauri::RunEvent::Exit) {
                cleanup(&fixture);
            }
        }),
        Err(_) => {
            cleanup(&fixture);
            2
        }
    }
}

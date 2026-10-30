//! Separate CI executable; absent from shipping builds and public host commands.
use crate::{
    consume_frames, desktop_transport, direct_native, handle_sidecar_value, retire_service_child,
    ServiceState,
};
use serde_json::json;
use std::time::Duration;
use tauri_plugin_shell::{process::CommandEvent, ShellExt};

pub fn run() -> i32 {
    let arguments: Vec<_> = std::env::args().skip(1).collect();
    if arguments.len() != 2 {
        return 2;
    }
    let state = ServiceState::default();
    let setup_state = state.clone();
    let mut context = tauri::generate_context!();
    context.config_mut().app.windows.clear();
    context.config_mut().build.dev_url = None;
    context.config_mut().identifier = format!(
        "com.meshchat.transportqualification.{}",
        uuid::Uuid::new_v4().simple()
    );
    let app = tauri::Builder::default().plugin(tauri_plugin_shell::init()).manage(state.clone())
        .invoke_handler(tauri::generate_handler![crate::desktop_transport_exchange])
        .setup(move |app| {
            let (mut events, child) = app.shell().command(&arguments[0]).arg(&arguments[1]).set_raw_out(true).spawn()?;
            let pid = child.pid();
            *setup_state.child.lock().unwrap() = Some(child);
            *setup_state.sidecar_pid.lock().unwrap() = Some(pid);
            desktop_transport::register(app.handle(), &setup_state, pid).map_err(std::io::Error::other)?;
            let app = app.handle().clone();
            let deadline_app = app.clone();
            let deadline_state = setup_state.clone();
            std::thread::spawn(move || {
                std::thread::sleep(Duration::from_secs(90));
                retire_service_child(&deadline_state);
                deadline_app.exit(2);
            });
            tauri::async_runtime::spawn(async move {
                let native = direct_native::NativeHost::default();
                let mut buffer = Vec::new();
                let mut reported = false;
                while let Some(event) = events.recv().await {
                    match event {
                        CommandEvent::Stdout(bytes) => {
                            buffer.extend_from_slice(&bytes);
                            if consume_frames(&mut buffer, |value| {
                                if value["type"] == "desktop_transport_qualification" {
                                    reported = true;
                                    let passed = value["ok"] == true;
                                    println!("{}", json!({"v":1, "source_commit":env!("MESH_BUILD_COMMIT"),
                                        "evidence_level":"windows_webview2_private_host_component", "result":value}));
                                    app.exit(if passed { 0 } else { 1 });
                                } else { handle_sidecar_value(&app, &setup_state, &native, pid, value); }
                            }).is_err() { app.exit(2); break; }
                            if reported { break; }
                        }
                        CommandEvent::Terminated(_) | CommandEvent::Error(_) => { app.exit(2); break; }
                        _ => {}
                    }
                }
            });
            Ok(())
        }).build(context);
    match app {
        Ok(app) => app.run_return(move |_, event| {
            if matches!(event, tauri::RunEvent::Exit) {
                retire_service_child(&state);
            }
        }),
        Err(_) => {
            retire_service_child(&state);
            2
        }
    }
}

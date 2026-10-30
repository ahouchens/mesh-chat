//! Trusted window registration and inherited-pipe routing. No peer policy.
use crate::{desktop_transport_broker::Binding, frame, ServiceState};
use serde_json::Value;
use tauri::{AppHandle, WebviewUrl, WebviewWindow, WebviewWindowBuilder};

pub struct RegisteredHost {
    binding: Binding,
    window: Option<WebviewWindow>,
}

fn trusted_location(url: &tauri::Url) -> bool {
    if url.path() != "/transport-host.html"
        || url.query().is_some()
        || url.fragment().is_some()
        || !url.username().is_empty()
        || url.password().is_some()
    {
        return false;
    }
    matches!(
        (url.scheme(), url.host_str(), url.port()),
        ("tauri", Some("localhost"), None) | ("http" | "https", Some("tauri.localhost"), None)
    ) || (cfg!(debug_assertions)
        && url.scheme() == "http"
        && url.host_str() == Some("localhost")
        && url.port() == Some(1420))
}

pub fn register(app: &AppHandle, state: &ServiceState, pid: u32) -> Result<(), String> {
    retire(state, None, false);
    let label = format!("mesh-transport-{}", uuid::Uuid::new_v4().simple());
    let token = uuid::Uuid::new_v4().simple().to_string();
    let bootstrap = serde_json::json!({"token": token}).to_string();
    *state
        .desktop_transport
        .lock()
        .map_err(|_| "transport_lock_failed")? = Some(RegisteredHost {
        binding: Binding::new(pid, label.clone(), token),
        window: None,
    });
    let result = WebviewWindowBuilder::new(app, &label, WebviewUrl::App("transport-host.html".into()))
        .visible(false).focused(false).skip_taskbar(true)
        .on_navigation(trusted_location)
        .initialization_script(format!(
            "if (location.pathname === '/transport-host.html') Object.defineProperty(window, '__MESH_TRANSPORT_BOOTSTRAP__', {{value:{bootstrap}}});"))
        .build();
    let window = match result {
        Ok(window) => window,
        Err(_) => {
            retire(state, Some(pid), true);
            return Err("transport_window_unavailable".into());
        }
    };
    let event_state = state.clone();
    window.on_window_event(move |event| {
        if matches!(event, tauri::WindowEvent::Destroyed) {
            retire(&event_state, Some(pid), true);
        }
    });
    let mut registered = state
        .desktop_transport
        .lock()
        .map_err(|_| "transport_lock_failed")?;
    if let Some(host) = registered.as_mut().filter(|host| host.binding.pid() == pid) {
        host.window = Some(window);
        Ok(())
    } else {
        drop(registered);
        let _ = window.close();
        Err("transport_retired".into())
    }
}

pub fn admit(state: &ServiceState, pid: u32, request: Value) -> Result<(), String> {
    let mut registered = state
        .desktop_transport
        .lock()
        .map_err(|_| "transport_lock_failed")?;
    if registered.is_none() && request["request"] == serde_json::json!({"op": "reset"}) {
        return Ok(()); // The exact window has already disposed its resources.
    }
    registered
        .as_mut()
        .ok_or("transport_host_unavailable")?
        .binding
        .admit(pid, request)
        .map_err(str::to_owned)
}

pub fn exchange(
    window: &WebviewWindow,
    state: &ServiceState,
    token: &str,
    frames: Vec<Value>,
    fault: bool,
) -> Result<Vec<Value>, String> {
    if !window.url().is_ok_and(|url| trusted_location(&url)) {
        return Err("transport_caller_denied".into());
    }
    let pid = state
        .sidecar_pid
        .lock()
        .map_err(|_| "transport_lock_failed")?
        .ok_or("transport_retired")?;
    let result = {
        let mut registered = state
            .desktop_transport
            .lock()
            .map_err(|_| "transport_lock_failed")?;
        let host = registered.as_mut().ok_or("transport_retired")?;
        host.binding.exchange(pid, window.label(), token, frames)
    };
    let (replies, requests) = match result {
        Ok(result) if !fault => result,
        Err("transport_caller_denied") => return Err("transport_caller_denied".into()),
        _ => {
            retire(state, Some(pid), true);
            return Err("transport_quarantined".into());
        }
    };
    for reply in replies {
        if send_to_process(state, pid, &reply).is_err() {
            retire(state, Some(pid), true);
            return Err("transport_pipe_failed".into());
        }
    }
    Ok(requests)
}

fn send_to_process(state: &ServiceState, pid: u32, value: &Value) -> Result<(), ()> {
    let encoded = frame(value).map_err(|_| ())?;
    let mut child = state.child.lock().map_err(|_| ())?;
    child
        .as_mut()
        .filter(|child| child.pid() == pid)
        .ok_or(())?
        .write(&encoded)
        .map_err(|_| ())
}

pub fn retire(state: &ServiceState, pid: Option<u32>, notify: bool) {
    let host = state.desktop_transport.lock().ok().and_then(|mut current| {
        if current
            .as_ref()
            .is_some_and(|host| pid.is_none_or(|pid| host.binding.pid() == pid))
        {
            current.take()
        } else {
            None
        }
    });
    if let Some(host) = host {
        if let Some(window) = host.window {
            let _ = window.close();
        }
        if let Some(fault) = host.binding.fault().filter(|_| notify) {
            // A pipe writer cannot block a window event or prevent exact host disposal.
            let state = state.clone();
            let pid = host.binding.pid();
            std::thread::spawn(move || {
                let _ = send_to_process(&state, pid, &fault);
            });
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn only_the_fixed_local_host_document_can_use_private_commands() {
        for allowed in [
            "tauri://localhost/transport-host.html",
            "http://tauri.localhost/transport-host.html",
        ] {
            assert!(trusted_location(&tauri::Url::parse(allowed).unwrap()));
        }
        for denied in [
            "https://example.com/transport-host.html",
            "tauri://localhost/index.html",
            "tauri://localhost/transport-host.html?caller=trusted",
            "tauri://localhost/transport-host.html#host",
            "http://tauri.localhost:9999/transport-host.html",
            "https://user@tauri.localhost/transport-host.html",
        ] {
            assert!(
                !trusted_location(&tauri::Url::parse(denied).unwrap()),
                "accepted {denied}"
            );
        }
    }
}

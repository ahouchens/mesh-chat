//! Trusted window registration and inherited-pipe routing. No peer policy.
use crate::{desktop_transport_broker::Binding, frame, ServiceState};
use serde_json::Value;
use tauri::{AppHandle, WebviewUrl, WebviewWindow, WebviewWindowBuilder};

pub struct RegisteredHost {
    binding: Binding,
    window: Option<WebviewWindow>,
}

impl RegisteredHost {
    pub fn pid(&self) -> u32 {
        self.binding.pid()
    }
    pub fn close(self) {
        if let Some(window) = self.window {
            let _ = window.close();
        }
    }
}

#[cfg(feature = "transport-qualification")]
pub fn diagnostics(state: &ServiceState) -> Value {
    state
        .desktop_transport
        .lock()
        .ok()
        .and_then(|host| host.as_ref().map(|host| host.binding.diagnostics()))
        .unwrap_or_else(|| serde_json::json!({"registered":false}))
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
    let label = format!("mesh-transport-{}", uuid::Uuid::new_v4().simple());
    let token = uuid::Uuid::new_v4().simple().to_string();
    let bootstrap = serde_json::json!({"token": token}).to_string();
    let process = state
        .sidecar_pid
        .lock()
        .map_err(|_| "transport_lock_failed")?;
    if *process != Some(pid) {
        return Err("transport_retired".into());
    }
    {
        let mut registered = state
            .desktop_transport
            .lock()
            .map_err(|_| "transport_lock_failed")?;
        if let Some(host) = registered
            .as_mut()
            .filter(|host| host.window.is_some() && host.binding.suspended())
        {
            host.binding.rebind(pid).map_err(str::to_owned)?;
            return Ok(());
        }
    }
    let previous = state
        .desktop_transport
        .lock()
        .map_err(|_| "transport_lock_failed")?
        .replace(RegisteredHost {
            binding: Binding::new(pid, label.clone(), token),
            window: None,
        });
    drop(process);
    if let Some(previous) = previous {
        previous.close();
    }
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
    let event_label = label.clone();
    window.on_window_event(move |event| {
        if matches!(event, tauri::WindowEvent::Destroyed) {
            retire_window(&event_state, &event_label);
        }
    });
    let mut registered = state
        .desktop_transport
        .lock()
        .map_err(|_| "transport_lock_failed")?;
    if let Some(host) = registered
        .as_mut()
        .filter(|host| host.binding.label() == label)
    {
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
    let process = state
        .sidecar_pid
        .lock()
        .map_err(|_| "transport_lock_failed")?;
    let (pid, result) = {
        let mut registered = state
            .desktop_transport
            .lock()
            .map_err(|_| "transport_lock_failed")?;
        let host = registered.as_mut().ok_or("transport_retired")?;
        let pid = host.binding.poll_process(*process).map_err(str::to_owned)?;
        (
            pid,
            host.binding.exchange(pid, window.label(), token, frames),
        )
    };
    drop(process);
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

pub fn detach(state: &ServiceState, pid: Option<u32>) -> Option<RegisteredHost> {
    state.desktop_transport.lock().ok().and_then(|mut current| {
        if current
            .as_ref()
            .is_some_and(|host| pid.is_none_or(|pid| host.binding.pid() == pid))
        {
            current.take()
        } else {
            None
        }
    })
}

pub fn suspend(state: &ServiceState, pid: u32) -> bool {
    state
        .desktop_transport
        .lock()
        .ok()
        .is_some_and(|mut current| {
            current
                .as_mut()
                .is_some_and(|host| host.window.is_some() && host.binding.suspend(pid).is_ok())
        })
}

fn retire_window(state: &ServiceState, label: &str) {
    let host = state.desktop_transport.lock().ok().and_then(|mut current| {
        if current
            .as_ref()
            .is_some_and(|host| host.binding.label() == label)
        {
            current.take()
        } else {
            None
        }
    });
    dispose(state, host, true);
}

pub fn retire(state: &ServiceState, pid: Option<u32>, notify: bool) {
    let host = detach(state, pid);
    dispose(state, host, notify);
}

fn dispose(state: &ServiceState, host: Option<RegisteredHost>, notify: bool) {
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
    fn explicit_shutdown_disposes_a_suspended_host_without_a_live_process() {
        let state = ServiceState::default();
        let mut binding = Binding::new(42, "retained".into(), "token".into());
        binding.suspend(42).unwrap();
        *state.desktop_transport.lock().unwrap() = Some(RegisteredHost {
            binding,
            window: None,
        });
        assert!(crate::detach_service(&state, Some(42)).is_none());
        let detached = crate::detach_service(&state, None).unwrap();
        assert!(!detached.process_present);
        assert!(detached.transport.is_some());
        assert!(state.desktop_transport.lock().unwrap().is_none());
        detached.dispose(true);
    }

    #[test]
    fn destroyed_window_is_fenced_by_its_identity_after_process_rebinding() {
        let state = ServiceState::default();
        let mut binding = Binding::new(42, "retained".into(), "token".into());
        binding.suspend(42).unwrap();
        binding.rebind(43).unwrap();
        *state.desktop_transport.lock().unwrap() = Some(RegisteredHost {
            binding,
            window: None,
        });
        retire_window(&state, "obsolete");
        assert_eq!(
            state
                .desktop_transport
                .lock()
                .unwrap()
                .as_ref()
                .unwrap()
                .pid(),
            43
        );
        retire_window(&state, "retained");
        assert!(state.desktop_transport.lock().unwrap().is_none());
    }

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

//! Android's private native/service pump. Never routes through renderer polling.
use crate::{direct_native::NativeHost, mobile_result};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc, Mutex,
};
use tauri::{AppHandle, Manager};
use tauri_plugin_mesh_runtime::{DirectExchangeRequest, MeshRuntimeExt};

struct Pump {
    stop: Arc<AtomicBool>,
    host: NativeHost,
}
#[derive(Default)]
pub struct MobileDirect(Mutex<Option<Pump>>);

impl MobileDirect {
    pub fn stop(&self) {
        if let Ok(mut pump) = self.0.lock() {
            if let Some(pump) = pump.take() {
                pump.stop.store(true, Ordering::Release);
                pump.host.close();
            }
        }
    }
    pub fn start(&self, app: AppHandle) {
        let Ok(mut current) = self.0.lock() else {
            return;
        };
        if current.is_some() {
            return;
        }
        let stop = Arc::new(AtomicBool::new(false));
        let host = NativeHost::default();
        *current = Some(Pump {
            stop: stop.clone(),
            host: host.clone(),
        });
        tauri::async_runtime::spawn(async move {
            let mut responses = vec![];
            while !stop.load(Ordering::Acquire) {
                let request = DirectExchangeRequest {
                    json: serde_json::json!({"responses":responses}).to_string(),
                };
                let caller = app.clone();
                let exchange = tauri::async_runtime::spawn_blocking(move || {
                    caller
                        .mesh_runtime()
                        .direct_exchange(request)
                        .map_err(|_| "direct_exchange_failed".to_owned())
                        .and_then(mobile_result)
                })
                .await;
                let Ok(Ok(value)) = exchange else {
                    break;
                };
                let Some(requests) = value.as_array().filter(|items| items.len() <= 1) else {
                    break;
                };
                if stop.load(Ordering::Acquire) {
                    break;
                }
                responses = requests
                    .iter()
                    .map(|request| host.handle(request.clone()))
                    .collect();
                tokio::time::sleep(std::time::Duration::from_millis(if responses.is_empty() {
                    250
                } else {
                    25
                }))
                .await;
            }
            host.close();
            // Restart requires explicit service lock/unlock after a broken pump.
        });
    }
}

pub fn start(app: &AppHandle) {
    app.state::<MobileDirect>().start(app.clone());
}
pub fn stop(app: &AppHandle) {
    app.state::<MobileDirect>().stop();
}

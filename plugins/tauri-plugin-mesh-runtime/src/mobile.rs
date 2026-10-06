use serde::de::DeserializeOwned;
use tauri::{
    plugin::{PluginApi, PluginHandle},
    AppHandle, Runtime,
};

use crate::{models::*, Result};

#[cfg(target_os = "ios")]
tauri::ios_plugin_binding!(init_plugin_mesh_runtime);

pub fn init<R: Runtime, C: DeserializeOwned>(
    _app: &AppHandle<R>,
    api: PluginApi<R, C>,
) -> Result<MeshRuntime<R>> {
    #[cfg(target_os = "android")]
    let handle = api.register_android_plugin("com.meshchat.runtime", "MeshRuntimePlugin")?;
    #[cfg(target_os = "ios")]
    let handle = api.register_ios_plugin(init_plugin_mesh_runtime)?;
    Ok(MeshRuntime(handle))
}

pub struct MeshRuntime<R: Runtime>(PluginHandle<R>);

impl<R: Runtime> MeshRuntime<R> {
    pub fn initialize(&self, payload: InitializeRequest) -> Result<NativeResponse> {
        Ok(self.0.run_mobile_plugin("initialize", payload)?)
    }

    pub fn command(&self, payload: CommandRequest) -> Result<NativeResponse> {
        Ok(self.0.run_mobile_plugin("command", payload)?)
    }

    pub fn drain_events(&self) -> Result<NativeResponse> {
        Ok(self.0.run_mobile_plugin("drainEvents", ())?)
    }

    pub fn shutdown(&self) -> Result<NativeResponse> {
        Ok(self.0.run_mobile_plugin("shutdown", ())?)
    }
}

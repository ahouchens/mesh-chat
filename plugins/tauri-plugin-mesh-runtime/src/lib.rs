use tauri::{
    plugin::{Builder, TauriPlugin},
    Manager, Runtime,
};

mod error;
mod models;

#[cfg(mobile)]
mod mobile;

pub use error::{Error, Result};
pub use models::*;

#[cfg(mobile)]
pub use mobile::MeshRuntime;

pub trait MeshRuntimeExt<R: Runtime> {
    fn mesh_runtime(&self) -> &MeshRuntime<R>;
}

impl<R: Runtime, T: Manager<R>> MeshRuntimeExt<R> for T {
    fn mesh_runtime(&self) -> &MeshRuntime<R> {
        self.state::<MeshRuntime<R>>().inner()
    }
}

pub fn init<R: Runtime>() -> TauriPlugin<R> {
    Builder::new("mesh-runtime")
        .setup(|app, api| {
            #[cfg(mobile)]
            app.manage(mobile::init(app, api)?);
            Ok(())
        })
        .build()
}

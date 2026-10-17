//! CI-only inherited-pipe executable using the exact shipping private dispatcher.
//! No Tauri/renderer/control listener, and no additional network protocol.
#[path = "../../../src-tauri/src/direct_native.rs"]
mod direct_native;
use std::io::{Read, Write};

#[tokio::main(worker_threads = 2)]
async fn main() {
    let host = direct_native::NativeHost::default();
    let mut input = std::io::stdin().lock();
    let mut output = std::io::stdout().lock();
    loop {
        let mut header = [0u8; 4];
        if input.read_exact(&mut header).is_err() {
            break;
        }
        let size = u32::from_be_bytes(header) as usize;
        if !(2..=65536).contains(&size) {
            break;
        }
        let mut data = vec![0u8; size];
        if input.read_exact(&mut data).is_err() {
            break;
        }
        let Ok(value) = serde_json::from_slice(&data) else {
            break;
        };
        let Ok(response) = serde_json::to_vec(&host.handle(value)) else {
            break;
        };
        if response.len() > 65536 {
            break;
        }
        if output
            .write_all(&(response.len() as u32).to_be_bytes())
            .is_err()
            || output.write_all(&response).is_err()
            || output.flush().is_err()
        {
            break;
        }
    }
    host.close();
}

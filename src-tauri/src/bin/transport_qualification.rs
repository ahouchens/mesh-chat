#[cfg(windows)]
fn main() {
    std::process::exit(mesh_chat_lib::run_desktop_transport_qualification());
}

#[cfg(not(windows))]
fn main() {
    std::process::exit(2);
}

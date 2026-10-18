fn main() {
    println!("cargo:rerun-if-env-changed=GITHUB_SHA");
    let commit = std::env::var("GITHUB_SHA").ok().filter(|value|
        value.len() == 40 && value.bytes().all(|byte| byte.is_ascii_hexdigit()));
    println!("cargo:rustc-env=MESH_BUILD_COMMIT={}", commit.as_deref().unwrap_or("unavailable"));
    tauri_build::build()
}

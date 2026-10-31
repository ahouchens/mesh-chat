fn main() {
    println!("cargo:rerun-if-env-changed=GITHUB_SHA");
    let commit = std::env::var("GITHUB_SHA")
        .ok()
        .filter(|value| value.len() == 40 && value.bytes().all(|byte| byte.is_ascii_hexdigit()));
    println!(
        "cargo:rustc-env=MESH_BUILD_COMMIT={}",
        commit.as_deref().unwrap_or("unavailable")
    );
    tauri_build::build();
    if std::env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("windows")
        && std::env::var("CARGO_CFG_TARGET_ENV").as_deref() == Ok("msvc")
    {
        // Unit-test executables do not get Tauri's application resource. Once
        // they link window disposal, Common Controls v6 must be selected at load.
        println!("cargo:rustc-link-arg=/MANIFEST:EMBED");
        println!("cargo:rustc-link-arg=/MANIFESTDEPENDENCY:type='win32' name='Microsoft.Windows.Common-Controls' version='6.0.0.0' processorArchitecture='*' publicKeyToken='6595b64144ccf1df' language='*'");
        // Tauri already embeds a complete manifest in each application binary.
        // Generating another resource with ID 1 would collide with that resource.
        println!("cargo:rustc-link-arg-bins=/MANIFEST:NO");
    }
}

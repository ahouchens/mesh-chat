// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "tauri-plugin-mesh-runtime",
    platforms: [.iOS(.v15)],
    products: [
        .library(
            name: "tauri-plugin-mesh-runtime",
            type: .static,
            targets: ["tauri-plugin-mesh-runtime"]
        )
    ],
    dependencies: [
        .package(name: "Tauri", path: "../.tauri/tauri-api")
    ],
    targets: [
        .binaryTarget(name: "Python", path: "Frameworks/Python.xcframework"),
        .target(
            name: "PythonBridge",
            dependencies: ["Python"],
            path: "Sources/PythonBridge",
            publicHeadersPath: "include",
            cSettings: [.headerSearchPath("include")]
        ),
        .target(
            name: "tauri-plugin-mesh-runtime",
            dependencies: [
                .byName(name: "Tauri"),
                .byName(name: "PythonBridge")
            ],
            path: "Sources/MeshRuntimePlugin"
        )
    ]
)

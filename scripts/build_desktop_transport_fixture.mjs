// Bundle the production transport for real Chromium/JNI instrumentation only.
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
import { build } from "vite";

const root = fileURLToPath(new URL("../", import.meta.url));
await build({
  configFile: false,
  root,
  build: {
    outDir: resolve(root, "plugins/tauri-plugin-mesh-runtime/android/build/generated/transport-test-assets"),
    emptyOutDir: false,
    target: "es2022",
    minify: false,
    lib: {
      entry: resolve(root, "src/desktop-transport.ts"),
      name: "MeshDesktopTransport",
      formats: ["iife"],
      fileName: () => "desktop-transport.js",
    },
  },
});

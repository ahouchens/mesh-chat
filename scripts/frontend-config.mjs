import react from "@vitejs/plugin-react";

export const frontendEntries = { main: "index.html", transport: "transport-host.html" };

/** Shared by the dev server and the cached production build. */
export function frontendConfig() {
  return {
    plugins: [react()],
    clearScreen: false,
    server: { strictPort: true, port: 1420 },
    envPrefix: ["VITE_", "TAURI_ENV_*"],
    build: {
      rollupOptions: { input: frontendEntries },
      outDir: "dist/web",
      target: ["es2022", "chrome105", "safari13"],
      minify: process.env.TAURI_ENV_DEBUG ? false : "esbuild",
      sourcemap: Boolean(process.env.TAURI_ENV_DEBUG),
    },
  };
}

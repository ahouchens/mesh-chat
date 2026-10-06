import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "jsdom",
    exclude: [
      "node_modules/**",
      "dist/**",
      "service/**",
      ".venv/**",
      "src-tauri/**",
      "plugins/**",
      ".test-tmp/**",
    ],
  },
});

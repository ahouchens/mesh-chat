import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "jsdom",
    include: [
      "src/**/*.test.ts",
      "src/**/*.test.tsx",
      "src/**/*.spec.ts",
      "src/**/*.spec.tsx",
    ],
    exclude: [
      "node_modules/**",
      "dist/**",
      "service/**",
      ".venv/**",
      "src-tauri/**",
      "plugins/**",
      ".test-tmp/**",
      "scripts/**",
    ],
  },
});

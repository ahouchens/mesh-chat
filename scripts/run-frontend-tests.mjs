import { startVitest } from "vitest/node";

const context = await startVitest(
  "test",
  ["src"],
  {
    config: false,
    environment: "jsdom",
    exclude: [
      "node_modules/**",
      "dist/**",
      ".test-tmp/**",
      "service/**",
      ".venv/**",
      "src-tauri/**",
      "plugins/**",
    ],
    root: process.cwd(),
    run: true,
    watch: false,
  },
);

if (!context) process.exitCode = 1;

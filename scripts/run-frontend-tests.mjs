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
      "sdk/**",
      // A sandboxed pytest run can leave these cache directories with ACLs
      // this user cannot traverse. They never contain frontend tests, and an
      // EPERM during the directory scan aborts the whole Vitest run.
      ".pytest_cache/**",
      "**/pytest-cache-files-*/**",
    ],
    root: process.cwd(),
    run: true,
    watch: false,
  },
);

if (!context) process.exitCode = 1;

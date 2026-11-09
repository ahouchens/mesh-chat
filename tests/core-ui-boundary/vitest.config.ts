import { defineConfig } from "vitest/config";

export default defineConfig({
  esbuild: { jsx: "automatic" },
  test: {
    environment: "jsdom",
    include: ["tests/core-ui-boundary/**/*.test.ts", "tests/core-ui-boundary/**/*.test.tsx"],
    testTimeout: 15000,
    hookTimeout: 15000,
    poolOptions: { forks: { singleFork: true } },
  },
});

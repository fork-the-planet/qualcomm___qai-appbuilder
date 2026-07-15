/**
 * Vitest configuration.
 *
 * Extracted from `vite.config.ts` in S5 PR-050 so the build/dev config
 * stays narrow. Test runner uses `happy-dom` (lighter than jsdom and
 * approved by the new frontend stack).
 */
import { defineConfig } from "vitest/config";
import vue from "@vitejs/plugin-vue";
import { fileURLToPath, URL } from "node:url";

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    globals: true,
    environment: "happy-dom",
    setupFiles: ["./tests/setup.ts"],
    include: ["src/**/*.spec.ts", "src/**/__tests__/**/*.spec.ts"],
    coverage: {
      provider: "v8",
      reporter: ["text", "html", "lcov"],
      exclude: [
        "node_modules/**",
        "dist/**",
        "js/**",
        "css/**",
        "vendor/**",
        "locales/**",
        "src/types/api.ts",
        "**/*.d.ts",
      ],
    },
  },
});

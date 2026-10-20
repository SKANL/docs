import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    rollupOptions: {
      // React is ~45% of the initial bytes and changes far less often than app code: its own long-cached chunk keeps the entry chunk to app + router + query.
      output: { manualChunks: id => (/node_modules[\/](react|react-dom|scheduler)[\/]/.test(id) ? "react" : undefined) },
    },
  },
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  test: {
    exclude: ["e2e/**", "node_modules/**"],
    setupFiles: ["./src/test/setup.ts"],
    css: { include: [/globals.css/] },
    // Under full-suite load (single worker, jsdom, lazy routes + i18n) a first render takes several seconds; vitest's 5s test / testing-library's 1s findBy defaults flake. Raised once here and in setup.ts.
    testTimeout: 20000,
    hookTimeout: 20000,
    pool: "threads",
    maxWorkers: 1,
    minWorkers: 1,
  },
});

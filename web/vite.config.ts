/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Everything under /api goes to Django. This removes CORS from the problem
    // entirely during development.
    proxy: {
      "/api": { target: process.env.API_PROXY_TARGET ?? "http://localhost:8000", changeOrigin: true },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/setupTests.ts",
    exclude: ["node_modules/**", "e2e/**"],
    coverage: {
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/**/*.test.*", "src/**/__mocks__/**", "src/setupTests.ts"],
      thresholds: { lines: 99, statements: 99, functions: 98, branches: 93 },
    },
  },
});

/// <reference types="vitest" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The development server proxies /api to the Python chart service, so the
// browser sees one origin in development and no CORS preflight at all. In a
// built deployment the same service serves this bundle, which is also one
// origin. The proxy target is the service's own default port; change it here
// if you start the service elsewhere.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8788",
        changeOrigin: false,
      },
    },
  },
  build: {
    target: "es2022",
    sourcemap: true,
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
  },
});

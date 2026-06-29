import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Build to ./dist (served by Flask). Use relative asset paths so the bundle
// works when served from the Flask root. During `npm run dev`, /api calls are
// proxied to the Flask server on :5000.
export default defineConfig({
  plugins: [react()],
  base: "./",
  build: {
    outDir: "dist",
    // The mounted workspace blocks file deletion, so don't empty the dir and
    // use stable (un-hashed) filenames so each build overwrites in place.
    emptyOutDir: false,
    rollupOptions: {
      output: {
        entryFileNames: "assets/index.js",
        chunkFileNames: "assets/[name].js",
        assetFileNames: "assets/index.[ext]",
      },
    },
  },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:5001",
    },
  },
});

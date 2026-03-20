import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://localhost:8005",
      "/portraits": "http://localhost:8005",
      "/backgrounds": "http://localhost:8005",
      "/generated-images": "http://localhost:8005",
      "/layout-images": "http://localhost:8005",
    },
  },
  build: {
    outDir: "dist",
  },
});

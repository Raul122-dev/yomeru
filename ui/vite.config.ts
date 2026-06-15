import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: "/ui/",
  build: {
    outDir: "../src/yomeru/static",
    emptyOutDir: true,
  },
  server: {
    port: 3000,
    proxy: {
      "/api": { target: "http://localhost:7788", changeOrigin: true, ws: true },
    },
  },
});

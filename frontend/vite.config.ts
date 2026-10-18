import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const API = "http://127.0.0.1:8010";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // decodeURIComponent: the project path contains spaces.
  resolve: { alias: { "@": decodeURIComponent(new URL("./src", import.meta.url).pathname) } },
  server: {
    port: 5190,
    strictPort: true,
    proxy: {
      "/api": { target: API, rewrite: (path) => path.replace(/^\/api/, "") },
      "/ws": { target: API, ws: true },
    },
  },
});

import preact from "@preact/preset-vite";
import { defineConfig } from "vite";

// Assets are served by the Python server under /static/ (src/open_hypergamy/gui/app.py).
export default defineConfig({
  base: "/static/",
  plugins: [preact()],
  build: {
    outDir: "../src/open_hypergamy/gui/static",
    emptyOutDir: true,
    assetsInlineLimit: 0, // CSP: no data: scripts or fonts
    sourcemap: false,
    target: "es2022",
  },
});

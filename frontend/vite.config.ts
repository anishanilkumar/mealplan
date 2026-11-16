import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: ["icon.svg", "apple-touch-icon.png"],
      manifest: {
        name: "Mealplan",
        short_name: "Plan",
        description: "The week's meals, from the recipe book.",
        theme_color: "#0a0e14",
        background_color: "#0a0e14",
        display: "standalone",
        orientation: "portrait",
        start_url: "/",
        icons: [
          { src: "icon-192.png", sizes: "192x192", type: "image/png" },
          { src: "icon-512.png", sizes: "512x512", type: "image/png" },
          { src: "icon-512-maskable.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
        ],
      },
      workbox: {
        globPatterns: ["**/*.{js,css,html,svg,png,woff2}"],
        // As Recipie's: /auth and /api must reach the server, or signing in
        // would be impossible behind a cached index.html.
        navigateFallback: "/index.html",
        navigateFallbackDenylist: [/^\/auth\//, /^\/api\//],
      },
    }),
  ],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8796",
      "/auth": "http://127.0.0.1:8796",
    },
    fs: { allow: [".."] },
  },
  test: {
    environment: "node",
  },
});

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In Docker, API_URL points to the backend container; locally to localhost.
const apiUrl = process.env.API_URL ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Polling, because file changes from Windows don't reach the container otherwise
    watch: { usePolling: true },
    proxy: { "/api": apiUrl },
  },
});

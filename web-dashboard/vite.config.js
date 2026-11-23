import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// `npm run dev` (port 5173) forwards API + camera stream to the Python server.
// For normal use run `npm run build` once; main.py then serves web-dashboard/dist.
const backend = 'http://127.0.0.1:8000';

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': backend,
      '/video_feed': backend,
    },
  },
});

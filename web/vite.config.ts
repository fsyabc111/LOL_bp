import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Dev server proxies the API; the production build is served by FastAPI from web/dist.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { '/api': 'http://127.0.0.1:8000' } },
});

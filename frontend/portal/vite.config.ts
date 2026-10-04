import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
export default defineConfig({ plugins: [react(), tailwindcss()], server: { port: 5174, strictPort: true, proxy: { '/portal-api': { target: 'http://127.0.0.1:8082', changeOrigin: true, rewrite: path => path.replace(/^\/portal-api/, '') } } }, preview: { proxy: { '/portal-api': { target: 'http://127.0.0.1:8082', changeOrigin: true, rewrite: path => path.replace(/^\/portal-api/, '') } } }, build: { rollupOptions: { output: { manualChunks(id) { if (id.includes('node_modules') && /recharts|d3-|victory-vendor/.test(id)) return 'charts'; } } } } });

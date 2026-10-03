import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
export default defineConfig({ plugins: [react(), tailwindcss()], server: { port: 5174, strictPort: true }, build: { rollupOptions: { output: { manualChunks(id) { if (id.includes('node_modules') && /recharts|d3-|victory-vendor/.test(id)) return 'charts'; } } } } });

import path from "path"
import tailwindcss from "@tailwindcss/vite"
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // Load env file based on `mode` in the current working directory.
  const env = loadEnv(mode, process.cwd(), '')
  
  // Backend target for vite dev server proxy
  // Can be configured via VITE_DEV_PROXY_TARGET in .env file
  const proxyTarget = env.VITE_DEV_PROXY_TARGET || 'http://127.0.0.1:8080'
  
  console.log('[Vite Proxy] Target:', proxyTarget)

  return {
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "./src"),
        "~": path.resolve(__dirname, "./src"),
      },
    },
    server: {
      proxy: {
        "/api": {
          target: proxyTarget,
          changeOrigin: true,
          secure: false,
          configure: (proxy, _options) => {
            proxy.on('error', (err, _req, _res) => {
              console.log('[Proxy Error]', err.message);
            });
            proxy.on('proxyReq', (_proxyReq, req, _res) => {
              console.log('[Proxy Request]', req.method, req.url, '->', proxyTarget);
            });
            proxy.on('proxyRes', (_proxyRes, req, _res) => {
              console.log('[Proxy Response]', req.url);
            });
          },
        },
      },
    },
  }
})

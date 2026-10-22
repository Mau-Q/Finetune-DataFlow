import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const backend = new URL(process.env.DATAFLOW_DEV_BACKEND || 'http://127.0.0.1:8001').origin

// https://vitejs.dev/config/
export default defineConfig({
    base: './',
    plugins: [
        vue(),
    ],
    resolve: {
        alias: {
            '@': fileURLToPath(new URL('./src', import.meta.url))
        }
    },
    css: {
        preprocessorOptions: {
            scss: {
                additionalData: `@use "@/style/global.scss" as *;`
            }
        }
    },
    server: {
        host: '127.0.0.1',
        strictPort: true,
        proxy: Object.fromEntries(['/api', '/team'].map(prefix => [prefix, {
            target: backend,
            changeOrigin: true,
            configure(proxy) {
                proxy.on('proxyReq', (outgoing, incoming) => {
                    // Preserve the gateway's same-origin check across the local
                    // Vite proxy; foreign origins must still be rejected.
                    if (incoming.headers.origin === `http://${incoming.headers.host}`) {
                        outgoing.setHeader('origin', backend)
                    }
                })
            }
        }]))
    }
})

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      '/forms': 'http://127.0.0.1:8000',
      '/tasks': 'http://127.0.0.1:8000',
      '/external-systems': 'http://127.0.0.1:8000',
      '/demo': 'http://127.0.0.1:8000',
      '/ai': 'http://127.0.0.1:8000',
      '/health': 'http://127.0.0.1:8000',
    },
  },
})

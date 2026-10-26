import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/students': 'http://127.0.0.1:8000',
      '/tasks': 'http://127.0.0.1:8000',
      '/sessions': 'http://127.0.0.1:8000',
    },
  },
})

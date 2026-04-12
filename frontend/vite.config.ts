import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import { readFileSync } from 'fs'

// Read from root VERSION file (repo root is one level up from frontend/)
// Falls back to package.json version for safety
function readVersion(): string {
  try {
    return readFileSync('../VERSION', 'utf-8').trim()
  } catch {
    return JSON.parse(readFileSync('./package.json', 'utf-8')).version
  }
}
const version = readVersion()

// https://vitejs.dev/config/
export default defineConfig({
  define: {
    __APP_VERSION__: JSON.stringify(version),
  },
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})

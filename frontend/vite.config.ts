import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

// 路径含中文/空格时，vite 自动发现 postcss.config.js / tailwind.config.js 偶尔会
// 拿到 tailwind 默认 theme（自定义 air.* 颜色因此"不存在"）。这里显式声明 postcss
// 路径强制使用项目根的配置文件。
const __dirname = path.dirname(fileURLToPath(import.meta.url))

export default defineConfig({
  plugins: [react()],
  base: process.env.VITE_BASE_PATH || '/',
  css: {
    postcss: path.resolve(__dirname, 'postcss.config.cjs'),
  },
  server: {
    port: 5199,
    proxy: {
      '/api': 'http://localhost:8765',
    },
  },
  cacheDir: path.resolve(__dirname, 'node_modules/.vite'),
})

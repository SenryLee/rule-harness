/**
 * 用 .cjs（CommonJS）后缀避免 package.json "type": "module" 让 vite 在
 * 含中文路径下走 ESM 解析时丢失 tailwind 自定义 theme 的问题。
 */
module.exports = {
  plugins: {
    tailwindcss: { config: require('path').resolve(__dirname, 'tailwind.config.cjs') },
    autoprefixer: {},
  },
}

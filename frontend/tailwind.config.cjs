/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        apple: {
          black: '#1d1d1f',
          gray: {
            1: '#424245',
            2: '#6e6e73',
            3: '#86868b',
            4: '#d2d2d7',
            5: '#f5f5f7',
            6: '#fbfbfd',
          },
          blue: '#0071e3',
          'blue-hover': '#147ce5',
          red: '#bf4800',
          amber: '#b25000',
          green: '#007a3d',
        },
      },
      fontFamily: {
        display: ['-apple-system', 'SF Pro Display', 'Inter', 'Noto Sans SC', 'sans-serif'],
        body: ['-apple-system', 'SF Pro Text', 'Inter', 'Noto Sans SC', 'sans-serif'],
        mono: ['SF Mono', 'JetBrains Mono', 'monospace'],
      },
      borderRadius: {
        card: '12px',
        input: '8px',
        btn: '8px',
      },
      boxShadow: {
        card: '0 0 0 1px rgba(0,0,0,0.04), 0 1px 2px rgba(0,0,0,0.04)',
        popover: '0 4px 12px rgba(0,0,0,0.08), 0 0 0 1px rgba(0,0,0,0.04)',
      },
      maxWidth: {
        content: '1080px',
      },
      animation: {
        'page-in': 'pageIn 0.4s cubic-bezier(0.25, 0.1, 0.25, 1)',
        'fade-in': 'fadeIn 0.3s ease-out',
        'slide-up': 'slideUp 0.3s ease-out',
        'drawer-in': 'drawerIn 0.35s cubic-bezier(0.32, 0.72, 0, 1)',
      },
      keyframes: {
        pageIn: {
          '0%': { opacity: '0', transform: 'translateY(12px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        slideUp: {
          '0%': { opacity: '0', transform: 'translateY(8px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        drawerIn: {
          '0%': { transform: 'translateX(100%)' },
          '100%': { transform: 'translateX(0)' },
        },
      },
    },
  },
  plugins: [],
}

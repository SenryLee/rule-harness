/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        air: {
          bg: '#FFFFFF',
          muted: '#F8FAFC',
          hover: '#F1F5F9',
          border: '#E2E8F0',
          'border-accent': '#BFDBFE',
        },
        primary: {
          DEFAULT: '#2563EB',
          hover: '#3B82F6',
          light: '#DBEAFE',
          soft: '#EFF6FF',
        },
        accent: {
          DEFAULT: '#0EA5E9',
          hover: '#38BDF8',
          light: '#E0F2FE',
        },
      },
      fontFamily: {
        display: ['Inter', 'sans-serif'],
        body: ['Inter', 'Noto Sans SC', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
      borderRadius: {
        card: '12px',
        input: '8px',
        btn: '8px',
      },
      boxShadow: {
        card: '0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04)',
        popover: '0 4px 12px rgba(0,0,0,0.08)',
        glow: '0 0 0 3px rgba(37,99,235,0.15)',
      },
      animation: {
        'slide-in': 'slideIn 0.25s ease-out',
        'fade-in': 'fadeIn 0.2s ease-out',
      },
      keyframes: {
        slideIn: {
          '0%': { transform: 'translateX(16px)', opacity: '0' },
          '100%': { transform: 'translateX(0)', opacity: '1' },
        },
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
      },
    },
  },
  plugins: [],
}

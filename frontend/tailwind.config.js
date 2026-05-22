/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        codex: {
          bg: '#0B1121',
          'bg-secondary': '#111827',
          'bg-tertiary': '#1A2332',
          surface: '#1E293B',
          border: '#2D3A4A',
          'text-primary': '#F1F5F9',
          'text-secondary': '#94A3B8',
          'text-muted': '#64748B',
        },
        accent: {
          DEFAULT: '#F59E0B',
          hover: '#D97706',
          soft: 'rgba(245,158,11,0.15)',
        },
      },
      fontFamily: {
        display: ['DM Serif Display', 'Noto Serif SC', 'serif'],
        body: ['Inter', 'Noto Sans SC', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
      borderRadius: {
        input: '6px',
        card: '10px',
        modal: '14px',
        btn: '8px',
      },
      boxShadow: {
        glow: '0 0 20px rgba(245,158,11,0.12)',
        'glow-lg': '0 0 40px rgba(245,158,11,0.18)',
      },
      animation: {
        'slide-in': 'slideIn 0.2s ease-out',
        'fade-in': 'fadeIn 0.2s ease-out',
      },
      keyframes: {
        slideIn: {
          '0%': { transform: 'translateX(-8px)', opacity: '0' },
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

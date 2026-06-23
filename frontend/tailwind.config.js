/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        primary: {
          DEFAULT: 'var(--primary)',
          hover: 'var(--primary-hover)',
          light: 'var(--primary-light)',
          glow: 'var(--primary-glow)',
        },
        secondary: {
          DEFAULT: 'var(--secondary)',
          hover: 'var(--secondary-hover)',
          light: 'var(--secondary-light)',
        },
        themeBg: {
          main: 'var(--bg-main)',
          sidebar: 'var(--bg-sidebar)',
          card: 'var(--bg-card)',
          panel: 'var(--bg-panel)',
        },
        themeBorder: 'var(--border-color)',
        themeText: {
          main: 'var(--text-main)',
          muted: 'var(--text-muted)',
          light: 'var(--text-light)',
        },
        accent: {
          orange: 'var(--accent-orange)',
          red: 'var(--accent-red)',
          green: 'var(--accent-green)',
        },
      },
      borderRadius: {
        'theme-sm': 'var(--radius-sm)',
        'theme-md': 'var(--radius-md)',
        'theme-lg': 'var(--radius-lg)',
        'theme-xl': 'var(--radius-xl)',
      },
      boxShadow: {
        'theme-sm': 'var(--shadow-sm)',
        'theme-md': 'var(--shadow-md)',
        'theme-lg': 'var(--shadow-lg)',
        'theme-premium': 'var(--shadow-premium)',
      },
      animation: {
        'pulse-subtle': 'pulse 2.5s cubic-bezier(0.4, 0, 0.6, 1) infinite',
      },
    },
  },
  plugins: [],
};

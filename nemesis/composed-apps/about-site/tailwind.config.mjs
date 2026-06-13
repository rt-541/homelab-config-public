/** @type {import('tailwindcss').Config} */
export default {
  content: ['./src/**/*.{astro,html,js,ts,jsx,tsx,md,mdx}'],
  theme: {
    extend: {
      colors: {
        chrome: '#F4ECD8',
        'chrome-divider': '#D7CDB5',
        body: '#1C2A40',
        'body-deep': '#0F1622',
        'body-mid': '#2A3B54',
        muted: '#4A5C77',
        subtle: '#A6B3C9',
        ice: '#DCE4EF',
      },
      fontFamily: {
        serif: ['ui-serif', 'Georgia', '"Times New Roman"', 'serif'],
        sans: ['ui-sans-serif', 'system-ui', '-apple-system', '"Segoe UI"', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Consolas', 'monospace'],
      },
      letterSpacing: {
        'display': '-0.015em',
        'meta': '0.14em',
        'eyebrow': '0.24em',
      },
    },
  },
  plugins: [],
};

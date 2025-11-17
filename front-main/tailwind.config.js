/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        'wink-orange': {
          light: '#FE942E',
          DEFAULT: '#FE942E',
          dark: '#E97315',
        },
        'wink-black': {
          DEFAULT: '#000000',
          dark: '#0A0A0A',
          gray: '#1A1A1A',
        },
      },
      fontFamily: {
        'cofo': ['Cofo Sans', 'sans-serif'],
        'cofo-kak': ['Cofo Kak', 'sans-serif'],
        'poppins': ['Poppins', 'sans-serif'],
        'unbounded': ['Unbounded', 'sans-serif'],
      },
      backgroundImage: {
        'gradient-orange': 'linear-gradient(45deg, #FE942E 0%, #E97315 100%)',
      },
    },
  },
  plugins: [],
}


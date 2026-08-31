/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        control: {
          950: "#0b1120",
          900: "#0f172a",
          850: "#131c31",
          800: "#1e293b",
          700: "#334155",
          600: "#475569",
        },
        accent: {
          DEFAULT: "#f97316",
          soft: "#fdba74",
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
};

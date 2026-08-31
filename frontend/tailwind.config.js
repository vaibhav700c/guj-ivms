/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        control: {
          950: "#050d1a",
          900: "#091120",
          850: "#0d1a2e",
          800: "#112038",
          750: "#162844",
          700: "#1e3352",
          600: "#2d4a72",
          500: "#3d6494",
        },
        accent: {
          DEFAULT: "#f97316",
          soft: "#fdba74",
          glow: "#f9731640",
        },
        cyan: {
          glow: "#06b6d440",
        },
      },
      fontFamily: {
        sans: ["Outfit", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
      backgroundImage: {
        "grid-pattern":
          "radial-gradient(circle, #1e333820 1px, transparent 1px)",
        "hero-gradient":
          "linear-gradient(135deg, #050d1a 0%, #091a32 50%, #050d1a 100%)",
      },
      backgroundSize: {
        "grid-30": "30px 30px",
      },
      boxShadow: {
        "glow-orange": "0 0 20px #f9731630, 0 0 40px #f9731615",
        "glow-cyan": "0 0 20px #06b6d430, 0 0 40px #06b6d415",
        "glow-red": "0 0 20px #ef444430, 0 0 40px #ef444415",
        card: "0 4px 24px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.05)",
      },
      animation: {
        "slide-in-right": "slideInRight 0.3s ease-out",
        "slide-in-up": "slideInUp 0.4s ease-out",
        "fade-in": "fadeIn 0.2s ease-out",
        ticker: "ticker 30s linear infinite",
        "pulse-slow": "pulse 3s ease-in-out infinite",
        "count-up": "countUp 0.6s ease-out",
      },
      keyframes: {
        slideInRight: {
          "0%": { transform: "translateX(100%)", opacity: "0" },
          "100%": { transform: "translateX(0)", opacity: "1" },
        },
        slideInUp: {
          "0%": { transform: "translateY(20px)", opacity: "0" },
          "100%": { transform: "translateY(0)", opacity: "1" },
        },
        fadeIn: {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        ticker: {
          "0%": { transform: "translateX(100%)" },
          "100%": { transform: "translateX(-100%)" },
        },
      },
    },
  },
  plugins: [],
};

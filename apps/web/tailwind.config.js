/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      colors: {
        ink: {
          950: "#111318",
          800: "#232833",
          600: "#4b5567",
          400: "#8590a3",
        },
        ocean: {
          700: "#09677a",
          600: "#0b7890",
          500: "#1198ad",
        },
        leaf: {
          600: "#16805b",
          500: "#1fa971",
        },
        signal: {
          500: "#e2a33a",
          600: "#c37f1f",
        },
      },
      boxShadow: {
        panel: "0 1px 2px rgba(17, 19, 24, 0.05), 0 18px 48px rgba(17, 19, 24, 0.08)",
      },
    },
  },
  plugins: [],
};

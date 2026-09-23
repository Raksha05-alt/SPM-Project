/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        navy: { 700: "#1F3864", 600: "#2E5C8A", 500: "#1168BD" },
      },
    },
  },
  plugins: [],
};

/** @type {import('tailwindcss').Config} */
// Theme = CSS variables defined in src/index.css.
// Each theme overrides --color-* variables under [data-theme="..."].
export default {
  // No darkMode class — we control via data-theme attribute on <html>.
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        // Semantic colors — read CSS variables, switch with theme.
        bg:          "rgb(var(--color-bg) / <alpha-value>)",
        surface:     "rgb(var(--color-surface) / <alpha-value>)",
        "surface-2": "rgb(var(--color-surface-2) / <alpha-value>)",
        fg:          "rgb(var(--color-fg) / <alpha-value>)",
        "fg-muted":  "rgb(var(--color-fg-muted) / <alpha-value>)",
        "fg-subtle": "rgb(var(--color-fg-subtle) / <alpha-value>)",
        border:      "rgb(var(--color-border) / <alpha-value>)",

        primary: {
          DEFAULT: "rgb(var(--color-primary) / <alpha-value>)",
          fg:      "rgb(var(--color-primary-fg) / <alpha-value>)",
          soft:    "rgb(var(--color-primary-soft) / <alpha-value>)",
        },

        accent:  "rgb(var(--color-accent) / <alpha-value>)",
        success: "rgb(var(--color-success) / <alpha-value>)",
        warning: "rgb(var(--color-warning) / <alpha-value>)",
        danger:  "rgb(var(--color-danger) / <alpha-value>)",
        info:    "rgb(var(--color-info) / <alpha-value>)",
      },
      fontFamily: {
        sans:    ['"Cairo"', '"Inter"', "system-ui", "sans-serif"],
        display: ['"Tajawal"', '"Plus Jakarta Sans"', "system-ui", "sans-serif"],
        mono:    ['"JetBrains Mono"', '"Cascadia Code"', "monospace"],
      },
      borderRadius: {
        sm: "4px",
        md: "8px",
        lg: "12px",
        xl: "16px",
      },
      boxShadow: {
        sm: "0 1px 2px rgba(0,0,0,0.05)",
        md: "0 4px 6px rgba(0,0,0,0.07), 0 2px 4px rgba(0,0,0,0.06)",
        lg: "0 10px 15px rgba(0,0,0,0.1), 0 4px 6px rgba(0,0,0,0.05)",
        xl: "0 20px 25px rgba(0,0,0,0.1), 0 10px 10px rgba(0,0,0,0.04)",
      },
    },
  },
  plugins: [],
};

/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./hotspot_ms/www/**/*.html",
    "./hotspot_ms/www/**/*.py"
  ],
  theme: {
    extend: {
      colors: {
        primary: "#135bec",
        "background-light": "#f6f6f8",
        "background-dark": "#101622"
      },
      fontFamily: {
        display: [
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "Helvetica Neue",
          "Arial",
          "Noto Sans",
          "sans-serif"
        ]
      },
      borderRadius: {
        DEFAULT: "0.25rem",
        lg: "0.5rem",
        xl: "0.75rem",
        full: "9999px"
      }
    }
  },
  safelist: [
    "hidden",
    "flex",
    "bg-red-50",
    "border-red-200",
    "text-red-600",
    "bg-green-50",
    "border-green-200",
    "text-green-600",
    "text-green-700",
    "bg-green-500",
    "border-green-400",
    "bg-blue-50",
    "border-blue-200",
    "text-blue-700",
    "mt-5",
    "text-sm",
    "font-medium",
    "text-white",
    "text-slate-600",
    "text-slate-700"
  ]
};

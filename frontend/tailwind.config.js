import forms from '@tailwindcss/forms'
import containerQueries from '@tailwindcss/container-queries'

/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
          "primary-fixed": "#d6e4f9",
          "primary": "#000000",
          "on-tertiary": "#ffffff",
          "on-secondary-fixed-variant": "#3a485b",
          "on-background": "#191c1e",
          "on-primary": "#ffffff",
          "on-primary-fixed-variant": "#3a4859",
          "surface-dim": "#d8dadc",
          "surface-container-high": "#e6e8ea",
          "on-tertiary-fixed": "#00201d",
          "error-container": "#ffdad6",
          "background": "#f7f9fb",
          "on-tertiary-container": "#0c9488",
          "tertiary-fixed": "#89f5e7",
          "tertiary": "#000000",
          "primary-fixed-dim": "#bac8dc",
          "inverse-surface": "#2d3133",
          "inverse-on-surface": "#eff1f3",
          "surface-tint": "#525f71",
          "on-tertiary-fixed-variant": "#005049",
          "secondary-fixed-dim": "#b9c7df",
          "surface-container-lowest": "#ffffff",
          "surface-container": "#eceef0",
          "surface": "#f7f9fb",
          "primary-container": "#0f1c2c",
          "secondary-fixed": "#d5e3fc",
          "on-secondary": "#ffffff",
          "surface-container-highest": "#e0e3e5",
          "on-error-container": "#93000a",
          "tertiary-fixed-dim": "#6bd8cb",
          "outline-variant": "#c4c6cc",
          "on-primary-container": "#778598",
          "error": "#ba1a1a",
          "on-secondary-fixed": "#0d1c2e",
          "secondary-container": "#d5e3fc",
          "on-surface-variant": "#44474c",
          "inverse-primary": "#bac8dc",
          "surface-variant": "#e0e3e5",
          "on-primary-fixed": "#0f1c2c",
          "surface-bright": "#f7f9fb",
          "on-surface": "#191c1e",
          "outline": "#74777d",
          "on-secondary-container": "#57657a",
          "on-error": "#ffffff",
          "surface-container-low": "#f2f4f6",
          "tertiary-container": "#00201d",
          "secondary": "#515f74"
      },
      borderRadius: {
          "DEFAULT": "0.125rem",
          "lg": "0.25rem",
          "xl": "0.5rem",
          "full": "0.75rem"
      },
      fontFamily: {
          "headline": ["Manrope"],
          "body": ["Inter"],
          "label": ["Inter"]
      }
    },
  },
  plugins: [
    forms,
    containerQueries
  ],
}

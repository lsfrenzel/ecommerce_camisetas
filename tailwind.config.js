/** @type {import('tailwindcss').Config} */
const rgb = (v) => `rgb(var(${v}) / <alpha-value>)`;

module.exports = {
  darkMode: "class",
  content: [
    "./templates/**/*.html",
    "./apps/**/templates/**/*.html",
    "./apps/**/*.py",
    "./static/js/**/*.js",
  ],
  theme: {
    screens: { xs: "400px", sm: "640px", md: "768px", lg: "1024px", xl: "1280px", "2xl": "1536px" },
    extend: {
      colors: {
        bg: rgb("--c-bg"),
        surface: rgb("--c-surface"),
        fg: rgb("--c-fg"),
        muted: rgb("--c-muted"),
        line: rgb("--c-line"),
        inverse: rgb("--c-inverse"),
        "on-inverse": rgb("--c-on-inverse"),
        lime: rgb("--c-lime"),
        orange: rgb("--c-orange"),
        electric: rgb("--c-blue"),
        ink: "#171717",
        danger: rgb("--c-danger"),
        success: rgb("--c-success"),
      },
      fontFamily: {
        display: ['"Space Grotesk Variable"', '"Space Grotesk"', "system-ui", "sans-serif"],
        sans: ['"Inter Variable"', "Inter", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
      fontSize: {
        "display-xl": ["clamp(3.2rem, 11vw, 9.5rem)", { lineHeight: "0.86", letterSpacing: "-0.045em" }],
        "display-lg": ["clamp(2.5rem, 7vw, 6rem)", { lineHeight: "0.9", letterSpacing: "-0.04em" }],
        "display-md": ["clamp(2rem, 4.5vw, 3.75rem)", { lineHeight: "0.95", letterSpacing: "-0.035em" }],
      },
      maxWidth: { shell: "1440px" },
      transitionTimingFunction: { snap: "cubic-bezier(.2,.8,.2,1)" },
      aspectRatio: { product: "4 / 5", poster: "3 / 4" },
      keyframes: {
        marquee: { from: { transform: "translateX(0)" }, to: { transform: "translateX(-50%)" } },
        rise: { from: { opacity: 0, transform: "translateY(14px)" }, to: { opacity: 1, transform: "none" } },
      },
      animation: {
        marquee: "marquee 38s linear infinite",
        rise: "rise .7s cubic-bezier(.2,.8,.2,1) both",
      },
    },
  },
  plugins: [require("@tailwindcss/forms")({ strategy: "class" })],
};

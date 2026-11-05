// Copia bibliotecas JS e fontes do node_modules para static/ (versões fixadas no package.json).
const fs = require("fs");
const path = require("path");
const copies = [
  ["alpinejs/dist/cdn.min.js", "static/vendor/alpine.min.js"],
  ["htmx.org/dist/htmx.min.js", "static/vendor/htmx.min.js"],
  ["chart.js/dist/chart.umd.js", "static/vendor/chart.umd.min.js"],
  ["@fontsource-variable/inter/files/inter-latin-wght-normal.woff2", "static/fonts/inter-latin-wght-normal.woff2"],
  ["@fontsource-variable/inter/files/inter-latin-ext-wght-normal.woff2", "static/fonts/inter-latin-ext-wght-normal.woff2"],
  ["@fontsource-variable/space-grotesk/files/space-grotesk-latin-wght-normal.woff2", "static/fonts/space-grotesk-latin-wght-normal.woff2"],
  ["@fontsource-variable/space-grotesk/files/space-grotesk-latin-ext-wght-normal.woff2", "static/fonts/space-grotesk-latin-ext-wght-normal.woff2"],
];
for (const [src, dest] of copies) {
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  let data = fs.readFileSync(path.join("node_modules", src));
  if (dest.endsWith(".js")) {
    // Remove referências a source maps (não distribuídos) para o ManifestStaticFilesStorage.
    data = Buffer.from(data.toString("utf8").replace(/\/\/# sourceMappingURL=.*$/gm, ""));
  }
  fs.writeFileSync(dest, data);
  console.log("ok", dest);
}

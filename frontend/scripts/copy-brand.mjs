// Copies the runtime subset of the brand kit (design-system/openhypergamy/brand) into public/brand/,
// which Vite ships under /static/brand/ and so into the Python wheel. The overview board and README
// stay in the design system only.
import { copyFileSync, mkdirSync } from "node:fs";

const src = "../design-system/openhypergamy/brand";
const files = ["logo-symbol-auto.svg", "favicon.svg", "favicon.ico", "apple-touch-icon.png"];

mkdirSync("public/brand", { recursive: true });
for (const f of files) copyFileSync(`${src}/${f}`, `public/brand/${f}`);
console.log(`brand assets copied: ${files.length}`);

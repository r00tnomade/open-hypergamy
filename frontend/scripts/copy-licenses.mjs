// Copies the licence texts of everything bundled into the GUI (fonts: SIL OFL 1.1; Preact: MIT)
// into public/licenses/, which Vite ships next to the assets and so into the Python wheel.
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";

const bundled = [
  ["@fontsource-variable/space-grotesk", "Space Grotesk (font)"],
  ["@fontsource/ibm-plex-mono", "IBM Plex Mono (font)"],
  ["preact", "Preact (JavaScript runtime)"],
];

mkdirSync("public/licenses", { recursive: true });
const lines = [
  "Third-party software bundled in the OpenHypergamy onboarding GUI.",
  "Each licence text is in this directory, copied from the exact package version that was built.",
  "",
];
for (const [pkg, what] of bundled) {
  const dir = `node_modules/${pkg}`;
  const meta = JSON.parse(readFileSync(`${dir}/package.json`, "utf8"));
  const file = `${pkg.replace(/^@/, "").replace(/\//g, "__")}.LICENSE.txt`;
  writeFileSync(`public/licenses/${file}`, readFileSync(`${dir}/LICENSE`, "utf8"));
  lines.push(`- ${what}: ${pkg}@${meta.version}, ${meta.license}. See ${file}.`);
}
writeFileSync("public/licenses/THIRD_PARTY_NOTICES.txt", lines.join("\n") + "\n");
console.log(`licences copied for ${bundled.length} packages`);

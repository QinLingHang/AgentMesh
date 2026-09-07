import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const assetsDir = path.join(root, "dist", "assets");
assert.ok(fs.existsSync(assetsDir), "dist/assets missing; run npm run build first");

const js = fs.readdirSync(assetsDir)
  .filter((name) => name.endsWith(".js"))
  .map((name) => ({ name, bytes: fs.statSync(path.join(assetsDir, name)).size }))
  .sort((a, b) => b.bytes - a.bytes);

assert.ok(js.length >= 4, `expected at least 4 JavaScript chunks, got ${js.length}`);
const oversized = js.filter((asset) => asset.bytes > 500_000);
assert.deepEqual(
  oversized,
  [],
  `JavaScript chunks over 500 kB: ${oversized.map((asset) => `${asset.name}=${asset.bytes}`).join(", ")}`,
);

console.log("P11 Bundle Gate: PASS");
for (const asset of js) {
  console.log(`${asset.name}\t${(asset.bytes / 1000).toFixed(1)} kB`);
}

import { cp, mkdir, rm } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const dist = path.join(root, "dist");
await rm(dist, { recursive: true, force: true });
await mkdir(path.join(dist, "adapters"), { recursive: true });
for (const file of ["manifest.json", "background.js", "content.js", "field_catalog.js", "namespace.js", "orchestrator.js", "plan_policy.js", "safety_policy.js", "scanner.js", "popup.html", "popup.js"]) {
  await cp(path.join(root, file), path.join(dist, file));
}
await cp(path.join(root, "adapters"), path.join(dist, "adapters"), { recursive: true });
console.log(`Built unpacked extension at ${dist}`);

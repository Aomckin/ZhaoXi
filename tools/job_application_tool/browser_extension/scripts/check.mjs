import { execFileSync } from "node:child_process";
import { readdirSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const visit = (dir) => {
  for (const name of readdirSync(dir)) {
    if (["dist", "node_modules"].includes(name)) continue;
    const file = path.join(dir, name);
    if (statSync(file).isDirectory()) visit(file);
    else if (name.endsWith(".js")) execFileSync(process.execPath, ["--check", file], { stdio: "inherit" });
  }
};
visit(root);
console.log("JavaScript syntax check passed.");

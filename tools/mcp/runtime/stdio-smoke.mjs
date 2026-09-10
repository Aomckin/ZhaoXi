import { spawn } from "node:child_process";

const [command, ...args] = process.argv.slice(2);
if (!command) throw new Error("usage: node stdio-smoke.mjs <command> [args...]");

const child = spawn(command, args, { stdio: ["pipe", "pipe", "pipe"], env: process.env });
let buffer = "";
const replies = [];

child.stderr.on("data", chunk => process.stderr.write(chunk));

const done = new Promise((resolve, reject) => {
  const timer = setTimeout(() => reject(new Error("MCP handshake timed out")), 15000);
  child.stdout.on("data", chunk => {
    buffer += chunk.toString();
    for (;;) {
      const newline = buffer.indexOf("\n");
      if (newline < 0) break;
      const line = buffer.slice(0, newline).trim();
      buffer = buffer.slice(newline + 1);
      if (!line) continue;
      try { replies.push(JSON.parse(line)); } catch { reject(new Error(`non-JSON stdout: ${line}`)); }
      if (replies.some(reply => reply.id === 1) && replies.some(reply => reply.id === 2)) {
        clearTimeout(timer);
        resolve();
      }
    }
  });
  child.on("error", reject);
  child.on("exit", code => reject(new Error(`MCP server exited early with code ${code}`)));
});

const send = message => child.stdin.write(JSON.stringify(message) + "\n");
send({ jsonrpc: "2.0", id: 1, method: "initialize", params: {
  protocolVersion: "2025-11-25", capabilities: {}, clientInfo: { name: "zhaoxi-smoke", version: "1.0.0" }
} });
send({ jsonrpc: "2.0", method: "notifications/initialized" });
send({ jsonrpc: "2.0", id: 2, method: "tools/list", params: {} });

await done;
child.kill();
const init = replies.find(reply => reply.id === 1);
const list = replies.find(reply => reply.id === 2);
if (!init?.result?.serverInfo || !Array.isArray(list?.result?.tools)) {
  throw new Error(`invalid MCP responses: ${JSON.stringify(replies)}`);
}
console.log(JSON.stringify({
  name: init.result.serverInfo.name,
  version: init.result.serverInfo.version,
  protocol: init.result.protocolVersion,
  tools: list.result.tools.map(tool => tool.name)
}));

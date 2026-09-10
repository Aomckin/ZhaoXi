import readline from "node:readline";

const input = readline.createInterface({ input: process.stdin });
const reply = value => process.stdout.write(JSON.stringify(value) + "\n");

input.on("line", line => {
  const message = JSON.parse(line);
  if (message.method === "initialize") {
    reply({ jsonrpc: "2.0", id: message.id, result: {
      protocolVersion: "2025-11-25",
      capabilities: { tools: {} },
      serverInfo: { name: "fake", version: "1.0.0" }
    } });
  } else if (message.method === "tools/list") {
    reply({ jsonrpc: "2.0", id: message.id, result: { tools: [
      {
        name: "lookup",
        description: "Look up a value",
        inputSchema: {
          type: "object",
          properties: { query: { type: "string", minLength: 1 } },
          required: ["query"],
          additionalProperties: false
        },
        annotations: { readOnlyHint: true }
      },
      {
        name: "change",
        description: "Change a value",
        inputSchema: {
          type: "object",
          properties: { value: { type: "integer" } },
          required: ["value"]
        },
        annotations: { readOnlyHint: false, destructiveHint: false, openWorldHint: false }
      }
    ] } });
  } else if (message.method === "tools/call") {
    reply({ jsonrpc: "2.0", id: message.id, result: {
      content: [{ type: "text", text: `called:${message.params.name}` }],
      structuredContent: { arguments: message.params.arguments },
      isError: false
    } });
  }
});

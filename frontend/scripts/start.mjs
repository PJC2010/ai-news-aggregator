import { cpSync, existsSync } from "node:fs";
import { resolve } from "node:path";
import { parseArgs } from "node:util";
import { pathToFileURL } from "node:url";

// Standalone output does not include static files or load the workspace's local
// environment. Package these for a normal local `npm start`, as Docker does.
for (const path of [".env.local", ".env"])
  if (existsSync(path)) process.loadEnvFile(path);
const { values } = parseArgs({
  options: {
    port: { type: "string", default: process.env.PORT || "3000" },
    hostname: { type: "string", default: "127.0.0.1" },
  },
});
if (
  !/^\d+$/.test(values.port) ||
  Number(values.port) < 1 ||
  Number(values.port) > 65535
)
  throw new Error("Invalid port");
cpSync(".next/static", ".next/standalone/.next/static", { recursive: true });
if (existsSync("public"))
  cpSync("public", ".next/standalone/public", { recursive: true });
process.env.PORT = values.port;
process.env.HOSTNAME = values.hostname;
await import(pathToFileURL(resolve(".next/standalone/server.js")).href);

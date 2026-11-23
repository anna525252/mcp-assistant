import "server-only";
import { createMCPClient } from "@ai-sdk/mcp";
import { error } from "console";

export async function openMcp() {
  const url = process.env.MCP_URL;
  const token = process.env.MCP_TOKEN;
  if (!url) {
    throw new Error("Не была задана переменная MCP_URL в .env.local.");
  }
  if (!token) {
    throw new Error("Не была задана перемнная MCP_TOKEN в .env.local.");
  }
  return createMCPClient({
    transport: {
      type: "http",
      url,
      headers: { Authorization: `Bearer ${token}` },
    },
  });
}
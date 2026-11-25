import { createOpenAICompatible } from "@ai-sdk/openai-compatible";
import { ollama } from "ai-sdk-ollama";

export function chatModel() {
  if (process.env.LLM_PROVIDER === "openai-compatible") {
    const baseURL = process.env.LLM_BASE_URL;
    const model = process.env.LLM_MODEL;
    if (!baseURL || !model) {
      throw new Error(
        "Для openai-compatible нужны LLM_BASE_URL и LLM_MODEL в web/.env.local",
      );
    }
    const provider = createOpenAICompatible({
      name: "llm",
      baseURL,
      apiKey: process.env.LLM_API_KEY,
    });
    return provider.chatModel(model);
  }
  return ollama(process.env.LLM_MODEL ?? "qwen3:4b-instruct");
}
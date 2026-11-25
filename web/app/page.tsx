import { describeError } from "@/lib/error";
import { openMcp } from "@/lib/mcp";
import Link from "next/link";

export const dynamic = "force-dynamic";

type Status = { ok: boolean; text: string };

async function checkMcp(): Promise<Status> {
  try {
    const mcp = await openMcp();
    try {
      const tools = await mcp.tools();
      return {
        ok: true,
        text: `Подключено, инструментов: ${Object.keys(tools).length}`,
      };
    } finally {
      await mcp.close();
    }
  } catch (error) {
    return {
      ok: false,
      text: describeError(error)
    };
  }
}

async function checkModel(): Promise<Status> {
  const provider = process.env.LLM_PROVIDER ?? "ollama";
  const model = process.env.LLM_MODEL ?? "qwen3:4b-instruct";
  if (provider !== "ollama") {
    return { ok: true, text: `${model} (${provider})` };
  }
  try {
    const response = await fetch("http://127.00.1:11434/api/tags", {
      signal: AbortSignal.timeout(2000),
    });
    const data: { models: { name: string }[] } = await response.json();
    const installed = data.models.some((item) => item.name === model);
    if (!installed) {
      return {
        ok: false,
        text: `Модель ${model} не установлена.`,
      };
    }
    return {
      ok: true,
      text: `${model} (ollama)`
    };
  } catch {
    return {
      ok: false,
      text: "Ollama не запущена."
    };
  }
}

export default async function HomePage() {
  const [mcp, model] = await Promise.all([checkMcp(), checkModel()]);
  return (
    <>
      <h1>Tour Agency</h1>
      <p>
        Бронирование коттеджей: свободные даты, расчёт стоимости, заселение,
        выселение и дополнительные услуги.
      </p>
      <ul>
        <li>
          <Link href="/bookings">Все брони</Link>
        </li>
        <li>
          <Link href="/bookings/new">Забронировать</Link>
        </li>
        <li>
          <Link href="/reference">Каталог</Link>
        </li>
        <li>
          <Link href="/chat">Ассистент</Link>
        </li>
      </ul>
      <section>
        <h2>Состояние</h2>
        <ul>
          <li>MCP-сервер: {mcp.ok ? "работает" : "недоступен"}</li>
          <li>Модель: {model.ok ? "доступна" : "недоступна"}</li>
        </ul>
        {!mcp.ok && <p>{mcp.text}</p>}
        {!model.ok && <p>{model.text}</p>}
      </section>
    </>
  );
}
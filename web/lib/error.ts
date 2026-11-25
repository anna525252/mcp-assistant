export function describeError(error: unknown): string {
    const text = error instanceof Error ? error.message : String(error);
    if (text.startsWith("Не задана переменная")) {
        return text;
    }
    if (text.includes("401")) {
        return "Ошибка доступа: сервер не принял токен."
    }
    return "Сервер недоступен."
}
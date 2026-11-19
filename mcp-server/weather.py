import os
import time

import httpx2
from mcp.server.mcpserver.exceptions import ToolError

WEATHER_BASE_URL = os.environ.get("WEATHER_BASE_URL", "https://mocks.academy.sharapov.biz/open-meteo")
BASE_LATITUDE = float(os.environ.get("BASE_LATITUDE", "51.96"))
BASE_LONGITUDE = float(os.environ.get("BASE_LONGITUDE", "85.96"))
REQUEST_TIMEOUT = 5.0
CACHE_TTL_SECONDS = 3600
REQUEST_HEADERS = {"User-Agent": "TourAgencyMCP/1.0"}

forecast_cache: dict[tuple[str, str], tuple[float, dict]] = {}

async def fetch_forecast(start_date: str, end_date: str) -> dict:
    cache_key = (start_date, end_date)
    cached = forecast_cache.get(cache_key)
    if cached and time.monotonic() - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    params = {
        "latitude": BASE_LATITUDE,
        "longitude": BASE_LONGITUDE,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
        "timezone": "auto",
        "start_date": start_date,
        "end_date": end_date,
    }
    try:
        async with httpx2.AsyncClient(
            base_url = WEATHER_BASE_URL,
            timeout = REQUEST_TIMEOUT,
            headers = REQUEST_HEADERS,
        ) as client:
            response = await client.get("v1/forecast", params=params)
            response.raise_for_status()
            data = response.json()
    except httpx2.TimeoutException:
        raise ToolError("Погода недоступна: сервис не отвечает.")
    except httpx2.HTTPStatusError as error:
        raise ToolError(f"Сервис погоды вернул ошибку {error.response.status_code}. "
                        f"Попробуйте позже.")
    except httpx2.RequestError:
        raise ToolError("Не удалось связаться с сервисом погоды. Проверьте подключение к сети.")
    except ValueError:
        raise ToolError("Прогноз недоступен: сервис погоды ответил с ошибкой.")

    forecast_cache[cache_key] = (time.monotonic(), data)
    return data

def format_forecast(data: dict) -> str:
    try:
        daily = data["daily"]
        lines = []
        for day, low, high, rain in zip(
            daily["time"],
            daily["temperature_2m_min"],
            daily["temperature_2m_max"],
            daily["precipitation_sum"],
        ):
            lines.append(f"{day}: от {low} до {high} °C, осадки {rain} мм")
    except (KeyError, TypeError):
        raise ToolError("Прогноз недоступен: в ответе сервиса погоды нет нужных данных.")
    if not lines:
        return "Прогноз погоды на эти даты не найден."
    return "\n".join(lines)
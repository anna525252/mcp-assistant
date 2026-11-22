import asyncio
import json
import logging
import os
import re
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

TEMP_DB = Path(tempfile.gettempdir()) / "check.db"
TEMP_DB.unlink(missing_ok=True)
os.environ["DB_PATH"] = str(TEMP_DB)
os.environ["MCP_TOKEN"] = "test-token"
os.environ["WEATHER_BASE_URL"] = "http://127.0.0.1:9"

from mcp.client import Client  # noqa: E402
import db  # noqa: E402
from server import BookingTokenVerifier, mcp as server  # noqa: E402

logging.getLogger().setLevel(logging.WARNING)
logging.getLogger("tour_agency").setLevel(logging.ERROR)

passed = 0
failed = 0


def check(title: str, condition: bool, seen: str = "") -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  OK   {title}")
    else:
        failed += 1
        print(f"  СБОЙ {title}")
        if seen:
            print(f"       получено: {seen}")


def booking_number(text: str) -> int:
    return int(re.search(r"№(\d+)", text).group(1))


async def main() -> None:
    db.init_db()
    async with Client(server) as client:
        tools = {t.name for t in (await client.list_tools()).tools}
        resources = {str(r.uri) for r in (await client.list_resources()).resources}
        prompts = {p.name for p in (await client.list_prompts()).prompts}

        print("\n=== 1. Сервер объявляет то, что обещал ===")
        check("девять инструментов", len(tools) == 9, ", ".join(sorted(tools)))
        check("есть create_booking и cancel_booking", {"create_booking", "cancel_booking"} <= tools)
        check("есть get_weather", "get_weather" in tools)
        check("три обычных ресурса", len(resources) == 3, ", ".join(sorted(resources)))
        check("один промпт", prompts == {"plan_stay"}, ", ".join(sorted(prompts)))

        print("\n=== 2. Основной сценарий администратора ===")
        free = await client.call_tool(
            "find_free_cabins", {"check_in": "2026-12-20", "check_out": "2026-12-24", "guests": 3}
        )
        free_text = free.content[0].text
        check("поиск не падает", not free.is_error, free_text)
        check("занятый Берёзка в выдаче отсутствует", "Берёзка" not in free_text, free_text)
        check("маленький Ёлочка не подходит по вместимости", "Ёлочка" not in free_text, free_text)
        check("Озёрный, Лесная сказка и Уютный свободны",
              all(name in free_text for name in ("Озёрный", "Лесная сказка", "Уютный")), free_text)
        nothing = await client.call_tool(
            "find_free_cabins", {"check_in": "2026-12-20", "check_out": "2026-12-24", "guests": 20}
        )
        check("пустой результат — текст, а не пустота", "не найдено" in nothing.content[0].text,
              nothing.content[0].text)
        price = await client.call_tool(
            "calculate_stay_price",
            {"cabin": "уютный", "check_in": "2026-12-01", "check_out": "2026-12-03"},
        )
        check("цена: 2 ночи по 4200 = 8400", "8400" in price.content[0].text and "2 ночи" in price.content[0].text,
              price.content[0].text)
        created = await client.call_tool(
            "create_booking",
            {"cabin": "Уютный", "guest_name": "Петров Пётр", "guests_count": 3,
             "check_in": "2026-12-01", "check_out": "2026-12-03"},
        )
        check("бронь создана", not created.is_error, created.content[0].text)
        number = booking_number(created.content[0].text)
        service = await client.call_tool("add_service", {"booking_id": number, "service": "баня"})
        check("допуслуга: 8400 + 2500 = 10900", "10900" in service.content[0].text, service.content[0].text)
        early_out = await client.call_tool("check_out_guest", {"booking_id": number})
        check("выселить до заселения нельзя", early_out.is_error and "пуст" in early_out.content[0].text,
              early_out.content[0].text)
        checked_in = await client.call_tool("check_in_guest", {"booking_id": number})
        check("заселение прошло", not checked_in.is_error, checked_in.content[0].text)
        again = await client.call_tool("check_in_guest", {"booking_id": number})
        check("повторное заселение отклонено", again.is_error, again.content[0].text)
        checked_out = await client.call_tool("check_out_guest", {"booking_id": number})
        check("выселение называет сумму 10900", not checked_out.is_error and "10900" in checked_out.content[0].text,
              checked_out.content[0].text)
        occupancy = await client.call_tool("get_occupancy", {"start": "2026-12-20", "end": "2026-12-27"})
        check("загрузка считается в процентах", "%" in occupancy.content[0].text, occupancy.content[0].text)

        print("\n=== 3. Неверные данные: сервер объясняет, а не падает ===")
        cases = [
            ("дата в неверном формате", "find_free_cabins",
             {"check_in": "20.12.2026", "check_out": "2026-12-24"}, "ГГГГ-ММ-ДД"),
            ("выезд раньше заезда", "find_free_cabins",
             {"check_in": "2026-12-24", "check_out": "2026-12-20"}, "позже"),
            ("слишком долгий срок", "calculate_stay_price",
             {"cabin": "Ёлочка", "check_in": "2026-01-01", "check_out": "2026-06-01"}, "Максимальный срок"),
            ("коттедж занят на даты", "create_booking",
             {"cabin": "Берёзка", "guest_name": "Сидоров", "guests_count": 2,
              "check_in": "2026-12-21", "check_out": "2026-12-23"}, "занят"),
            ("гостей больше вместимости", "create_booking",
             {"cabin": "Ёлочка", "guest_name": "Сидоров", "guests_count": 3,
              "check_in": "2026-11-01", "check_out": "2026-11-03"}, "рассчитан"),
            ("коттеджа нет в каталоге", "calculate_stay_price",
             {"cabin": "Замок", "check_in": "2026-12-01", "check_out": "2026-12-03"}, "Доступные коттеджи"),
            ("услуги нет в прайсе", "add_service", {"booking_id": 1, "service": "вертолёт"}, "Доступные услуги"),
            ("брони нет в базе", "cancel_booking", {"booking_id": 9999}, "нет"),
            ("пустое имя гостя", "create_booking",
             {"cabin": "Уютный", "guest_name": "   ", "guests_count": 1,
              "check_in": "2026-11-01", "check_out": "2026-11-03"}, "не должно быть пустым"),
            ("слишком длинное имя", "create_booking",
             {"cabin": "Уютный", "guest_name": "я" * 101, "guests_count": 1,
              "check_in": "2026-11-01", "check_out": "2026-11-03"}, "длиннее"),
        ]
        for title, tool, args, expected in cases:
            result = await client.call_tool(tool, args)
            text = result.content[0].text
            check(f"{title}: ошибка с подсказкой", result.is_error and expected in text, text)
        too_many = await client.call_tool(
            "find_free_cabins", {"check_in": "2026-12-20", "check_out": "2026-12-24", "guests": 99}
        )
        check("число гостей вне диапазона отклонено схемой", too_many.is_error)

        print("\n=== 4. Защита и необратимая операция ===")
        attack = "Сидоров'); DROP TABLE bookings; --"
        hacked = await client.call_tool(
            "create_booking",
            {"cabin": "Лесная сказка", "guest_name": attack, "guests_count": 2,
             "check_in": "2026-11-10", "check_out": "2026-11-12"},
        )
        check("опасная строка сохранена как обычный текст", not hacked.is_error, hacked.content[0].text)
        hacked_number = booking_number(hacked.content[0].text)
        check("имя в базе совпадает с исходным", db.get_booking(hacked_number)["guest_name"] == attack)
        with db.get_conn() as conn:
            tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        check("таблица bookings на месте после «инъекции»", "bookings" in tables, str(tables))
        cancelled = await client.call_tool("cancel_booking", {"booking_id": hacked_number})
        check("отмена брони выполнена", not cancelled.is_error, cancelled.content[0].text)
        check("мягкая отмена: запись осталась со статусом cancelled",
              db.get_booking(hacked_number)["status"] == "cancelled")
        twice = await client.call_tool("cancel_booking", {"booking_id": hacked_number})
        check("повторная отмена отклонена", twice.is_error, twice.content[0].text)
        blocked = await client.call_tool("add_service", {"booking_id": hacked_number, "service": "Баня"})
        check("в отменённую бронь услуги не добавляются", blocked.is_error, blocked.content[0].text)
        verifier = BookingTokenVerifier()
        check("неверный токен не проходит", await verifier.verify_token("подобрал") is None)
        good = await verifier.verify_token(os.environ["MCP_TOKEN"])
        check("верный токен проходит", good is not None and good.client_id == "web-app")

        print("\n=== 5. Внешний сервис ===")
        forecast = await client.call_tool("get_weather", {"check_in": "2026-12-20", "check_out": "2026-12-22"})
        check("недоступная погода даёт отказ, а не падение",
              forecast.is_error and "погоды" in forecast.content[0].text,
              forecast.content[0].text)

        print("\n=== 6. Ресурсы и промпт ===")
        catalog = await client.read_resource("cabins://catalog")
        check("каталог содержит шесть коттеджей", len(json.loads(catalog.contents[0].text)) == 6)
        listing = await client.read_resource("bookings://list")
        check("список броней содержит бронь Иванов Пётр", "Иванов Пётр" in listing.contents[0].text)
        card = await client.read_resource("bookings://1")
        check("карточка-шаблон отдаёт бронь №1 с суммами", '"totals"' in card.contents[0].text,
              card.contents[0].text[:60])
        prices = await client.read_resource("services://list")
        check("прайс содержит баню", "Баня" in prices.contents[0].text)
        prompt = await client.get_prompt(
            "plan_stay", {"guests": "4", "check_in": "2026-12-20", "check_out": "2026-12-24"}
        )
        check("промпт подставил даты", "2026-12-20" in prompt.messages[0].content.text,
              prompt.messages[0].content.text[:60])

        first_day = date(2027, 1, 1)
        for number in range(110):
            night = first_day + timedelta(days=number)
            db.create_booking(6, f"Гость {number}", 1, night.isoformat(), (night + timedelta(days=1)).isoformat())
        big = await client.read_resource("bookings://list")
        check("выдача списка обрезана потолком в 100 броней", len(json.loads(big.contents[0].text)) == 100,
              str(len(json.loads(big.contents[0].text))))

    print(f"\nИтог: {passed} проверок пройдено, {failed} провалено.")
    TEMP_DB.unlink(missing_ok=True)
    sys.exit(1 if failed else 0)


asyncio.run(main())
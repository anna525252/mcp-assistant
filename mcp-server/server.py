import hmac
import json
import logging
import os
import sys
from datetime import date
from typing import Annotated

from pydantic import Field
from mcp.server import MCPServer
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver.exceptions import ToolError

import db
import weather

logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%d.%m.%Y %H:%M:%S")

log = logging.getLogger("tour_agency")

HOST = "127.0.0.1"
PORT = 8000
MCP_TOKEN = os.environ.get("MCP_TOKEN")
if not MCP_TOKEN:
    log.error("Не задана переменная окружения MCP_TOKEN, сервер не запущен")
    raise SystemExit("Не задана переменная окружения MCP_TOKEN.")


class BookingTokenVerifier(TokenVerifier):
    async def verify_token(self, token: str) -> AccessToken | None:
        if not hmac.compare_digest(token.encode(), MCP_TOKEN.encode()):
            log.warning("Отказ в доступе: неверный токен")
            return None
        return AccessToken(token=token, client_id="web-app", scopes=["booking"])


mcp = MCPServer(
    "Tour Agency",
    token_verifier=BookingTokenVerifier(),
    auth=AuthSettings(
        issuer_url=f"http://{HOST}:{PORT}",
        resource_server_url=f"http://{HOST}:{PORT}/mcp",
        required_scopes=["booking"],
    ),
)

MAX_STAY_NIGHTS = 60
MAX_NAME_LEN = 100

def parse_date(value: str, field: str) -> str:
    try:
        return date.fromisoformat(value.strip()).isoformat()
    except ValueError:
        raise ToolError(f"Поле {field}: дата {value} не распознана. Верный формат: ГГГГ-ММ-ДД")

def check_range(check_in: str, check_out: str) -> str:
    ci = parse_date(check_in, "check_in")
    co = parse_date(check_out, "check_out")
    nights = db.nights_between(ci, co)
    if nights <= 0:
        raise ToolError("Дата выезда должна быть позже даты заезда.")
    if nights > MAX_STAY_NIGHTS:
        raise ToolError(f"Максимальный срок проживания: {MAX_STAY_NIGHTS} ночей.")
    return ci, co, nights


def check_name(value: str, field: str) -> str:
    name = value.strip()
    if not name:
        raise ToolError(f"Поле {field} не должно быть пустым.")
    if len(name) > MAX_NAME_LEN:
        raise ToolError(f"Поле {field} длиннее {MAX_NAME_LEN} символов.")
    return name

def normalize(value: str) -> str:
    return value.strip("«»\"").lower()

def find_cabin(name: str) -> dict:
    cabins = db.list_cabins()
    for cabin in cabins:
        if normalize(cabin["name"]) == normalize(name):
            return cabin
    names = ", ".join(c["name"] for c in cabins)
    raise ToolError(f"Домика «{name}» нет в каталоге. Доступные коттеджи: {names}.")

def find_service(name: str) -> dict:
    services = db.list_services()
    for service in services:
        if normalize(service["name"]) == normalize(name):
            return service
    names = ", ".join(service["name"] for s in services)
    raise ToolError(f"Услуги {name} нет в прайсе. Доступные услуги: {names}.")

def load_booking(booking_id: int) -> dict:
    booking = db.get_booking(booking_id)
    if booking is None:
        raise ToolError(f"Брони с номером {booking_id} нет.")
    return booking

def night_form(n: int) -> str:
    if n % 100 in (11, 12, 13, 14):
        return "ночей"
    last = n % 10
    if last == 1:
        return "ночь"
    if last in (2, 3, 4):
        return "ночи"
    return "ночей"
@mcp.tool()
def find_free_cabins(check_in: str, check_out: str, guests: Annotated[int, Field(ge=1, le=20)] = 1) -> str:
    ci, co, nights = check_range(check_in, check_out)
    rows = db.find_free_cabins(ci, co, guests)
    if not rows:
        return f"На даты {ci} - {co} для {guests} гостей свободных коттеджей не найдено."
    lines = [f"Свободно на {ci} - {co} ({nights} {night_form(nights)})"]
    for r in rows:
        lines.append(f"{r['name']} до {r['capacity']} гостей, "
                     f"{r['price_per_night']} рублей за ночь,"
                     f" полная цена: {r['price_per_night'] * nights} рублей.")
    return "\n".join(lines)

@mcp.tool()
def calculate_stay_price(cabin: str, check_in: str, check_out: str) -> str:
    ci, co, nights = check_range(check_in, check_out)
    found = find_cabin(cabin)
    total = nights * found["price_per_night"]
    return(
        f"Домик «{found['name']}», {ci} - {co}: {nights} {night_form(nights)},"
        f"за {found['price_per_night']} рублей, итого {total} рублей."
    )

@mcp.tool()
def get_occupancy(start: str, end: str) -> str:
    period_start, period_end, _ = check_range(start, end)
    stats = db.occupancy(period_start, period_end)
    return (
        f"Загрузка за {period_start} - {period_end}: {stats['percent']}% "
        f"Занято {stats['occupied_nights']} из {stats['total_nights']} ночей,"
        f"(домиков: {stats['cabins']}, дней: {stats['days']}."
    )

@mcp.tool()
def create_booking(cabin: str, guest_name: str, guests_count: Annotated[int, Field(ge=1, le=20)], check_in: str, check_out: str) -> str:
    ci, co, nights = check_range(check_in, check_out)
    name = check_name(guest_name, "guest_name")
    found = find_cabin(cabin)
    if guests_count > found["capacity"]:
        raise ToolError(
            f"Домик «{found['name']}» рассчитан на {found['capacity']} гостей, "
            f"указано: {guests_count}. Выберите другой коттедж."
        )
    booking_id = db.create_booking(found["id"], name, guests_count, ci, co)
    if booking_id is None:
        raise ToolError(
            f"Домик «{found['name']}» занят на даты {ci} - {co}. "
            "Выберите другие даты или другой домик."
        )
    total = nights * found["price_per_night"]
    log.info("Создана бронь №%s", booking_id)
    return (
        f"Бронь №{booking_id}: {name}, домик «{found['name']}», "
        f"{ci} - {co}, гостей: {guests_count}, проживание {total} ₽."
    )

@mcp.tool()
def add_service(booking_id: Annotated[int, Field(ge=1)], service: str, quantity: Annotated[int, Field(ge=1, le=20)] = 1) -> str:
    booking = load_booking(booking_id)
    if booking["status"] not in db.ACTIVE:
        raise ToolError(
            f"К брони №{booking_id} нельзя добавить услугу: "
            f"статус «{booking['status']}»."
        )
    found = find_service(service)
    db.add_booking_service(booking_id, found["id"], quantity)
    total = db.get_booking(booking_id)["totals"]["total"]
    return (
        f"К брони №{booking_id} добавлено: {found['name']} в количестве {quantity}. "
        f"Общая сумма: {total} рублей."
    )

@mcp.tool()
def check_in_guest(booking_id: Annotated[int, Field(ge=1)]) -> str:
    booking = load_booking(booking_id)
    if booking["status"] != "booked":
        raise ToolError(
            f"Бронь №{booking_id} нельзя заселить: гость уже заселён или бронь закрыта."
        )
    db.set_status(booking_id, "checked_in")
    return f"Гость {booking['guest_name']} заселён в домик «{booking['cabin_name']}»."

@mcp.tool()
def check_out_guest(booking_id: Annotated[int, Field(ge=1)]) -> str:
    booking = load_booking(booking_id)
    if booking["status"] != "checked_in":
        raise ToolError(
            f"Выселение по брони №{booking_id} невозможно: "
            f"коттедж «{booking['cabin_name']}» сейчас пуст. "
            "Выселить можно только заселённого гостя."
        )
    db.set_status(booking_id, "checked_out")
    total = booking["totals"]["total"]
    return (
        f"Гость {booking['guest_name']} выселен из домика «{booking['cabin_name']}». "
        f"К оплате: {total} рублей."
    )

@mcp.tool()
def cancel_booking(booking_id: Annotated[int, Field(ge=1)]) -> str:
    booking = load_booking(booking_id)
    if booking["status"] != "booked":
        raise ToolError(
            f"Бронь №{booking_id} нельзя отменить: статус «{booking['status']}». "
            "Отменить можно только бронь до заселения."
        )
    db.set_status(booking_id, "cancelled")
    log.info("Отменена бронь №%s", booking_id)
    return f"Бронь номер {booking_id} для {booking['guest_name']} отменена."

@mcp.tool()
async def get_weather(check_in: str, check_out: str) -> str:
    arrival, departure, _ = check_range(check_in, check_out)
    forecast = await weather.fetch_forecast(arrival, departure)
    return weather.format_forecast(forecast)

@mcp.resource("bookings://list")
def bookings_list() -> str:
    return json.dumps(db.list_bookings(), ensure_ascii=False)

@mcp.resource("bookings://{booking_id}")
def booking_card(booking_id: str) -> str:
    if not booking_id.isdigit():
        raise ToolError("Номер брони должен быть числом.")
    return json.dumps(load_booking(int(booking_id)), ensure_ascii=False)

@mcp.resource("cabins://catalog")
def cabins_catalog() -> str:
    return json.dumps(db.list_cabins(), ensure_ascii=False)

@mcp.resource("services://list")
def services_list() -> str:
    return json.dumps(db.list_services(), ensure_ascii=False)

@mcp.prompt()
def plan_stay(guests: str, check_in: str, check_out: str) -> str:
    return (
        f"Подбери коттедж для {guests} гостей на даты с {check_in} по {check_out}. "
        "Найди свободные коттеджи, посчитай стоимость проживания "
        "и расскажи, какая будет погода на время заезда."
    )

if __name__ == "__main__":
    db.init_db()
    log.info("Сервер запущен на %s:%s", HOST, PORT)
    mcp.run(transport="streamable-http")
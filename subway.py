"""
subway.py — система метро Токио.

Игрок может быстро перемещаться между ключевыми районами за 💠.
Стоимость зависит от расстояния: 1💠 за каждые 10 единиц X.
Минимальная цена — 5💠.

Станции размещены в 12 ключевых районах. В остальные районы
добраться можно только пешком.
"""
import math

import database
from world import get_district_by_x, get_district_by_id


# Стоимость: 💠 за каждые 10 единиц X
FARE_PER_10_UNITS = 1
MIN_FARE = 5


# Станции: district_id → отображаемое название
STATIONS = {
    "tachikawa":       "Татикава",
    "hachioji":        "Хатиодзи",
    "shinagawa":       "Синагава",
    "setagaya":        "Сэтагая",
    "shinjuku":        "Синдзюку",
    "shinjuku_dark":   "Синдзюку: Квартал Тьмы",
    "shibuya":         "Сибуя",
    "shibuya_incident": "Зона Инцидента",
    "jujutsu_high":    "Школа магии",
    "ikebukuro":       "Икэбукуро",
    "roppongi":        "Роппонги",
    "ginza":           "Гиндза",
    "odaiba":          "Одайба",
    "asakusa":         "Асакуса",
    "ueno":            "Уэно",
    "chofu":           "Тёфу",
    "fuchu":           "Футю",
}


def get_station_name(district_id: str) -> str | None:
    """Название станции или None, если в районе нет метро."""
    return STATIONS.get(district_id)


def has_station(district_id: str) -> bool:
    return district_id in STATIONS


def _district_center_x(district_id: str) -> int | None:
    """Возвращает X-центр района, если он существует."""
    d = get_district_by_id(district_id)
    if not d:
        return None
    return (d["x_min"] + d["x_max"]) // 2


def calculate_fare(from_x: int, to_x: int) -> int:
    """Стоимость в 💠 между двумя X. 1💠 за каждые 10 единиц, минимум 5💠."""
    distance = abs(to_x - from_x)
    fare = math.ceil(distance / 10) * FARE_PER_10_UNITS
    return max(MIN_FARE, fare)


def _station_entry(district_id: str, current_x: int, gold: int) -> dict | None:
    """Информация о станции для UI."""
    d = get_district_by_id(district_id)
    if not d:
        return None
    name = STATIONS.get(district_id)
    if not name:
        return None

    center_x = (d["x_min"] + d["x_max"]) // 2
    fare = calculate_fare(current_x, center_x)

    return {
        "district_id": district_id,
        "name": name,
        "emoji": d["emoji"],
        "x": center_x,
        "fare": fare,
        "affordable": gold >= fare,
        "is_current": d["x_min"] <= current_x <= d["x_max"],
    }


def list_reachable(current_x: int, gold: int) -> list[dict]:
    """Список всех станций с ценами и доступностью.
    Отсортирован по расстоянию от текущей позиции."""
    result = []
    for district_id in STATIONS.keys():
        entry = _station_entry(district_id, current_x, gold)
        if entry:
            result.append(entry)
    result.sort(key=lambda e: e["fare"])
    return result


def use_subway(user_id: int, target_district_id: str) -> dict:
    """Телепортирует игрока к станции за 💠.
    Возвращает {ok, msg, district}."""
    d = get_district_by_id(target_district_id)
    if not d:
        return {"ok": False, "msg": "Такого района нет на карте."}

    if not has_station(target_district_id):
        return {"ok": False, "msg": "В этом районе нет станции метро."}

    player = database.get_or_create_player(user_id, "")
    current_x = player["x"]

    # Уже здесь?
    if d["x_min"] <= current_x <= d["x_max"]:
        return {"ok": False, "msg": "Ты уже находишься в этом районе."}

    center_x = (d["x_min"] + d["x_max"]) // 2
    fare = calculate_fare(current_x, center_x)

    if player["gold"] < fare:
        return {
            "ok": False,
            "msg": (
                f"❌ Не хватает 💠 на билет.\n"
                f"Нужно: <b>{fare}💠</b>, у тебя: <b>{player['gold']}💠</b>."
            ),
        }

    # Списываем золото и телепортируем
    database.add_gold(user_id, -fare)
    database.update_player_x(user_id, center_x)

    station_name = STATIONS[target_district_id]
    return {
        "ok": True,
        "msg": (
            f"🚇 <b>Метро Токио</b>\n\n"
            f"Ты добрался до станции <b>{d['emoji']} {station_name}</b>.\n"
            f"💠 Списано: <b>{fare}</b>."
        ),
        "district": d,
        "x": center_x,
    }


def format_subway_text(user_id: int) -> str:
    """Текст для меню метро."""
    player = database.get_or_create_player(user_id, "")
    current_x = player["x"]
    current_district = get_district_by_x(current_x)
    current_station = STATIONS.get(current_district["id"])

    lines = [
        "🚇 <b>Метро Токио</b>",
        "",
        f"📍 Текущая позиция: X = {current_x}",
    ]
    if current_station:
        lines.append(f"🎫 Ты на станции: <b>{current_station}</b>")
    else:
        lines.append("⚠️ В этом районе нет станции. Пройди до ближайшей пешком.")

    lines.append("")
    lines.append(f"💠 У тебя: <b>{player['gold']}</b>")
    lines.append(f"💵 Тариф: <b>{FARE_PER_10_UNITS}💠 за 10 ед. дистанции</b> (минимум {MIN_FARE}💠)")
    lines.append("")
    lines.append("<i>Выбери станцию назначения:</i>")

    return "\n".join(lines)

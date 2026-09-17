"""
Система спавна проклятий.

Каждые SPAWN_INTERVAL_SECONDS для каждого игрока, у которого сейчас нет
активной встречи, кидаем RNG: почувствует ли он проклятие в своём районе.
Игрок находит и вступает в бой через кнопку "🩸 Патрулирование".

Безопасные зоны (в world.py помечены "safe": True, например школа магии)
исключены из спавна — там проклятия не появляются.

Баффы curse_hunt_1 и curse_hunt_2 повышают шанс спавна 1-го и 2-го
классов соответственно (см. consumables.py → «🧭 Компас Скверны» и
«🎯 Метка Годжо»). В сюжетных temp-локациях они НЕ применяются —
там фиксированный пул из story.py.
"""
import random
import time
import database
from config import SPAWN_CHANCE, PATROL_CHANCE, ENCOUNTER_TTL_SECONDS, CLASS_TO_DROP_RARITY
from loot import weighted_choice
from world import get_district_by_x


def format_curse_name(base_name: str, curse_class: str) -> str:
    return f"{base_name} ({curse_class})"


def _pick_curse(district: dict, user_id: int = None, apply_hunt: bool = True) -> dict:
    """Выбирает случайное проклятие из пула района с учётом весов.
    Если apply_hunt=True и передан user_id — учитывает баффы усиления охоты
    (curse_hunt_1 и curse_hunt_2), временно повышающие вес 1-го и 2-го классов."""
    table = []
    hunt_1 = database.get_buff_value(user_id, "curse_hunt_1") if user_id and apply_hunt else 0
    hunt_2 = database.get_buff_value(user_id, "curse_hunt_2") if user_id and apply_hunt else 0

    for c in district["curses"]:
        name, curse_class, weight = c[0], c[1], c[7]
        w = weight
        if curse_class == "1-й класс" and hunt_1:
            w = int(w * (1 + hunt_1))
        elif curse_class == "2-й класс" and hunt_2:
            w = int(w * (1 + hunt_2))
        table.append((name, curse_class, w))

    picked = weighted_choice(table)
    full = next(c for c in district["curses"] if c[0] == picked["name"] and c[1] == picked["rarity"])
    base_name, curse_class, hp, dmg_min, dmg_max, emoji, drop_item, _weight = full
    return {
        "name": format_curse_name(base_name, curse_class),
        "hp": hp,
        "dmg_min": dmg_min,
        "dmg_max": dmg_max,
        "emoji": emoji,
        "rarity": curse_class,
        "curse_class": curse_class,
        "drop_item": drop_item,
        "drop_rarity": CLASS_TO_DROP_RARITY.get(curse_class, "обычный"),
    }


def try_spawn_for_player(user_id: int, x: int, chance: float = SPAWN_CHANCE):
    """Пытается заспавнить проклятие в обычном районе."""
    existing = database.get_encounter(user_id)
    if existing:
        if int(time.time()) - existing["spawned_at"] > ENCOUNTER_TTL_SECONDS:
            database.clear_encounter(user_id)
        else:
            return None

    district = get_district_by_x(x)
    if district.get("safe"):
        return None

    if random.random() > chance:
        return None

    monster = _pick_curse(district, user_id=user_id, apply_hunt=True)
    database.set_encounter(user_id, district["id"], monster)
    return monster


def patrol(user_id: int, x: int):
    """Обычный патруль."""
    return try_spawn_for_player(user_id, x, chance=PATROL_CHANCE)


def patrol_in_temp(user_id: int, temp_district: dict):
    """Патруль в сюжетной temp-локации. Всегда успешен, если нет активного боя.
    Баффы curse_hunt_1/2 здесь НЕ применяются."""
    existing = database.get_encounter(user_id)
    if existing:
        return None
    monster = _pick_curse(temp_district, user_id=user_id, apply_hunt=False)
    database.set_encounter(user_id, temp_district["id"], monster)
    return monster


def spawn_tick_for_all_players():
    """Фоновый тик для всех игроков. Возвращает список (user_id, monster, district)."""
    conn = database.get_conn()
    cur = conn.cursor()
    cur.execute("SELECT user_id, x FROM players")
    rows = cur.fetchall()
    spawned = []
    for row in rows:
        monster = try_spawn_for_player(row["user_id"], row["x"])
        if monster:
            district = get_district_by_x(row["x"])
            spawned.append((row["user_id"], monster, district))
    return spawned
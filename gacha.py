"""
Гача врождённых техник.

Данные 120 техник вынесены в techniques_data.py, здесь только логика:
ролл редкости, крутки x1/x10, экип в боевой набор и рефанд за дубликаты.

Чёрная Вспышка — не техника из гачи, а боевой крит (см. combat.py).
"""
import random
import database
import quests
from techniques_data import TECHNIQUES
from config import (
    GACHA_ROLL_COST, GACHA_ROLL_COST_X10, GACHA_RARITY_WEIGHTS,
    MAX_EQUIPPED_TECHNIQUES,
)


def get_technique(name: str) -> dict | None:
    return TECHNIQUES.get(name)


def _pool_by_rarity(rarity: str):
    return [name for name, t in TECHNIQUES.items() if t["rarity"] == rarity]


def _roll_rarity() -> str:
    rarities = list(GACHA_RARITY_WEIGHTS.keys())
    weights = list(GACHA_RARITY_WEIGHTS.values())
    return random.choices(rarities, weights=weights, k=1)[0]


def roll_once(user_id: int) -> dict:
    """Одна прокрутка гачи."""
    player = database.get_or_create_player(user_id, "")
    if player["gold"] < GACHA_ROLL_COST:
        return {"ok": False, "msg": f"Не хватает очков Ассоциации. Нужно {GACHA_ROLL_COST}💠."}

    database.add_gold(user_id, -GACHA_ROLL_COST)
    rarity = _roll_rarity()
    pool = _pool_by_rarity(rarity)
    name = random.choice(pool)
    technique = TECHNIQUES[name]

    is_new = database.add_player_technique(user_id, name, rarity)
    refund = 0
    if not is_new:
        refund = GACHA_ROLL_COST // 2
        database.add_gold(user_id, refund)

    quests.add_progress(user_id, "gacha_roll")

    return {
        "ok": True,
        "name": name,
        "rarity": rarity,
        "emoji": technique["emoji"],
        "duplicate": not is_new,
        "refund": refund,
    }


def roll_x10(user_id: int) -> dict:
    player = database.get_or_create_player(user_id, "")
    if player["gold"] < GACHA_ROLL_COST_X10:
        return {"ok": False, "msg": f"Не хватает очков Ассоциации. Нужно {GACHA_ROLL_COST_X10}💠.", "results": []}

    database.add_gold(user_id, -GACHA_ROLL_COST_X10)
    results = []
    for _ in range(10):
        rarity = _roll_rarity()
        pool = _pool_by_rarity(rarity)
        name = random.choice(pool)
        technique = TECHNIQUES[name]
        is_new = database.add_player_technique(user_id, name, rarity)
        refund = 0
        if not is_new:
            refund = GACHA_ROLL_COST // 2
            database.add_gold(user_id, refund)
        results.append({
            "name": name, "rarity": rarity, "emoji": technique["emoji"],
            "duplicate": not is_new, "refund": refund,
        })

    quests.add_progress(user_id, "gacha_roll", amount=10)

    return {"ok": True, "results": results}


# ---------------- Боевой набор техник ----------------

def get_equipped(user_id: int) -> list[str]:
    return [row["technique_name"] for row in database.get_equipped_techniques(user_id)]


def equip(user_id: int, technique_name: str) -> dict:
    if not database.has_technique(user_id, technique_name):
        return {"ok": False, "msg": "Эта техника ещё не изучена."}

    equipped = database.get_equipped_techniques(user_id)
    if any(row["technique_name"] == technique_name for row in equipped):
        return {"ok": False, "msg": "Эта техника уже в боевом наборе."}

    if len(equipped) >= MAX_EQUIPPED_TECHNIQUES:
        return {"ok": False, "msg": f"В бою можно взять максимум {MAX_EQUIPPED_TECHNIQUES} техники. Сначала убери одну."}

    used_slots = {row["slot"] for row in equipped}
    slot = next(i for i in range(MAX_EQUIPPED_TECHNIQUES) if i not in used_slots)
    database.equip_technique(user_id, slot, technique_name)
    return {"ok": True, "msg": f"✅ Техника «{technique_name}» добавлена в боевой набор."}


def unequip(user_id: int, technique_name: str) -> dict:
    equipped = database.get_equipped_techniques(user_id)
    for row in equipped:
        if row["technique_name"] == technique_name:
            database.unequip_technique(user_id, row["slot"])
            return {"ok": True, "msg": f"❎ Техника «{technique_name}» снята из боевого набора."}
    return {"ok": False, "msg": "Эта техника не в боевом наборе."}

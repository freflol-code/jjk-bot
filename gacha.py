"""
Гача врождённых техник (замена системы крафта).

Игрок тратит очки Магической Ассоциации (фарм-валюта, "gold" в БД) у
Хакари, чтобы получить случайную врождённую технику. Техники делятся на
редкости: Обычная, Редкая, Эпическая, Легендарная (Особый класс).

Названия техник — каноничные из Jujutsu Kaisen (или в стилистике первоисточника):
    Обычные:     Кулак Дивергента, Импульс Проклятой Энергии, ...
    Редкие:      Клинок Проклятой Энергии, Ледяная Хватка, ...
    Эпические:   Вороны Меймей, Клык Бездны, Обратный Удар, Расщепление
    Легендарные: Пустотный Пурпур, Абсолютный Ноль, Рассечение

ВАЖНО: Чёрная Вспышка (Black Flash) — НЕ техника из гачи, а боевой крит
(см. combat.py). При критическом ударе игрок искажает ПЭ, наносит двойной
урон и может оглушить проклятие.

Изученные техники хранятся в player_techniques, из них можно выбрать до
MAX_EQUIPPED_TECHNIQUES для боевого набора (equipped_techniques).
Каждая техника тратит ПЭ, наносит урон (умноженный на "Контроль ПЭ",
см. combat.py) и может накладывать эффект: stun (стан), bleed
(кровотечение) или buff_dmg (бафф физического урона).
"""
import random
import database
import quests
from config import (
    GACHA_ROLL_COST, GACHA_ROLL_COST_X10, GACHA_RARITY_WEIGHTS,
    MAX_EQUIPPED_TECHNIQUES,
)


TECHNIQUES = {
    # ---------------- ОБЫЧНЫЕ ----------------
    "Кулак Дивергента": {
        "emoji": "👊", "rarity": "Обычная", "ce_cost": 8,
        "dmg_min": 6, "dmg_max": 10, "effect": None,
        "desc": "Прямой удар, усиленный запоздалым импульсом ПЭ (техника Итадори).",
    },
    "Импульс Проклятой Энергии": {
        "emoji": "💨", "rarity": "Обычная", "ce_cost": 10,
        "dmg_min": 5, "dmg_max": 8,
        "effect": {"type": "stun", "turns": 1, "chance": 0.25},
        "desc": "Волна ПЭ, иногда сбивающая проклятие с ритма (25% стан на 1 ход).",
    },
    "Кровавый Росчерк": {
        "emoji": "🩸", "rarity": "Обычная", "ce_cost": 12,
        "dmg_min": 4, "dmg_max": 7,
        "effect": {"type": "bleed", "turns": 2, "dmg": 3, "chance": 0.5},
        "desc": "Резкий разряд по контуру проклятия (50% кровотечение 2 хода).",
    },
    "Прилив Проклятой Энергии": {
        "emoji": "🔥", "rarity": "Обычная", "ce_cost": 9,
        "dmg_min": 3, "dmg_max": 5,
        "effect": {"type": "buff_dmg", "turns": 2, "mult": 1.2, "chance": 1.0},
        "desc": "Разгоняет собственную ПЭ (+20% физ. урона на 2 хода).",
    },

    # ---------------- РЕДКИЕ ----------------
    "Клинок Проклятой Энергии": {
        "emoji": "🗡️", "rarity": "Редкая", "ce_cost": 16,
        "dmg_min": 12, "dmg_max": 18, "effect": None,
        "desc": "Сгусток ПЭ, спрессованный в режущую кромку.",
    },
    "Ледяная Хватка": {
        "emoji": "❄️", "rarity": "Редкая", "ce_cost": 18,
        "dmg_min": 9, "dmg_max": 14,
        "effect": {"type": "stun", "turns": 1, "chance": 0.4},
        "desc": "Сковывает конечности проклятия (40% стан на 1 ход).",
    },
    "Разрыв Плоти": {
        "emoji": "🩸", "rarity": "Редкая", "ce_cost": 20,
        "dmg_min": 8, "dmg_max": 12,
        "effect": {"type": "bleed", "turns": 3, "dmg": 5, "chance": 0.6},
        "desc": "Глубокий проклятый разрез (60% кровотечение 3 хода).",
    },
    "Второе Дыхание": {
        "emoji": "⚡", "rarity": "Редкая", "ce_cost": 15,
        "dmg_min": 6, "dmg_max": 10,
        "effect": {"type": "buff_dmg", "turns": 2, "mult": 1.35, "chance": 1.0},
        "desc": "Резкий прилив силы (+35% физ. урона на 2 хода).",
    },

    # ---------------- ЭПИЧЕСКИЕ ----------------
    "Вороны Меймей": {
        "emoji": "🐦‍⬛", "rarity": "Эпическая", "ce_cost": 28,
        "dmg_min": 20, "dmg_max": 28,
        "effect": {"type": "bleed", "turns": 3, "dmg": 8, "chance": 0.6},
        "desc": "Стая смертоносных воронов Меймей терзает проклятие (60% кровотечение 3 хода).",
    },
    "Клык Бездны": {
        "emoji": "🦷", "rarity": "Эпическая", "ce_cost": 30,
        "dmg_min": 16, "dmg_max": 22,
        "effect": {"type": "bleed", "turns": 3, "dmg": 9, "chance": 0.7},
        "desc": "Проклятая энергия прогрызает контур цели (70% кровотечение 3 хода).",
    },
    "Обратный Удар": {
        "emoji": "🔄", "rarity": "Эпическая", "ce_cost": 26,
        "dmg_min": 14, "dmg_max": 20,
        "effect": {"type": "buff_dmg", "turns": 3, "mult": 1.5, "chance": 1.0},
        "desc": "Оборачивает удар проклятия против него (+50% физ. урона на 3 хода).",
    },
    "Расщепление": {
        "emoji": "🩸", "rarity": "Эпическая", "ce_cost": 32,
        "dmg_min": 18, "dmg_max": 24,
        "effect": {"type": "bleed", "turns": 3, "dmg": 10, "chance": 0.7},
        "desc": "Режущая сеть Сукуны, разрывающая контур цели (70% кровотечение 3 хода).",
    },

    # ---------------- ЛЕГЕНДАРНЫЕ (ОСОБЫЙ КЛАСС) ----------------
    "Пустотный Пурпур": {
        "emoji": "🟣", "rarity": "Легендарная (Особый класс)", "ce_cost": 45,
        "dmg_min": 32, "dmg_max": 44,
        "effect": {"type": "stun", "turns": 2, "chance": 0.6},
        "desc": "Слияние Синего и Красного Годжо — стирает всё на пути (60% стан на 2 хода).",
    },
    "Абсолютный Ноль": {
        "emoji": "🥶", "rarity": "Легендарная (Особый класс)", "ce_cost": 48,
        "dmg_min": 35, "dmg_max": 48,
        "effect": {"type": "stun", "turns": 2, "chance": 0.6},
        "desc": "Мгновенная заморозка контура проклятия (60% стан на 2 хода).",
    },
    "Рассечение": {
        "emoji": "⚔️", "rarity": "Легендарная (Особый класс)", "ce_cost": 50,
        "dmg_min": 38, "dmg_max": 50,
        "effect": {"type": "bleed", "turns": 4, "dmg": 14, "chance": 0.8},
        "desc": "Невидимые лезвия Сукуны рассекают всё на своём пути (80% кровотечение 4 хода).",
    },
}


def get_technique(name: str) -> dict | None:
    return TECHNIQUES.get(name)


def _pool_by_rarity(rarity: str):
    return [name for name, t in TECHNIQUES.items() if t["rarity"] == rarity]


def _roll_rarity() -> str:
    rarities = list(GACHA_RARITY_WEIGHTS.keys())
    weights = list(GACHA_RARITY_WEIGHTS.values())
    return random.choices(rarities, weights=weights, k=1)[0]


def roll_once(user_id: int) -> dict:
    """Одна прокрутка гачи. Возвращает {ok, name, rarity, emoji, duplicate, refund}."""
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

    # Квестовый трекинг
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

    # Квестовый трекинг — 10 круток за раз
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
"""
Логика типов ПЭ, кланов и проклятий небес.

- Ролл редкости и случайного типа ПЭ с учётом 15% шанса на Проклятие Небес.
- Ролл клана (80% пусто).
- Выдача, экип, снятие.
- Функции для combat.py: get_active_effects(user_id) собирает все эффекты
  от типа ПЭ, клана и проклятия небес в один словарь.
"""
import random
import time
import database
from ce_types_data import (
    CE_TYPES, CLANS, HEAVENLY_RESTRICTIONS,
    HEAVENLY_RESTRICTION_CHANCE, CE_RARITY_WEIGHTS, CLAN_ROLL_EMPTY_CHANCE,
)


# ---------- Выборка по редкости ----------

def _pool_by_rarity(rarity: str):
    return [key for key, t in CE_TYPES.items() if t["rarity"] == rarity]


def _roll_ce_rarity() -> str:
    rarities = list(CE_RARITY_WEIGHTS.keys())
    weights = list(CE_RARITY_WEIGHTS.values())
    return random.choices(rarities, weights=weights, k=1)[0]


# ---------- Крутка типа ПЭ ----------

def roll_ce_type(user_id: int) -> dict:
    """Одна крутка гачи типов ПЭ.
    Возвращает {ok, kind, ...}:
        kind = "ce"       — выпал обычный тип ПЭ
        kind = "heavenly" — выпало Проклятие Небес
        kind = "duplicate" — тип уже был (только для ce)
        kind = "heavenly_duplicate" — Проклятие Небес уже было
    """
    # 1) Сначала роллим 15% на Проклятие Небес
    if random.random() < HEAVENLY_RESTRICTION_CHANCE:
        key = random.choice(list(HEAVENLY_RESTRICTIONS.keys()))
        is_new = database.add_heavenly_restriction(user_id, key)
        return {
            "ok": True,
            "kind": "heavenly" if is_new else "heavenly_duplicate",
            "key": key,
            "name": HEAVENLY_RESTRICTIONS[key]["name"],
            "emoji": HEAVENLY_RESTRICTIONS[key]["emoji"],
            "desc": HEAVENLY_RESTRICTIONS[key]["desc"],
        }

    # 2) Иначе — обычный тип ПЭ
    rarity = _roll_ce_rarity()
    key = random.choice(_pool_by_rarity(rarity))
    is_new = database.add_ce_type(user_id, key, rarity)
    return {
        "ok": True,
        "kind": "ce" if is_new else "duplicate",
        "key": key,
        "rarity": rarity,
        "name": CE_TYPES[key]["name"],
        "emoji": CE_TYPES[key]["emoji"],
        "desc": CE_TYPES[key]["desc"],
    }


def roll_clan(user_id: int) -> dict:
    """Одна крутка гачи кланов. 80% — пусто."""
    if random.random() < CLAN_ROLL_EMPTY_CHANCE:
        return {"ok": True, "kind": "empty"}

    key = random.choice(list(CLANS.keys()))
    is_new = database.add_clan(user_id, key)
    return {
        "ok": True,
        "kind": "clan" if is_new else "duplicate",
        "key": key,
        "name": CLANS[key]["name"],
        "emoji": CLANS[key]["emoji"],
        "desc": CLANS[key]["desc"],
    }


# ---------- Активные слоты ----------

def get_active_ce_type(user_id: int) -> str | None:
    return database.get_active_ce_type(user_id)


def get_active_clan(user_id: int) -> str | None:
    return database.get_active_clan(user_id)


def get_active_heavenly(user_id: int) -> str | None:
    return database.get_active_heavenly(user_id)


def set_active_ce_type(user_id: int, key: str) -> dict:
    if key not in CE_TYPES:
        return {"ok": False, "msg": "Такого типа ПЭ не существует."}
    if not database.has_ce_type(user_id, key):
        return {"ok": False, "msg": "Этот тип ПЭ ещё не выбит."}
    database.set_active_ce_type(user_id, key)
    return {"ok": True, "msg": f"✅ Активный тип ПЭ: {CE_TYPES[key]['emoji']} {CE_TYPES[key]['name']}"}


def set_active_clan(user_id: int, key: str) -> dict:
    if key not in CLANS:
        return {"ok": False, "msg": "Такого клана не существует."}
    if not database.has_clan(user_id, key):
        return {"ok": False, "msg": "Этот клан ещё не выбит."}
    database.set_active_clan(user_id, key)
    return {"ok": True, "msg": f"✅ Активный клан: {CLANS[key]['emoji']} {CLANS[key]['name']}"}


def set_active_heavenly(user_id: int, key: str) -> dict:
    if key not in HEAVENLY_RESTRICTIONS:
        return {"ok": False, "msg": "Такого Проклятия Небес не существует."}
    if not database.has_heavenly_restriction(user_id, key):
        return {"ok": False, "msg": "Это Проклятие Небес ещё не выбито."}
    database.set_active_heavenly(user_id, key)
    return {"ok": True, "msg": f"✅ Активное Проклятие Небес: {HEAVENLY_RESTRICTIONS[key]['emoji']} {HEAVENLY_RESTRICTIONS[key]['name']}"}


def clear_ce_type(user_id: int) -> dict:
    database.clear_active_ce_type(user_id)
    return {"ok": True, "msg": "Активный тип ПЭ снят."}


def clear_clan(user_id: int) -> dict:
    database.clear_active_clan(user_id)
    return {"ok": True, "msg": "Активный клан снят."}


# ---------- Сборка эффектов для combat ----------

def get_active_effects(user_id: int) -> dict:
    """Возвращает словарь всех активных эффектов от ПЭ, клана и Проклятия Небес.
    Ключи — как в ce_types_data.py. Значения — числа. Множители умножаются,
    шансы складываются, 'phys_taken_div' берём максимальный (не перемножаем).
    """
    result = {
        "phys_dmg_mult": 1.0,
        "tech_dmg_mult": 1.0,
        "crit_bonus": 0.0,
        "stun_chance": 0.0,
        "stun_chance_every_2": 0.0,
        "bleed_chance": 0.0,
        "vampire": 0.0,
        "ce_regen_mult": 1.0,
        "defense_mult": 1.0,
        "hp_mult": 1.0,
        "ce_mult": 1.0,
        "tech_vs_self_mult": 1.0,
        "phys_taken_div": 1.0,
    }

    sources = []

    ce_key = get_active_ce_type(user_id)
    if ce_key and ce_key in CE_TYPES:
        sources.append(CE_TYPES[ce_key]["effect"])

    clan_key = get_active_clan(user_id)
    if clan_key and clan_key in CLANS:
        sources.append(CLANS[clan_key]["effect"])

    heavenly_key = get_active_heavenly(user_id)
    if heavenly_key and heavenly_key in HEAVENLY_RESTRICTIONS:
        sources.append(HEAVENLY_RESTRICTIONS[heavenly_key]["effect"])

    for eff in sources:
        for k, v in eff.items():
            if k in ("phys_dmg_mult", "tech_dmg_mult", "ce_regen_mult",
                     "defense_mult", "hp_mult", "ce_mult", "tech_vs_self_mult"):
                result[k] *= v
            elif k == "phys_taken_div":
                result[k] = max(result[k], v)
            else:
                result[k] += v

    return result


# ---------- Форматирование ----------

def format_ce_list(user_id: int) -> str:
    owned = database.get_ce_types(user_id)
    active = get_active_ce_type(user_id)
    if not owned:
        return "⚡ <b>Типы ПЭ</b>\n\n<i>Пока ничего не выбито.</i>"

    lines = ["⚡ <b>Твои типы ПЭ</b>", ""]
    for row in owned:
        key = row["ce_key"]
        t = CE_TYPES.get(key)
        if not t:
            continue
        marker = " 🎯" if key == active else ""
        lines.append(f"{t['emoji']} <b>{t['name']}</b> ({t['rarity']}){marker}")
        lines.append(f"   <i>{t['desc']}</i>")
        lines.append("")
    return "\n".join(lines)


def format_clan_list(user_id: int) -> str:
    owned = database.get_clans(user_id)
    active = get_active_clan(user_id)
    if not owned:
        return "🩸 <b>Кланы</b>\n\n<i>Пока ничего не выбито.</i>"

    lines = ["🩸 <b>Твои кланы</b>", ""]
    for row in owned:
        key = row["clan_key"]
        c = CLANS.get(key)
        if not c:
            continue
        marker = " 🎯" if key == active else ""
        lines.append(f"{c['emoji']} <b>{c['name']}</b>{marker}")
        lines.append(f"   <i>{c['desc']}</i>")
        lines.append("")
    return "\n".join(lines)


def format_heavenly_list(user_id: int) -> str:
    owned = database.get_heavenly_restrictions(user_id)
    active = get_active_heavenly(user_id)
    if not owned:
        return "🌠 <b>Проклятия Небес</b>\n\n<i>Пока ничего не выбито.</i>"

    lines = ["🌠 <b>Твои Проклятия Небес</b>", ""]
    for row in owned:
        key = row["heavenly_key"]
        h = HEAVENLY_RESTRICTIONS.get(key)
        if not h:
            continue
        marker = " 🎯" if key == active else ""
        lines.append(f"{h['emoji']} <b>{h['name']}</b>{marker}")
        lines.append(f"   <i>{h['desc']}</i>")
        lines.append("")
    return "\n".join(lines)
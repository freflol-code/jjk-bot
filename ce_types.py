"""
Логика типов ПЭ, кланов и Проклятий Небес.

- Типы ПЭ: копятся у игрока, можно переключать активный.
- Кланы и Проклятия Небес: НЕ копятся. Выпало — сразу встало в слот,
  старое затирается. Крутишь снова — заменяется.
- get_active_effects(user_id) собирает эффекты от активных слотов.
- get_effective_stats(user_id, player) — max_hp/max_ce с учётом hp_mult/ce_mult
  от Проклятий Небес.
- При смене/снятии Проклятия Небес hp/ce пропорционально пересчитываются.
"""
import random
import database
from ce_types_data import (
    CE_TYPES, CLANS, HEAVENLY_RESTRICTIONS,
    CE_RARITY_WEIGHTS,
    CLAN_GACHA_HEAVENLY_CHANCE, CLAN_GACHA_CLAN_CHANCE,
)


# ============================================================
#  ВЫБОРКА ПО РЕДКОСТИ (для типов ПЭ)
# ============================================================

def _pool_by_rarity(rarity: str):
    return [key for key, t in CE_TYPES.items() if t["rarity"] == rarity]


def _roll_ce_rarity() -> str:
    rarities = list(CE_RARITY_WEIGHTS.keys())
    weights = list(CE_RARITY_WEIGHTS.values())
    return random.choices(rarities, weights=weights, k=1)[0]


# ============================================================
#  КРУТКА ТИПА ПЭ (типы копятся)
# ============================================================

def roll_ce_type(user_id: int) -> dict:
    """Типы ПЭ копятся. Если выпал новый — добавляем в коллекцию.
    Не выпал — kind='duplicate', ничего не меняется."""
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


# ============================================================
#  КРУТКА КЛАНА (кланы и Проклятия Небес НЕ копятся)
# ============================================================

def roll_clan(user_id: int) -> dict:
    """15% — Проклятие Небес, 10% — обычный клан, 75% — пусто.
    Выпавшее сразу ставится в единственный слот (заменяет старое)."""
    roll = random.random()

    # 1) Проклятие Небес
    if roll < CLAN_GACHA_HEAVENLY_CHANCE:
        old_effects = get_active_effects(user_id)
        old_mult_hp = old_effects.get("hp_mult", 1.0)
        old_mult_ce = old_effects.get("ce_mult", 1.0)

        old_key = database.get_active_heavenly(user_id)
        old_name = None
        if old_key and old_key in HEAVENLY_RESTRICTIONS:
            old_name = HEAVENLY_RESTRICTIONS[old_key]["name"]

        key = random.choice(list(HEAVENLY_RESTRICTIONS.keys()))
        database.set_active_heavenly(user_id, key)
        _rescale_hp_ce_on_switch(user_id, old_mult_hp, old_mult_ce)

        return {
            "ok": True,
            "kind": "heavenly",
            "key": key,
            "name": HEAVENLY_RESTRICTIONS[key]["name"],
            "emoji": HEAVENLY_RESTRICTIONS[key]["emoji"],
            "desc": HEAVENLY_RESTRICTIONS[key]["desc"],
            "old_name": old_name,
        }

    # 2) Обычный клан
    if roll < CLAN_GACHA_HEAVENLY_CHANCE + CLAN_GACHA_CLAN_CHANCE:
        old_key = database.get_active_clan(user_id)
        old_name = None
        if old_key and old_key in CLANS:
            old_name = CLANS[old_key]["name"]

        key = random.choice(list(CLANS.keys()))
        database.set_active_clan(user_id, key)

        return {
            "ok": True,
            "kind": "clan",
            "key": key,
            "name": CLANS[key]["name"],
            "emoji": CLANS[key]["emoji"],
            "desc": CLANS[key]["desc"],
            "old_name": old_name,
        }

    # 3) Пусто
    return {"ok": True, "kind": "empty"}


# ============================================================
#  АКТИВНЫЕ СЛОТЫ
# ============================================================

def get_active_ce_type(user_id: int) -> str | None:
    return database.get_active_ce_type(user_id)


def get_active_clan(user_id: int) -> str | None:
    return database.get_active_clan(user_id)


def get_active_heavenly(user_id: int) -> str | None:
    return database.get_active_heavenly(user_id)


# --- Типы ПЭ: переключение между выбитыми ---

def set_active_ce_type(user_id: int, key: str) -> dict:
    if key not in CE_TYPES:
        return {"ok": False, "msg": "Такого типа ПЭ не существует."}
    if not database.has_ce_type(user_id, key):
        return {"ok": False, "msg": "Этот тип ПЭ ещё не выбит."}
    database.set_active_ce_type(user_id, key)
    return {"ok": True, "msg": f"✅ Активный тип ПЭ: {CE_TYPES[key]['emoji']} {CE_TYPES[key]['name']}"}


def clear_ce_type(user_id: int) -> dict:
    database.clear_active_ce_type(user_id)
    return {"ok": True, "msg": "Активный тип ПЭ снят."}


# --- Кланы и Проклятия Небес: только снятие (ставить — через крутку) ---

def clear_clan(user_id: int) -> dict:
    database.clear_active_clan(user_id)
    return {"ok": True, "msg": "Клан снят."}


def clear_heavenly(user_id: int) -> dict:
    old_effects = get_active_effects(user_id)
    old_mult_hp = old_effects.get("hp_mult", 1.0)
    old_mult_ce = old_effects.get("ce_mult", 1.0)

    database.clear_active_heavenly(user_id)
    _rescale_hp_ce_on_switch(user_id, old_mult_hp, old_mult_ce)

    return {"ok": True, "msg": "Проклятие Небес снято."}


# ============================================================
#  СБОРКА ЭФФЕКТОВ
# ============================================================

def get_active_effects(user_id: int) -> dict:
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


# ============================================================
#  ЭФФЕКТИВНЫЕ СТАТЫ
# ============================================================

def get_effective_stats(user_id: int, player=None) -> dict:
    if player is None:
        player = database.get_or_create_player(user_id, "")
    effects = get_active_effects(user_id)
    hp_mult = effects.get("hp_mult", 1.0)
    ce_mult = effects.get("ce_mult", 1.0)

    eff_max_hp = max(1, int(player["max_hp"] * hp_mult))
    eff_max_ce = max(1, int(player["max_ce"] * ce_mult))

    return {
        "max_hp": eff_max_hp,
        "max_ce": eff_max_ce,
        "hp": min(player["hp"], eff_max_hp),
        "ce": min(player["ce"], eff_max_ce),
    }


def get_effective_player(user_id: int) -> dict:
    player = database.get_or_create_player(user_id, "")
    eff = get_effective_stats(user_id, player)
    d = dict(player)
    d["max_hp"] = eff["max_hp"]
    d["max_ce"] = eff["max_ce"]
    d["hp"] = eff["hp"]
    d["ce"] = eff["ce"]
    return d


def _rescale_hp_ce_on_switch(user_id: int, old_mult_hp: float, old_mult_ce: float):
    player = database.get_or_create_player(user_id, "")
    new_effects = get_active_effects(user_id)
    new_mult_hp = new_effects.get("hp_mult", 1.0)
    new_mult_ce = new_effects.get("ce_mult", 1.0)

    if old_mult_hp != new_mult_hp:
        old_eff_max = max(1, int(player["max_hp"] * old_mult_hp))
        new_eff_max = max(1, int(player["max_hp"] * new_mult_hp))
        old_eff_hp = min(player["hp"], old_eff_max)
        new_eff_hp = int(old_eff_hp * new_eff_max / old_eff_max)
        new_eff_hp = max(1, min(new_eff_hp, new_eff_max))
        database.update_player_hp(user_id, new_eff_hp)

    if old_mult_ce != new_mult_ce:
        old_eff_max = max(1, int(player["max_ce"] * old_mult_ce))
        new_eff_max = max(1, int(player["max_ce"] * new_mult_ce))
        old_eff_ce = min(player["ce"], old_eff_max)
        new_eff_ce = int(old_eff_ce * new_eff_max / old_eff_max)
        new_eff_ce = max(0, min(new_eff_ce, new_eff_max))
        database.update_player_ce(user_id, new_eff_ce)


def compress_hp_ce(user_id: int):
    player = database.get_or_create_player(user_id, "")
    eff = get_effective_stats(user_id, player)
    if player["hp"] > eff["max_hp"]:
        database.update_player_hp(user_id, eff["max_hp"])
    if player["ce"] > eff["max_ce"]:
        database.update_player_ce(user_id, eff["max_ce"])


# ============================================================
#  UI-ФОРМАТИРОВАНИЕ
# ============================================================

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


def format_equipment_list(user_id: int) -> str:
    """Единый экран снаряжения: текущий клан и текущее Проклятие Небес.
    Оба — в единственном слоте, заменяются при следующем выпадении."""
    clan_key = get_active_clan(user_id)
    heavenly_key = get_active_heavenly(user_id)

    lines = ["🎯 <b>Снаряжение Проклятий</b>", ""]

    if clan_key and clan_key in CLANS:
        c = CLANS[clan_key]
        lines.append(f"🩸 <b>Клан:</b> {c['emoji']} {c['name']}")
        lines.append(f"   <i>{c['desc']}</i>")
    else:
        lines.append("🩸 <b>Клан:</b> <i>не выбит</i>")

    lines.append("")

    if heavenly_key and heavenly_key in HEAVENLY_RESTRICTIONS:
        h = HEAVENLY_RESTRICTIONS[heavenly_key]
        lines.append(f"🌠 <b>Проклятие Небес:</b> {h['emoji']} {h['name']}")
        lines.append(f"   <i>{h['desc']}</i>")
    else:
        lines.append("🌠 <b>Проклятие Небес:</b> <i>не выбито</i>")

    lines.append("")
    lines.append("<i>Крути гачу — что выпадет, то и встанет в слот. "
                 "Старое затирается. Снять можно вручную.</i>")

    return "\n".join(lines)

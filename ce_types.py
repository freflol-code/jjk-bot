"""
Логика типов ПЭ, кланов и Проклятий Небес.

- Ролл типа ПЭ (по редкости, без Проклятий Небес).
- Ролл x10 типов ПЭ разом.
- Ролл клана: 15% — Проклятие Небес, 10% — обычный клан, 75% — пусто.
- Выдача, экип, снятие.
- get_active_effects(user_id) собирает эффекты от активных слотов.
- get_effective_stats(user_id, player) — эффективные max_hp/max_ce с учётом
  hp_mult/ce_mult от Проклятий Небес.
- При смене/снятии Проклятия Небес hp/ce в БД пропорционально пересчитываются.
"""
import random
import database
from ce_types_data import (
    CE_TYPES, CLANS, HEAVENLY_RESTRICTIONS,
    CE_RARITY_WEIGHTS,
    CLAN_GACHA_HEAVENLY_CHANCE, CLAN_GACHA_CLAN_CHANCE,
)


# ============================================================
#  ВЫБОРКА ПО РЕДКОСТИ
# ============================================================

def _pool_by_rarity(rarity: str):
    return [key for key, t in CE_TYPES.items() if t["rarity"] == rarity]


def _roll_ce_rarity() -> str:
    rarities = list(CE_RARITY_WEIGHTS.keys())
    weights = list(CE_RARITY_WEIGHTS.values())
    return random.choices(rarities, weights=weights, k=1)[0]


# ============================================================
#  КРУТКА ТИПА ПЭ
# ============================================================

def roll_ce_type(user_id: int) -> dict:
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


def roll_ce_type_x10(user_id: int) -> dict:
    """10 круток типов ПЭ разом. Возвращает список результатов."""
    results = []
    for _ in range(10):
        rarity = _roll_ce_rarity()
        key = random.choice(_pool_by_rarity(rarity))
        is_new = database.add_ce_type(user_id, key, rarity)
        results.append({
            "ok": True,
            "kind": "ce" if is_new else "duplicate",
            "key": key,
            "rarity": rarity,
            "name": CE_TYPES[key]["name"],
            "emoji": CE_TYPES[key]["emoji"],
            "desc": CE_TYPES[key]["desc"],
        })
    return {"ok": True, "results": results}


# ============================================================
#  КРУТКА КЛАНА
# ============================================================

def roll_clan(user_id: int) -> dict:
    roll = random.random()
    if roll < CLAN_GACHA_HEAVENLY_CHANCE:
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
    if roll < CLAN_GACHA_HEAVENLY_CHANCE + CLAN_GACHA_CLAN_CHANCE:
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

    old_effects = get_active_effects(user_id)
    old_mult_hp = old_effects.get("hp_mult", 1.0)
    old_mult_ce = old_effects.get("ce_mult", 1.0)

    database.set_active_heavenly(user_id, key)
    _rescale_hp_ce_on_switch(user_id, old_mult_hp, old_mult_ce)

    return {"ok": True, "msg": (
        f"✅ Активное Проклятие Небес: "
        f"{HEAVENLY_RESTRICTIONS[key]['emoji']} {HEAVENLY_RESTRICTIONS[key]['name']}"
    )}


def clear_ce_type(user_id: int) -> dict:
    database.clear_active_ce_type(user_id)
    return {"ok": True, "msg": "Активный тип ПЭ снят."}


def clear_clan(user_id: int) -> dict:
    database.clear_active_clan(user_id)
    return {"ok": True, "msg": "Активный клан снят."}


def clear_heavenly(user_id: int) -> dict:
    old_effects = get_active_effects(user_id)
    old_mult_hp = old_effects.get("hp_mult", 1.0)
    old_mult_ce = old_effects.get("ce_mult", 1.0)

    database.clear_active_heavenly(user_id)
    _rescale_hp_ce_on_switch(user_id, old_mult_hp, old_mult_ce)

    return {"ok": True, "msg": "Активное Проклятие Небес снято."}


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
        "phys_dmg_div": 1.0,
        "dodge_chance": 0.0,
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
            elif k == "phys_dmg_div":
                result[k] = max(result[k], v)
            else:
                result[k] += v

    return result


# ============================================================
#  ЭФФЕКТИВНЫЕ СТАТЫ
# ============================================================

def get_effective_stats(user_id: int, player=None) -> dict:
    """Возвращает {hp, max_hp, ce, max_ce} с учётом hp_mult / ce_mult.
    Если множитель = 0, соответствующий стат = 0 (Тоджи/Маки: ПЭ = 0)."""
    if player is None:
        player = database.get_or_create_player(user_id, "")
    effects = get_active_effects(user_id)
    hp_mult = effects.get("hp_mult", 1.0)
    ce_mult = effects.get("ce_mult", 1.0)

    if hp_mult <= 0:
        eff_max_hp = 0
    else:
        eff_max_hp = max(1, int(player["max_hp"] * hp_mult))

    if ce_mult <= 0:
        eff_max_ce = 0
    else:
        eff_max_ce = max(1, int(player["max_ce"] * ce_mult))

    eff_hp = min(player["hp"], eff_max_hp) if eff_max_hp > 0 else 0
    eff_ce = min(player["ce"], eff_max_ce) if eff_max_ce > 0 else 0

    return {
        "max_hp": eff_max_hp,
        "max_ce": eff_max_ce,
        "hp": eff_hp,
        "ce": eff_ce,
    }


def get_effective_player(user_id: int) -> dict:
    """dict-обёртка игрока с эффективными hp/ce."""
    player = database.get_or_create_player(user_id, "")
    eff = get_effective_stats(user_id, player)
    d = dict(player)
    d["max_hp"] = eff["max_hp"]
    d["max_ce"] = eff["max_ce"]
    d["hp"] = eff["hp"]
    d["ce"] = eff["ce"]
    return d


def _rescale_hp_ce_on_switch(user_id: int, old_mult_hp: float, old_mult_ce: float):
    """Пропорционально пересчитывает hp/ce в БД после смены Проклятия Небес.
    Корректно обрабатывает случаи old/new mult = 0 (Тоджи/Маки: ПЭ = 0)."""
    player = database.get_or_create_player(user_id, "")
    new_effects = get_active_effects(user_id)
    new_mult_hp = new_effects.get("hp_mult", 1.0)
    new_mult_ce = new_effects.get("ce_mult", 1.0)

    # ---- HP ----
    if old_mult_hp != new_mult_hp:
        if old_mult_hp <= 0:
            old_eff_max = 0
            old_eff_hp = 0
        else:
            old_eff_max = max(1, int(player["max_hp"] * old_mult_hp))
            old_eff_hp = min(player["hp"], old_eff_max)

        if new_mult_hp <= 0:
            new_eff_hp = 0
        else:
            new_eff_max = max(1, int(player["max_hp"] * new_mult_hp))
            if old_eff_max > 0:
                new_eff_hp = int(old_eff_hp * new_eff_max / old_eff_max)
            else:
                new_eff_hp = new_eff_max
            new_eff_hp = max(1, min(new_eff_hp, new_eff_max))
        database.update_player_hp(user_id, new_eff_hp)

    # ---- CE ----
    if old_mult_ce != new_mult_ce:
        if old_mult_ce <= 0:
            old_eff_max = 0
            old_eff_ce = 0
        else:
            old_eff_max = max(1, int(player["max_ce"] * old_mult_ce))
            old_eff_ce = min(player["ce"], old_eff_max)

        if new_mult_ce <= 0:
            new_eff_ce = 0
        else:
            new_eff_max = max(1, int(player["max_ce"] * new_mult_ce))
            if old_eff_max > 0:
                new_eff_ce = int(old_eff_ce * new_eff_max / old_eff_max)
            else:
                new_eff_ce = new_eff_max
            new_eff_ce = max(0, min(new_eff_ce, new_eff_max))
        database.update_player_ce(user_id, new_eff_ce)


def compress_hp_ce(user_id: int):
    """Обрезает hp/ce в БД до эффективных значений. Вызывать после levelup."""
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

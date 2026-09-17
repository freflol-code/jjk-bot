"""
equipment.py — проклятое оружие: покупка, крафт, экипировка.

Оружие бывает двух типов:
  - Покупается у Хакари во вкладке «🏴‍☠️ Склад проклятого оружия»
    (только слабые и средние мечи).
  - Крафтится из КОНКРЕТНЫХ трофеев проклятий (см. RECIPES) —
    сильные и легендарные. Ингредиенты разбросаны по районам и требуют
    реальной охоты, а топовое оружие требует дропа с боссов Особого класса.

Бонусы оружия применяются в combat.py:
  - dmg_bonus_min/max — прибавка к физ. урону
  - tech_power       — множитель урона врождённых техник
  - crit_bonus       — плюс к шансу Чёрной Вспышки (0.02 = +2%)

За экипированное оружие можно держать только одно. Сменить можно
в любой момент, ничего не теряется.
"""
import database


# ---------------- ОРУЖИЕ ----------------

WEAPONS = {
    # --- ОБЫЧНЫЕ (покупка) ---
    "Ржавый тесак": {
        "emoji": "🗡", "rarity": "обычный", "price": 100,
        "dmg_bonus_min": 2, "dmg_bonus_max": 4,
        "tech_power": 1.00, "crit_bonus": 0.0,
        "desc": "Тупой, но всё же лучше кулака.",
    },
    "Учебный боккэн": {
        "emoji": "🥋", "rarity": "обычный", "price": 150,
        "dmg_bonus_min": 3, "dmg_bonus_max": 5,
        "tech_power": 1.05, "crit_bonus": 0.0,
        "desc": "Деревянный меч из школы магии. Учит не размахивать зря.",
    },

    # --- НЕОБЫЧНЫЕ (покупка) ---
    "Клинок Магической Ассоциации": {
        "emoji": "⚔️", "rarity": "необычный", "price": 350,
        "dmg_bonus_min": 5, "dmg_bonus_max": 9,
        "tech_power": 1.10, "crit_bonus": 0.01,
        "desc": "Стандартный клинок выпускника школы.",
    },
    "Копьё Послушника": {
        "emoji": "🔱", "rarity": "необычный", "price": 400,
        "dmg_bonus_min": 4, "dmg_bonus_max": 11,
        "tech_power": 1.08, "crit_bonus": 0.02,
        "desc": "Длинное, неудобное, но пробивает хорошо.",
    },

    # --- РЕДКИЕ (крафт) ---
    "Клинок Проклятой Энергии": {
        "emoji": "🗡️", "rarity": "редкий", "price": 0,
        "dmg_bonus_min": 9, "dmg_bonus_max": 15,
        "tech_power": 1.15, "crit_bonus": 0.02,
        "desc": "Клинок, что пропускает через себя ПЭ владельца.",
    },
    "Парные клинки": {
        "emoji": "⚔️", "rarity": "редкий", "price": 0,
        "dmg_bonus_min": 7, "dmg_bonus_max": 17,
        "tech_power": 1.18, "crit_bonus": 0.03,
        "desc": "Быстрые, несимметричные, требуют обеих рук.",
    },

    # --- ЭПИЧЕСКИЕ (крафт) ---
    "Меч Кровавой Луны": {
        "emoji": "🌒", "rarity": "эпический", "price": 0,
        "dmg_bonus_min": 14, "dmg_bonus_max": 22,
        "tech_power": 1.25, "crit_bonus": 0.04,
        "desc": "Пьёт кровь проклятий и возвращает её владельцу.",
    },
    "Катана Фушигуро": {
        "emoji": "🗾", "rarity": "эпический", "price": 0,
        "dmg_bonus_min": 16, "dmg_bonus_max": 24,
        "tech_power": 1.28, "crit_bonus": 0.05,
        "desc": "Одно из проклятых орудий клана Зенин. Помнит своего хозяина.",
    },

    # --- ЛЕГЕНДАРНЫЕ (крафт) ---
    "Копьё Небесного Обращения": {
        "emoji": "🌠", "rarity": "легендарный", "price": 0,
        "dmg_bonus_min": 20, "dmg_bonus_max": 30,
        "tech_power": 1.35, "crit_bonus": 0.06,
        "desc": "Оружие, способное отменять врождённые техники. Требует особого трофея.",
    },
    "Разделяющий клинок": {
        "emoji": "💀", "rarity": "легендарный", "price": 0,
        "dmg_bonus_min": 24, "dmg_bonus_max": 36,
        "tech_power": 1.45, "crit_bonus": 0.08,
        "desc": "Говорят, его выковали по осколку памяти Сукуны.",
    },
}


# ---------------- РЕЦЕПТЫ КРАФТА ----------------

# materials: {точное_имя_предмета: количество}.
# Ингредиенты разбросаны по районам — придётся патрулировать разные локации.
# Печати (эпические) дропают мини-боссы 1-го класса.
# Уникальные легендарные трофеи — только с боссов Особого класса.
RECIPES = {
    # ---- РЕДКИЕ ----
    "Клинок Проклятой Энергии": {
        "materials": {
            "Осколок Погасшей Вывески": 3,   # Синдзюку: Квартал Тьмы, 4-й класс
            "Треснувший Жетон": 3,            # Икэбукуро, 4-й класс
            "Треснувший Колокольчик": 2,      # Асакуса, 4-й класс
        },
        "gold": 250,
    },
    "Парные клинки": {
        "materials": {
            "Разбитый Экран Телефона": 2,     # Сибуя, 3-й класс
            "Пыльная Коробка": 2,             # Акихабара, 3-й класс
            "Треснувшее Зеркальце": 3,        # Гиндза, 4-й класс
        },
        "gold": 400,
    },

    # ---- ЭПИЧЕСКИЕ ----
    "Меч Кровавой Луны": {
        "materials": {
            "Рваный Плащ Скверны": 2,         # Синдзюку, 2-й класс
            "Чётки Скверны": 2,               # Асакуса, 2-й класс
            "Фальшивый Бриллиант": 1,         # Гиндза, 2-й класс
        },
        "gold": 800,
    },
    "Катана Фушигуро": {
        "materials": {
            "Обрывок Троса": 2,               # Одайба, 2-й класс
            "Мятая Карта Метро": 2,           # Сибуя, 2-й класс
            "Оплавленный Чип": 3,             # Акихабара, 2-й класс
        },
        "gold": 1200,
    },

    # ---- ЛЕГЕНДАРНЫЕ ----
    "Копьё Небесного Обращения": {
        "materials": {
            "Печать Тьмы": 1,                 # Синдзюку, мини-босс (1-й класс)
            "Печать Забытых Богов": 1,        # Уэно или Асакуса, мини-босс
            "Печать Высоты": 1,               # Роппонги или Гиндза, мини-босс
        },
        "gold": 1500,
    },
    "Разделяющий клинок": {
        "materials": {
            "Печать Бездны": 1,               # Зона Инцидента, мини-босс
            "Печать Залива": 1,               # Одайба, мини-босс
            "Печать Толпы": 1,                # Сибуя, мини-босс
            "Сердце Пустоты": 1,              # Только с босса «Проклятие Истинной Бездны»
        },
        "gold": 2500,
    },
}


# ---------------- ФУНКЦИИ ----------------

def get_weapon(name: str) -> dict | None:
    return WEAPONS.get(name)


def is_purchasable(name: str) -> bool:
    w = WEAPONS.get(name)
    return bool(w and w.get("price", 0) > 0)


def is_craftable(name: str) -> bool:
    return name in RECIPES


def list_purchasable() -> list[tuple[str, dict]]:
    """Оружие, которое продаёт Хакари (price > 0)."""
    return [(n, w) for n, w in WEAPONS.items() if w.get("price", 0) > 0]


def list_craftable() -> list[tuple[str, dict]]:
    """Оружие, которое можно скрафтить."""
    return [(n, WEAPONS[n]) for n in RECIPES if n in WEAPONS]


def check_recipe(user_id: int, weapon_name: str) -> dict:
    """Проверяет, хватает ли КОНКРЕТНЫХ ингредиентов и золота.
    Возвращает {ok, missing:[...], recipe}."""
    recipe = RECIPES.get(weapon_name)
    if not recipe:
        return {"ok": False, "msg": "У этого оружия нет рецепта."}

    player = database.get_or_create_player(user_id, "")
    missing = []
    for item_name, need in recipe["materials"].items():
        have = database.count_item(user_id, item_name)
        if have < need:
            missing.append(f"{item_name}: нужно {need}, есть {have}")

    gold_need = recipe["gold"]
    gold_have = player["gold"]
    if gold_have < gold_need:
        missing.append(f"💠 нужно {gold_need}, есть {gold_have}")

    return {
        "ok": not missing,
        "missing": missing,
        "gold_need": gold_need,
        "gold_have": gold_have,
        "recipe": recipe,
    }


def craft(user_id: int, weapon_name: str) -> dict:
    """Крафтит оружие. Списывает конкретные трофеи и золото, добавляет в коллекцию."""
    if not is_craftable(weapon_name):
        return {"ok": False, "msg": "Это оружие нельзя скрафтить."}
    if database.has_weapon(user_id, weapon_name):
        return {"ok": False, "msg": "У тебя уже есть это оружие."}

    check = check_recipe(user_id, weapon_name)
    if not check["ok"]:
        return {"ok": False, "msg": "Не хватает ресурсов: " + "; ".join(check["missing"])}

    recipe = check["recipe"]
    for item_name, need in recipe["materials"].items():
        database.consume_item(user_id, item_name, need)
    database.add_gold(user_id, -recipe["gold"])
    database.add_player_weapon(user_id, weapon_name)

    w = WEAPONS[weapon_name]
    return {
        "ok": True,
        "msg": f"🔨 Скрафчено: {w['emoji']} <b>{weapon_name}</b> ({w['rarity']}).",
    }


def buy(user_id: int, weapon_name: str) -> dict:
    """Покупка оружия у Хакари."""
    if not is_purchasable(weapon_name):
        return {"ok": False, "msg": "Хакари такое не продаёт. Такое только крафтить."}
    if database.has_weapon(user_id, weapon_name):
        return {"ok": False, "msg": "У тебя уже есть это оружие."}

    w = WEAPONS[weapon_name]
    player = database.get_or_create_player(user_id, "")
    if player["gold"] < w["price"]:
        return {"ok": False, "msg": f"Не хватает очков. Нужно {w['price']}💠, у тебя {player['gold']}💠."}

    database.add_gold(user_id, -w["price"])
    database.add_player_weapon(user_id, weapon_name)
    return {
        "ok": True,
        "msg": f"✅ Куплено: {w['emoji']} <b>{weapon_name}</b> за {w['price']}💠.",
    }


def equip(user_id: int, weapon_name: str) -> dict:
    if not database.has_weapon(user_id, weapon_name):
        return {"ok": False, "msg": "У тебя нет этого оружия."}
    database.set_equipped_weapon(user_id, weapon_name)
    w = WEAPONS[weapon_name]
    return {"ok": True, "msg": f"⚔️ Экипировано: {w['emoji']} <b>{weapon_name}</b>."}


def unequip(user_id: int) -> dict:
    current = database.get_equipped_weapon_name(user_id)
    if not current:
        return {"ok": False, "msg": "Ты и так без оружия."}
    database.clear_equipped_weapon(user_id)
    return {"ok": True, "msg": f"❎ Снято: <b>{current}</b>."}


def get_equipped(user_id: int) -> dict | None:
    name = database.get_equipped_weapon_name(user_id)
    if not name:
        return None
    w = WEAPONS.get(name)
    if not w:
        return None
    return {"name": name, **w}


def get_bonuses(user_id: int) -> dict:
    """Суммарные бонусы от экипированного оружия (для combat.py)."""
    w = get_equipped(user_id)
    if not w:
        return {"dmg_min": 0, "dmg_max": 0, "tech_power": 1.0, "crit_bonus": 0.0}
    return {
        "dmg_min": w["dmg_bonus_min"],
        "dmg_max": w["dmg_bonus_max"],
        "tech_power": w["tech_power"],
        "crit_bonus": w["crit_bonus"],
    }
"""
Боссы Особого класса и ритуальные печати, которые их призывают.

Печати дропаются с мини-боссов (проклятия 1-го класса, см. world.py) с
шансом DROP_CHANCE в бою (combat.py) и попадают в инвентарь с
rarity="призыв". Использовать печать можно из инвентаря — начнётся бой
с боссом Особого класса того же района.
Бой идёт через тот же combat.py, что и обычный - просто у боссов
значительно больше HP, урона и наград.
"""
import database
from world import get_district_by_x


BOSSES = {
    "Проклятие Бесконечной Ночи (Особый класс)": {
        "emoji": "🌑",
        "hp": 900,
        "dmg_min": 30, "dmg_max": 45,
        "rarity": "Особый класс",
        "reward_gold": 900,
        "reward_exp": 700,
        "drop_item": ("Осколок Вечной Тьмы", "легендарный", 2),
    },
    "Королева Пустого Квартала (Особый класс)": {
        "emoji": "📱",
        "hp": 750,
        "dmg_min": 26, "dmg_max": 38,
        "rarity": "Особый класс",
        "reward_gold": 750,
        "reward_exp": 600,
        "drop_item": ("Ядро Цифрового Голода", "легендарный", 2),
    },
    "Страж Забытых Богов (Особый класс)": {
        "emoji": "⛩️",
        "hp": 650,
        "dmg_min": 22, "dmg_max": 33,
        "rarity": "Особый класс",
        "reward_gold": 650,
        "reward_exp": 520,
        "drop_item": ("Печать Древнего Святилища", "легендарный", 2),
    },
    "Проклятие Финального Экзамена (Особый класс)": {
        "emoji": "📝",
        "hp": 400,
        "dmg_min": 16, "dmg_max": 24,
        "rarity": "Особый класс",
        "reward_gold": 300,
        "reward_exp": 250,
        "drop_item": ("Идеальный Конспект", "эпический", 2),
    },
    "Пожиратель Тысячи Лиц (Особый класс)": {
        "emoji": "🚦",
        "hp": 700,
        "dmg_min": 24, "dmg_max": 34,
        "rarity": "Особый класс",
        "reward_gold": 700,
        "reward_exp": 560,
        "drop_item": ("Маска Скрещения", "легендарный", 2),
    },
    "Владыка Небоскрёбов (Особый класс)": {
        "emoji": "🏙️",
        "hp": 850,
        "dmg_min": 28, "dmg_max": 40,
        "rarity": "Особый класс",
        "reward_gold": 850,
        "reward_exp": 680,
        "drop_item": ("Осколок Небесного Стекла", "легендарный", 2),
    },
    "Морской Владыка Одайбы (Особый класс)": {
        "emoji": "🌊",
        "hp": 800,
        "dmg_min": 27, "dmg_max": 39,
        "rarity": "Особый класс",
        "reward_gold": 800,
        "reward_exp": 640,
        "drop_item": ("Трезубец Скверны", "легендарный", 2),
    },
    "Проклятие Истинной Бездны (Особый класс)": {
        "emoji": "🕳️",
        "hp": 1300,
        "dmg_min": 38, "dmg_max": 55,
        "rarity": "Особый класс",
        "reward_gold": 2200,
        "reward_exp": 1700,
        "drop_item": ("Сердце Пустоты", "легендарный", 3),
    },
}


# Ключ = название ритуальной печати (предмет из инвентаря)
SUMMON_RECIPES = {
    "Печать Тьмы": {
        "emoji": "🌑",
        "boss": "Проклятие Бесконечной Ночи (Особый класс)",
        "materials": {"Печать Тьмы": 1},
        "required_biome": ["shinjuku_dark"],
        "desc": "Призывает Проклятие Бесконечной Ночи (Квартал Тьмы)",
    },
    "Печать Цифрового Голода": {
        "emoji": "📱",
        "boss": "Королева Пустого Квартала (Особый класс)",
        "materials": {"Печать Цифрового Голода": 1},
        "required_biome": ["ikebukuro", "akihabara"],
        "desc": "Призывает Королеву Пустого Квартала (Икэбукуро/Акихабара)",
    },
    "Печать Забытых Богов": {
        "emoji": "⛩️",
        "boss": "Страж Забытых Богов (Особый класс)",
        "materials": {"Печать Забытых Богов": 1},
        "required_biome": ["ueno", "asakusa"],
        "desc": "Призывает Стража Забытых Богов (Уэно/Асакуса)",
    },
    "Печать Учебной Тревоги": {
        "emoji": "📝",
        "boss": "Проклятие Финального Экзамена (Особый класс)",
        "materials": {"Печать Учебной Тревоги": 1},
        "required_biome": ["jujutsu_high"],
        "desc": "Призывает Проклятие Финального Экзамена (Школа магии)",
    },
    "Печать Толпы": {
        "emoji": "🚦",
        "boss": "Пожиратель Тысячи Лиц (Особый класс)",
        "materials": {"Печать Толпы": 1},
        "required_biome": ["shibuya"],
        "desc": "Призывает Пожирателя Тысячи Лиц (Сибуя)",
    },
    "Печать Высоты": {
        "emoji": "🏙️",
        "boss": "Владыка Небоскрёбов (Особый класс)",
        "materials": {"Печать Высоты": 1},
        "required_biome": ["roppongi", "ginza"],
        "desc": "Призывает Владыку Небоскрёбов (Роппонги/Гиндза)",
    },
    "Печать Залива": {
        "emoji": "🌊",
        "boss": "Морской Владыка Одайбы (Особый класс)",
        "materials": {"Печать Залива": 1},
        "required_biome": ["odaiba"],
        "desc": "Призывает Морского Владыку Одайбы (Одайба)",
    },
    "Печать Бездны": {
        "emoji": "🕳️",
        "boss": "Проклятие Истинной Бездны (Особый класс)",
        "materials": {"Печать Бездны": 1},
        "required_biome": ["shibuya_incident"],
        "desc": "Призывает Проклятие Истинной Бездны (Зона Инцидента) — сильнейший враг игры",
    },
}


def is_boss(monster_name: str) -> bool:
    return monster_name in BOSSES


def summon(user_id: int, item_name: str, x: int) -> dict:
    recipe = SUMMON_RECIPES.get(item_name)
    if not recipe:
        return {"ok": False, "msg": "Это не ритуальная печать."}
    if database.count_item(user_id, item_name) < 1:
        return {"ok": False, "msg": "У тебя нет этой печати."}

    if database.get_encounter(user_id):
        return {"ok": False, "msg": "Ты уже в бою! Сначала закончи текущий бой."}

    required = recipe.get("required_biome")
    district = get_district_by_x(x)
    if required and district["id"] not in required:
        return {"ok": False, "msg": f"Здесь печать не сработает. {recipe['desc']}"}

    boss_name = recipe["boss"]
    boss = BOSSES[boss_name]
    monster = {
        "name": boss_name,
        "hp": boss["hp"],
        "dmg_min": boss["dmg_min"],
        "dmg_max": boss["dmg_max"],
        "emoji": boss["emoji"],
        "rarity": boss["rarity"],
        "curse_class": "Особый класс",
        "drop_item": None,
        "drop_rarity": None,
    }
    database.set_encounter(user_id, district["id"], monster)
    database.consume_item(user_id, item_name, 1)
    return {
        "ok": True,
        "msg": f"⚡ {boss['emoji']} <b>{boss_name}</b> материализовался! Годжо: «Ну наконец-то, повеселимся.»",
    }

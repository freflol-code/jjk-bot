"""
Расходуемые предметы: еда, зелья, свитки, талисманы.
"""
import database
import quests
from config import RARITY_EMOJI


CONSUMABLES = {
    # ---------------- ЕДА И ЗЕЛЬЯ ----------------
    "🍙 Онигири": {
        "price": 16,
        "heal": 20,
        "desc": "Восстанавливает 20 HP",
    },
    "🍜 Рамен додзё": {
        "price": 40,
        "heal": 50,
        "desc": "Восстанавливает 50 HP",
    },
    "🧪 Проклятая микстура": {
        "price": 120,
        "heal_full": True,
        "ce_full": True,
        "desc": "Полностью восстанавливает HP и Проклятую Энергию",
    },
    "📜 Свиток телепортации": {
        "price": 64,
        "teleport_to": 0,
        "desc": "Телепорт в Токийскую школу магии (центр карты)",
    },
    "📜 Свиток опыта Годжо": {
        "price": 0,
        "exp_gain": 500,
        "desc": "Даёт 500 опыта. Награда за все выполненные недельные задания.",
    },

    # ---------------- БАФФЫ (реальное время) ----------------
    "🧧 Талисман силы": {
        "price": 160,
        "buff": {"stat": "dmg_bonus", "value": 0.15, "duration_minutes": 30},
        "desc": "+15% физ. урона на 30 минут",
    },
    "🛡 Талисман стойкости": {
        "price": 160,
        "buff": {"stat": "defense_bonus", "value": 0.10, "duration_minutes": 30},
        "desc": "+10% защиты на 30 минут",
    },
    "💠 Талисман потока": {
        "price": 200,
        "buff": {"stat": "ce_regen_bonus", "value": 0.50, "duration_minutes": 20},
        "desc": "+50% к регену ПЭ на 20 минут",
    },
    "⚫ Талисман Вспышки": {
        "price": 240,
        "buff": {"stat": "crit_bonus", "value": 0.05, "duration_minutes": 20},
        "desc": "+5% к шансу Чёрной Вспышки на 20 минут",
    },
    "🧬 Эликсир роста": {
        "price": 400,
        "buff": {"stat": "exp_bonus", "value": 0.25, "duration_minutes": 60},
        "desc": "+25% опыта с боёв на 60 минут",
    },
    "💰 Эликсир охотника": {
        "price": 400,
        "buff": {"stat": "gold_bonus", "value": 0.25, "duration_minutes": 60},
        "desc": "+25% очков Ассоциации с боёв на 60 минут",
    },

    # ---------------- ПРИМАНКИ НА КЛАССЫ ----------------
    "🧭 Компас Скверны": {
        "price": 250,
        "buff": {"stat": "curse_hunt_2", "value": 2.0, "duration_minutes": 30},
        "desc": "+200% к шансу появления проклятий 2-го класса на 30 минут",
    },
    "🎯 Метка Годжо": {
        "price": 400,
        "buff": {"stat": "curse_hunt_1", "value": 4.0, "duration_minutes": 20},
        "desc": "+400% к шансу появления проклятий 1-го класса на 20 минут",
    },
}


def is_buff(item_name: str) -> bool:
    item = CONSUMABLES.get(item_name)
    return bool(item and item.get("buff"))


def use(user_id: int, item_name: str) -> dict:
    item = CONSUMABLES.get(item_name)
    if not item:
        return {"ok": False, "msg": "Это не расходуемый предмет."}
    if database.count_item(user_id, item_name) < 1:
        return {"ok": False, "msg": "У тебя нет этого предмета."}

    player = database.get_or_create_player(user_id, "")
    msgs = []
    leveled = False
    new_level = None

    if item.get("heal_full"):
        database.update_player_hp(user_id, player["max_hp"])
        msgs.append(f"❤️ HP полностью восстановлено до {player['max_hp']}")
    elif "heal" in item:
        new_hp = min(player["hp"] + item["heal"], player["max_hp"])
        healed = new_hp - player["hp"]
        database.update_player_hp(user_id, new_hp)
        msgs.append(f"❤️ +{healed} HP (теперь {new_hp}/{player['max_hp']})")

    if item.get("ce_full"):
        database.update_player_ce(user_id, player["max_ce"])
        msgs.append(f"🔵 ПЭ полностью восстановлена до {player['max_ce']}")

    if "teleport_to" in item:
        database.update_player_x(user_id, item["teleport_to"])
        msgs.append("🌀 Ты телепортировался в Токийскую школу магии")

    if "exp_gain" in item:
        new_level, leveled = database.add_exp_and_level(user_id, item["exp_gain"])
        msgs.append(f"🧬 +{item['exp_gain']} опыта Годжо")
        if leveled:
            msgs.append(f"🎉 <b>Уровень повышен до {new_level}!</b> HP и ПЭ восстановлены.")

    if "buff" in item:
        b = item["buff"]
        duration_sec = b["duration_minutes"] * 60
        database.add_player_buff(user_id, b["stat"], b["value"], duration_sec)
        label_map = {
            "dmg_bonus": "урона",
            "defense_bonus": "защиты",
            "ce_regen_bonus": "регена ПЭ",
            "crit_bonus": "шанса Чёрной Вспышки",
            "exp_bonus": "опыта",
            "gold_bonus": "очков Ассоциации",
            "curse_hunt_1": "шанса 1-го класса",
            "curse_hunt_2": "шанса 2-го класса",
        }
        msgs.append(
            f"✨ Бафф активен: +{int(b['value']*100)}% {label_map.get(b['stat'], b['stat'])} "
            f"на {b['duration_minutes']} мин."
        )

    database.consume_item(user_id, item_name, 1)

    # Квестовый трекинг
    quests.add_progress(user_id, "consumable_use")

    return {"ok": True, "msg": "\n".join(msgs)}
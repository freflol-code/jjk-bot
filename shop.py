"""
НПС и магазин.

Хакари стоит в Токийской школе магии (X=0). Продаёт расходники (еду,
зелья, свитки, талисманы), скупает трофеи проклятий. Отдельная вкладка —
«🏴‍☠️ Склад проклятого оружия» (реализована в equipment.py + main.py),
там же можно скрафтить оружие из трофеев.
"""
import database
from consumables import CONSUMABLES


SELL_PRICES = {
    "обычный": 3,
    "необычный": 8,
    "редкий": 25,
    "эпический": 70,
    "легендарный": 220,
}

NON_SELLABLE_RARITIES = {"расходник", "призыв"}


NPCS = {
    "hakari": {
        "id": "hakari",
        "name": "Хакари",
        "emoji": "🎰",
        "x": 0,
        "greeting": "О, свежее мясо для патруля. Заходи — у меня есть и снаряжение, и кручёные техники.",
        "sells": [
            "🍙 Онигири", "🍜 Рамен додзё", "🧪 Проклятая микстура", "📜 Свиток телепортации",
            "🧧 Талисман силы", "🛡 Талисман стойкости", "💠 Талисман потока", "⚫ Талисман Вспышки",
            "🧬 Эликсир роста", "💰 Эликсир охотника",
        ],
        "buy_multiplier": 1.0,
    },
}


def npc_at(x: int):
    for npc in NPCS.values():
        if npc["x"] == x:
            return npc
    return None


def get_npc(npc_id: str):
    return NPCS.get(npc_id)


def buy(user_id: int, npc_id: str, item_name: str) -> dict:
    npc = NPCS.get(npc_id)
    if not npc:
        return {"ok": False, "msg": "Такого торговца нет."}
    if item_name not in npc["sells"]:
        return {"ok": False, "msg": "Хакари такое не продаёт."}

    item = CONSUMABLES.get(item_name)
    if not item:
        return {"ok": False, "msg": "Такого товара нет."}

    price = item["price"]
    player = database.get_or_create_player(user_id, "")
    if player["gold"] < price:
        return {"ok": False, "msg": f"Не хватает очков Ассоциации. Нужно {price}💠, у тебя {player['gold']}💠."}

    database.add_gold(user_id, -price)
    database.add_item(user_id, item_name, "расходник", 1)
    return {"ok": True, "msg": f"✅ Куплено: {item_name} за {price}💠"}


def sell(user_id: int, npc_id: str, item_name: str, rarity: str) -> dict:
    npc = NPCS.get(npc_id)
    if not npc:
        return {"ok": False, "msg": "Такого торговца нет."}
    if rarity in NON_SELLABLE_RARITIES:
        return {"ok": False, "msg": "Это нельзя продать."}
    if database.count_item(user_id, item_name) < 1:
        return {"ok": False, "msg": "У тебя нет этого предмета."}

    base = SELL_PRICES.get(rarity, 1)
    price = max(1, int(base * npc.get("buy_multiplier", 1.0)))

    database.consume_item(user_id, item_name, 1)
    database.add_gold(user_id, price)
    return {"ok": True, "msg": f"✅ Продано: {item_name} ({rarity}) за {price}💠"}


def get_sellable_items(user_id: int, npc_id: str = "hakari"):
    """[(item_name, rarity, quantity, price), ...] — только то, что можно продать."""
    npc = NPCS.get(npc_id, {})
    multiplier = npc.get("buy_multiplier", 1.0)

    rows = database.get_inventory(user_id)
    result = []
    for r in rows:
        if r["rarity"] in NON_SELLABLE_RARITIES:
            continue
        base_price = SELL_PRICES.get(r["rarity"], 1)
        final_price = max(1, int(base_price * multiplier))
        result.append((r["item_name"], r["rarity"], r["quantity"], final_price))
    return result


def sell_all_junk(user_id: int, npc_id: str = "hakari") -> dict:
    """Продаёт ВСЕ обычные и необычные трофеи оптом.
    Редкие/эпические/легендарные не трогает — их жалко, они идут на крафт."""
    npc = NPCS.get(npc_id)
    if not npc:
        return {"ok": False, "msg": "Такого торговца нет."}

    multiplier = npc.get("buy_multiplier", 1.0)
    junk_rarities = {"обычный", "необычный"}

    rows = database.get_inventory(user_id)
    sold_count = 0
    total_gold = 0

    for r in rows:
        if r["rarity"] not in junk_rarities:
            continue
        qty = r["quantity"]
        base = SELL_PRICES.get(r["rarity"], 1)
        price_per = max(1, int(base * multiplier))
        total = qty * price_per
        database.consume_item(user_id, r["item_name"], qty)
        sold_count += qty
        total_gold += total

    if sold_count == 0:
        return {"ok": False, "msg": "Нечего продавать — нет обычных или необычных трофеев."}

    database.add_gold(user_id, total_gold)
    return {"ok": True, "msg": f"✅ Продано {sold_count} трофеев на {total_gold}💠"}
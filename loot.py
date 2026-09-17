"""
Универсальная система RNG-выбора с весами.
Используется при спавне проклятий (weighted_choice по классам) и при
определении количества дропнутого трофея (roll_quantity по редкости).
"""
import random
from config import RARITY_EMOJI


def weighted_choice(table):
    """
    table: список кортежей (name, rarity, weight)
    Возвращает один случайный элемент с учётом веса (чем больше weight - тем чаще выпадает).
    """
    names = table
    weights = [entry[2] for entry in table]
    chosen = random.choices(names, weights=weights, k=1)[0]
    return {"name": chosen[0], "rarity": chosen[1]}


def roll_quantity(rarity: str) -> int:
    """Редкие трофеи выпадают в меньшем количестве."""
    ranges = {
        "обычный": (2, 4),
        "необычный": (1, 3),
        "редкий": (1, 2),
        "эпический": (1, 1),
        "легендарный": (1, 1),
    }
    lo, hi = ranges.get(rarity, (1, 1))
    return random.randint(lo, hi)


def format_loot_line(item: dict, quantity: int) -> str:
    emoji = RARITY_EMOJI.get(item["rarity"], "⚪")
    return f"{emoji} {item['name']} x{quantity} ({item['rarity']})"

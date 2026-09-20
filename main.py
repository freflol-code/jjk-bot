"""
Магическая Битва: Токио — RPG-бот для Telegram по мотивам Jujutsu Kaisen.
"""
import logging
import time

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice,
)
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    PreCheckoutQueryHandler,
    filters,
    ContextTypes,
)

import assets
import config
import database
import monsters
import combat
import subway
import gacha
import consumables
import bosses
import shop
import quests
import rest
import equipment
import leaderboard
import story
import raid
import ce_types
from config import (
    VIP_PRICE_STARS, VIP_DURATION_DAYS, VIP_PAYLOAD,
    DONATE_RATE, DONATE_PAYLOAD_PREFIX, DONATE_PACKAGES,
)
from ce_types_data import (
    CE_TYPES, CLANS, HEAVENLY_RESTRICTIONS,
    CE_GACHA_ROLL_COST, CE_GACHA_ROLL_COST_X10, CLAN_GACHA_ROLL_COST,
)
from world import get_district_by_x, get_world_map_text, get_neighbor_district
from loot import format_loot_line

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

CAPTION_LIMIT = 1024
GOJO = "Годжо"
HAKARI = "Хакари"
SPAWN_NOTIFY_TTL_SECONDS = 300
EFFECT_GIF_TTL_SECONDS = 3
BUFF_CLEANUP_INTERVAL = 60


BUFF_LABELS = {
    "dmg_bonus": "🧧 +{}% урона",
    "defense_bonus": "🛡 +{}% защиты",
    "ce_regen_bonus": "💠 +{}% реген ПЭ",
    "crit_bonus": "⚫ +{}% Вспышка",
    "exp_bonus": "🧬 +{}% опыта",
    "gold_bonus": "💰 +{}% очков",
    "curse_hunt_1": "🎯 +{}% шанс 1-го кл.",
    "curse_hunt_2": "🧭 +{}% шанс 2-го кл.",
}

RARITY_SHORT = {
    "Обычная": "com",
    "Редкая": "rar",
    "Эпическая": "epi",
    "Мифическая": "myth",
    "Легендарная (Особый класс)": "leg",
}
RARITY_FROM_SHORT = {v: k for k, v in RARITY_SHORT.items()}


def format_active_buffs(user_id: int) -> str:
    buffs = database.get_active_buffs(user_id)
    if not buffs:
        return ""
    parts = []
    for b in buffs:
        label = BUFF_LABELS.get(b["stat"], b["stat"])
        secs = b["seconds_left"]
        m, s = divmod(secs, 60)
        time_str = f"{m}м{s:02d}с" if m else f"{s}с"
        parts.append(f"{label.format(int(b['value'] * 100))} ({time_str})")
    return " | ".join(parts)


def _domain_button(user_id: int) -> tuple[str, str]:
    """Кнопка домена с учётом ПЭ и Проклятия Небес."""
    dk, dt = database.get_domain(user_id)
    if dk and dt > 0:
        return (f"🌌 Домен активен ({dt} х.)", "noop")

    technique_name = combat.get_unlocked_domain_technique(user_id)
    if technique_name:
        cond = combat.check_activation_condition(user_id)
        if cond["ok"]:
            player_now = database.get_or_create_player(user_id, "")
            eff = ce_types.get_effective_stats(user_id, player_now)

            if eff["max_ce"] <= 0:
                return ("🌌 Нет ПЭ (Проклятие Небес)", "domain_info")

            domain_cost = max(1, int(eff["max_ce"] * 0.60))
            if eff["ce"] < domain_cost:
                return (f"🌌 Мало ПЭ ({eff['ce']}/{domain_cost}🔵)", "domain_info")

            uses_before = database.get_domain_uses_in_battle(user_id)
            penalty = combat._get_reactivation_penalty(uses_before)
            if penalty > 0:
                return (f"🌌 Использовать домен (−{int(penalty*100)}% HP)", "domain_activate")
            return ("🌌 Использовать домен", "domain_activate")
        return (f"🌌 Условие: {cond['text']}", "domain_info")

    equipped = gacha.get_equipped(user_id)
    best = 0
    has_master = False
    for name in equipped:
        t = gacha.get_technique(name)
        if not t or not t.get("has_domain"):
            continue
        has_master = True
        uses = database.get_technique_uses(user_id, name)
        if uses > best:
            best = uses
    if has_master:
        return (f"🌌 Домен: {best}/{config.DOMAIN_UNLOCK_USES}", "domain_info")
    return ("🌌 Домен недоступен", "noop")


def _get_current_step_info(user_id: int):
    chapter = story.get_current_chapter(user_id)
    if not chapter:
        return None
    prog = story.get_progress(user_id)
    for i, step in enumerate(chapter["steps"]):
        if prog.get(str(i), 0) >= step["goal"]:
            continue
        return i, step
    return None


def _get_symbols(puzzle: dict) -> list:
    return puzzle.get("symbols") or list(dict.fromkeys(puzzle["sequence"]))


def puzzle_keyboard(puzzle_id: str) -> InlineKeyboardMarkup:
    puzzle = story.get_puzzle(puzzle_id)
    if not puzzle:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Назад", callback_data="story_temp_back")],
        ])
    rows = []
    ptype = puzzle["type"]
    if ptype == "sequence":
        symbols = _get_symbols(puzzle)
        for i, sym in enumerate(symbols):
            rows.append([InlineKeyboardButton(
                sym,
                callback_data=f"story_puzzle:{puzzle_id}:tap:{i}",
            )])
    elif ptype == "reaction":
        rows.append([InlineKeyboardButton(
            "▶️ Начать", callback_data=f"story_puzzle:{puzzle_id}:start",
        )])
        rows.append([InlineKeyboardButton(
            "🛑 Тормоз", callback_data=f"story_puzzle:{puzzle_id}:brake",
        )])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="story_temp_back")])
    return InlineKeyboardMarkup(rows)


# ---------------------- Клавиатуры ----------------------

def main_keyboard(user_id: int):
    in_combat = database.get_encounter(user_id) is not None
    player = database.get_or_create_player(user_id, "")
    npc = shop.npc_at(player["x"])
    district = get_district_by_x(player["x"])

    if in_combat:
        rows = [[InlineKeyboardButton("⚔️ Обычная атака", callback_data="attack")]]
        eff = ce_types.get_effective_stats(user_id)
        if eff["max_ce"] > 0:
            equipped = gacha.get_equipped(user_id)
            for i, name in enumerate(equipped):
                t = gacha.get_technique(name)
                if t:
                    rows.append([InlineKeyboardButton(
                        f"{t['emoji']} {name} ({t['ce_cost']}🔵)",
                        callback_data=f"tech:{i}",
                    )])
        dom_text, dom_cb = _domain_button(user_id)
        rows.append([InlineKeyboardButton(dom_text, callback_data=dom_cb)])
        rows.append([
            InlineKeyboardButton("🛡 Защита", callback_data="defend"),
            InlineKeyboardButton("🏃 Сбежать", callback_data="flee"),
        ])
        rows.append([
            InlineKeyboardButton("🎒 Инвентарь", callback_data="inventory"),
            InlineKeyboardButton("🗺 Карта", callback_data="map"),
        ])
        return InlineKeyboardMarkup(rows)

    left_district = get_neighbor_district(player["x"], "left")
    right_district = get_neighbor_district(player["x"], "right")
    left_label = f"⬅️ {left_district['short']}" if left_district else "⬅️ Край мира"
    right_label = f"➡️ {right_district['short']}" if right_district else "➡️ Край мира"

    rows = [
        [
            InlineKeyboardButton(left_label, callback_data="move_left"),
            InlineKeyboardButton(right_label, callback_data="move_right"),
        ],
        [InlineKeyboardButton("🩸 Патрулирование", callback_data="patrol")],
    ]

    if district["id"] == "jujutsu_high":
        can, remaining = rest.can_rest(user_id)
        if can:
            rest_label = "🧘 Отдохнуть (HP + ПЭ)"
        else:
            m, s = divmod(remaining, 60)
            rest_label = f"⏳ Отдых через {m}:{s:02d}"
        rows.append([InlineKeyboardButton(rest_label, callback_data="rest")])

    if npc:
        rows.append([InlineKeyboardButton(f"🏪 {npc['emoji']} {npc['name']}", callback_data=f"npc:{npc['id']}")])

    quests_label = "📋 Задания"
    if quests.has_ready(user_id):
        quests_label = "🎁 Задания (есть награда!)"

    rows.append([
        InlineKeyboardButton(quests_label, callback_data="quests_menu"),
        InlineKeyboardButton("📖 Сюжет", callback_data="story_menu"),
    ])
    rows.append([
        InlineKeyboardButton("👤 Профиль", callback_data="profile_menu"),
        InlineKeyboardButton("🗺 Карта", callback_data="map"),
    ])
    rows.append([
        InlineKeyboardButton("🚇 Метро", callback_data="subway_open"),
    ])

    active_raid = raid.get_active_raid_for_user(user_id)
    if active_raid:
        rows.append([InlineKeyboardButton("👺 Вернуться в рейд", callback_data="raid_show")])
    elif raid.can_use_fingers(user_id):
        rows.append([InlineKeyboardButton("👺 Рейд на Сукуну", callback_data="raid_menu")])

    return InlineKeyboardMarkup(rows)


def kb_for(user_id: int) -> InlineKeyboardMarkup:
    return main_keyboard(user_id)


def quests_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📋 Ежедневные", callback_data="quests_daily"),
            InlineKeyboardButton("📅 Недельные", callback_data="quests_weekly"),
        ],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_game")],
    ])


def quests_period_keyboard(period: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎁 Забрать всё", callback_data=f"quests_claim_all:{period}")],
        [InlineKeyboardButton("⬅️ К заданиям", callback_data="quests_menu")],
    ])


def gacha_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"🎰 1 крутка ({config.GACHA_ROLL_COST}💠)", callback_data="gacha_roll1"),
            InlineKeyboardButton(f"🎰 10 круток ({config.GACHA_ROLL_COST_X10}💠)", callback_data="gacha_roll10"),
        ],
        [InlineKeyboardButton("📖 Мои техники", callback_data="gacha_list")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="gacha_back")],
    ])


def gacha_list_keyboard(user_id: int) -> InlineKeyboardMarkup:
    learned = database.get_player_techniques(user_id)
    counts = {}
    for row in learned:
        t = gacha.get_technique(row["technique_name"])
        if not t:
            continue
        counts[t["rarity"]] = counts.get(t["rarity"], 0) + 1

    rows = []
    for rarity, short in RARITY_SHORT.items():
        cnt = counts.get(rarity, 0)
        if cnt == 0:
            continue
        em = config.GACHA_RARITY_EMOJI.get(rarity, "")
        rows.append([InlineKeyboardButton(
            f"{em} {rarity} ({cnt})",
            callback_data=f"gacha_rarity:{short}",
        )])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="gacha_back_to_menu")])
    return InlineKeyboardMarkup(rows)


def gacha_rarity_keyboard(user_id: int, short: str) -> InlineKeyboardMarkup:
    rarity = RARITY_FROM_SHORT.get(short)
    if not rarity:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Назад", callback_data="gacha_list")],
        ])
    learned = database.get_player_techniques(user_id)
    techs = []
    for row in learned:
        name = row["technique_name"]
        t = gacha.get_technique(name)
        if t and t["rarity"] == rarity:
            techs.append(name)
    techs.sort()

    equipped = set(gacha.get_equipped(user_id))
    rows = []
    for i, name in enumerate(techs):
        t = gacha.get_technique(name)
        if name in equipped:
            rows.append([InlineKeyboardButton(
                f"✅ {t['emoji']} {name} (снять)",
                callback_data=f"gq:u:{short}:{i}",
            )])
        else:
            rows.append([InlineKeyboardButton(
                f"{t['emoji']} {name} (взять)",
                callback_data=f"gq:e:{short}:{i}",
            )])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="gacha_list")])
    return InlineKeyboardMarkup(rows)


def gacha_hub_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌀 Техники", callback_data="gacha_menu_from_shop")],
        [InlineKeyboardButton("🩸 Кланы и Проклятия Небес", callback_data="gacha_clan_menu")],
        [InlineKeyboardButton("⚡ Типы Проклятой Энергии", callback_data="gacha_ce_menu")],
        [InlineKeyboardButton("⬅️ Выйти", callback_data="back_to_game")],
    ])


def gacha_clan_menu_keyboard(user_id: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            f"🎰 Крутка клана ({CLAN_GACHA_ROLL_COST}💠)",
            callback_data="gacha_clan_roll1",
        )],
        [InlineKeyboardButton("📖 Мои кланы", callback_data="gacha_my_clans")],
        [InlineKeyboardButton("🌠 Мои Проклятия Небес", callback_data="gacha_my_heavenly")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="gacha_hub")],
    ]
    return InlineKeyboardMarkup(rows)


def gacha_ce_menu_keyboard(user_id: int) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                f"🎰 1 крутка ({CE_GACHA_ROLL_COST}💠)",
                callback_data="gacha_ce_roll1",
            ),
            InlineKeyboardButton(
                f"🎰 10 круток ({CE_GACHA_ROLL_COST_X10}💠)",
                callback_data="gacha_ce_roll10",
            ),
        ],
        [InlineKeyboardButton("📖 Мои типы ПЭ", callback_data="gacha_my_ce")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="gacha_hub")],
    ]
    return InlineKeyboardMarkup(rows)


def my_clans_keyboard(user_id: int) -> InlineKeyboardMarkup:
    owned = database.get_clans(user_id)
    active = database.get_active_clan(user_id)
    rows = []
    for row in owned:
        key = row["clan_key"]
        c = CLANS.get(key)
        if not c:
            continue
        if key == active:
            rows.append([InlineKeyboardButton(
                f"✅ {c['emoji']} {c['name']} (снять)",
                callback_data="clan_clear",
            )])
        else:
            rows.append([InlineKeyboardButton(
                f"{c['emoji']} {c['name']} — надеть",
                callback_data=f"clan_set:{key}",
            )])
    if not owned:
        rows.append([InlineKeyboardButton("— пусто —", callback_data="noop")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="gacha_clan_menu")])
    return InlineKeyboardMarkup(rows)


def my_ce_keyboard(user_id: int) -> InlineKeyboardMarkup:
    owned = database.get_ce_types(user_id)
    active = database.get_active_ce_type(user_id)
    rows = []
    for row in owned:
        key = row["ce_key"]
        t = CE_TYPES.get(key)
        if not t:
            continue
        if key == active:
            rows.append([InlineKeyboardButton(
                f"✅ {t['emoji']} {t['name']} (снять)",
                callback_data="ce_clear",
            )])
        else:
            rows.append([InlineKeyboardButton(
                f"{t['emoji']} {t['name']} ({t['rarity']}) — надеть",
                callback_data=f"ce_set:{key}",
            )])
    if not owned:
        rows.append([InlineKeyboardButton("— пусто —", callback_data="noop")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="gacha_ce_menu")])
    return InlineKeyboardMarkup(rows)


def my_heavenly_keyboard(user_id: int) -> InlineKeyboardMarkup:
    owned = database.get_heavenly_restrictions(user_id)
    active = database.get_active_heavenly(user_id)
    rows = []
    for row in owned:
        key = row["heavenly_key"]
        h = HEAVENLY_RESTRICTIONS.get(key)
        if not h:
            continue
        if key == active:
            rows.append([InlineKeyboardButton(
                f"✅ {h['emoji']} {h['name']} (снять)",
                callback_data="heavenly_clear",
            )])
        else:
            rows.append([InlineKeyboardButton(
                f"{h['emoji']} {h['name']} — надеть",
                callback_data=f"heavenly_set:{key}",
            )])
    if not owned:
        rows.append([InlineKeyboardButton("— пусто —", callback_data="noop")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="gacha_clan_menu")])
    return InlineKeyboardMarkup(rows)


def inventory_keyboard(user_id: int):
    items = database.get_inventory(user_id)
    rows = []
    for i, item in enumerate(items):
        is_seal = item["rarity"] == "призыв" or item["item_name"] in bosses.SUMMON_RECIPES
        if item["rarity"] == "расходник":
            rows.append([InlineKeyboardButton(
                f"🧪 Использовать: {item['item_name']} x{item['quantity']}",
                callback_data=f"use_item:{i}",
            )])
        elif is_seal:
            rows.append([InlineKeyboardButton(
                f"⚡ Призвать: {item['item_name']} x{item['quantity']}",
                callback_data=f"summon_item:{i}",
            )])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_to_game")])
    return InlineKeyboardMarkup(rows)


def shop_menu_keyboard(npc_id: str):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🧪 Расходники", callback_data=f"shop_buy:{npc_id}"),
            InlineKeyboardButton("💰 Продать", callback_data=f"shop_sell:{npc_id}"),
        ],
        [InlineKeyboardButton("🏴‍☠️ Склад проклятого оружия", callback_data=f"gear_menu:{npc_id}")],
        [InlineKeyboardButton("🎰 Гача", callback_data="gacha_hub")],
        [InlineKeyboardButton("⬅️ Выйти", callback_data="back_to_game")],
    ])


def shop_buy_keyboard(npc_id: str):
    npc = shop.get_npc(npc_id)
    rows = []
    for item_name in npc["sells"]:
        item = consumables.CONSUMABLES.get(item_name)
        if not item:
            continue
        idx = npc["sells"].index(item_name)
        rows.append([InlineKeyboardButton(
            f"Купить {item_name} — {item['price']}💠",
            callback_data=f"shop_do_buy:{npc_id}:{idx}",
        )])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data=f"npc:{npc_id}")])
    return InlineKeyboardMarkup(rows)


def shop_sell_keyboard(npc_id: str, user_id: int):
    items = shop.get_sellable_items(user_id, npc_id)
    rows = []
    for idx, (name, rarity, qty, price) in enumerate(items):
        rows.append([InlineKeyboardButton(
            f"Продать {name} ({rarity}) x{qty} — {price}💠",
            callback_data=f"shop_do_sell:{npc_id}:{idx}",
        )])

    if items:
        rows.append([InlineKeyboardButton(
            "💰 Продать весь хлам (⚪🟢)",
            callback_data=f"shop_sell_junk:{npc_id}",
        )])

    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data=f"npc:{npc_id}")])
    return InlineKeyboardMarkup(rows)


def gear_menu_keyboard(npc_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 Купить оружие", callback_data="gear_shop_list")],
        [InlineKeyboardButton("🔨 Скрафтить оружие", callback_data="gear_craft_list")],
        [InlineKeyboardButton("⚔️ Моё оружие", callback_data="gear_owned")],
        [InlineKeyboardButton("⬅️ Назад", callback_data=f"npc:{npc_id}")],
    ])


def gear_buy_list_keyboard(user_id: int) -> InlineKeyboardMarkup:
    rows = []
    for idx, (name, w) in enumerate(equipment.list_purchasable()):
        owned = database.has_weapon(user_id, name)
        marker = "✅ " if owned else ""
        rows.append([InlineKeyboardButton(
            f"{marker}{w['emoji']} {name} ({w['rarity']}) — {w['price']}💠",
            callback_data=f"gear_buy:{idx}",
        )])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="gear_menu:hakari")])
    return InlineKeyboardMarkup(rows)


def gear_craft_list_keyboard() -> InlineKeyboardMarkup:
    rows = []
    for idx, (name, w) in enumerate(equipment.list_craftable()):
        rows.append([InlineKeyboardButton(
            f"{w['emoji']} {name} ({w['rarity']})",
            callback_data=f"gear_craft:{idx}",
        )])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="gear_menu:hakari")])
    return InlineKeyboardMarkup(rows)


def gear_owned_keyboard(user_id: int) -> InlineKeyboardMarkup:
    owned = database.get_player_weapons(user_id)
    equipped_name = database.get_equipped_weapon_name(user_id)
    rows = []
    for idx, name in enumerate(owned):
        w = equipment.get_weapon(name)
        if not w:
            continue
        if name == equipped_name:
            rows.append([InlineKeyboardButton(
                f"✅ {w['emoji']} {name} (снять)",
                callback_data="gear_unequip",
            )])
        else:
            rows.append([InlineKeyboardButton(
                f"{w['emoji']} {name} — экипировать",
                callback_data=f"gear_equip:{idx}",
            )])
    if not owned:
        rows.append([InlineKeyboardButton("— пусто —", callback_data="noop")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="gear_menu:hakari")])
    return InlineKeyboardMarkup(rows)


def story_menu_keyboard(user_id: int) -> InlineKeyboardMarkup:
    rows = []
    chapter = story.get_current_chapter(user_id)
    player = database.get_or_create_player(user_id, "")

    if chapter:
        min_level = chapter.get("min_level", 1)
        if player["level"] < min_level:
            rows.append([InlineKeyboardButton(
                f"🔒 Нужен уровень {min_level}",
                callback_data="noop",
            )])
        else:
            temp = story.get_temp_district(user_id)
            if temp:
                rows.append([InlineKeyboardButton(
                    f"📖 Отправиться: {temp['emoji']} {temp['name']}",
                    callback_data="story_enter_temp",
                )])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_to_game")])
    return InlineKeyboardMarkup(rows)


def story_temp_keyboard(user_id: int) -> InlineKeyboardMarkup:
    rows = []
    info = _get_current_step_info(user_id)
    if info:
        _, step = info
        if step["type"] == "puzzle":
            rows.append([InlineKeyboardButton(
                "🧩 Решить головоломку", callback_data="story_temp_puzzle",
            )])
        elif step["type"] == "kill_boss":
            rows.append([InlineKeyboardButton(
                "👁 Войти к боссу", callback_data="story_temp_boss",
            )])

    # Кнопка «Поговорить» — если в локации есть NPC под задачу talk
    npc = story.get_current_npc(user_id)
    if npc:
        rows.append([InlineKeyboardButton(
            f"💬 Поговорить с {npc['name']}",
            callback_data="story_temp_talk",
        )])

    rows.append([InlineKeyboardButton("🩸 Патрулирование", callback_data="story_temp_patrol")])
    rows.append([InlineKeyboardButton("⬅️ Вернуться в школу", callback_data="story_exit_temp")])
    return InlineKeyboardMarkup(rows)


def profile_menu_keyboard(user_id: int) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("🎒 Инвентарь", callback_data="profile_inventory"),
            InlineKeyboardButton("🌀 Техники", callback_data="profile_techniques"),
        ],
        [InlineKeyboardButton("🏆 Таблица лидеров", callback_data="profile_leaderboard")],
    ]
    if database.has_vip(user_id):
        until = database.get_vip_until(user_id)
        days_left = (until - int(time.time())) // 86400
        vip_label = f"💎 VIP ({days_left} дн.)"
    else:
        vip_label = "💎 VIP"
    rows.append([
        InlineKeyboardButton(vip_label, callback_data="vip_info"),
        InlineKeyboardButton("💰 Донат", callback_data="donate_menu"),
    ])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_to_game")])
    return InlineKeyboardMarkup(rows)


def subway_keyboard(user_id: int) -> InlineKeyboardMarkup:
    player = database.get_or_create_player(user_id, "")
    stations = subway.list_reachable(player["x"], player["gold"])

    rows = []
    for s in stations:
        if s["is_current"]:
            label = f"📍 {s['emoji']} {s['name']} — ты здесь"
            cb = "noop"
        elif s["affordable"]:
            label = f"{s['emoji']} {s['name']} — {s['fare']}💠"
            cb = f"subway_travel:{s['district_id']}"
        else:
            label = f"🔒 {s['emoji']} {s['name']} — {s['fare']}💠"
            cb = "subway_no_money"
        rows.append([InlineKeyboardButton(label, callback_data=cb)])

    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_to_game")])
    return InlineKeyboardMarkup(rows)


def raid_menu_keyboard(user_id: int) -> InlineKeyboardMarkup:
    available = raid.get_available_fingers(user_id)
    rows = []
    for n in range(1, min(3, available) + 1):
        rows.append([InlineKeyboardButton(
            f"👺 Создать рейд на {n} 🩸",
            callback_data=f"raid_create:{n}",
        )])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_to_game")])
    return InlineKeyboardMarkup(rows)


def raid_lobby_keyboard(raid_id: int, user_id: int, bot_username: str | None) -> InlineKeyboardMarkup:
    r = raid.get_raid(raid_id)
    rows = []
    if r and r["creator_id"] == user_id:
        rows.append([InlineKeyboardButton("▶️ Начать бой", callback_data=f"raid_start:{raid_id}")])

    if bot_username:
        share_url = (
            f"https://t.me/share/url?"
            f"url=https://t.me/{bot_username}?start=raid_{raid_id}"
            f"&text=Присоединяйся к рейду на Сукуну!"
        )
        rows.append([InlineKeyboardButton("📤 Пригласить друзей", url=share_url)])

    rows.append([InlineKeyboardButton("🔄 Обновить", callback_data=f"raid_show:{raid_id}")])
    rows.append([InlineKeyboardButton("🚪 Выйти", callback_data=f"raid_leave:{raid_id}")])
    return InlineKeyboardMarkup(rows)


def raid_battle_keyboard(raid_id: int, user_id: int) -> InlineKeyboardMarkup:
    rows = []
    if raid.is_player_turn(raid_id, user_id):
        rows.append([InlineKeyboardButton(
            "⚔️ Обычная атака",
            callback_data=f"raid_attack:{raid_id}",
        )])
        eff = ce_types.get_effective_stats(user_id)
        if eff["max_ce"] > 0:
            equipped = gacha.get_equipped(user_id)
            for i, name in enumerate(equipped):
                t = gacha.get_technique(name)
                if t:
                    rows.append([InlineKeyboardButton(
                        f"{t['emoji']} {name} ({t['ce_cost']}🔵)",
                        callback_data=f"raid_attack:{raid_id}:t:{i}",
                    )])
    rows.append([InlineKeyboardButton("🔄 Обновить", callback_data=f"raid_show:{raid_id}")])
    return InlineKeyboardMarkup(rows)


def raid_finished_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ В меню", callback_data="back_to_game")],
    ])


# ---------------------- Рендер ----------------------

def truncate_caption(text: str, limit: int = CAPTION_LIMIT) -> str:
    if len(text) <= limit:
        return text
    suffix = "..."
    cut = max(0, limit - len(suffix))
    truncated = text[:cut]
    last_lt = truncated.rfind("<")
    last_gt = truncated.rfind(">")
    if last_lt > last_gt:
        truncated = truncated[:last_lt]
    return truncated + suffix


async def render(query, context: ContextTypes.DEFAULT_TYPE, text: str,
                  reply_markup: InlineKeyboardMarkup, image_path: str | None = None,
                  force_new: bool = False):
    chat_id = query.message.chat_id
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except BadRequest as e:
        logger.info(f"Не удалось убрать кнопки: {e}")

    if image_path:
        caption = truncate_caption(text)
        try:
            with open(image_path, "rb") as media_file:
                if assets.is_animation(image_path):
                    await context.bot.send_animation(
                        chat_id=chat_id, animation=media_file, caption=caption,
                        parse_mode="HTML", reply_markup=reply_markup,
                    )
                else:
                    await context.bot.send_photo(
                        chat_id=chat_id, photo=media_file, caption=caption,
                        parse_mode="HTML", reply_markup=reply_markup,
                    )
            return
        except (OSError, BadRequest) as e:
            logger.warning(f"Не удалось отправить медиа {image_path}: {e}")
    await context.bot.send_message(
        chat_id=chat_id, text=text, parse_mode="HTML", reply_markup=reply_markup,
    )


def district_image_for_x(x: int) -> str | None:
    return assets.get_biome_image(get_district_by_x(x)["id"])


async def send_effect_gif(context: ContextTypes.DEFAULT_TYPE, chat_id: int,
                          effect_key: str | None, ttl: int = EFFECT_GIF_TTL_SECONDS):
    if not effect_key:
        return
    path = None
    if effect_key.startswith("technique:"):
        tname = effect_key.split(":", 1)[1]
        path = assets.get_technique_image(tname)
        if not path:
            t = gacha.get_technique(tname)
            if t:
                rarity_map = {
                    "Обычная": "_обычная",
                    "Редкая": "_редкая",
                    "Эпическая": "_эпическая",
                    "Мифическая": "_мифическая",
                    "Легендарная (Особый класс)": "_легендарная",
                }
                key = rarity_map.get(t["rarity"])
                if key:
                    path = assets.get_technique_image(key)
    else:
        path = assets.get_effect_image(effect_key)

    if not path:
        return
    try:
        with open(path, "rb") as media_file:
            if assets.is_animation(path):
                msg = await context.bot.send_animation(chat_id=chat_id, animation=media_file)
            else:
                msg = await context.bot.send_photo(chat_id=chat_id, photo=media_file)
        context.job_queue.run_once(
            delete_message_job, when=ttl,
            data={"chat_id": chat_id, "message_id": msg.message_id},
            name=f"del_effect_{chat_id}_{msg.message_id}",
        )
    except Exception as e:
        logger.warning(f"Не удалось показать эффект {effect_key}: {e}")


# ---------------------- Тексты ----------------------

def location_text(user_id: int, x: int) -> str:
    district = get_district_by_x(x)
    player = database.get_or_create_player(user_id, "")
    npc = shop.npc_at(x)

    npc_line = ""
    if npc:
        npc_line = f"\n\n{npc['emoji']} Здесь стоит <b>{npc['name']}</b>."
    gojo_line = ""
    if district["id"] == "jujutsu_high":
        gojo_line = f"\n\n💬 {GOJO}: «С возвращением в школу. Отдохни и снова иди работать.»"

    weapon_line = ""
    w = equipment.get_equipped(user_id)
    if w:
        weapon_line = f"\n⚔️ {w['emoji']} <b>{w['name']}</b>"

    buffs_line = ""
    buffs = format_active_buffs(user_id)
    if buffs:
        buffs_line = f"\n✨ {buffs}"

    safe_line = ""
    if district.get("safe"):
        safe_line = "\n🛡 <i>Безопасная зона — проклятия сюда не заходят.</i>"

    story_hint = ""
    if district["id"] == "jujutsu_high":
        msg = story.get_school_message(user_id)
        if msg:
            story_hint = f"\n\n{msg}"

    eff = ce_types.get_effective_stats(user_id, player)

    return (
        f"{district['emoji']} <b>{district['name']}</b>\n"
        f"<i>{district['description']}</i>\n\n"
        f"📍 {x}\n"
        f"❤️ {eff['hp']}/{eff['max_hp']}  ·  🔵 {eff['ce']}/{eff['max_ce']}  ·  💠 {player['gold']}\n"
        f"🧬 {player['level']}  ·  🎚 {player['ce_control']}"
        f"{weapon_line}"
        f"{buffs_line}\n"
        f"{world_bounds_line(player['level'])}"
        f"{safe_line}"
        f"{npc_line}"
        f"{gojo_line}"
        f"{story_hint}"
    )


def world_bounds_line(level: int) -> str:
    lvl_min, lvl_max = config.get_world_bounds(level)
    if lvl_min <= -config.MAX_WORLD and lvl_max >= config.MAX_WORLD:
        return f"🌍 Открыта вся карта: X от {lvl_min} до {lvl_max}."
    next_level = level + 1
    next_min, next_max = config.get_world_bounds(next_level)
    return f"🌍 Доступно: X от {lvl_min} до {lvl_max} (на ур.{next_level} откроется {next_min}..{next_max})"


def gacha_menu_text(user_id: int) -> str:
    player = database.get_or_create_player(user_id, "")
    equipped = gacha.get_equipped(user_id)
    learned = database.get_player_techniques(user_id)
    pity = database.get_pity(user_id)
    pity_left = max(0, config.GACHA_PITY_LIMIT - pity)

    eq_lines = []
    for name in equipped:
        t = gacha.get_technique(name)
        if t:
            line = f"  {t['emoji']} <b>{name}</b> — {t['ce_cost']}🔵, {t['dmg_min']}-{t['dmg_max']} урона"
            if t.get("has_domain"):
                uses = database.get_technique_uses(user_id, name)
                if uses >= config.DOMAIN_UNLOCK_USES:
                    line += "\n     🌌 Домен: <b>разблокирован</b>"
                else:
                    line += f"\n     🌀 Домен: {uses}/{config.DOMAIN_UNLOCK_USES}"
            eq_lines.append(line)
    eq_text = "\n".join(eq_lines) if eq_lines else "  <i>пусто</i>"

    rates = "\n".join(
        f"{config.GACHA_RARITY_EMOJI.get(r,'')} {r}: {w}%"
        for r, w in config.GACHA_RARITY_WEIGHTS.items()
    )
    return (
        "🌀 <b>Хакари: гача врождённых техник</b>\n\n"
        f"💠 У тебя: {player['gold']} очков Ассоциации\n"
        f"📖 Изучено техник: {len(learned)}\n\n"
        f"<b>Боевой набор ({len(equipped)}/{config.MAX_EQUIPPED_TECHNIQUES}):</b>\n{eq_text}\n\n"
        f"<b>Шансы выпадения:</b>\n{rates}\n\n"
        f"🎯 <b>Гарант через:</b> {pity_left} круток\n\n"
        "<i>Хакари: «Ставки честные. Ну, почти.»</i>"
    )


def gacha_clan_menu_text(user_id: int) -> str:
    player = database.get_or_create_player(user_id, "")
    return (
        "🩸 <b>Гача кланов и Проклятий Небес</b>\n\n"
        f"💠 У тебя: {player['gold']} очков Ассоциации\n\n"
        "<b>Шансы:</b>\n"
        "  🌠 Проклятие Небес — <b>15%</b>\n"
        "  🩸 Обычный клан — <b>10%</b>\n"
        "  💨 Пусто — 75%\n\n"
        "<i>Хакари: «Рискни — тут либо клан, либо проклятие, либо ничего.»</i>"
    )


def gacha_ce_menu_text(user_id: int) -> str:
    player = database.get_or_create_player(user_id, "")
    owned = database.get_ce_types(user_id)
    return (
        "⚡ <b>Гача типов Проклятой Энергии</b>\n\n"
        f"💠 У тебя: {player['gold']} очков Ассоциации\n"
        f"📖 Изучено типов: {len(owned)}\n\n"
        "<b>Шансы по редкости:</b>\n"
        "  ⚪ Обычная — 68%\n"
        "  🟣 Эпическая — 26%\n"
        "  🟠 Легендарная — 6%\n\n"
        "<i>Хакари: «Каждому своя энергия. Некоторым — вообще никакой.»</i>"
    )


def profile_text(user_id: int) -> str:
    player = database.get_or_create_player(user_id, "")
    need = player["level"] * config.EXP_BASE
    max_level = story.get_max_level(user_id)

    rank_info = leaderboard.get_player_rank(user_id)
    rank_line = ""
    if rank_info["rank"] is not None:
        rank_line = f"\n🏆 Место в топе: <b>#{rank_info['rank']}</b> из {rank_info['total']}"

    weapon = equipment.get_equipped(user_id)
    if weapon:
        weapon_line = f"⚔️ Оружие: {weapon['emoji']} <b>{weapon['name']}</b>"
    else:
        weapon_line = "⚔️ Оружие: <i>не экипировано</i>"

    buffs = format_active_buffs(user_id)
    buffs_line = f"\n✨ Баффы: {buffs}" if buffs else ""

    cap_line = ""
    if player["level"] >= max_level:
        cap_line = f"\n⚠️ Достигнут потолок уровня по сюжету: <b>{max_level}</b>"

    learned = database.get_player_techniques(user_id)
    equipped_tech = gacha.get_equipped(user_id)
    weapons_owned = database.get_player_weapons(user_id)

    ce_line = _ce_summary(user_id)
    eff = ce_types.get_effective_stats(user_id, player)

    return (
        "👤 <b>Профиль шамана</b>\n\n"
        f"🧬 Уровень: <b>{player['level']}</b> ({player['exp']}/{need}) · потолок: {max_level}\n"
        f"🎚 Контроль ПЭ: <b>{player['ce_control']}</b>\n"
        f"❤️ HP: {eff['hp']}/{eff['max_hp']}\n"
        f"🔵 ПЭ: {eff['ce']}/{eff['max_ce']}\n"
        f"💠 Очки Ассоциации: {player['gold']}\n\n"
        f"{weapon_line}\n"
        f"🌀 Техник изучено: {len(learned)} · в бою: {len(equipped_tech)}/{config.MAX_EQUIPPED_TECHNIQUES}\n"
        f"⚔️ Оружия в коллекции: {len(weapons_owned)}"
        f"{ce_line}"
        f"{rank_line}"
        f"{buffs_line}"
        f"{cap_line}"
        + _vip_line(user_id)
    )


def _ce_summary(user_id: int) -> str:
    ce_key = database.get_active_ce_type(user_id)
    clan_key = database.get_active_clan(user_id)
    heavenly_key = database.get_active_heavenly(user_id)

    lines = []
    if ce_key and ce_key in CE_TYPES:
        t = CE_TYPES[ce_key]
        lines.append(f"{t['emoji']} ПЭ: {t['name']}")
    if clan_key and clan_key in CLANS:
        c = CLANS[clan_key]
        lines.append(f"{c['emoji']} Клан: {c['name']}")
    if heavenly_key and heavenly_key in HEAVENLY_RESTRICTIONS:
        h = HEAVENLY_RESTRICTIONS[heavenly_key]
        lines.append(f"{h['emoji']} {h['name']}")
    if not lines:
        return ""
    return "\n" + " · ".join(lines)


def _vip_line(user_id: int) -> str:
    until = database.get_vip_until(user_id)
    if until:
        days_left = (until - int(time.time())) // 86400
        return f"\n\n💎 <b>VIP активен</b> — осталось {days_left} дн. (награды ×2)"
    return ""


def _quests_done_text(done: list[dict]) -> str:
    if not done:
        return ""
    lines = ["\n\n📋 <b>Задание Годжо выполнено:</b>"]
    for q in done:
        lines.append(f"  {q['emoji']} {q['name']} — забери награду во вкладке «Задания»")
    return "\n".join(lines)


# ---------------------- Хелперы рейда ----------------------

async def _bot_username(context: ContextTypes.DEFAULT_TYPE) -> str | None:
    try:
        name = context.bot.username
        if name:
            return name
        me = await context.bot.get_me()
        return me.username
    except Exception:
        return None


async def _render_raid_screen(query, context: ContextTypes.DEFAULT_TYPE,
                              raid_id: int, user_id: int):
    r = raid.get_raid(raid_id)
    if not r:
        await render(query, context, "❌ Рейд не найден.", kb_for(user_id))
        return

    if r["status"] == "lobby":
        text = raid.format_lobby(raid_id)
        bot_name = await _bot_username(context)
        if bot_name:
            text += (
                f"\n\n🔗 Ссылка для друзей:\n"
                f"<code>https://t.me/{bot_name}?start=raid_{raid_id}</code>"
            )
        kb = raid_lobby_keyboard(raid_id, user_id, bot_name)
    elif r["status"] == "battle":
        text = raid.format_battle(raid_id, user_id)
        kb = raid_battle_keyboard(raid_id, user_id)
    else:
        text = raid.format_finished(raid_id)
        kb = raid_finished_keyboard()
    await render(query, context, text, kb)


async def _notify_raid_players(context: ContextTypes.DEFAULT_TYPE,
                               raid_id: int, user_ids: list[int],
                               exclude: int | None = None):
    r = raid.get_raid(raid_id)
    if not r:
        return
    for uid in user_ids:
        if uid == exclude:
            continue
        try:
            if r["status"] == "finished":
                text = raid.format_finished(raid_id)
                kb = raid_finished_keyboard()
            else:
                text = raid.format_battle(raid_id, uid)
                kb = raid_battle_keyboard(raid_id, uid)
            await context.bot.send_message(
                chat_id=uid, text=text, parse_mode="HTML", reply_markup=kb,
            )
        except Exception as e:
            logger.warning(f"Не удалось уведомить рейд-игрока {uid}: {e}")


# ---------------------- Команды ----------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    database.get_or_create_player(user.id, user.username or user.first_name)

    args = context.args or []
    if args and args[0].startswith("raid_"):
        try:
            rid = int(args[0].split("_", 1)[1])
        except (ValueError, IndexError):
            rid = None
        if rid:
            res = raid.join_raid(rid, user.id)
            if not res.get("ok"):
                msg = res.get("msg", "Не удалось присоединиться к рейду.")
                await update.message.reply_html(
                    f"❌ {msg}", reply_markup=kb_for(user.id),
                )
                return

            r = raid.get_raid(rid)
            if not r or r["status"] not in ("lobby", "battle"):
                await update.message.reply_html(
                    "❌ Рейд уже завершён или недоступен.",
                    reply_markup=kb_for(user.id),
                )
                return

            if r["status"] == "lobby":
                text = "✅ Ты в рейде!\n\n" + raid.format_lobby(rid)
            else:
                text = "✅ Ты в бою!\n\n" + raid.format_battle(rid, user.id)

            bot_name = await _bot_username(context)
            kb = (raid_lobby_keyboard(rid, user.id, bot_name)
                  if r["status"] == "lobby"
                  else raid_battle_keyboard(rid, user.id))
            await update.message.reply_html(text, reply_markup=kb)
            return

    text = (
        f"👋 Привет, {user.first_name}!\n\n"
        f"💬 {GOJO}: «О, новое лицо. Добро пожаловать в Токийскую школу магии. "
        f"Я Годжо Сатору — буду присматривать за тобой. Патрулируй районы Токио, "
        f"изгоняй проклятия, качай Контроль ПЭ и выбивай техники у Хакари. "
        f"Постарайся не умереть в первую же неделю.»\n\n"
    ) + location_text(user.id, 0)

    image_path = district_image_for_x(0)
    if image_path:
        try:
            with open(image_path, "rb") as media_file:
                if assets.is_animation(image_path):
                    await update.message.reply_animation(
                        animation=media_file, caption=truncate_caption(text),
                        parse_mode="HTML", reply_markup=kb_for(user.id),
                    )
                else:
                    await update.message.reply_photo(
                        photo=media_file, caption=truncate_caption(text),
                        parse_mode="HTML", reply_markup=kb_for(user.id),
                    )
            return
        except (OSError, BadRequest) as e:
            logger.warning(f"Не удалось отправить медиа {image_path}: {e}")
    await update.message.reply_html(text, reply_markup=kb_for(user.id))


async def map_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    player = database.get_or_create_player(user.id, user.username or user.first_name)
    text = "🗺 <b>Карта районов Токио</b>\n\n" + get_world_map_text(player["x"])
    await update.message.reply_html(text)


async def inventory_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_inventory(update.effective_user.id, update.message.reply_html)


async def send_inventory(user_id: int, sender):
    items = database.get_inventory(user_id)
    if not items:
        await sender("🎒 Твой инвентарь пуст. Иди патрулировать!", reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("⬅️ Назад", callback_data="back_to_game")]]
        ))
        return
    pretty = []
    for i in items:
        if i["rarity"] == "расходник":
            pretty.append(f"🧪 {i['item_name']} x{i['quantity']} (расходник)")
        elif i["rarity"] == "призыв" or i["item_name"] in bosses.SUMMON_RECIPES:
            pretty.append(f"⚡ {i['item_name']} x{i['quantity']} (ритуальная печать)")
        else:
            pretty.append(format_loot_line({"name": i["item_name"], "rarity": i["rarity"]}, i["quantity"]))
    await sender("🎒 <b>Инвентарь</b>\n\n" + "\n".join(pretty),
                 reply_markup=inventory_keyboard(user_id))


async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not update.message or not update.message.text:
        return
    text = update.message.text.strip()
    if text.startswith("/"):
        return

    res = story.solve_current_puzzle_text(user.id, text)
    if not res.get("active"):
        return
    if res.get("wrong_type"):
        return

    if res["correct"]:
        body = "✅ <b>Верно!</b>\n\n" + story.format_story_screen(user.id)
        await update.message.reply_html(body, reply_markup=story_temp_keyboard(user.id))
    else:
        body = "❌ Неверно. Попробуй ещё раз."
        found = story.get_current_puzzle_step(user.id)
        if found:
            _, pid, _ = found
            await update.message.reply_html(body, reply_markup=puzzle_keyboard(pid))
        else:
            await update.message.reply_html(body, reply_markup=kb_for(user.id))


# ---------------------- VIP ----------------------

def _vip_description_text(user_id: int) -> str:
    until = database.get_vip_until(user_id)
    is_active = until > 0

    lines = ["💎 <b>VIP-статус</b>", ""]

    if is_active:
        days_left = (until - int(time.time())) // 86400
        lines.append(f"✅ <b>Статус активен.</b> Осталось дней: <b>{days_left}</b>")
        lines.append("")

    lines.append("<b>Что даёт VIP:</b>")
    lines.append("  • 💰 ×2 очков Ассоциации с боёв")
    lines.append("  • 🧬 ×2 опыта с боёв")
    lines.append("  • 🎁 ×2 к дропу с обычных проклятий и боссов")
    lines.append("  • 📋 ×2 к наградам за задания (ежедневные и недельные)")
    lines.append("  • 📖 ×2 к наградам за сюжетные главы")
    lines.append("  • ⚡ Работает во всех районах, рейдах и главах")
    lines.append("  • 🎁 Бонус складывается с баффами")
    lines.append("")
    lines.append(f"<b>Стоимость:</b> {VIP_PRICE_STARS} ⭐ за {VIP_DURATION_DAYS} дней")
    lines.append("")
    lines.append("<i>Оплата через Telegram Stars. Продление возможно в любой момент — "
                 "сроки суммируются.</i>")

    if is_active:
        lines.append("")
        lines.append("<i>Ты можешь продлить VIP — дни добавятся к текущему сроку.</i>")

    return "\n".join(lines)


async def vip_buy_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    try:
        await context.bot.send_invoice(
            chat_id=user_id,
            title=f"VIP на {VIP_DURATION_DAYS} дней",
            description=(
                f"×2 золото, опыт, дроп, награды за задания и сюжетные главы "
                f"на {VIP_DURATION_DAYS} дней. Работает во всех районах и рейдах. "
                f"Продление возможно в любой момент."
            ),
            payload=VIP_PAYLOAD,
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(f"VIP {VIP_DURATION_DAYS} дней", VIP_PRICE_STARS)],
        )
    except Exception as e:
        logger.warning(f"Не удалось отправить инвойс: {e}")
        await query.message.reply_text(f"❌ Ошибка оплаты: {e}")


async def precheckout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    payload = query.invoice_payload
    if payload == VIP_PAYLOAD or payload.startswith(DONATE_PAYLOAD_PREFIX):
        await query.answer(ok=True)
    else:
        await query.answer(ok=False, error_message="Неизвестный платёж")


async def successful_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.successful_payment:
        return
    payment = msg.successful_payment
    payload = payment.invoice_payload
    user_id = msg.from_user.id

    # --- VIP ---
    if payload == VIP_PAYLOAD:
        database.add_vip_days(user_id, VIP_DURATION_DAYS)
        until = database.get_vip_until(user_id)
        days_left = (until - int(time.time())) // 86400
        await msg.reply_html(
            f"💎 <b>VIP активирован!</b>\n\n"
            f"Срок: {VIP_DURATION_DAYS} дней (осталось {days_left}).\n"
            f"Награды с боёв теперь ×2.\n\n"
            f"<i>Спасибо за поддержку!</i>",
            reply_markup=kb_for(user_id),
        )
        return

    # --- Донат (💠 за звёзды) ---
    if payload.startswith(DONATE_PAYLOAD_PREFIX):
        key = payload[len(DONATE_PAYLOAD_PREFIX):]
        pkg = DONATE_PACKAGES.get(key)
        if not pkg:
            return
        database.add_gold(user_id, pkg["currency"])
        player = database.get_or_create_player(user_id, "")
        bonus = pkg.get("bonus_pct", 0)
        bonus_line = f" (включая +{bonus}% бонус)" if bonus > 0 else ""
        await msg.reply_html(
            f"💰 <b>Спасибо за поддержку!</b>\n\n"
            f"{pkg['emoji']} Пакет: <b>{pkg['name']}</b>\n"
            f"💠 +{pkg['currency']} очков Ассоциации{bonus_line}\n\n"
            f"💠 Теперь у тебя: <b>{player['gold']}</b>\n\n"
            f"<i>Годжо: «Хорошо, что ты не жадный.»</i>",
            reply_markup=kb_for(user_id),
        )
        return


async def vip_info_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    is_active = database.has_vip(user_id)

    kb_rows = []
    if is_active:
        kb_rows.append([InlineKeyboardButton(
            f"💎 Продлить на {VIP_DURATION_DAYS} дней ({VIP_PRICE_STARS}⭐)",
            callback_data="vip_buy",
        )])
    else:
        kb_rows.append([InlineKeyboardButton(
            f"💎 Купить VIP ({VIP_PRICE_STARS}⭐ / {VIP_DURATION_DAYS} дн.)",
            callback_data="vip_buy",
        )])
    kb_rows.append([InlineKeyboardButton("⬅️ Назад в профиль", callback_data="profile_menu")])

    await render(query, context, _vip_description_text(user_id),
                 InlineKeyboardMarkup(kb_rows))


# ---------------------- Донат ----------------------

def _donate_description_text(user_id: int) -> str:
    player = database.get_or_create_player(user_id, "")
    lines = [
        "💰 <b>Донат — Очки Ассоциации за звёзды</b>",
        "",
        f"Базовый курс: <b>{DONATE_RATE} 💠 за 1 ⭐</b>",
        f"💠 У тебя сейчас: <b>{player['gold']}</b>",
        "",
        "🎁 <b>Чем больше пакет — тем выгоднее курс!</b>",
        "   🥉 Малый       — ×1.0 к курсу",
        "   🥈 Средний     — <b>+20% бонус</b>",
        "   🥇 Большой     — <b>+33% бонус</b>",
        "   💎 Гигантский  — <b>+50% бонус</b> ⭐ ЛУЧШАЯ ЦЕНА",
        "",
        "Выбери пакет 👇",
        "",
        "<i>Оплата через Telegram Stars. Валюта начисляется мгновенно.</i>",
    ]
    return "\n".join(lines)


def donate_menu_keyboard() -> InlineKeyboardMarkup:
    rows = []
    for key, pkg in DONATE_PACKAGES.items():
        best = " ⭐" if key == "huge" else ""
        rows.append([InlineKeyboardButton(
            f"{pkg['emoji']} {pkg['name']}: {pkg['currency']}💠 за {pkg['stars']}⭐{best}",
            callback_data=f"donate_buy:{key}",
        )])
    rows.append([InlineKeyboardButton("⬅️ Назад в профиль", callback_data="profile_menu")])
    return InlineKeyboardMarkup(rows)


async def donate_buy_handler(update: Update, context: ContextTypes.DEFAULT_TYPE,
                              package_key: str):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    pkg = DONATE_PACKAGES.get(package_key)
    if not pkg:
        await query.message.reply_text("❌ Пакет не найден.")
        return

    bonus = pkg.get("bonus_pct", 0)
    base = pkg["stars"] * DONATE_RATE
    if bonus > 0:
        desc = (
            f"Покупка {pkg['currency']} 💠 за {pkg['stars']} ⭐.\n"
            f"Базовая цена: {base} 💠 + {bonus}% бонус = {pkg['currency']} 💠."
        )
    else:
        desc = f"Покупка {pkg['currency']} 💠 за {pkg['stars']} ⭐."

    try:
        await context.bot.send_invoice(
            chat_id=user_id,
            title=f"{pkg['emoji']} {pkg['name']} пакет",
            description=desc,
            payload=f"{DONATE_PAYLOAD_PREFIX}{package_key}",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(f"{pkg['currency']} 💠", pkg["stars"])],
        )
    except Exception as e:
        logger.warning(f"Не удалось отправить инвойс доната: {e}")
        await query.message.reply_text(f"❌ Ошибка оплаты: {e}")


# ---------------------- Кнопки ----------------------

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    player = database.get_or_create_player(user_id, query.from_user.username or query.from_user.first_name)
    x = player["x"]

    in_raid_now = raid.get_active_raid_for_user(user_id)
    if (not in_raid_now
            and -25 <= x <= 25
            and not story.is_in_temp(user_id)
            and not database.get_encounter(user_id)):
        event = story.check_and_finish(user_id)
        if event:
            text = story.format_completion(
                event["completed_chapter"],
                event["reward_gold"], event["reward_exp"],
                event["leveled"], event["new_level"],
                event.get("vip_applied", False),
            )
            if event["next_chapter"]:
                text += "\n\n" + story.format_intro(event["next_chapter"])
            else:
                text += "\n\n🏁 <b>Все доступные главы пройдены.</b>"
            text += f"\n\n📈 Новый потолок уровня: <b>{event['new_max_level']}</b>"
            await render(query, context, text, kb_for(user_id),
                         image_path=district_image_for_x(x))
            return

    data = query.data
    done: list[dict] = []

    # ================= РЕЙД =================

    if data == "raid_menu":
        if raid.get_active_raid_for_user(user_id):
            await _render_raid_screen(query, context,
                                      raid.get_active_raid_for_user(user_id)["id"], user_id)
            return
        available = raid.get_available_fingers(user_id)
        cd = raid.get_cooldown_until(user_id)
        if cd:
            left = cd - int(time.time())
            text = (
                "👺 <b>Рейд на Сукуну</b>\n\n"
                f"⏳ Твои пальцы в КД ещё <b>{raid.format_cooldown(left)}</b>.\n"
                "<i>Пальцы Сукуны добываются в сюжетных главах.</i>"
            )
            await render(query, context, text, kb_for(user_id))
            return
        if available == 0:
            text = (
                "👺 <b>Рейд на Сукуну</b>\n\n"
                "У тебя нет 🩸 Пальцев Сукуны.\n"
                "<i>Пальцы дропают сюжетные боссы (см. «📖 Сюжет»).</i>"
            )
            await render(query, context, text, kb_for(user_id))
            return
        text = (
            "👺 <b>Рейд на Сукуну</b>\n\n"
            f"🩸 Доступно пальцев: <b>{available}</b>\n"
            "Чем больше пальцев — тем сильнее Сукуна и жирнее награда.\n\n"
            "Создай рейд, позови друзей по ссылке (до 5 игроков) и дерись.\n"
            "⚠️ <i>У каждого участника должно быть не меньше пальцев, чем "
            "в рейде.</i>\n\n"
            "<i>Годжо: «Веселитесь, только не помрите все сразу.»</i>"
        )
        await render(query, context, text, raid_menu_keyboard(user_id))
        return

    if data.startswith("raid_create:"):
        try:
            n = int(data.split(":", 1)[1])
        except ValueError:
            n = 0
        res = raid.create_raid(user_id, n)
        if not res["ok"]:
            await render(query, context, "❌ " + res["msg"], kb_for(user_id))
            return
        await _render_raid_screen(query, context, res["raid_id"], user_id)
        return

    if data == "raid_show":
        r = raid.get_active_raid_for_user(user_id)
        if not r:
            await render(query, context,
                         "ℹ️ У тебя нет активного рейда.",
                         kb_for(user_id))
            return
        await _render_raid_screen(query, context, r["id"], user_id)
        return

    if data.startswith("raid_show:"):
        try:
            rid = int(data.split(":", 1)[1])
        except ValueError:
            rid = None
        if not rid:
            await render(query, context, "❌ Рейд не найден.", kb_for(user_id))
            return
        await _render_raid_screen(query, context, rid, user_id)
        return

    if data.startswith("raid_start:"):
        try:
            rid = int(data.split(":", 1)[1])
        except ValueError:
            rid = None
        if not rid:
            await render(query, context, "❌ Рейд не найден.", kb_for(user_id))
            return
        res = raid.start_battle(rid, user_id)
        if not res["ok"]:
            await render(query, context, "❌ " + res["msg"], kb_for(user_id))
            return
        await _render_raid_screen(query, context, rid, user_id)
        parts = raid.get_participants(rid)
        await _notify_raid_players(
            context, rid,
            [p["user_id"] for p in parts],
            exclude=user_id,
        )
        return

    if data.startswith("raid_leave:"):
        try:
            rid = int(data.split(":", 1)[1])
        except ValueError:
            rid = None
        if not rid:
            await render(query, context, "❌ Рейд не найден.", kb_for(user_id))
            return
        res = raid.leave_raid(rid, user_id)
        if res.get("disband"):
            text = "🚪 Ты вышел. Рейд распущен."
        else:
            text = "🚪 " + res.get("msg", "Ты вышел из рейда.")
        await render(query, context, text, kb_for(user_id))
        r = raid.get_raid(rid)
        if r and r["status"] in ("lobby", "battle"):
            await _notify_raid_players(
                context, rid,
                [p["user_id"] for p in raid.get_participants(rid)],
                exclude=user_id,
            )
        return

    if data.startswith("raid_attack:"):
        parts = data.split(":")
        try:
            rid = int(parts[1])
        except (ValueError, IndexError):
            rid = None
        if not rid:
            await render(query, context, "❌ Рейд не найден.", kb_for(user_id))
            return

        tech_name = None
        if len(parts) >= 4 and parts[2] == "t":
            try:
                slot = int(parts[3])
            except ValueError:
                slot = -1
            equipped = gacha.get_equipped(user_id)
            if 0 <= slot < len(equipped):
                tech_name = equipped[slot]

        res = raid.player_attack(rid, user_id, tech_name)
        if not res.get("ok"):
            await render(query, context,
                         "❌ " + res.get("msg", "Не удалось атаковать."),
                         kb_for(user_id))
            return

        r = raid.get_raid(rid)
        if r and r["status"] == "finished":
            text = raid.format_finished(rid)
            await render(query, context, text, raid_finished_keyboard())
        else:
            text = raid.format_battle(rid, user_id)
            await render(query, context, text, raid_battle_keyboard(rid, user_id))

        notify_ids = res.get("notify") or []
        await _notify_raid_players(context, rid, notify_ids, exclude=user_id)
        return

    # ================= ДОМЕН =================

    if data == "domain_activate":
        result = combat.activate_domain_manual(user_id)
        encounter = database.get_encounter(user_id)
        fresh_player = database.get_or_create_player(user_id, "")

        if not result.get("ok"):
            if encounter:
                text = ("❌ " + result["msg"] + "\n\n"
                        + combat.encounter_status_text(encounter) + "\n\n"
                        + combat.player_status_text(fresh_player, user_id))
                image_path = assets.get_monster_image(encounter["monster_name"])
                await render(query, context, text, kb_for(user_id), image_path=image_path)
            else:
                text = "❌ " + result["msg"] + "\n\n" + location_text(user_id, x)
                await render(query, context, text, kb_for(user_id),
                             image_path=district_image_for_x(x))
            return

        log_text = "\n".join(result["log"])
        if encounter:
            text = (combat.encounter_status_text(encounter) + "\n\n" + log_text + "\n\n"
                    + combat.player_status_text(fresh_player, user_id))
            image_path = assets.get_monster_image(encounter["monster_name"])
            await render(query, context, text, kb_for(user_id), image_path=image_path)
        else:
            text = log_text + "\n\n" + location_text(user_id, x)
            await render(query, context, text, kb_for(user_id),
                         image_path=district_image_for_x(x))
        if result.get("effect"):
            await send_effect_gif(context, query.message.chat_id, result["effect"])
        return

    if data == "domain_info":
        technique_name = combat.get_unlocked_domain_technique(user_id)
        if technique_name:
            cond = combat.check_activation_condition(user_id)
            uses_before = database.get_domain_uses_in_battle(user_id)
            penalty = combat._get_reactivation_penalty(uses_before)

            player_now = database.get_or_create_player(user_id, "")
            eff = ce_types.get_effective_stats(user_id, player_now)
            domain_cost = max(1, int(eff["max_ce"] * 0.60)) if eff["max_ce"] > 0 else 0

            lines = [f"{cond['domain_emoji']} <b>{cond['domain_name']}</b>", ""]
            lines.append(
                f"🔵 Стоимость активации: <b>{domain_cost} ПЭ</b> "
                f"(60% от максимума). Сейчас у тебя: <b>{eff['ce']} ПЭ</b>."
            )
            lines.append("")

            if cond["ok"]:
                lines.append(f"✅ Условие активации выполнено: <b>{cond['text']}</b>.")
                if eff["max_ce"] <= 0:
                    lines.append("❌ У тебя нет ПЭ (Проклятие Небес) — домен недоступен.")
                elif eff["ce"] < domain_cost:
                    lines.append("❌ Не хватает ПЭ для активации.")
                elif penalty > 0:
                    lines.append(
                        f"⚠️ Сейчас в бою уже активировали {uses_before} раз — "
                        f"повторное расширение отнимет <b>{int(penalty*100)}% HP</b>."
                    )
                else:
                    lines.append("Нажми кнопку, чтобы активировать домен.")
            else:
                lines.append(f"⏳ Условие активации: <b>{cond['text']}</b>")
                lines.append("")
                lines.append(
                    "<i>Выполни условие в этом бою — и кнопка активации заработает.</i>"
                )
            await render(query, context, "\n".join(lines), kb_for(user_id))
        else:
            equipped = gacha.get_equipped(user_id)
            lines = ["🌌 <b>Домен ещё не разблокирован</b>", ""]
            lines.append(
                f"Используй мастер-технику в бою <b>{config.DOMAIN_UNLOCK_USES} раз</b>, "
                f"чтобы открыть её домен."
            )
            lines.append("")
            any_master = False
            for name in equipped:
                t = gacha.get_technique(name)
                if not t or not t.get("has_domain"):
                    continue
                any_master = True
                uses = database.get_technique_uses(user_id, name)
                bar = "▰" * (uses * 10 // config.DOMAIN_UNLOCK_USES) + "▱" * (10 - uses * 10 // config.DOMAIN_UNLOCK_USES)
                lines.append(f"  {t['emoji']} <b>{name}</b>")
                lines.append(f"     {bar} {uses}/{config.DOMAIN_UNLOCK_USES}")
            if not any_master:
                lines.append("<i>У тебя нет экипированных мастер-техник.</i>")
            await render(query, context, "\n".join(lines), kb_for(user_id))
        return

    # ================= МЕТРО =================

    if data == "subway_open":
        text = subway.format_subway_text(user_id)
        await render(query, context, text, subway_keyboard(user_id))
        return

    if data.startswith("subway_travel:"):
        target_id = data.split(":", 1)[1]
        result = subway.use_subway(user_id, target_id)

        if not result.get("ok"):
            text = "❌ " + result["msg"] + "\n\n" + subway.format_subway_text(user_id)
            await render(query, context, text, subway_keyboard(user_id))
            return

        new_x = result["x"]
        text = result["msg"] + "\n\n" + location_text(user_id, new_x)
        await render(query, context, text, kb_for(user_id),
                     image_path=district_image_for_x(new_x))
        return

    if data == "subway_no_money":
        await render(
            query, context,
            "❌ Не хватает 💠 на этот билет.\n\n" + subway.format_subway_text(user_id),
            subway_keyboard(user_id),
        )
        return

    # ================= ДВИЖЕНИЕ / ОТДЫХ / ПАТРУЛЬ =================

    if data in ("move_left", "move_right"):
        step = -config.MOVE_STEP if data == "move_left" else config.MOVE_STEP
        raw_new_x = x + step
        lvl_min, lvl_max = config.get_world_bounds(player["level"])

        if raw_new_x < lvl_min or raw_new_x > lvl_max:
            needed_level = player["level"] + 1
            while needed_level <= 20:
                nb_min, nb_max = config.get_world_bounds(needed_level)
                if nb_min <= raw_new_x <= nb_max:
                    break
                needed_level += 1

            if -config.MAX_WORLD <= raw_new_x <= config.MAX_WORLD and needed_level <= 20:
                text = (f"🚧 Дальше не пройти. Нужен уровень {needed_level} "
                        f"(у тебя {player['level']}).\n\n" + location_text(user_id, x))
            else:
                text = "🌍 Дальше некуда — это край мира.\n\n" + location_text(user_id, x)

            await render(query, context, text, kb_for(user_id), image_path=district_image_for_x(x))
            return

        old_district = get_district_by_x(x)
        new_district = get_district_by_x(raw_new_x)
        database.update_player_x(user_id, raw_new_x)

        done += quests.add_progress(user_id, "move")

        district_changed = old_district["id"] != new_district["id"]
        if district_changed:
            done += quests.add_progress(user_id, "district_change")
            done += quests.add_progress(user_id, "visit_district", target=new_district["id"])

        text = location_text(user_id, raw_new_x) + _quests_done_text(done)
        await render(query, context, text, kb_for(user_id),
                     image_path=district_image_for_x(raw_new_x))
        return

    elif data == "rest":
        district = get_district_by_x(x)
        if district["id"] != "jujutsu_high":
            text = "❌ Отдохнуть можно только в Токийской школе магии.\n\n" + location_text(user_id, x)
            await render(query, context, text, kb_for(user_id), image_path=district_image_for_x(x))
            return
        result = rest.try_rest(user_id)
        prefix = "✅ " if result["ok"] else "❌ "
        text = prefix + result["msg"] + "\n\n" + location_text(user_id, x)
        await render(query, context, text, kb_for(user_id), image_path=district_image_for_x(x))
        return

    elif data == "patrol":
        district = get_district_by_x(x)

        if district.get("safe") and not database.get_encounter(user_id):
            text = (
                "🛡 <b>Здесь безопасно.</b>\n\n"
                f"💬 {GOJO}: «В школу проклятия не суются — это моя территория. "
                f"Хочешь бой — иди в другой район.»\n\n"
                + location_text(user_id, x)
            )
            await render(query, context, text, kb_for(user_id),
                         image_path=district_image_for_x(x))
            return

        encounter = database.get_encounter(user_id)
        if not encounter:
            found = monsters.patrol(user_id, x)
            encounter = database.get_encounter(user_id) if found else None

        if not encounter:
            text = ("🩸 Ты патрулируешь район, но проклятий не чувствуется. "
                    "Попробуй ещё раз через минуту!")
            text += "\n\n" + location_text(user_id, x)
            await render(query, context, text, kb_for(user_id), image_path=district_image_for_x(x))
        else:
            done += quests.add_progress(user_id, "patrol_start")
            text = ("⚔️ <b>Бой начался!</b>\n\n"
                    + combat.encounter_status_text(encounter) + "\n\n"
                    + combat.player_status_text(player, user_id)
                    + _quests_done_text(done))
            image_path = assets.get_monster_image(encounter["monster_name"])
            await render(query, context, text, kb_for(user_id), image_path=image_path)
            await send_effect_gif(context, query.message.chat_id, "encounter_start", ttl=2)

    # ================= БОЙ =================

    elif data == "attack" or data == "defend" or data == "flee" or data.startswith("tech:"):
        if data == "attack":
            result = combat.attack(user_id)
        elif data == "defend":
            result = combat.defend(user_id)
        elif data == "flee":
            result = combat.flee(user_id)
        else:
            try:
                slot = int(data.split(":", 1)[1])
            except ValueError:
                slot = -1
            equipped = gacha.get_equipped(user_id)
            if 0 <= slot < len(equipped):
                technique_name = equipped[slot]
                result = combat.attack(user_id, technique_name=technique_name)
            else:
                result = {"status": "invalid", "log": ["❌ Техника недоступна."]}

        if result["status"] == "no_encounter":
            text = "Перед тобой никого нет.\n\n" + location_text(user_id, x)
            await render(query, context, text, kb_for(user_id),
                         image_path=district_image_for_x(x))
            return

        log_text = "\n".join(result["log"])

        if result["status"] == "invalid":
            encounter = database.get_encounter(user_id)
            text = ("❌ " + log_text + "\n\n"
                    + combat.encounter_status_text(encounter) + "\n\n"
                    + combat.player_status_text(database.get_or_create_player(user_id, ""), user_id))
            image_path = assets.get_monster_image(encounter["monster_name"])
            await render(query, context, text, kb_for(user_id), image_path=image_path)
            return

        fresh_player = database.get_or_create_player(user_id, "")
        encounter = database.get_encounter(user_id)

        if encounter and result["status"] == "ongoing":
            text = (combat.encounter_status_text(encounter) + "\n\n" + log_text + "\n\n"
                    + combat.player_status_text(fresh_player, user_id))
            image_path = assets.get_monster_image(encounter["monster_name"])
            await render(query, context, text, kb_for(user_id), image_path=image_path)
        elif story.is_in_temp(user_id) and result["status"] == "victory":
            temp = story.get_temp_district(user_id)
            text = log_text + "\n\n"
            if temp:
                text += (f"{temp['emoji']} <b>{temp['name']}</b>\n"
                         f"<i>{temp['description']}</i>")
            await render(query, context, text, story_temp_keyboard(user_id))
        else:
            text = log_text + "\n\n" + location_text(user_id, fresh_player["x"])
            await render(query, context, text, kb_for(user_id),
                         image_path=district_image_for_x(fresh_player["x"]))

        if result.get("effect"):
            await send_effect_gif(context, query.message.chat_id, result["effect"])

    # ================= ИНВЕНТАРЬ =================

    elif data == "inventory":
        items = database.get_inventory(user_id)
        if not items:
            text = "🎒 Твой инвентарь пуст. Иди патрулировать!"
        else:
            pretty = []
            for i in items:
                if i["rarity"] == "расходник":
                    pretty.append(f"🧪 {i['item_name']} x{i['quantity']} (расходник)")
                elif i["rarity"] == "призыв" or i["item_name"] in bosses.SUMMON_RECIPES:
                    pretty.append(f"⚡ {i['item_name']} x{i['quantity']} (ритуальная печать)")
                else:
                    pretty.append(format_loot_line({"name": i["item_name"], "rarity": i["rarity"]}, i["quantity"]))
            text = "🎒 <b>Инвентарь</b>\n\n" + "\n".join(pretty)
        await render(query, context, text, inventory_keyboard(user_id))

    elif data.startswith("use_item:"):
        try:
            idx = int(data.split(":", 1)[1])
        except ValueError:
            idx = -1
        items = database.get_inventory(user_id)
        if idx < 0 or idx >= len(items):
            await render(query, context, "❌ Предмет недоступен. Открой инвентарь заново.",
                         kb_for(user_id))
            return
        item = items[idx]
        if item["rarity"] != "расходник":
            await render(query, context, "❌ Этот предмет нельзя использовать.",
                         inventory_keyboard(user_id))
            return
        item_name = item["item_name"]
        result = consumables.use(user_id, item_name)
        prefix = "✅ " if result["ok"] else "❌ "

        encounter = database.get_encounter(user_id)
        if encounter:
            fresh_player = database.get_or_create_player(user_id, "")
            text = (combat.encounter_status_text(encounter) + "\n\n"
                    + prefix + result["msg"] + "\n\n"
                    + combat.player_status_text(fresh_player, user_id))
            image_path = assets.get_monster_image(encounter["monster_name"])
            await render(query, context, text, kb_for(user_id), image_path=image_path)
        else:
            items_now = database.get_inventory(user_id)
            pretty = []
            for i in items_now:
                if i["rarity"] == "расходник":
                    pretty.append(f"🧪 {i['item_name']} x{i['quantity']} (расходник)")
                elif i["rarity"] == "призыв" or i["item_name"] in bosses.SUMMON_RECIPES:
                    pretty.append(f"⚡ {i['item_name']} x{i['quantity']} (ритуальная печать)")
                else:
                    pretty.append(format_loot_line({"name": i["item_name"], "rarity": i["rarity"]}, i["quantity"]))
            body = prefix + result["msg"] + "\n\n🎒 <b>Инвентарь</b>\n\n" + ("\n".join(pretty) if pretty else "пусто")
            await render(query, context, body, inventory_keyboard(user_id))

    elif data.startswith("summon_item:"):
        try:
            idx = int(data.split(":", 1)[1])
        except ValueError:
            idx = -1
        items = database.get_inventory(user_id)
        if idx < 0 or idx >= len(items):
            await render(query, context, "❌ Предмет недоступен. Открой инвентарь заново.",
                         kb_for(user_id))
            return
        item = items[idx]
        is_seal = item["rarity"] == "призыв" or item["item_name"] in bosses.SUMMON_RECIPES
        if not is_seal:
            await render(query, context, "❌ Это не ритуальная печать.",
                         inventory_keyboard(user_id))
            return
        item_name = item["item_name"]
        result = bosses.summon(user_id, item_name, x)
        if not result["ok"]:
            text = "❌ " + result["msg"] + "\n\n" + location_text(user_id, x)
            await render(query, context, text, kb_for(user_id), image_path=district_image_for_x(x))
            return
        encounter = database.get_encounter(user_id)
        fresh_player = database.get_or_create_player(user_id, "")
        text = (result["msg"] + "\n\n"
                + combat.encounter_status_text(encounter) + "\n\n"
                + combat.player_status_text(fresh_player, user_id))
        image_path = assets.get_monster_image(encounter["monster_name"])
        await render(query, context, text, kb_for(user_id), image_path=image_path)
        await send_effect_gif(context, query.message.chat_id, "encounter_start", ttl=2)

    # ================= КАРТА / СЮЖЕТ =================

    elif data == "map":
        text = "🗺 <b>Карта районов Токио</b>\n\n" + get_world_map_text(x)
        await render(query, context, text, kb_for(user_id))

    elif data == "story_menu":
        text = story.format_story_screen(user_id)
        await render(query, context, text, story_menu_keyboard(user_id))

    elif data == "story_enter_temp":
        if not story.can_start_chapter(user_id):
            min_level = story.get_chapter_min_level(user_id)
            text = (
                f"🔒 <b>Нужен уровень {min_level}</b> (у тебя {player['level']}).\n\n"
                f"💬 {GOJO}: «Прокачайся и возвращайся. Не хочу, чтобы тебя убили в первую же минуту.»"
            )
            await render(query, context, text, story_menu_keyboard(user_id))
            return
        temp = story.get_temp_district(user_id)
        if not temp:
            text = "📖 Сейчас нечего делать по сюжету.\n\n" + location_text(user_id, x)
            await render(query, context, text, kb_for(user_id), image_path=district_image_for_x(x))
            return
        story.exit_temp(user_id)
        story.enter_temp(user_id)

        # Регистрируем find-шаг, если он есть в текущей главе
        story.register_find_step(user_id, temp["id"])

        text = (
            f"{temp['emoji']} <b>{temp['name']}</b>\n"
            f"<i>{temp['description']}</i>\n\n"
            "🩸 Патрулируй или продолжай по сюжету."
        )
        await render(query, context, text, story_temp_keyboard(user_id))

    elif data == "story_exit_temp":
        story.exit_temp(user_id)
        event = story.check_and_finish(user_id)
        if event:
            text = story.format_completion(
                event["completed_chapter"],
                event["reward_gold"], event["reward_exp"],
                event["leveled"], event["new_level"],
                event.get("vip_applied", False),
            )
            if event["next_chapter"]:
                text += "\n\n" + story.format_intro(event["next_chapter"])
            else:
                text += "\n\n🏁 <b>Все доступные главы пройдены.</b>"
            text += f"\n\n📈 Новый потолок уровня: <b>{event['new_max_level']}</b>"
            await render(query, context, text, kb_for(user_id),
                         image_path=district_image_for_x(x))
            return
        text = location_text(user_id, x)
        await render(query, context, text, kb_for(user_id),
                     image_path=district_image_for_x(x))

    elif data == "story_temp_patrol":
        temp = story.get_temp_district(user_id)
        if not temp or not story.is_in_temp(user_id):
            story.exit_temp(user_id)
            text = location_text(user_id, x)
            await render(query, context, text, kb_for(user_id),
                         image_path=district_image_for_x(x))
            return
        monster = monsters.patrol_in_temp(user_id, temp)
        if not monster:
            text = f"{temp['emoji']} <b>{temp['name']}</b>\n\n🩸 Тишина... но что-то шевелится."
            await render(query, context, text, story_temp_keyboard(user_id))
            return

        # Регистрируем reach-шаг при старте боя в сюжетной локации
        story.register_reach_step(user_id, temp["id"])

        encounter = database.get_encounter(user_id)
        text = ("⚔️ <b>Бой начался!</b>\n\n"
                + combat.encounter_status_text(encounter) + "\n\n"
                + combat.player_status_text(player, user_id))
        image_path = assets.get_monster_image(encounter["monster_name"])
        await render(query, context, text, kb_for(user_id), image_path=image_path)

    elif data == "story_temp_talk":
        result = story.talk_to_current_npc(user_id)
        if not result.get("ok"):
            text = "❌ " + result["msg"] + "\n\n" + story.format_story_screen(user_id)
            await render(query, context, text, story_temp_keyboard(user_id))
            return

        text = result["msg"]
        temp = story.get_temp_district(user_id)
        if temp:
            text += f"\n\n{temp['emoji']} <b>{temp['name']}</b>\n<i>{temp['description']}</i>"
        await render(query, context, text, story_temp_keyboard(user_id))

    elif data == "story_temp_puzzle":
        found = story.get_current_puzzle_step(user_id)
        if not found:
            await render(query, context,
                         "✅ Головоломка уже решена.\n\n" + story.format_story_screen(user_id),
                         story_temp_keyboard(user_id))
            return
        _, pid, puzzle = found
        if puzzle["type"] == "sequence":
            story.start_sequence_puzzle(user_id, pid)
        text = story.format_puzzle_prompt(user_id) or "🧩 Головоломка"
        await render(query, context, text, puzzle_keyboard(pid))

    elif data == "story_temp_back":
        if story.is_in_temp(user_id):
            temp = story.get_temp_district(user_id)
            if temp:
                text = (f"{temp['emoji']} <b>{temp['name']}</b>\n"
                        f"<i>{temp['description']}</i>\n\n"
                        "🩸 Патрулируй или продолжай по сюжету.")
            else:
                text = "📖 Сюжет"
            await render(query, context, text, story_temp_keyboard(user_id))
        else:
            text = location_text(user_id, x)
            await render(query, context, text, kb_for(user_id),
                         image_path=district_image_for_x(x))

    elif data.startswith("story_puzzle:"):
        parts = data.split(":", 3)
        if len(parts) < 3:
            return
        pid = parts[1]
        action = parts[2]
        puzzle = story.get_puzzle(pid)
        if not puzzle:
            await render(query, context, "❌ Головоломка не найдена.",
                         story_temp_keyboard(user_id))
            return

        if action == "start":
            if puzzle["type"] == "sequence":
                story.start_sequence_puzzle(user_id, pid)
                text = story.format_puzzle_prompt(user_id) or "🧩 Головоломка"
                await render(query, context, text, puzzle_keyboard(pid))
            elif puzzle["type"] == "reaction":
                story.start_reaction_puzzle(user_id, pid)
                text = ("🧩 <b>Приготовься…</b>\n\n"
                        "Как только почувствуешь момент — жми «🛑 Тормоз»!")
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🛑 Тормоз",
                                          callback_data=f"story_puzzle:{pid}:brake")],
                ])
                await render(query, context, text, kb)
            return

        if action == "tap":
            if len(parts) < 4:
                return
            try:
                sym_idx = int(parts[3])
            except ValueError:
                return
            symbols = _get_symbols(puzzle)
            if sym_idx < 0 or sym_idx >= len(symbols):
                return
            sym = symbols[sym_idx]
            res = story.check_sequence_tap(user_id, pid, sym)
            r = res["result"]
            total = len(puzzle["sequence"])
            if r == "wrong":
                bar = " ".join("⬜" for _ in range(total))
                text = (f"❌ <b>Не та печать!</b> Все гаснут.\n\n"
                        f"<b>Прогресс:</b> {bar}\n"
                        f"<b>Угадано:</b> 0 из {total}\n\n"
                        "Попробуй снова. Печати те же, порядок тот же.")
                await render(query, context, text, puzzle_keyboard(pid))
            elif r == "correct":
                pos = res["position"]
                bar = story.format_sequence_progress(pid, pos)
                text = (f"✅ <b>Верно!</b>\n\n"
                        f"<b>Прогресс:</b> {bar}\n"
                        f"<b>Угадано:</b> {pos} из {total}")
                await render(query, context, text, puzzle_keyboard(pid))
            elif r == "complete":
                text = ("🎉 <b>Все печати зажжены!</b>\n\n"
                        + story.format_story_screen(user_id))
                await render(query, context, text, story_temp_keyboard(user_id))
            return

        if action == "brake":
            res = story.check_reaction_tap(user_id, pid)
            r = res["result"]
            if r == "not_started":
                text = "❌ Сначала нажми «▶️ Начать»."
                await render(query, context, text, puzzle_keyboard(pid))
            elif r == "too_early":
                text = "❌ Слишком рано! Попробуй ещё раз."
                await render(query, context, text, puzzle_keyboard(pid))
            elif r == "too_late":
                text = "❌ Слишком поздно! Попробуй ещё раз."
                await render(query, context, text, puzzle_keyboard(pid))
            elif r == "success":
                text = ("🎉 <b>Головоломка решена!</b>\n\n"
                        + story.format_story_screen(user_id))
                await render(query, context, text, story_temp_keyboard(user_id))
            return

    elif data == "story_temp_boss":
        chapter = story.get_current_chapter(user_id)
        temp = story.get_temp_district(user_id)
        if not chapter or not temp or "boss" not in temp or not story.is_in_temp(user_id):
            text = "❌ Сейчас нечего делать."
            await render(query, context, text, story_temp_keyboard(user_id))
            return

        puzzle_found = story.get_current_puzzle_step(user_id)
        if puzzle_found:
            _, pid, _ = puzzle_found
            text = ("🔒 Сначала разгадай головоломку — вход закрыт.\n\n"
                    + (story.format_puzzle_prompt(user_id) or ""))
            await render(query, context, text, puzzle_keyboard(pid))
            return

        boss = temp["boss"]
        monster = {
            "name": boss["name"],
            "hp": boss["hp"],
            "dmg_min": boss["dmg_min"],
            "dmg_max": boss["dmg_max"],
            "emoji": boss["emoji"],
            "rarity": "Особый класс",
            "curse_class": "Особый класс",
            "defense": boss.get("defense", 0.0),
            "drop_item": None,
            "drop_rarity": None,
        }
        database.set_encounter(user_id, temp["id"], monster)
        encounter = database.get_encounter(user_id)
        text = ("👁 <b>Хранитель пробудился!</b>\n\n"
                + combat.encounter_status_text(encounter) + "\n\n"
                + combat.player_status_text(player, user_id))
        image_path = assets.get_monster_image(encounter["monster_name"])
        await render(query, context, text, kb_for(user_id), image_path=image_path)

    # ================= ПРОФИЛЬ =================

    elif data == "profile_menu":
        await render(query, context, profile_text(user_id), profile_menu_keyboard(user_id))

    elif data == "vip_buy":
        await vip_buy_handler(update, context)
        return

    elif data == "vip_info":
        await vip_info_handler(update, context)
        return

    elif data == "donate_menu":
        await render(query, context, _donate_description_text(user_id),
                     donate_menu_keyboard())
        return

    elif data.startswith("donate_buy:"):
        key = data.split(":", 1)[1]
        await donate_buy_handler(update, context, key)
        return

    elif data == "profile_inventory":
        context.user_data["prev_screen"] = "profile"
        items = database.get_inventory(user_id)
        if not items:
            text = "🎒 Твой инвентарь пуст. Иди патрулировать!"
        else:
            pretty = []
            for i in items:
                if i["rarity"] == "расходник":
                    pretty.append(f"🧪 {i['item_name']} x{i['quantity']} (расходник)")
                elif i["rarity"] == "призыв" or i["item_name"] in bosses.SUMMON_RECIPES:
                    pretty.append(f"⚡ {i['item_name']} x{i['quantity']} (ритуальная печать)")
                else:
                    pretty.append(format_loot_line({"name": i["item_name"], "rarity": i["rarity"]}, i["quantity"]))
            text = "🎒 <b>Инвентарь</b>\n\n" + "\n".join(pretty)
        await render(query, context, text, inventory_keyboard(user_id))

    elif data == "profile_techniques":
        context.user_data["gacha_from"] = "profile"
        await render(query, context, gacha_menu_text(user_id), gacha_menu_keyboard())

    elif data == "profile_leaderboard":
        context.user_data["prev_screen"] = "profile"
        text = leaderboard.format_leaderboard(user_id, limit=10)
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Обновить", callback_data="profile_leaderboard")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_game")],
        ])
        await render(query, context, text, keyboard)

    elif data == "leaderboard":
        text = leaderboard.format_leaderboard(user_id, limit=10)
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Обновить", callback_data="leaderboard")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_game")],
        ])
        await render(query, context, text, keyboard)

    # ================= ЗАДАНИЯ =================

    elif data == "quests_menu":
        text = (
            "📋 <b>Задания Годжо</b>\n\n"
            "Годжо выдаёт 3 ежедневных и 3 недельных задания.\n"
            "Прогресс считается автоматически, награду нужно забрать вручную.\n"
            "💎 VIP даёт ×2 к наградам за задания.\n\n"
            "<i>Годжо: «Работай — и я подкину тебе очков на крутки.»</i>"
        )
        await render(query, context, text, quests_menu_keyboard())

    elif data in ("quests_daily", "quests_weekly"):
        period = "daily" if data == "quests_daily" else "weekly"
        text = quests.format_quests_text(user_id, period)
        await render(query, context, text, quests_period_keyboard(period))

    elif data.startswith("quests_claim_all:"):
        period = data.split(":", 1)[1]
        res = quests.claim_all_ready(user_id, period)
        prefix = "✅ " if res["ok"] else "ℹ️ "
        text = prefix + res["msg"] + "\n\n" + quests.format_quests_text(user_id, period)
        await render(query, context, text, quests_period_keyboard(period))

    # ================= ГАЧА =================

    elif data == "gacha_hub":
        await render(query, context,
                     "🎰 <b>Гача Хакари</b>\n\n"
                     "Три раздела, три валюты, три шанса изменить свою судьбу.\n"
                     "Что крутим сегодня?",
                     gacha_hub_keyboard())

    elif data == "gacha_clan_menu":
        await render(query, context, gacha_clan_menu_text(user_id),
                     gacha_clan_menu_keyboard(user_id))

    elif data == "gacha_ce_menu":
        await render(query, context, gacha_ce_menu_text(user_id),
                     gacha_ce_menu_keyboard(user_id))

    elif data == "gacha_clan_roll1":
        cost = CLAN_GACHA_ROLL_COST
        player_now = database.get_or_create_player(user_id, "")
        if player_now["gold"] < cost:
            await render(query, context,
                         f"❌ Не хватает очков. Нужно {cost}💠.",
                         gacha_clan_menu_keyboard(user_id))
            return
        database.add_gold(user_id, -cost)

        res = ce_types.roll_clan(user_id)
        k = res["kind"]
        if k == "empty":
            line = "💨 Пусто. Ничего не выпало."
        elif k == "heavenly":
            line = f"🌠 <b>{res['emoji']} {res['name']}</b> — новое!\n   <i>{res['desc']}</i>"
        elif k == "heavenly_duplicate":
            line = f"🌠 {res['emoji']} {res['name']} (уже было)"
        elif k == "clan":
            line = f"🩸 <b>{res['emoji']} {res['name']}</b> — новый клан!\n   <i>{res['desc']}</i>"
        else:
            line = f"🩸 {res['emoji']} {res['name']} (уже было)"

        text = "🩸 <b>Результат крутки:</b>\n\n" + line + "\n\n" + gacha_clan_menu_text(user_id)
        await render(query, context, text, gacha_clan_menu_keyboard(user_id))

    elif data == "gacha_ce_roll1":
        cost = CE_GACHA_ROLL_COST
        player_now = database.get_or_create_player(user_id, "")
        if player_now["gold"] < cost:
            await render(query, context,
                         f"❌ Не хватает очков. Нужно {cost}💠.",
                         gacha_ce_menu_keyboard(user_id))
            return
        database.add_gold(user_id, -cost)

        res = ce_types.roll_ce_type(user_id)
        tag = " — новый!" if res["kind"] == "ce" else " (уже было)"
        line = f"{res['emoji']} <b>{res['name']}</b> ({res['rarity']}){tag}"
        text = "⚡ <b>Результат крутки:</b>\n\n" + line + "\n\n" + gacha_ce_menu_text(user_id)
        await render(query, context, text, gacha_ce_menu_keyboard(user_id))

    elif data == "gacha_ce_roll10":
        cost = CE_GACHA_ROLL_COST_X10
        player_now = database.get_or_create_player(user_id, "")
        if player_now["gold"] < cost:
            await render(query, context,
                         f"❌ Не хватает очков. Нужно {cost}💠.",
                         gacha_ce_menu_keyboard(user_id))
            return
        database.add_gold(user_id, -cost)

        res = ce_types.roll_ce_type_x10(user_id)
        lines = ["⚡ <b>Результаты 10 круток ПЭ:</b>", ""]
        new_count = 0
        dup_count = 0
        for r in res["results"]:
            tag = " ✨НОВОЕ✨" if r["kind"] == "ce" else " (дубликат)"
            lines.append(f"{r['emoji']} <b>{r['name']}</b> ({r['rarity']}){tag}")
            if r["kind"] == "ce":
                new_count += 1
            else:
                dup_count += 1
        lines.append("")
        lines.append(f"📊 Новых: <b>{new_count}</b> · Дубликатов: {dup_count}")
        lines.append("")
        lines.append(gacha_ce_menu_text(user_id))

        text = "\n".join(lines)
        await render(query, context, text, gacha_ce_menu_keyboard(user_id))

    elif data == "gacha_my_clans":
        await render(query, context, ce_types.format_clan_list(user_id),
                     my_clans_keyboard(user_id))

    elif data == "gacha_my_ce":
        await render(query, context, ce_types.format_ce_list(user_id),
                     my_ce_keyboard(user_id))

    elif data == "gacha_my_heavenly":
        await render(query, context, ce_types.format_heavenly_list(user_id),
                     my_heavenly_keyboard(user_id))

    elif data.startswith("clan_set:"):
        key = data.split(":", 1)[1]
        res = ce_types.set_active_clan(user_id, key)
        text = ("✅ " if res["ok"] else "❌ ") + res["msg"] + "\n\n" + ce_types.format_clan_list(user_id)
        await render(query, context, text, my_clans_keyboard(user_id))

    elif data == "clan_clear":
        ce_types.clear_clan(user_id)
        await render(query, context,
                     "✅ Активный клан снят.\n\n" + ce_types.format_clan_list(user_id),
                     my_clans_keyboard(user_id))

    elif data.startswith("ce_set:"):
        key = data.split(":", 1)[1]
        res = ce_types.set_active_ce_type(user_id, key)
        text = ("✅ " if res["ok"] else "❌ ") + res["msg"] + "\n\n" + ce_types.format_ce_list(user_id)
        await render(query, context, text, my_ce_keyboard(user_id))

    elif data == "ce_clear":
        ce_types.clear_ce_type(user_id)
        await render(query, context,
                     "✅ Активный тип ПЭ снят.\n\n" + ce_types.format_ce_list(user_id),
                     my_ce_keyboard(user_id))

    elif data.startswith("heavenly_set:"):
        key = data.split(":", 1)[1]
        res = ce_types.set_active_heavenly(user_id, key)
        text = ("✅ " if res["ok"] else "❌ ") + res["msg"] + "\n\n" + ce_types.format_heavenly_list(user_id)
        await render(query, context, text, my_heavenly_keyboard(user_id))

    elif data == "heavenly_clear":
        ce_types.clear_heavenly(user_id)
        await render(query, context,
                     "✅ Активное Проклятие Небес снято.\n\n" + ce_types.format_heavenly_list(user_id),
                     my_heavenly_keyboard(user_id))

    elif data == "gacha_menu":
        context.user_data["gacha_from"] = "game"
        await render(query, context, gacha_menu_text(user_id), gacha_menu_keyboard())

    elif data == "gacha_menu_from_shop":
        context.user_data["gacha_from"] = "shop"
        image_path = assets.get_npc_image("hakari_shop")
        await render(query, context, gacha_menu_text(user_id), gacha_menu_keyboard(),
                     image_path=image_path)

    elif data == "gacha_back":
        gacha_from = context.user_data.get("gacha_from")
        if gacha_from == "shop":
            await render(query, context,
                         "🎰 <b>Гача Хакари</b>\n\nЧто крутим сегодня?",
                         gacha_hub_keyboard())
        elif gacha_from == "profile":
            await render(query, context, profile_text(user_id), profile_menu_keyboard(user_id))
        else:
            text = location_text(user_id, x)
            await render(query, context, text, kb_for(user_id),
                         image_path=district_image_for_x(x))

    elif data == "gacha_back_to_menu":
        image_path = None
        if context.user_data.get("gacha_from") == "shop":
            image_path = assets.get_npc_image("hakari_shop")
        await render(query, context, gacha_menu_text(user_id), gacha_menu_keyboard(),
                     image_path=image_path)

    elif data == "gacha_list":
        image_path = None
        if context.user_data.get("gacha_from") == "shop":
            image_path = assets.get_npc_image("hakari_shop")
        await render(query, context, gacha_menu_text(user_id), gacha_list_keyboard(user_id),
                     image_path=image_path)

    elif data.startswith("gacha_rarity:"):
        short = data.split(":", 1)[1]
        image_path = None
        if context.user_data.get("gacha_from") == "shop":
            image_path = assets.get_npc_image("hakari_shop")
        await render(query, context, gacha_menu_text(user_id),
                     gacha_rarity_keyboard(user_id, short), image_path=image_path)

    elif data == "gacha_roll1":
        result = gacha.roll_once(user_id)
        if not result["ok"]:
            text = "❌ " + result["msg"] + "\n\n" + gacha_menu_text(user_id)
        else:
            emoji = config.GACHA_RARITY_EMOJI.get(result["rarity"], "")
            if result["duplicate"]:
                text = (f"🎰 Выпало: {result['emoji']} <b>{result['name']}</b> {emoji}({result['rarity']})\n"
                        f"Уже изучена — Хакари вернул {result['refund']}💠 в качестве компенсации.")
            else:
                text = f"🎉 Новая техника: {result['emoji']} <b>{result['name']}</b> {emoji}({result['rarity']})!"
            if result["rarity"] in ("Легендарная (Особый класс)", "Мифическая"):
                text += "\n\n✨ <b>Счётчик гаранта сброшен!</b>"
            text += "\n\n" + gacha_menu_text(user_id)
        image_path = assets.get_npc_image("hakari_shop") if context.user_data.get("gacha_from") == "shop" else None
        await render(query, context, text, gacha_menu_keyboard(), image_path=image_path)

    elif data == "gacha_roll10":
        result = gacha.roll_x10(user_id)
        if not result["ok"]:
            text = "❌ " + result["msg"] + "\n\n" + gacha_menu_text(user_id)
        else:
            lines = ["🎰 <b>Результаты 10 круток:</b>"]
            for r in result["results"]:
                emoji = config.GACHA_RARITY_EMOJI.get(r["rarity"], "")
                tag = " (дубликат)" if r["duplicate"] else " ✨НОВОЕ✨"
                lines.append(f"{r['emoji']} {r['name']} {emoji}({r['rarity']}){tag}")
            text = "\n".join(lines) + "\n\n" + gacha_menu_text(user_id)
        image_path = assets.get_npc_image("hakari_shop") if context.user_data.get("gacha_from") == "shop" else None
        await render(query, context, text, gacha_menu_keyboard(), image_path=image_path)

    elif data.startswith("gq:"):
        parts = data.split(":")
        if len(parts) != 4:
            return
        act, short, idx_str = parts[1], parts[2], parts[3]
        try:
            idx = int(idx_str)
        except ValueError:
            return
        rarity = RARITY_FROM_SHORT.get(short)
        if not rarity:
            await render(query, context, "❌ Неверная редкость.", kb_for(user_id))
            return
        learned = database.get_player_techniques(user_id)
        techs = sorted([
            r["technique_name"] for r in learned
            if gacha.get_technique(r["technique_name"])
            and gacha.get_technique(r["technique_name"])["rarity"] == rarity
        ])
        if idx < 0 or idx >= len(techs):
            await render(query, context,
                         "❌ Техника не найдена. Открой список заново.",
                         gacha_list_keyboard(user_id))
            return
        name = techs[idx]
        if act == "e":
            result = gacha.equip(user_id, name)
        else:
            result = gacha.unequip(user_id, name)
        text = ("✅ " if result["ok"] else "❌ ") + result["msg"] + "\n\n" + gacha_menu_text(user_id)
        image_path = assets.get_npc_image("hakari_shop") if context.user_data.get("gacha_from") == "shop" else None
        await render(query, context, text, gacha_rarity_keyboard(user_id, short),
                     image_path=image_path)

    # ================= НПС / МАГАЗИН / ОРУЖИЕ =================

    elif data.startswith("npc:"):
        npc_id = data.split(":", 1)[1]
        npc = shop.get_npc(npc_id)
        if not npc:
            await render(query, context, "НПС не найден.", kb_for(user_id))
            return
        text = f"{npc['emoji']} <b>{npc['name']}</b>\n\n<i>{npc['greeting']}</i>"
        image_path = assets.get_npc_image(npc_id)
        await render(query, context, text, shop_menu_keyboard(npc_id), image_path=image_path)

    elif data.startswith("shop_buy:"):
        npc_id = data.split(":", 1)[1]
        npc = shop.get_npc(npc_id)
        player_now = database.get_or_create_player(user_id, "")
        lines = [f"{npc['emoji']} <b>{npc['name']} — расходники</b>",
                 f"💠 У тебя: {player_now['gold']} очков\n"]
        for item_name in npc["sells"]:
            it = consumables.CONSUMABLES.get(item_name, {})
            lines.append(f"{item_name} — {it.get('price','?')}💠 — <i>{it.get('desc','')}</i>")
        image_path = assets.get_npc_image(f"{npc_id}_shop")
        await render(query, context, "\n".join(lines), shop_buy_keyboard(npc_id),
                     image_path=image_path)

    elif data.startswith("shop_do_buy:"):
        _, npc_id, idx_str = data.split(":", 2)
        try:
            idx = int(idx_str)
        except ValueError:
            idx = -1
        npc = shop.get_npc(npc_id)
        if idx < 0 or idx >= len(npc["sells"]):
            text = "❌ Товар недоступен."
            await render(query, context, text, shop_buy_keyboard(npc_id))
            return
        item_name = npc["sells"][idx]
        result = shop.buy(user_id, npc_id, item_name)
        player_now = database.get_or_create_player(user_id, "")
        text = ("✅ " if result["ok"] else "❌ ") + result["msg"] + f"\n\n💠 У тебя: {player_now['gold']}"
        image_path = assets.get_npc_image(f"{npc_id}_shop")
        await render(query, context, text, shop_buy_keyboard(npc_id), image_path=image_path)

    elif data.startswith("shop_sell:"):
        npc_id = data.split(":", 1)[1]
        npc = shop.get_npc(npc_id)
        items = shop.get_sellable_items(user_id, npc_id)
        if not items:
            text = f"{npc['emoji']} <b>{npc['name']}</b>\n\n<i>У тебя нечего продать.</i>"
            image_path = assets.get_npc_image(f"{npc_id}_shop")
            await render(query, context, text, shop_menu_keyboard(npc_id), image_path=image_path)
            return
        lines = [f"{npc['emoji']} <b>{npc['name']} — скупка трофеев</b>\n"]
        for name, rarity, qty, price in items:
            lines.append(f"• {name} ({rarity}) x{qty} — {price}💠")
        image_path = assets.get_npc_image(f"{npc_id}_shop")
        await render(query, context, "\n".join(lines), shop_sell_keyboard(npc_id, user_id),
                     image_path=image_path)

    elif data.startswith("shop_sell_junk:"):
        npc_id = data.split(":", 1)[1]
        npc = shop.get_npc(npc_id)
        result = shop.sell_all_junk(user_id, npc_id)
        player_now = database.get_or_create_player(user_id, "")
        prefix = "✅ " if result["ok"] else "❌ "
        msg_line = prefix + result["msg"] + f"\n\n💠 У тебя: {player_now['gold']}"

        items = shop.get_sellable_items(user_id, npc_id)
        if items:
            lines = [f"{npc['emoji']} <b>{npc['name']} — скупка трофеев</b>\n", msg_line, ""]
            for name, rarity, qty, price in items:
                lines.append(f"• {name} ({rarity}) x{qty} — {price}💠")
            await render(query, context, "\n".join(lines), shop_sell_keyboard(npc_id, user_id))
        else:
            text = msg_line + f"\n\n{npc['emoji']} <b>{npc['name']}</b>\n\n<i>Больше нечего продать.</i>"
            await render(query, context, text, shop_menu_keyboard(npc_id))

    elif data.startswith("shop_do_sell:"):
        _, npc_id, idx_str = data.split(":", 2)
        try:
            idx = int(idx_str)
        except ValueError:
            idx = -1
        items = shop.get_sellable_items(user_id, npc_id)
        if idx < 0 or idx >= len(items):
            text = "❌ Предмет уже недоступен. Открой меню продажи заново."
            image_path = assets.get_npc_image(f"{npc_id}_shop")
            await render(query, context, text, shop_menu_keyboard(npc_id), image_path=image_path)
            return
        name, rarity, qty, price = items[idx]
        result = shop.sell(user_id, npc_id, name, rarity)
        player_now = database.get_or_create_player(user_id, "")
        text = ("✅ " if result["ok"] else "❌ ") + result["msg"] + f"\n\n💠 У тебя: {player_now['gold']}"
        image_path = assets.get_npc_image(f"{npc_id}_shop")
        await render(query, context, text, shop_sell_keyboard(npc_id, user_id), image_path=image_path)

    elif data.startswith("gear_menu:"):
        npc_id = data.split(":", 1)[1]
        text = (
            "🏴‍☠️ <b>Склад проклятого оружия</b>\n\n"
            f"<i>{HAKARI}: «Это мне Маки и Фушигуро помогли добыть, хе-хе. "
            f"Смотри, что есть. Слабое продам, сильное — скрафти сам из трофеев.»</i>"
        )
        image_path = assets.get_npc_image("hakari_shop")
        await render(query, context, text, gear_menu_keyboard(npc_id), image_path=image_path)

    elif data == "gear_shop_list":
        lines = ["🛒 <b>Оружие на продажу</b>\n"]
        for name, w in equipment.list_purchasable():
            owned = database.has_weapon(user_id, name)
            marker = " ✅ (куплено)" if owned else ""
            lines.append(
                f"{w['emoji']} <b>{name}</b> ({w['rarity']}) — {w['price']}💠{marker}\n"
                f"   <i>{w['desc']}</i>\n"
                f"   +{w['dmg_bonus_min']}–{w['dmg_bonus_max']} урона, x{w['tech_power']} техник, +{int(w['crit_bonus']*100)}% крит"
            )
        await render(query, context, "\n".join(lines), gear_buy_list_keyboard(user_id))

    elif data.startswith("gear_buy:"):
        idx = int(data.split(":", 1)[1])
        weapons = equipment.list_purchasable()
        if idx < 0 or idx >= len(weapons):
            text = "❌ Оружие недоступно."
            await render(query, context, text, gear_buy_list_keyboard(user_id))
            return
        name, w = weapons[idx]
        result = equipment.buy(user_id, name)
        prefix = "✅ " if result["ok"] else "❌ "
        player_now = database.get_or_create_player(user_id, "")
        text = prefix + result["msg"] + f"\n\n💠 У тебя: {player_now['gold']}"
        await render(query, context, text, gear_buy_list_keyboard(user_id))

    elif data == "gear_craft_list":
        lines = ["🔨 <b>Крафт оружия</b>\n",
                 "<i>Собери конкретные трофеи нужных проклятий и возвращайся.</i>\n"]
        for name, w in equipment.list_craftable():
            recipe = equipment.RECIPES[name]
            mats = ", ".join(f"{item} ×{q}" for item, q in recipe["materials"].items())
            owned = database.has_weapon(user_id, name)
            marker = " ✅" if owned else ""
            lines.append(
                f"{w['emoji']} <b>{name}</b> ({w['rarity']}){marker}\n"
                f"   <i>{w['desc']}</i>\n"
                f"   +{w['dmg_bonus_min']}–{w['dmg_bonus_max']} урона, x{w['tech_power']} техник, +{int(w['crit_bonus']*100)}% крит\n"
                f"   Материалы: {mats} + {recipe['gold']}💠"
            )
        await render(query, context, "\n".join(lines), gear_craft_list_keyboard())

    elif data.startswith("gear_craft:"):
        idx = int(data.split(":", 1)[1])
        weapons = equipment.list_craftable()
        if idx < 0 or idx >= len(weapons):
            text = "❌ Оружие недоступно."
            await render(query, context, text, gear_craft_list_keyboard())
            return
        name, w = weapons[idx]
        check = equipment.check_recipe(user_id, name)
        if not check["ok"]:
            miss = "\n".join("  • " + m for m in check["missing"])
            text = (f"❌ Не хватает ресурсов для <b>{name}</b>:\n{miss}")
            await render(query, context, text, gear_craft_list_keyboard())
            return
        result = equipment.craft(user_id, name)
        prefix = "✅ " if result["ok"] else "❌ "
        text = prefix + result["msg"]
        await render(query, context, text, gear_craft_list_keyboard())

    elif data == "gear_owned":
        owned = database.get_player_weapons(user_id)
        if not owned:
            text = "⚔️ У тебя пока нет оружия. Купи слабое или скрафти из трофеев."
        else:
            lines = ["⚔️ <b>Твоё оружие</b>\n"]
            equipped_name = database.get_equipped_weapon_name(user_id)
            for name in owned:
                w = equipment.get_weapon(name)
                if not w:
                    continue
                marker = " 🎯 (экипировано)" if name == equipped_name else ""
                lines.append(f"{w['emoji']} <b>{name}</b> ({w['rarity']}){marker}")
            text = "\n".join(lines)
        await render(query, context, text, gear_owned_keyboard(user_id))

    elif data.startswith("gear_equip:"):
        idx_str = data.split(":", 1)[1]
        try:
            idx = int(idx_str)
        except ValueError:
            idx = -1
        owned = database.get_player_weapons(user_id)
        if idx < 0 or idx >= len(owned):
            text = "❌ Оружие недоступно. Открой меню заново."
            await render(query, context, text, gear_owned_keyboard(user_id))
            return
        name = owned[idx]
        result = equipment.equip(user_id, name)
        prefix = "✅ " if result["ok"] else "❌ "
        text = prefix + result["msg"]
        await render(query, context, text, gear_owned_keyboard(user_id))

    elif data == "gear_unequip":
        result = equipment.unequip(user_id)
        prefix = "✅ " if result["ok"] else "❌ "
        text = prefix + result["msg"]
        await render(query, context, text, gear_owned_keyboard(user_id))

    # ================= НАЗАД / NOOP =================

    elif data == "back_to_game":
        if context.user_data.pop("prev_screen", None) == "profile":
            await render(query, context, profile_text(user_id), profile_menu_keyboard(user_id))
            return

        r = raid.get_active_raid_for_user(user_id)
        if r:
            await _render_raid_screen(query, context, r["id"], user_id)
            return

        encounter = database.get_encounter(user_id)
        if encounter:
            fresh_player = database.get_or_create_player(user_id, "")
            text = (combat.encounter_status_text(encounter) + "\n\n"
                    + combat.player_status_text(fresh_player, user_id))
            image_path = assets.get_monster_image(encounter["monster_name"])
            await render(query, context, text, kb_for(user_id), image_path=image_path)
        else:
            text = location_text(user_id, x)
            await render(query, context, text, kb_for(user_id),
                         image_path=district_image_for_x(x))

    elif data == "noop":
        return


# ---------------------- Планировщик ----------------------

async def delete_message_job(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data or {}
    chat_id = data.get("chat_id")
    message_id = data.get("message_id")
    if not chat_id or not message_id:
        return
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as e:
        logger.info(f"Не удалось удалить сообщение {message_id}: {e}")


async def spawn_job(context: ContextTypes.DEFAULT_TYPE):
    spawned = monsters.spawn_tick_for_all_players()
    for user_id, monster, district in spawned:
        curse_class = monster.get("curse_class", "")
        if curse_class == "Особый класс":
            header = "⛔ <b>ОСОБОЕ ПРОКЛЯТИЕ</b> появилось"
        elif curse_class == "1-й класс":
            header = "⚠️ <b>Проклятие 1-го ранга</b> появилось"
        else:
            header = "👀 <b>Проклятие</b> замечено"

        text = (
            f"{header} в локации: "
            f"{district['emoji']} <b>{district['name']}</b>\n\n"
            f"Нажми «🩸 Патрулирование», чтобы найти его."
        )
        try:
            msg = await context.bot.send_message(chat_id=user_id, text=text, parse_mode="HTML")
            context.job_queue.run_once(
                delete_message_job,
                when=SPAWN_NOTIFY_TTL_SECONDS,
                data={"chat_id": user_id, "message_id": msg.message_id},
                name=f"del_spawn_{user_id}_{msg.message_id}",
            )
        except Exception as e:
            logger.warning(f"Не удалось уведомить {user_id}: {e}")


async def clear_buffs_job(context: ContextTypes.DEFAULT_TYPE):
    removed = database.clear_expired_buffs()
    if removed:
        logger.info(f"Очищено истёкших баффов: {removed}")


# ---------------------- Миграции ----------------------

def migrate_curse_seals():
    conn = database.get_conn()
    cur = conn.cursor()
    total = 0
    for seal_name in bosses.SUMMON_RECIPES.keys():
        cur.execute(
            "UPDATE inventory SET rarity = 'призыв' WHERE item_name = ? AND rarity != 'призыв'",
            (seal_name,),
        )
        total += cur.rowcount
    conn.commit()
    if total > 0:
        logger.info(f"Миграция печатей: исправлено {total} записей")


# ---------------------- Точка входа ----------------------

def main():
    from health import start_health_server
    start_health_server()

    database.init_db()
    rest._ensure_column()

    try:
        raid._ensure_tables()
    except Exception as e:
        logger.warning(f"Не удалось подготовить таблицы рейда: {e}")
    try:
        story._ensure_table()
    except Exception as e:
        logger.warning(f"Не удалось подготовить таблицу сюжета: {e}")

    migrate_curse_seals()

    app = Application.builder().token(config.BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("map", map_command))
    app.add_handler(CommandHandler("inventory", inventory_command))
    app.add_handler(PreCheckoutQueryHandler(precheckout_handler))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_handler))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler))

    app.job_queue.run_repeating(
        spawn_job,
        interval=

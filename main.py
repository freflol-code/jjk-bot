"""
Магическая Битва: Токио — RPG-бот для Telegram по мотивам Jujutsu Kaisen.
"""
import logging

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
)
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

import assets
import config
import database
import monsters
import combat
import gacha
import consumables
import bosses
import shop
import quests
import rest
import equipment
import leaderboard
import story
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


# ---------------------- Клавиатуры ----------------------

def main_keyboard(user_id: int):
    in_combat = database.get_encounter(user_id) is not None
    player = database.get_or_create_player(user_id, "")
    npc = shop.npc_at(player["x"])
    district = get_district_by_x(player["x"])

    if in_combat:
        rows = [[InlineKeyboardButton("⚔️ Обычная атака", callback_data="attack")]]
        for name in gacha.get_equipped(user_id):
            t = gacha.get_technique(name)
            if t:
                rows.append([InlineKeyboardButton(
                    f"{t['emoji']} {name} ({t['ce_cost']}🔵)", callback_data=f"tech:{name}",
                )])
        rows.append([
            InlineKeyboardButton("🏃 Сбежать", callback_data="flee"),
            InlineKeyboardButton("🎒 Инвентарь", callback_data="inventory"),
        ])
        rows.append([InlineKeyboardButton("🗺 Карта", callback_data="map")])
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
    equipped = set(gacha.get_equipped(user_id))
    rows = []
    for row in learned:
        name = row["technique_name"]
        t = gacha.get_technique(name)
        emoji = t["emoji"] if t else "❔"
        rarity_em = config.GACHA_RARITY_EMOJI.get(t["rarity"], "") if t else ""
        if name in equipped:
            rows.append([InlineKeyboardButton(
                f"✅ {rarity_em} {emoji} {name} (снять)",
                callback_data=f"gacha_unequip:{name}",
            )])
        else:
            rows.append([InlineKeyboardButton(
                f"{rarity_em} {emoji} {name} (взять в бой)",
                callback_data=f"gacha_equip:{name}",
            )])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="gacha_back_to_menu")])
    return InlineKeyboardMarkup(rows)


def inventory_keyboard(user_id: int):
    items = database.get_inventory(user_id)
    rows = []
    for i in items:
        is_seal = i["rarity"] == "призыв" or i["item_name"] in bosses.SUMMON_RECIPES
        if i["rarity"] == "расходник":
            rows.append([InlineKeyboardButton(
                f"🧪 Использовать: {i['item_name']} x{i['quantity']}",
                callback_data=f"use_item:{i['item_name']}",
            )])
        elif is_seal:
            rows.append([InlineKeyboardButton(
                f"⚡ Призвать: {i['item_name']} x{i['quantity']}",
                callback_data=f"summon_item:{i['item_name']}",
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
        [InlineKeyboardButton("🌀 Гача техник", callback_data="gacha_menu_from_shop")],
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
    chapter = story.get_current_chapter(user_id)
    rows = []
    if chapter:
        prog = story.get_progress(user_id)
        first_step_done = False
        for i, step in enumerate(chapter["steps"]):
            if step["type"] == "kill":
                first_step_done = prog.get(str(i), 0) >= step["goal"]
                break
        boss_pending = any(
            step["type"] == "kill_boss" and prog.get(str(i), 0) < step["goal"]
            for i, step in enumerate(chapter["steps"])
        )
        if first_step_done and boss_pending:
            rows.append([InlineKeyboardButton(
                "👁 Войти в подвал (босс)", callback_data="story_temp_boss",
            )])
    rows.append([InlineKeyboardButton("🩸 Патрулирование", callback_data="story_temp_patrol")])
    rows.append([InlineKeyboardButton("⬅️ Вернуться в школу", callback_data="story_exit_temp")])
    return InlineKeyboardMarkup(rows)


def profile_menu_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎒 Инвентарь", callback_data="profile_inventory"),
            InlineKeyboardButton("🌀 Техники", callback_data="profile_techniques"),
        ],
        [InlineKeyboardButton("🏆 Таблица лидеров", callback_data="profile_leaderboard")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_game")],
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
        weapon_line = f"\n⚔️ Оружие: {w['emoji']} <b>{w['name']}</b>"

    buffs_line = ""
    buffs = format_active_buffs(user_id)
    if buffs:
        buffs_line = f"\n✨ Баффы: {buffs}"

    safe_line = ""
    if district.get("safe"):
        safe_line = "\n🛡 <i>Безопасная зона — проклятия сюда не заходят.</i>"

    story_hint = ""
    if district["id"] == "jujutsu_high":
        msg = story.get_school_message(user_id)
        if msg:
            story_hint = f"\n\n{msg}"

    return (
        f"{district['emoji']} <b>{district['name']}</b>\n"
        f"<i>{district['description']}</i>\n\n"
        f"📍 Координата: {x}\n"
        f"💠 Очки Ассоциации: {player['gold']} | ❤️ HP: {player['hp']}/{player['max_hp']} | "
        f"🔵 ПЭ: {player['ce']}/{player['max_ce']}\n"
        f"🧬 Уровень: {player['level']} | 🎚 Контроль ПЭ: {player['ce_control']}"
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
    eq_lines = []
    for name in equipped:
        t = gacha.get_technique(name)
        if t:
            eq_lines.append(f"  {t['emoji']} <b>{name}</b> — {t['ce_cost']}🔵, {t['dmg_min']}-{t['dmg_max']} урона")
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
        "<i>Хакари: «Ставки честные. Ну, почти.»</i>"
    )


def profile_text(user_id: int) -> str:
    player = database.get_or_create_player(user_id, "")
    need = player["level"] * config.EXP_BASE

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

    learned = database.get_player_techniques(user_id)
    equipped_tech = gacha.get_equipped(user_id)
    weapons_owned = database.get_player_weapons(user_id)

    return (
        "👤 <b>Профиль шамана</b>\n\n"
        f"🧬 Уровень: <b>{player['level']}</b> ({player['exp']}/{need})\n"
        f"🎚 Контроль ПЭ: <b>{player['ce_control']}</b>\n"
        f"❤️ HP: {player['hp']}/{player['max_hp']}\n"
        f"🔵 ПЭ: {player['ce']}/{player['max_ce']}\n"
        f"💠 Очки Ассоциации: {player['gold']}\n\n"
        f"{weapon_line}\n"
        f"🌀 Техник изучено: {len(learned)} · в бою: {len(equipped_tech)}/{config.MAX_EQUIPPED_TECHNIQUES}\n"
        f"⚔️ Оружия в коллекции: {len(weapons_owned)}"
        f"{rank_line}"
        f"{buffs_line}"
    )


def _quests_done_text(done: list[dict]) -> str:
    if not done:
        return ""
    lines = ["\n\n📋 <b>Задание Годжо выполнено:</b>"]
    for q in done:
        lines.append(f"  {q['emoji']} {q['name']} — забери награду во вкладке «Задания»")
    return "\n".join(lines)


# ---------------------- Команды ----------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    database.get_or_create_player(user.id, user.username or user.first_name)
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


# ---------------------- Кнопки ----------------------

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    player = database.get_or_create_player(user_id, query.from_user.username or query.from_user.first_name)
    x = player["x"]

    if (-10 <= x <= 10) and not story.is_in_temp(user_id) and not database.get_encounter(user_id):
        event = story.check_and_finish(user_id)
        if event:
            text = story.format_completion(
                event["completed_chapter"],
                event["reward_gold"], event["reward_exp"],
                event["leveled"], event["new_level"],
            )
            if event["next_chapter"]:
                text += "\n\n" + story.format_intro(event["next_chapter"])
            else:
                text += "\n\n🏁 <b>Все доступные главы пройдены.</b>"
            await render(query, context, text, kb_for(user_id),
                         image_path=district_image_for_x(x))
            return

    data = query.data
    done: list[dict] = []

    # ---------- Движение ----------
    if data in ("move_left", "move_right"):
        step = -config.MOVE_STEP if data == "move_left" else config.MOVE_STEP
        raw_new_x = x + step
        lvl_min, lvl_max = config.get_world_bounds(player["level"])

        if raw_new_x < lvl_min or raw_new_x > lvl_max:
            needed_level = player["level"] + 1
            while needed_level <= 6:
                nb_min, nb_max = config.get_world_bounds(needed_level)
                if nb_min <= raw_new_x <= nb_max:
                    break
                needed_level += 1

            if -config.MAX_WORLD <= raw_new_x <= config.MAX_WORLD and needed_level <= 6:
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

    # ---------- Отдых ----------
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

    # ---------- Патруль ----------
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
                    + combat.player_status_text(player)
                    + _quests_done_text(done))
            image_path = assets.get_monster_image(encounter["monster_name"])
            await render(query, context, text, kb_for(user_id), image_path=image_path)
            await send_effect_gif(context, query.message.chat_id, "encounter_start", ttl=2)

    # ---------- Бой ----------
    elif data in ("attack", "flee") or data.startswith("tech:"):
        if data == "attack":
            result = combat.attack(user_id)
        elif data == "flee":
            result = combat.flee(user_id)
        else:
            technique_name = data.split(":", 1)[1]
            result = combat.attack(user_id, technique_name=technique_name)

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
                    + combat.player_status_text(database.get_or_create_player(user_id, "")))
            image_path = assets.get_monster_image(encounter["monster_name"])
            await render(query, context, text, kb_for(user_id), image_path=image_path)
            return

        fresh_player = database.get_or_create_player(user_id, "")
        encounter = database.get_encounter(user_id)

        if encounter and result["status"] == "ongoing":
            text = (combat.encounter_status_text(encounter) + "\n\n" + log_text + "\n\n"
                    + combat.player_status_text(fresh_player))
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

    # ---------- Инвентарь ----------
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
        item_name = data.split(":", 1)[1]
        result = consumables.use(user_id, item_name)
        prefix = "✅ " if result["ok"] else "❌ "

        encounter = database.get_encounter(user_id)
        if encounter:
            fresh_player = database.get_or_create_player(user_id, "")
            text = (combat.encounter_status_text(encounter) + "\n\n"
                    + prefix + result["msg"] + "\n\n"
                    + combat.player_status_text(fresh_player))
            image_path = assets.get_monster_image(encounter["monster_name"])
            await render(query, context, text, kb_for(user_id), image_path=image_path)
        else:
            items = database.get_inventory(user_id)
            pretty = []
            for i in items:
                if i["rarity"] == "расходник":
                    pretty.append(f"🧪 {i['item_name']} x{i['quantity']} (расходник)")
                elif i["rarity"] == "призыв" or i["item_name"] in bosses.SUMMON_RECIPES:
                    pretty.append(f"⚡ {i['item_name']} x{i['quantity']} (ритуальная печать)")
                else:
                    pretty.append(format_loot_line({"name": i["item_name"], "rarity": i["rarity"]}, i["quantity"]))
            body = prefix + result["msg"] + "\n\n🎒 <b>Инвентарь</b>\n\n" + ("\n".join(pretty) if pretty else "пусто")
            await render(query, context, body, inventory_keyboard(user_id))

    elif data.startswith("summon_item:"):
        item_name = data.split(":", 1)[1]
        result = bosses.summon(user_id, item_name, x)
        if not result["ok"]:
            text = "❌ " + result["msg"] + "\n\n" + location_text(user_id, x)
            await render(query, context, text, kb_for(user_id), image_path=district_image_for_x(x))
            return
        encounter = database.get_encounter(user_id)
        fresh_player = database.get_or_create_player(user_id, "")
        text = (result["msg"] + "\n\n"
                + combat.encounter_status_text(encounter) + "\n\n"
                + combat.player_status_text(fresh_player))
        image_path = assets.get_monster_image(encounter["monster_name"])
        await render(query, context, text, kb_for(user_id), image_path=image_path)
        await send_effect_gif(context, query.message.chat_id, "encounter_start", ttl=2)

    # ---------- Карта ----------
    elif data == "map":
        text = "🗺 <b>Карта районов Токио</b>\n\n" + get_world_map_text(x)
        await render(query, context, text, kb_for(user_id))

    # ---------- Сюжет ----------
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
        text = (
            f"{temp['emoji']} <b>{temp['name']}</b>\n"
            f"<i>{temp['description']}</i>\n\n"
            "🩸 Патрулируй или зайди в подвал, если готов."
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
            )
            if event["next_chapter"]:
                text += "\n\n" + story.format_intro(event["next_chapter"])
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
        encounter = database.get_encounter(user_id)
        text = ("⚔️ <b>Бой начался!</b>\n\n"
                + combat.encounter_status_text(encounter) + "\n\n"
                + combat.player_status_text(player))
        image_path = assets.get_monster_image(encounter["monster_name"])
        await render(query, context, text, kb_for(user_id), image_path=image_path)

    elif data == "story_temp_boss":
        chapter = story.get_current_chapter(user_id)
        temp = story.get_temp_district(user_id)
        if not chapter or not temp or "boss" not in temp or not story.is_in_temp(user_id):
            text = "❌ Сейчас нечего делать."
            await render(query, context, text, story_temp_keyboard(user_id))
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
            "drop_item": None,
            "drop_rarity": None,
        }
        database.set_encounter(user_id, temp["id"], monster)
        encounter = database.get_encounter(user_id)
        text = ("👁 <b>Хранитель Пальца пробудился!</b>\n\n"
                + combat.encounter_status_text(encounter) + "\n\n"
                + combat.player_status_text(player))
        image_path = assets.get_monster_image(encounter["monster_name"])
        await render(query, context, text, kb_for(user_id), image_path=image_path)

    # ---------- Профиль ----------
    elif data == "profile_menu":
        await render(query, context, profile_text(user_id), profile_menu_keyboard(user_id))

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

    # ---------- Доска лидеров ----------
    elif data == "leaderboard":
        text = leaderboard.format_leaderboard(user_id, limit=10)
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Обновить", callback_data="leaderboard")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_game")],
        ])
        await render(query, context, text, keyboard)

    # ---------- Задания ----------
    elif data == "quests_menu":
        text = (
            "📋 <b>Задания Годжо</b>\n\n"
            "Годжо выдаёт 3 ежедневных и 3 недельных задания.\n"
            "Прогресс считается автоматически, награду нужно забрать вручную.\n\n"
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

    # ---------- Гача ----------
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
            npc_id = "hakari"
            npc = shop.get_npc(npc_id)
            text = f"{npc['emoji']} <b>{npc['name']}</b>\n\n<i>{npc['greeting']}</i>"
            image_path = assets.get_npc_image(npc_id)
            await render(query, context, text, shop_menu_keyboard(npc_id),
                         image_path=image_path)
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
                tag = " (дубликат, компенсация)" if r["duplicate"] else " ✨НОВОЕ✨"
                lines.append(f"{r['emoji']} {r['name']} {emoji}({r['rarity']}){tag}")
            text = "\n".join(lines) + "\n\n" + gacha_menu_text(user_id)
        image_path = assets.get_npc_image("hakari_shop") if context.user_data.get("gacha_from") == "shop" else None
        await render(query, context, text, gacha_menu_keyboard(), image_path=image_path)

    elif data.startswith("gacha_equip:"):
        name = data.split(":", 1)[1]
        result = gacha.equip(user_id, name)
        text = ("✅ " if result["ok"] else "❌ ") + result["msg"] + "\n\n" + gacha_menu_text(user_id)
        image_path = assets.get_npc_image("hakari_shop") if context.user_data.get("gacha_from") == "shop" else None
        await render(query, context, text, gacha_list_keyboard(user_id), image_path=image_path)

    elif data.startswith("gacha_unequip:"):
        name = data.split(":", 1)[1]
        result = gacha.unequip(user_id, name)
        text = ("✅ " if result["ok"] else "❌ ") + result["msg"] + "\n\n" + gacha_menu_text(user_id)
        image_path = assets.get_npc_image("hakari_shop") if context.user_data.get("gacha_from") == "shop" else None
        await render(query, context, text, gacha_list_keyboard(user_id), image_path=image_path)

    # ---------- НПС ----------
    elif data.startswith("npc:"):
        npc_id = data.split(":", 1)[1]
        npc = shop.get_npc(npc_id)
        if not npc:
            await render(query, context, "НПС не найден.", kb_for(user_id))
            return
        text = f"{npc['emoji']} <b>{npc['name']}</b>\n\n<i>{npc['greeting']}</i>"
        image_path = assets.get_npc_image(npc_id)
        await render(query, context, text, shop_menu_keyboard(npc_id), image_path=image_path)

    # ---------- Расходники ----------
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

    # ---------- Склад проклятого оружия ----------
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

    # ---------- Назад ----------
    elif data == "back_to_game":
        if context.user_data.pop("prev_screen", None) == "profile":
            await render(query, context, profile_text(user_id), profile_menu_keyboard(user_id))
            return

        encounter = database.get_encounter(user_id)
        if encounter:
            fresh_player = database.get_or_create_player(user_id, "")
            text = (combat.encounter_status_text(encounter) + "\n\n"
                    + combat.player_status_text(fresh_player))
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
    """Одноразовая миграция: печати должны иметь rarity='призыв'.
    Раньше они дропались с rarity='эпический' из-за CLASS_TO_DROP_RARITY,
    и у игроков не появлялась кнопка «Призвать». Исправляем уже выданные."""
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
    # Health-сервер для Back4App / Render (иначе деплой падает — они ждут TCP-порт)
    from health import start_health_server
    start_health_server()

    database.init_db()
    rest._ensure_column()
    migrate_curse_seals()

    app = Application.builder().token(config.BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("map", map_command))
    app.add_handler(CommandHandler("inventory", inventory_command))
    app.add_handler(CallbackQueryHandler(button_handler))

    app.job_queue.run_repeating(
        spawn_job,
        interval=config.SPAWN_INTERVAL_SECONDS,
        first=config.SPAWN_INTERVAL_SECONDS,
    )
    app.job_queue.run_repeating(
        clear_buffs_job,
        interval=BUFF_CLEANUP_INTERVAL,
        first=BUFF_CLEANUP_INTERVAL,
    )

    logger.info("Бот запущен")
    app.run_polling()


if __name__ == "__main__":
    main()

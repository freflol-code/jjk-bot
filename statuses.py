"""
statuses.py — косметические статусы профиля (аналог скинов в Fortnite).

Покупаются за 50 ⭐ ИЛИ за большое количество 💠 (очки Ассоциации).
Боевых бонусов НЕ дают — только визуальный оттиск рядом с ником
в профиле, на доске лидеров и в рейдах.

Стилизация — через юникод-буквы разных начертаний + декоративные
символы. Telegram не поддерживает цветной текст в bot-сообщениях,
поэтому «цвета» — это визуальные эмодзи-обёртки и разные начертания.

Все декорации — только префикс перед ником. Суффикс (💎) — отдельно,
им управляет VIP-логика. И статус, и значок можно скрыть, не теряя их.
"""
import database


STATUSES = {
    "novice": {
        "emoji": "🔰",
        "styled": "⟪ ɴᴏᴠɪᴄᴇ ⟫",
        "star_price": 50,
        "gold_price": 50_000,
        "desc": "Для тех, кто только начал — но уже хочет выделиться.",
    },
    "shadow": {
        "emoji": "🌑",
        "styled": "⟨ 𝓢𝓱𝓪𝓭𝓸𝔀 ⟩",
        "star_price": 50,
        "gold_price": 100_000,
        "desc": "Тень, которая всегда рядом.",
    },
    "cursed": {
        "emoji": "💀",
        "styled": "† ＣＵＲＳＥＤ †",
        "star_price": 50,
        "gold_price": 250_000,
        "desc": "Проклятие в твоём имени.",
    },
    "sorcerer": {
        "emoji": "🔮",
        "styled": "✦ 𝕾𝖔𝖗𝖈𝖊𝖗𝖊𝖗 ✦",
        "star_price": 50,
        "gold_price": 500_000,
        "desc": "Настоящий маг, не мальчик на побегушках.",
    },
    "grinder": {
        "emoji": "⚒",
        "styled": "⚒ 𝗚𝗿𝗶𝗻𝗱𝗲𝗿 ⚒",
        "star_price": 50,
        "gold_price": 1_000_000,
        "desc": "Ты не спишь — ты фармишь.",
    },
    "veteran": {
        "emoji": "🎖",
        "styled": "⌬ ᴠᴇᴛᴇʀᴀɴ ⌬",
        "star_price": 50,
        "gold_price": 2_000_000,
        "desc": "Прошёл через многое и выжил.",
    },
    "monarch": {
        "emoji": "♛",
        "styled": "♛ 𝔐𝔬𝔫𝔞𝔯𝔠𝔥 ♛",
        "star_price": 50,
        "gold_price": 5_000_000,
        "desc": "Монарх проклятий.",
    },
    "godslayer": {
        "emoji": "⚡",
        "styled": "⚡ 𝕲𝖔𝖉𝖘𝖑𝖆𝖞𝖊𝖗 ⚡",
        "star_price": 50,
        "gold_price": 10_000_000,
        "desc": "Тот, кто убивает богов.",
    },
    "king": {
        "emoji": "👑",
        "styled": "『 𝕶𝖎𝖓𝖌 』",
        "star_price": 50,
        "gold_price": 25_000_000,
        "desc": "Король. Без уточнений.",
    },
    "damned": {
        "emoji": "☠",
        "styled": "☠ 𝕯𝖆𝖒𝖓𝖊𝖉 ☠",
        "star_price": 50,
        "gold_price": 50_000_000,
        "desc": "Проклятый навеки.",
    },
    "absolute": {
        "emoji": "🌌",
        "styled": "◈ 𝓐𝓫𝓼𝓸𝓵𝓾𝓽𝓮 ◈",
        "star_price": 50,
        "gold_price": 100_000_000,
        "desc": "Абсолютная сила. Абсолютный статус.",
    },
    "void": {
        "emoji": "⟁",
        "styled": "⧉ ᴠᴏɪᴅ ⧉",
        "star_price": 50,
        "gold_price": 250_000_000,
        "desc": "Пустота. Предел. То, за чем ничего нет.",
    },
}

STATUS_ORDER = list(STATUSES.keys())


def _fmt_gold(n):
    if n >= 1_000_000:
        return f"{n // 1_000_000}кк"
    if n >= 1_000:
        return f"{n // 1_000}к"
    return str(n)


def _fmt_spaced(n):
    return f"{n:,}".replace(",", " ")


def _is_badge_visible(user_id):
    """💎 показывается, если VIP активен И игрок не скрыл значок."""
    if not database.has_vip(user_id):
        return False
    return not database.is_vip_badge_hidden(user_id)


def get_prefix(user_id):
    """Декоративный префикс статуса или пустая строка."""
    key = database.get_active_status(user_id)
    if key and key in STATUSES:
        return f"{STATUSES[key]['styled']} "
    return ""


def get_suffix(user_id):
    """💎 рядом с ником — если VIP активен и значок не скрыт."""
    return " 💎" if _is_badge_visible(user_id) else ""


def decorate_name(user_id, name):
    """Полное имя с префиксом статуса и суффиксом 💎."""
    return f"{get_prefix(user_id)}{name}{get_suffix(user_id)}"


def format_profile_header(user_id):
    """Заголовок профиля: статус + 💎, если они есть и не скрыты."""
    key = database.get_active_status(user_id)
    badge = get_suffix(user_id)
    if key and key in STATUSES:
        return f"👤 <b>Профиль</b>\n\n{STATUSES[key]['styled']}{badge}"
    return f"👤 <b>Профиль шамана</b>{badge}"


def buy_with_gold(user_id, key):
    if key not in STATUSES:
        return {"ok": False, "msg": "Такого статуса не существует."}
    if database.has_player_status(user_id, key):
        return {"ok": False, "msg": "У тебя уже есть этот статус."}
    st = STATUSES[key]
    player = database.get_or_create_player(user_id, "")
    if player["gold"] < st["gold_price"]:
        return {"ok": False, "msg": (
            f"❌ Не хватает очков. Нужно <b>{_fmt_spaced(st['gold_price'])}💠</b>, "
            f"у тебя <b>{_fmt_spaced(player['gold'])}💠</b>."
        )}
    database.add_gold(user_id, -st["gold_price"])
    database.add_player_status(user_id, key)
    database.set_active_status(user_id, key)
    return {"ok": True, "msg": (
        f"✅ Статус куплен и надет!\n\n"
        f"{st['styled']}\n\n"
        f"<i>{st['desc']}</i>"
    )}


def grant_from_stars(user_id, key):
    """Выдать статус после оплаты Stars. Если уже был — просто переключаем."""
    if key not in STATUSES:
        return {"ok": False, "msg": "Такого статуса не существует."}
    st = STATUSES[key]
    is_new = database.add_player_status(user_id, key)
    database.set_active_status(user_id, key)
    if is_new:
        return {"ok": True, "msg": (
            f"💎 <b>Статус активирован!</b>\n\n"
            f"{st['styled']}\n\n"
            f"<i>{st['desc']}</i>"
        )}
    return {"ok": True, "msg": (
        f"💎 <b>Статус снова надет.</b>\n\n"
        f"{st['styled']}\n\n"
        f"<i>Он уже был у тебя — оплата пошла в поддержку бота, спасибо!</i>"
    )}


def set_status(user_id, key):
    """Надеть купленный статус."""
    if key not in STATUSES:
        return {"ok": False, "msg": "Статус не найден."}
    if not database.has_player_status(user_id, key):
        return {"ok": False, "msg": "Этот статус ещё не куплен."}
    database.set_active_status(user_id, key)
    return {"ok": True, "msg": f"✅ Надет статус: {STATUSES[key]['styled']}"}


def clear_status(user_id):
    """Снять статус (покупка остаётся)."""
    current = database.get_active_status(user_id)
    if not current:
        return {"ok": False, "msg": "У тебя и так нет активного статуса."}
    database.clear_active_status(user_id)
    return {"ok": True, "msg": "✅ Статус снят. Купленное сохранено — можно надеть обратно."}


def toggle_vip_badge(user_id):
    """Скрыть/показать значок 💎. Покупка VIP не теряется."""
    if not database.has_vip(user_id):
        return {"ok": False, "msg": "У тебя нет активного VIP."}
    new_hidden = database.toggle_vip_badge(user_id)
    if new_hidden:
        return {"ok": True, "msg": "🙈 Значок 💎 скрыт. VIP продолжает работать."}
    return {"ok": True, "msg": "✅ Значок 💎 снова виден."}


def format_list(user_id):
    player = database.get_or_create_player(user_id, "")
    owned = database.get_player_statuses(user_id)
    active = database.get_active_status(user_id)
    badge_hidden = database.is_vip_badge_hidden(user_id)
    has_vip = database.has_vip(user_id)

    lines = [
        "🎭 <b>Статусы профиля</b>",
        "",
        "<i>Косметика. Никаких бонусов к статам — только стиль, "
        "как скины в Fortnite.</i>",
        "",
        f"💠 У тебя: <b>{_fmt_spaced(player['gold'])}</b>",
        f"📖 Открыто: <b>{len(owned)}/{len(STATUSES)}</b>",
    ]
    if active and active in STATUSES:
        lines.append(f"🎯 Сейчас надет: {STATUSES[active]['styled']}")
    else:
        lines.append("🎯 Сейчас надет: <i>— пусто —</i>")

    if has_vip:
        badge_state = "скрыт 🙈" if badge_hidden else "виден ✅"
        lines.append(f"💎 Значок VIP: <b>{badge_state}</b>")

    lines.append("")
    lines.append("<i>Нажми на статус, чтобы посмотреть детали.</i>")
    return "\n".join(lines)


def format_detail(user_id, key):
    st = STATUSES.get(key)
    if not st:
        return "❌ Статус не найден."
    owned = database.has_player_status(user_id, key)
    active = database.get_active_status(user_id) == key
    lines = [
        "🎭 <b>Статус:</b>",
        "",
        f"{st['styled']}",
        "",
        f"<i>{st['desc']}</i>",
        "",
    ]
    if active:
        lines.append("✅ <b>Сейчас надет</b>")
    elif owned:
        lines.append("📖 <b>Уже куплен</b> — можно надеть")
    else:
        lines.append(f"💰 Цена: <b>50⭐</b> или <b>{_fmt_spaced(st['gold_price'])}💠</b>")
    return "\n".join(lines)
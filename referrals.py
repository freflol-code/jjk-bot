"""
referrals.py — реферальная система.

За каждого приглашённого друга реферер получает:
- +3 дня VIP
- +1000 💠 очков Ассоциации

Правила:
- Ссылка: https://t.me/<bot_username>?start=ref_<user_id>
- Награда выдаётся ТОЛЬКО если приглашённый — новый игрок
  (не было записи в таблице players до перехода по ссылке)
- Один игрок может быть приглашён только один раз
- Пригласить самого себя нельзя
- Реферер должен существовать в БД (иначе реф-ссылка невалидна)

Всё хранится в таблице `referrals` в основной SQLite-базе.
"""
import time

import database


REWARD_VIP_DAYS = 3
REWARD_GOLD = 1000


_db_ready = False


def _ensure_tables():
    global _db_ready
    if _db_ready:
        return
    conn = database.get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            referrer_id INTEGER NOT NULL,
            referred_id INTEGER NOT NULL,
            created_at  INTEGER NOT NULL,
            PRIMARY KEY (referred_id)
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_referrals_referrer "
        "ON referrals (referrer_id)"
    )
    conn.commit()
    _db_ready = True


def _player_exists(user_id):
    conn = database.get_conn()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM players WHERE user_id = ?", (user_id,))
    return cur.fetchone() is not None


def _already_referred(user_id):
    conn = database.get_conn()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM referrals WHERE referred_id = ?", (user_id,))
    return cur.fetchone() is not None


def get_invited_count(user_id):
    """Сколько друзей привёл игрок."""
    _ensure_tables()
    conn = database.get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) AS c FROM referrals WHERE referrer_id = ?",
        (user_id,),
    )
    return cur.fetchone()["c"]


def register_referral(new_user_id, new_username, referrer_id):
    """Регистрирует игрока и, если он новый и реф-код валиден, засчитывает реферал.

    Возвращает dict:
        {"ok": True, "referred": True}   — реферал засчитан, рефереру выдана награда
        {"ok": True, "referred": False, "reason": "..."}   — игрок создан, но реферал не засчитан
        {"ok": False, "reason": "..."}    — что-то не так, игрок не создан (маловероятно)

    ВСЕГДА создаёт/обновляет игрока, даже если реферал не засчитан.
    """
    _ensure_tables()

    was_existing = _player_exists(new_user_id)

    # создаём игрока в любом случае — это заход в бота
    database.get_or_create_player(new_user_id, new_username or "")

    if was_existing:
        return {"ok": True, "referred": False, "reason": "not_new_player"}

    if not referrer_id:
        return {"ok": True, "referred": False, "reason": "no_referrer"}

    if referrer_id == new_user_id:
        return {"ok": True, "referred": False, "reason": "self_referral"}

    if not _player_exists(referrer_id):
        return {"ok": True, "referred": False, "reason": "referrer_not_found"}

    if _already_referred(new_user_id):
        return {"ok": True, "referred": False, "reason": "already_referred"}

    # засчитываем
    conn = database.get_conn()
    conn.execute(
        "INSERT INTO referrals (referrer_id, referred_id, created_at) "
        "VALUES (?, ?, ?)",
        (referrer_id, new_user_id, int(time.time())),
    )
    conn.commit()

    database.add_vip_days(referrer_id, REWARD_VIP_DAYS)
    database.add_gold(referrer_id, REWARD_GOLD)

    return {"ok": True, "referred": True, "referrer_id": referrer_id}


# ============================================================
#  UI
# ============================================================

def _build_link(bot_username, user_id):
    if not bot_username:
        return None
    return f"https://t.me/{bot_username}?start=ref_{user_id}"


def format_menu(user_id, bot_username):
    count = get_invited_count(user_id)
    total_vip = count * REWARD_VIP_DAYS
    total_gold = count * REWARD_GOLD

    link = _build_link(bot_username, user_id) or "(ссылка пока недоступна)"

    lines = [
        "🎁 <b>Реферальная программа</b>",
        "",
        "<b>За каждого друга ты получаешь:</b>",
        f"  💎 <b>{REWARD_VIP_DAYS} дня VIP</b> (×2 золото, опыт, дроп и награды)",
        f"  💠 <b>{REWARD_GOLD} очков Ассоциации</b>",
        "",
        "<i>Друг должен быть новым игроком — кто уже заходил в бота, "
        "по ссылке не засчитается.</i>",
        "",
        f"📊 <b>Уже приглашено:</b> {count}",
    ]
    if count > 0:
        lines.append(f"💰 <b>Всего заработано:</b> {total_vip} дн. VIP · {total_gold}💠")
    lines.append("")
    lines.append("<b>Твоя ссылка:</b>")
    lines.append(f"<code>{link}</code>")
    lines.append("")
    lines.append("<i>Скинь ссылку друзьям. Как только они зайдут — "
                 "награда придёт автоматически.</i>")
    return "\n".join(lines)


def menu_keyboard(user_id, bot_username):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    rows = []
    link = _build_link(bot_username, user_id)
    if link:
        share_text = "Заходи в «Магическую Битву: Токио» — я уже там!"
        share_url = (
            f"https://t.me/share/url?url={link}&text={share_text}"
        )
        rows.append([InlineKeyboardButton("📤 Поделиться", url=share_url)])
    rows.append([InlineKeyboardButton("⬅️ В профиль", callback_data="profile_menu")])
    return InlineKeyboardMarkup(rows)


def format_success_for_referrer(user_id):
    """Короткое сообщение для реферера о новом реферале."""
    return (
        f"🎁 <b>+1 реферал!</b>\n\n"
        f"Тебе начислено:\n"
        f"  💎 +{REWARD_VIP_DAYS} дня VIP\n"
        f"  💠 +{REWARD_GOLD} очков Ассоциации\n\n"
        f"<i>Спасибо, что делишься ботом!</i>"
    )
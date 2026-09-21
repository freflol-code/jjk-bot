"""
boss_rush.py — «Боевой клуб Хакари»: фарм-режим усиленных прошлых боссов.

Открывается после прохождения BOSS_RUSH_UNLOCK_CHAPTER глав сюжета.
Хакари стоит в школе (X=0) и продаёт доступ к «спаррингам» с копиями
боссов, которых игрок уже побеждал в сюжете.

Ключевые отличия от сюжетных боёв:
- Босс усилен: HP ×2, урон ×1.3 (BOSS_RUSH_HP_MULT / DMG_MULT).
- Броня у клубных боссов ВСЕГДА = 0 — их РЕАЛЬНО можно ваншотнуть.
- Награда — 25% от сюжетной (BOSS_RUSH_REWARD_MULT).
- Дропа предметов нет (это тренировка, а не охота).
- Кулдаун между боями — BOSS_RUSH_COOLDOWN секунд.
- Цена входа — BOSS_RUSH_ENTRY_COST 💠.

Технически: все клубные боссы регистрируются в bosses.BOSSES
с префиксом "[Клуб] " в имени. combat.get_effective_boss_defense()
видит префикс и НЕ применяет уровневую защиту — поэтому ваншот реален.
"""
import time

import database
import story
import bosses
from config import (
    BOSS_RUSH_UNLOCK_CHAPTER, BOSS_RUSH_ENTRY_COST, BOSS_RUSH_COOLDOWN,
    BOSS_RUSH_HP_MULT, BOSS_RUSH_DMG_MULT, BOSS_RUSH_REWARD_MULT,
)


CLUB_PREFIX = "[Клуб] "


# ============================================================
#  ПОСТРОЕНИЕ РЕЕСТРА КЛУБНЫХ БОССОВ
# ============================================================

_club_bosses: dict[str, dict] = {}   # full_name -> {chapter_num, base_name, ...}


def _build_club_bosses():
    """Проходит по всем главам сюжета и делает из их боссов клубные версии.
    Клубные версии получают префикс "[Клуб] " и усиленные статы."""
    global _club_bosses
    if _club_bosses:
        return

    for ch in story.CHAPTERS:
        td = ch.get("temp_district") or {}
        boss = td.get("boss")
        if not boss:
            continue

        base_name = boss["name"]
        full_name = CLUB_PREFIX + base_name

        new_hp = int(boss["hp"] * BOSS_RUSH_HP_MULT)
        new_dmg_min = int(boss["dmg_min"] * BOSS_RUSH_DMG_MULT)
        new_dmg_max = int(boss["dmg_max"] * BOSS_RUSH_DMG_MULT)
        new_gold = int(boss.get("reward_gold", 0) * BOSS_RUSH_REWARD_MULT)
        new_exp = int(boss.get("reward_exp", 0) * BOSS_RUSH_REWARD_MULT)

        _club_bosses[full_name] = {
            "full_name": full_name,
            "base_name": base_name,
            "chapter_num": ch["num"],
            "chapter_id": ch["id"],
            "emoji": boss.get("emoji", "👹"),
            "hp": new_hp,
            "dmg_min": new_dmg_min,
            "dmg_max": new_dmg_max,
            "reward_gold": new_gold,
            "reward_exp": new_exp,
        }

    # Регистрируем клубных боссов в bosses.BOSSES, чтобы combat._victory()
    # нашёл их и начислил награду. drop_item не задаём — тренировка без дропа.
    for full_name, b in _club_bosses.items():
        bosses.BOSSES[full_name] = {
            "emoji": b["emoji"],
            "hp": b["hp"],
            "dmg_min": b["dmg_min"],
            "dmg_max": b["dmg_max"],
            "rarity": "Особый класс",
            "reward_gold": b["reward_gold"],
            "reward_exp": b["reward_exp"],
            "drop_item": None,
        }

    # Наследуем боевые пассивки/скиллы от сюжетных боссов.
    # Ключи в story.BOSS_SKILLS совпадают с base_name, поэтому
    # регистрируем под full_name тоже.
    for full_name, b in _club_bosses.items():
        base_skills = story.BOSS_SKILLS.get(b["base_name"])
        if base_skills:
            story.BOSS_SKILLS[full_name] = base_skills


# Регистрируем сразу при импорте — combat.py ждёт записи в BOSSES.
_build_club_bosses()


# ============================================================
#  БД: КУЛДАУНЫ
# ============================================================

_db_ready = False


def _ensure_tables():
    global _db_ready
    if _db_ready:
        return
    conn = database.get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS boss_rush_cooldowns (
            user_id    INTEGER NOT NULL PRIMARY KEY,
            expires_at INTEGER NOT NULL
        )
    """)
    conn.commit()
    _db_ready = True


def _get_cooldown_until(user_id: int) -> int:
    _ensure_tables()
    conn = database.get_conn()
    cur = conn.cursor()
    cur.execute("SELECT expires_at FROM boss_rush_cooldowns WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if not row:
        return 0
    if row["expires_at"] <= int(time.time()):
        conn.execute("DELETE FROM boss_rush_cooldowns WHERE user_id = ?", (user_id,))
        conn.commit()
        return 0
    return row["expires_at"]


def _set_cooldown(user_id: int):
    _ensure_tables()
    expires = int(time.time()) + BOSS_RUSH_COOLDOWN
    conn = database.get_conn()
    conn.execute(
        "INSERT INTO boss_rush_cooldowns (user_id, expires_at) VALUES (?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET expires_at = excluded.expires_at",
        (user_id, expires),
    )
    conn.commit()


def get_cooldown_left(user_id: int) -> int:
    until = _get_cooldown_until(user_id)
    if until <= 0:
        return 0
    return max(0, until - int(time.time()))


def format_cooldown(seconds: int) -> str:
    m, s = divmod(seconds, 60)
    return f"{m}м {s:02d}с" if m else f"{s}с"


# ============================================================
#  ДОСТУП
# ============================================================

def is_unlocked(user_id: int) -> bool:
    """Клуб открывается после прохождения N-й главы сюжета."""
    return story.get_completed_chapters(user_id) >= BOSS_RUSH_UNLOCK_CHAPTER


def get_available_bosses(user_id: int) -> list[dict]:
    """Все боссы из глав, которые игрок уже прошёл.
    Возвращает список словарей с индексом для callback_data."""
    completed = story.get_completed_chapters(user_id)
    result = []
    for full_name, b in _club_bosses.items():
        if b["chapter_num"] <= completed:
            result.append({**b, "index": len(result)})
    return result


def _find_boss_by_index(user_id: int, idx: int) -> dict | None:
    """Ищет босса по его позиции в списке доступных."""
    available = get_available_bosses(user_id)
    if idx < 0 or idx >= len(available):
        return None
    return available[idx]


# ============================================================
#  ЗАПУСК БОЯ
# ============================================================

def start_battle(user_id: int, idx: int) -> dict:
    """Списывает 💠, ставит encounter с клубным боссом, ставит КД."""
    if not is_unlocked(user_id):
        return {
            "ok": False,
            "msg": (
                f"🔒 Клуб откроется после прохождения "
                f"{BOSS_RUSH_UNLOCK_CHAPTER} глав сюжета."
            ),
        }

    if database.get_encounter(user_id):
        return {"ok": False, "msg": "Ты уже в бою! Сначала закончи текущий."}

    if story.is_in_temp(user_id):
        return {"ok": False, "msg": "Сначала покинь сюжетную локацию (⬅️ Вернуться в школу)."}

    cd = get_cooldown_left(user_id)
    if cd > 0:
        return {
            "ok": False,
            "msg": f"⏳ Хакари не даст тебе драться так часто. Отдых: <b>{format_cooldown(cd)}</b>.",
        }

    boss = _find_boss_by_index(user_id, idx)
    if not boss:
        return {"ok": False, "msg": "Этот босс тебе ещё недоступен."}

    player = database.get_or_create_player(user_id, "")
    if player["gold"] < BOSS_RUSH_ENTRY_COST:
        return {
            "ok": False,
            "msg": (
                f"❌ Не хватает 💠 на вход. Нужно <b>{BOSS_RUSH_ENTRY_COST}</b>, "
                f"у тебя <b>{player['gold']}</b>."
            ),
        }

    database.add_gold(user_id, -BOSS_RUSH_ENTRY_COST)

    monster = {
        "name": boss["full_name"],
        "hp": boss["hp"],
        "dmg_min": boss["dmg_min"],
        "dmg_max": boss["dmg_max"],
        "emoji": boss["emoji"],
        "rarity": "Особый класс",
        "curse_class": "Особый класс",
        "drop_item": None,
        "drop_rarity": None,
        # ВАЖНО: defense = 0 → combat.get_effective_boss_defense() уже
        # отсечёт скейл по префиксу "[Клуб] ", но на всякий случай.
        "defense": 0.0,
    }
    database.set_encounter(user_id, "jujutsu_high", monster)
    _set_cooldown(user_id)

    return {
        "ok": True,
        "msg": (
            f"🥊 <b>Боевой клуб Хакари</b>\n\n"
            f"{boss['emoji']} Против тебя выходит <b>{boss['base_name']}</b> "
            f"(клубная версия).\n\n"
            f"<i>Хакари: «Ставка сделана — не облажайся.»</i>"
        ),
        "boss": boss,
    }


# ============================================================
#  UI-ТЕКСТЫ
# ============================================================

def format_menu(user_id: int) -> str:
    """Главный экран клуба."""
    if not is_unlocked(user_id):
        completed = story.get_completed_chapters(user_id)
        return (
            "🥊 <b>Боевой клуб Хакари</b>\n\n"
            f"🔒 <b>Закрыто.</b> Откроется после прохождения "
            f"<b>{BOSS_RUSH_UNLOCK_CHAPTER}</b> глав сюжета.\n"
            f"Сейчас пройдено: <b>{completed}/{BOSS_RUSH_UNLOCK_CHAPTER}</b>.\n\n"
            "<i>Хакари: «Пока не заслужил — иди работай.»</i>"
        )

    player = database.get_or_create_player(user_id, "")
    available = get_available_bosses(user_id)
    cd = get_cooldown_left(user_id)

    lines = [
        "🥊 <b>Боевой клуб Хакари</b>",
        "",
        f"<i>Хакари: «Прошлые боссы? Ерунда. Я сделал их сильнее, "
        f"но оставил без брони — если ты хорош, ваншотнешь.»</i>",
        "",
        f"💠 Вход: <b>{BOSS_RUSH_ENTRY_COST}</b> · "
        f"награда: <b>{int(BOSS_RUSH_REWARD_MULT * 100)}%</b> от сюжетной",
        f"⏱ Кулдаун: <b>{format_cooldown(BOSS_RUSH_COOLDOWN)}</b>",
        f"💠 У тебя: <b>{player['gold']}</b>",
    ]

    if cd > 0:
        lines.append(f"⏳ Следующий бой через: <b>{format_cooldown(cd)}</b>")

    lines.append("")
    lines.append("<b>Доступные противники:</b>")
    if not available:
        lines.append("<i>Пока никого — проходи сюжет.</i>")
    else:
        for b in available:
            lines.append(
                f"  {b['emoji']} <b>{b['base_name']}</b> "
                f"(гл. {b['chapter_num']}) — "
                f"❤️ {b['hp']} · 🗡 {b['dmg_min']}-{b['dmg_max']}"
            )

    return "\n".join(lines)


def format_boss_detail(user_id: int, idx: int) -> str:
    """Карточка одного босса — для экрана подтверждения."""
    boss = _find_boss_by_index(user_id, idx)
    if not boss:
        return "❌ Этот босс тебе недоступен."

    player = database.get_or_create_player(user_id, "")
    cd = get_cooldown_left(user_id)

    lines = [
        f"{boss['emoji']} <b>{boss['base_name']}</b> — клубная версия",
        f"<i>Глава {boss['chapter_num']} сюжета</i>",
        "",
        "⚙️ <b>Характеристики:</b>",
        f"  ❤️ HP: <b>{boss['hp']}</b>",
        f"  🗡 Урон: <b>{boss['dmg_min']}-{boss['dmg_max']}</b>",
        f"  🛡 Броня: <b>0</b> (можно ваншотнуть!)",
        "",
        "🎁 <b>Награда за победу:</b>",
        f"  💠 +{boss['reward_gold']} · 🧬 +{boss['reward_exp']}",
        "",
        f"💠 Вход: <b>{BOSS_RUSH_ENTRY_COST}</b> (у тебя {player['gold']})",
    ]
    if cd > 0:
        lines.append(f"⏳ Кулдаун: <b>{format_cooldown(cd)}</b>")

    return "\n".join(lines)
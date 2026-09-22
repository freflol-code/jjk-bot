"""
boss_rush.py — «Боевой клуб Хакари»: boss rush через всех пройденных боссов.

Формат:
- Игрок платит за вход и бьётся с боссами ПОСЛЕДОВАТЕЛЬНО, один за другим.
- На СТАРТЕ забега HP и ПЭ восстанавливаются один раз.
- МЕЖДУ боями HP и ПЭ НЕ восстанавливаются.
- Использовать расходники во время забега НЕЛЬЗЯ.
- Проиграл → забег закончился, получил накопленное.
- Сбежал → забег закончился, потерял всё.
- Прошёл всех → накопленное + 30% бонусом + легендарный трофей.

Цена входа:
    5000 💠 (первый босс) + 1000 💠 за каждого следующего.
    Пример: 4 босса = 5000 + 1000×3 = 8000.

Награда за каждого убитого босса:
    REWARD_FRACTION × среднее_арифметическое(награды всех боссов забега)
    По умолчанию REWARD_FRACTION = 0.25 (25%).
    Умножается на VIP-множитель, если VIP активен.

Боссы в клубе: HP × 2.0, урон × 1.5, броня = 0.
Против клубных боссов у игрока работает пробитие защиты 40%
(см. combat.CLUB_DEFENSE_PIERCE).
"""
import json
import time

import database
import story
from config import BOSS_RUSH_UNLOCK_CHAPTER


CLUB_PREFIX = "[Клуб] "
BASE_ENTRY = 5000
PER_BOSS_ENTRY = 1000

BOSS_HP_MULT = 2.0
BOSS_DMG_MULT = 1.5

# Доля от среднего арифметического наград всех боссов в забеге.
# 0.25 = 25%. За каждого убитого босса.
REWARD_FRACTION = 0.25

FULL_CLEAR_GOLD_BONUS_MULT = 0.30
FULL_CLEAR_EXP_BONUS_MULT = 0.30
FULL_CLEAR_ITEM_NAME = "Осколок Боевого Клуба"
FULL_CLEAR_ITEM_RARITY = "легендарный"
FULL_CLEAR_ITEM_QTY = 1

RUSH_COOLDOWN_SECONDS = 120


_db_ready = False


def _ensure_tables():
    global _db_ready
    if _db_ready:
        return
    conn = database.get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS boss_rush_runs (
            user_id          INTEGER PRIMARY KEY,
            bosses_json      TEXT    NOT NULL,
            current_idx      INTEGER NOT NULL DEFAULT 0,
            accumulated_gold INTEGER NOT NULL DEFAULT 0,
            accumulated_exp  INTEGER NOT NULL DEFAULT 0,
            bosses_killed    INTEGER NOT NULL DEFAULT 0,
            started_at       INTEGER NOT NULL,
            status           TEXT    NOT NULL DEFAULT 'active'
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS boss_rush_cooldowns (
            user_id    INTEGER PRIMARY KEY,
            expires_at INTEGER NOT NULL
        )
    """)
    conn.commit()
    _db_ready = True


# ============ ДОСТУП И ДАННЫЕ ============

def is_unlocked(user_id):
    return story.get_completed_chapters(user_id) >= BOSS_RUSH_UNLOCK_CHAPTER


def _build_boss_list(user_id):
    completed = story.get_completed_chapters(user_id)
    result = []
    for ch in story.CHAPTERS:
        if ch["num"] > completed:
            continue
        td = ch.get("temp_district") or {}
        boss = td.get("boss")
        if not boss:
            continue
        result.append({
            "chapter_num": ch["num"],
            "chapter_id": ch["id"],
            "base_name": boss["name"],
            "emoji": boss.get("emoji", "👹"),
            "hp": boss["hp"],
            "dmg_min": boss["dmg_min"],
            "dmg_max": boss["dmg_max"],
            "reward_gold": boss.get("reward_gold", 0),
            "reward_exp": boss.get("reward_exp", 0),
        })
    return result


def get_boss_list(user_id):
    return _build_boss_list(user_id)


def entry_cost(user_id):
    n = len(_build_boss_list(user_id))
    if n <= 0:
        return 0
    return BASE_ENTRY + PER_BOSS_ENTRY * (n - 1)


def _avg_rewards(boss_list):
    """Среднее арифметическое награды всех боссов в забеге.
    Возвращает (avg_gold, avg_exp)."""
    if not boss_list:
        return (0, 0)
    n = len(boss_list)
    total_gold = sum(b["reward_gold"] for b in boss_list)
    total_exp = sum(b["reward_exp"] for b in boss_list)
    return (total_gold // n, total_exp // n)


def per_boss_reward(boss_list):
    """Сколько игрок получит за одного босса (без VIP).
    REWARD_FRACTION × среднее."""
    avg_gold, avg_exp = _avg_rewards(boss_list)
    return (int(avg_gold * REWARD_FRACTION), int(avg_exp * REWARD_FRACTION))


# ============ КУЛДАУН ============

def get_cooldown_left(user_id):
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
    return row["expires_at"] - int(time.time())


def _set_cooldown(user_id):
    _ensure_tables()
    expires = int(time.time()) + RUSH_COOLDOWN_SECONDS
    conn = database.get_conn()
    conn.execute(
        "INSERT INTO boss_rush_cooldowns (user_id, expires_at) VALUES (?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET expires_at = excluded.expires_at",
        (user_id, expires),
    )
    conn.commit()


def format_cooldown(seconds):
    m, s = divmod(int(seconds), 60)
    return f"{m}м {s:02d}с" if m else f"{s}с"


# ============ RUN STATE ============

def _get_run(user_id):
    _ensure_tables()
    conn = database.get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM boss_rush_runs WHERE user_id = ?", (user_id,))
    return cur.fetchone()


def is_rush_active(user_id):
    row = _get_run(user_id)
    return bool(row and row["status"] == "active")


def _delete_run(user_id):
    conn = database.get_conn()
    conn.execute("DELETE FROM boss_rush_runs WHERE user_id = ?", (user_id,))
    conn.commit()


def _update_run(user_id, current_idx, acc_gold, acc_exp, killed, status="active"):
    conn = database.get_conn()
    conn.execute(
        "UPDATE boss_rush_runs SET current_idx = ?, accumulated_gold = ?, "
        "accumulated_exp = ?, bosses_killed = ?, status = ? WHERE user_id = ?",
        (current_idx, acc_gold, acc_exp, killed, status, user_id),
    )
    conn.commit()


def _full_heal_at_start(user_id):
    """Один раз в начале забега — полный HP и ПЭ.
    Между боями НЕ вызывается."""
    try:
        import ce_types
        player = database.get_or_create_player(user_id, "")
        eff = ce_types.get_effective_stats(user_id, player)
        database.update_player_hp(user_id, eff["max_hp"])
        database.update_player_ce(user_id, eff["max_ce"])
    except Exception:
        pass


def _freeze_bosses(user_id):
    run = _get_run(user_id)
    if not run:
        return []
    names = json.loads(run["bosses_json"])
    by_name = {b["base_name"]: b for b in _build_boss_list(user_id)}
    return [by_name[n] for n in names if n in by_name]


# ============ СПАВН БОССА ============

def _spawn_boss(user_id, boss_list, idx):
    if idx < 0 or idx >= len(boss_list):
        return {"ok": False, "msg": "Некорректный индекс босса."}
    b = boss_list[idx]
    full_name = f"{CLUB_PREFIX}[{idx + 1}/{len(boss_list)}] {b['base_name']}"

    base_skills = story.BOSS_SKILLS.get(b["base_name"])
    if base_skills:
        story.BOSS_SKILLS[full_name] = base_skills

    try:
        import bosses
        bosses.BOSSES[full_name] = {
            "emoji": b["emoji"],
            "hp": int(b["hp"] * BOSS_HP_MULT),
            "dmg_min": int(b["dmg_min"] * BOSS_DMG_MULT),
            "dmg_max": int(b["dmg_max"] * BOSS_DMG_MULT),
            "rarity": "Особый класс",
            "reward_gold": 0,
            "reward_exp": 0,
            "drop_item": None,
        }
    except Exception:
        pass

    new_hp = int(b["hp"] * BOSS_HP_MULT)
    new_dmg_min = int(b["dmg_min"] * BOSS_DMG_MULT)
    new_dmg_max = int(b["dmg_max"] * BOSS_DMG_MULT)

    monster = {
        "name": full_name,
        "hp": new_hp,
        "dmg_min": new_dmg_min,
        "dmg_max": new_dmg_max,
        "emoji": b["emoji"],
        "rarity": "Особый класс",
        "curse_class": "Особый класс",
        "defense": 0.0,
        "drop_item": None,
        "drop_rarity": None,
    }
    database.set_encounter(user_id, "jujutsu_high", monster)
    return {"ok": True, "stage": idx + 1, "total": len(boss_list), "boss": b}


def respawn_current_boss(user_id):
    """Пересоздаёт encounter для текущего индекса забега.
    Используется, если encounter пропал (истёк TTL, сброс бота и т.п.),
    а забег всё ещё активен.

    Возвращает dict как _spawn_boss: {ok, stage, total, boss} или {ok: False, msg}.
    """
    run = _get_run(user_id)
    if not run or run["status"] != "active":
        return {"ok": False, "msg": "У тебя нет активного забега."}

    boss_list = _freeze_bosses(user_id)
    if not boss_list:
        return {"ok": False, "msg": "Список боссов пуст."}

    idx = run["current_idx"]
    if idx < 0 or idx >= len(boss_list):
        return {"ok": False, "msg": "Некорректный индекс босса."}

    existing = database.get_encounter(user_id)
    if existing:
        return {"ok": True, "stage": idx + 1, "total": len(boss_list),
                "boss": boss_list[idx], "already_spawned": True}

    return _spawn_boss(user_id, boss_list, idx)


# ============ СТАРТ ЗАБЕГА ============

def start_rush(user_id):
    if not is_unlocked(user_id):
        return {"ok": False, "msg": f"🔒 Клуб откроется после прохождения {BOSS_RUSH_UNLOCK_CHAPTER} глав сюжета."}
    if database.get_encounter(user_id):
        return {"ok": False, "msg": "Ты уже в бою! Сначала закончи текущий."}
    if story.is_in_temp(user_id):
        return {"ok": False, "msg": "Сначала покинь сюжетную локацию (⬅️ Вернуться в школу)."}
    if is_rush_active(user_id):
        return {"ok": False, "msg": "У тебя уже идёт забег."}
    cd = get_cooldown_left(user_id)
    if cd > 0:
        return {"ok": False, "msg": f"⏳ Хакари не даст тебе драться так часто. Отдых: {format_cooldown(cd)}."}

    boss_list = _build_boss_list(user_id)
    if not boss_list:
        return {"ok": False, "msg": "Пока ни одного босса не пройдено."}

    cost = entry_cost(user_id)
    player = database.get_or_create_player(user_id, "")
    if player["gold"] < cost:
        return {"ok": False, "msg": f"❌ Не хватает 💠 на вход. Нужно <b>{cost}</b>, у тебя <b>{player['gold']}</b>."}

    database.add_gold(user_id, -cost)
    _set_cooldown(user_id)

    _ensure_tables()
    conn = database.get_conn()
    conn.execute("DELETE FROM boss_rush_runs WHERE user_id = ?", (user_id,))
    conn.execute(
        "INSERT INTO boss_rush_runs (user_id, bosses_json, current_idx, "
        "accumulated_gold, accumulated_exp, bosses_killed, started_at, status) "
        "VALUES (?, ?, 0, 0, 0, 0, ?, 'active')",
        (user_id, json.dumps([b["base_name"] for b in boss_list]), int(time.time())),
    )
    conn.commit()

    _full_heal_at_start(user_id)
    spawn = _spawn_boss(user_id, boss_list, 0)
    if not spawn["ok"]:
        _delete_run(user_id)
        return spawn

    return {
        "ok": True,
        "entry_cost": cost,
        "stage": 1,
        "total": len(boss_list),
        "boss": boss_list[0],
    }


# ============ ХУКИ ИЗ COMBAT ============

def on_rush_boss_victory(user_id, encounter, log):
    run = _get_run(user_id)
    if not run:
        database.clear_encounter(user_id)
        return {"status": "victory", "log": log, "effect": "boss_victory"}

    boss_list = _freeze_bosses(user_id)
    idx = run["current_idx"]
    killed = run["bosses_killed"] + 1
    acc_gold = run["accumulated_gold"]
    acc_exp = run["accumulated_exp"]

    avg_gold, avg_exp = _avg_rewards(boss_list)
    base_gold = int(avg_gold * REWARD_FRACTION)
    base_exp = int(avg_exp * REWARD_FRACTION)

    vip = database.vip_mult(user_id)
    gold_add = int(base_gold * vip)
    exp_add = int(base_exp * vip)
    acc_gold += gold_add
    acc_exp += exp_add

    log.append(f"\n🥊 <b>Босс {killed}/{len(boss_list)} повержен!</b>")
    log.append(f"💰 +{gold_add}💠 · 🧬 +{exp_add} опыта")
    log.append(f"📦 Накоплено: {acc_gold}💠 / {acc_exp}🧬")
    if vip > 1:
        log.append("💎 <i>VIP: награды ×2</i>")

    database.clear_encounter(user_id)

    next_idx = idx + 1
    if next_idx < len(boss_list):
        _update_run(user_id, next_idx, acc_gold, acc_exp, killed, "active")
        spawn = _spawn_boss(user_id, boss_list, next_idx)
        if not spawn["ok"]:
            return _finalize_rush(user_id, acc_gold, acc_exp, killed, log, full_clear=False)
        nxt = boss_list[next_idx]
        log.append(f"\n👉 Следующий: {nxt['emoji']} <b>{nxt['base_name']}</b>")
        log.append("<i>HP и ПЭ не восстанавливаются между боями. Расходники запрещены.</i>")
        return {
            "status": "ongoing",
            "log": log,
            "effect": "boss_victory",
            "rush_continue": True,
        }

    return _finalize_rush(user_id, acc_gold, acc_exp, killed, log, full_clear=True)


def on_rush_player_death(user_id, player, log):
    run = _get_run(user_id)
    if not run:
        return {"status": "death", "log": log, "effect": "death"}

    acc_gold = run["accumulated_gold"]
    acc_exp = run["accumulated_exp"]
    killed = run["bosses_killed"]

    if acc_gold > 0:
        database.add_gold(user_id, acc_gold)
    if acc_exp > 0:
        database.add_exp_and_level(user_id, acc_exp)

    log.append(f"\n☠️ <b>Ты повержен в бою с боссом {killed + 1}.</b>")
    log.append(f"📦 Награда за забег: 💠 +{acc_gold}, 🧬 +{acc_exp}")
    log.append(f"🎯 Убито боссов: {killed}")

    try:
        import ce_types
        eff = ce_types.get_effective_stats(user_id, player)
        respawn_hp = max(1, eff["max_hp"] // 2) if eff["max_hp"] > 0 else 1
        database.update_player_hp(user_id, respawn_hp)
    except Exception:
        pass
    database.update_player_x(user_id, 0)
    _delete_run(user_id)

    return {"status": "death", "log": log, "effect": "death", "rush_finished": True}


def on_rush_flee(user_id, log):
    run = _get_run(user_id)
    if not run:
        database.clear_encounter(user_id)
        return {"status": "fled", "log": log}

    killed = run["bosses_killed"]
    log.append("\n🏃 <b>Ты сбежал из боевого клуба!</b>")
    log.append("💀 Хакари не любит трусов. Всё накопленное пропало.")
    log.append(f"🎯 Убито боссов: {killed}")

    database.clear_encounter(user_id)
    _delete_run(user_id)

    return {"status": "fled", "log": log, "rush_finished": True}


def _finalize_rush(user_id, acc_gold, acc_exp, killed, log, full_clear=False):
    bonus_gold = 0
    bonus_exp = 0
    if full_clear:
        bonus_gold = int(acc_gold * FULL_CLEAR_GOLD_BONUS_MULT)
        bonus_exp = int(acc_exp * FULL_CLEAR_EXP_BONUS_MULT)
        acc_gold += bonus_gold
        acc_exp += bonus_exp

    if acc_gold > 0:
        database.add_gold(user_id, acc_gold)
    new_level = None
    leveled = False
    if acc_exp > 0:
        new_level, leveled = database.add_exp_and_level(user_id, acc_exp)

    if full_clear:
        vip = database.vip_mult(user_id)
        qty = FULL_CLEAR_ITEM_QTY * (2 if vip > 1.0 else 1)
        database.add_item(user_id, FULL_CLEAR_ITEM_NAME, FULL_CLEAR_ITEM_RARITY, qty)

    log.append("\n🏆 <b>ЗАБЕГ ЗАВЕРШЁН!</b>")
    log.append(f"🎯 Убито боссов: {killed}")
    log.append(f"💰 Итого: <b>{acc_gold}</b>💠 · 🧬 <b>{acc_exp}</b> опыта")
    if full_clear:
        log.append(f"✨ <b>Бонус за полное прохождение: +{bonus_gold}💠 / +{bonus_exp}🧬</b>")
        log.append(f"🎁 Трофей: {FULL_CLEAR_ITEM_NAME} ×{FULL_CLEAR_ITEM_QTY}")

    if leveled:
        log.append(f"\n🎉 <b>Уровень повышен до {new_level}!</b>")

    _delete_run(user_id)

    return {
        "status": "victory",
        "log": log,
        "effect": "boss_victory",
        "rush_finished": True,
        "rush_full_clear": full_clear,
    }


# ============ UI ============

def format_menu(user_id):
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
    boss_list = _build_boss_list(user_id)
    n = len(boss_list)
    cost = entry_cost(user_id)
    cd = get_cooldown_left(user_id)
    active = is_rush_active(user_id)

    avg_gold, avg_exp = _avg_rewards(boss_list)
    per_gold, per_exp = per_boss_reward(boss_list)

    lines = [
        "🥊 <b>Боевой клуб Хакари</b>",
        "",
        "<i>Хакари: «Boss rush через всех, кого ты уже побеждал. "
        "Один забег без остановок. HP и ПЭ восстанавливаю ОДИН РАЗ на входе. "
        "Между боями — не жди пощады. Зелья не помогут. "
        "Проиграл — забег кончился, получил что успел. "
        "Сбежал — ушёл ни с чем. Прошёл всех — большой бонус.»</i>",
        "",
        f"💠 <b>Вход:</b> {cost} (за {n} боссов)",
        f"⏱ Кулдаун между забегами: {format_cooldown(RUSH_COOLDOWN_SECONDS)}",
        f"💠 У тебя: <b>{player['gold']}</b>",
        "🚫 <b>Расходники запрещены</b>",
        "💔 <b>HP и ПЭ между боями НЕ восстанавливаются</b>",
    ]
    if cd > 0:
        lines.append(f"⏳ Следующий забег через: <b>{format_cooldown(cd)}</b>")
    lines.append("")
    lines.append("<b>В забеге:</b>")
    for i, b in enumerate(boss_list, start=1):
        lines.append(
            f"  {i}. {b['emoji']} <b>{b['base_name']}</b> "
            f"(гл. {b['chapter_num']}) — ❤️ {int(b['hp'] * BOSS_HP_MULT)} · "
            f"💰 {b['reward_gold']} · 🧬 {b['reward_exp']}"
        )
    lines.append("")
    lines.append("<b>Награды:</b>")
    lines.append(
        f"  💰 За босса: <b>{per_gold}💠</b> "
        f"({int(REWARD_FRACTION * 100)}% от среднего {avg_gold})"
    )
    lines.append(
        f"  🧬 За босса: <b>{per_exp}</b> "
        f"({int(REWARD_FRACTION * 100)}% от среднего {avg_exp})"
    )
    lines.append(f"  💎 VIP: ×2")
    lines.append(f"  🏆 Полное прохождение: +{int(FULL_CLEAR_GOLD_BONUS_MULT * 100)}% и «{FULL_CLEAR_ITEM_NAME}»")
    lines.append("")
    if active:
        run = _get_run(user_id)
        idx = run["current_idx"]
        lines.append(f"⚔️ <b>Активный забег:</b> босс {idx + 1}/{n} · убито {run['bosses_killed']}")

    return "\n".join(lines)


def format_rush_progress(user_id):
    run = _get_run(user_id)
    if not run:
        return ""
    n = len(json.loads(run["bosses_json"]))
    idx = run["current_idx"]
    return (
        f"🥊 <b>Боевой клуб:</b> босс {idx + 1}/{n} · "
        f"убито {run['bosses_killed']} · "
        f"накоплено {run['accumulated_gold']}💠 / {run['accumulated_exp']}🧬"
    )


def rush_menu_keyboard(user_id):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    rows = []
    if is_unlocked(user_id):
        if is_rush_active(user_id):
            rows.append([InlineKeyboardButton(
                "▶️ Продолжить забег",
                callback_data="boss_rush_continue",
            )])
        else:
            cost = entry_cost(user_id)
            if cost > 0:
                rows.append([InlineKeyboardButton(
                    f"🥊 Начать забег ({cost}💠)",
                    callback_data="boss_rush_start",
                )])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="npc:hakari")])
    return InlineKeyboardMarkup(rows)

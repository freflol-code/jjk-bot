"""
raid.py — рейды на Сукуну для 1-5 игроков.

Ключевые механики:
- Пальцы Сукуны НЕ списываются. При старте боя все пальцы участника
  уходят в КД на 12 часов (FINGER_CD_SECONDS).
- Пальцы добываются только в сюжетке (см. story.py), поэтому их можно
  использовать многократно с задержкой.
- Уровень рейда (1/2/3 пальца) задаёт создатель. Чтобы присоединиться,
  у игрока должно быть НЕ МЕНЬШЕ пальцев, чем в рейде.
- Бой: пошаговый. Каждый живой игрок делает по одной атаке — обычной
  или врождённой техникой (если хватает ПЭ). Затем Сукуна отвечает.
- Сукуна может критовать.
- VIP даёт ×2 к золоту, опыту и дропу с рейда.
- Победа/поражение заканчивают рейд, все возвращаются в школу (X=0).
"""
import json
import random
import time

import database
import gacha


FINGER_CD_SECONDS = 12 * 3600
MAX_PLAYERS = 5
SUKUNA_NAME = "Сукуна (Рейд-босс)"
SUKUNA_EMOJI = "👺"


SUKUNA_PHASES = {
    1: {
        "hp": 1500,
        "dmg_min": 25, "dmg_max": 35,
        "crit_chance": 0.10, "crit_mult": 1.8,
        "reward_gold": 1500, "reward_exp": 800,
        "drop": ("Осколок Плоти Сукуны", "эпический", 1),
    },
    2: {
        "hp": 2800,
        "dmg_min": 35, "dmg_max": 50,
        "crit_chance": 0.15, "crit_mult": 1.8,
        "reward_gold": 3000, "reward_exp": 1600,
        "drop": ("Метка Сукуны", "легендарный", 1),
    },
    3: {
        "hp": 5000,
        "dmg_min": 50, "dmg_max": 70,
        "crit_chance": 0.20, "crit_mult": 2.0,
        "reward_gold": 6000, "reward_exp": 3500,
        "drop": ("Сердце Сукуны", "легендарный", 1),
    },
}


_db_ready = False


def _ensure_tables():
    global _db_ready
    if _db_ready:
        return
    conn = database.get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS raids (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            creator_id      INTEGER NOT NULL,
            fingers         INTEGER NOT NULL,
            status          TEXT    NOT NULL DEFAULT 'lobby',
            boss_hp         INTEGER NOT NULL,
            boss_max_hp     INTEGER NOT NULL,
            turn_order_json TEXT    NOT NULL DEFAULT '[]',
            turn_idx        INTEGER NOT NULL DEFAULT 0,
            log_json        TEXT    NOT NULL DEFAULT '[]',
            created_at      INTEGER NOT NULL,
            finished_at     INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS raid_participants (
            raid_id   INTEGER NOT NULL,
            user_id   INTEGER NOT NULL,
            hp        INTEGER NOT NULL,
            max_hp    INTEGER NOT NULL,
            alive     INTEGER NOT NULL DEFAULT 1,
            joined_at INTEGER NOT NULL,
            PRIMARY KEY (raid_id, user_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS finger_cooldowns (
            user_id    INTEGER NOT NULL PRIMARY KEY,
            expires_at INTEGER NOT NULL
        )
    """)
    conn.commit()
    _db_ready = True


# ============================================================
#  КД НА ПАЛЬЦЫ
# ============================================================

def _get_finger_count(user_id: int) -> int:
    return database.count_item(user_id, "Палец Сукуны")


def get_cooldown_until(user_id: int) -> int:
    _ensure_tables()
    conn = database.get_conn()
    cur = conn.cursor()
    cur.execute("SELECT expires_at FROM finger_cooldowns WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if not row:
        return 0
    if row["expires_at"] <= int(time.time()):
        conn.execute("DELETE FROM finger_cooldowns WHERE user_id = ?", (user_id,))
        conn.commit()
        return 0
    return row["expires_at"]


def can_use_fingers(user_id: int) -> bool:
    return get_cooldown_until(user_id) == 0 and _get_finger_count(user_id) > 0


def get_available_fingers(user_id: int) -> int:
    if not can_use_fingers(user_id):
        return 0
    return min(3, _get_finger_count(user_id))


def start_finger_cooldown(user_id: int):
    _ensure_tables()
    expires = int(time.time()) + FINGER_CD_SECONDS
    conn = database.get_conn()
    conn.execute(
        "INSERT INTO finger_cooldowns (user_id, expires_at) VALUES (?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET expires_at = excluded.expires_at",
        (user_id, expires),
    )
    conn.commit()


def format_cooldown(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}ч {m:02d}м"
    if m:
        return f"{m}м {s:02d}с"
    return f"{s}с"


# ============================================================
#  ЛОББИ
# ============================================================

def get_active_raid_for_user(user_id: int):
    _ensure_tables()
    conn = database.get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT r.* FROM raids r
        JOIN raid_participants p ON p.raid_id = r.id
        WHERE p.user_id = ? AND r.status IN ('lobby', 'battle')
        ORDER BY r.created_at DESC LIMIT 1
    """, (user_id,))
    row = cur.fetchone()
    if not row:
        return None
    return _row_to_raid(row)


def _row_to_raid(row) -> dict:
    return {
        "id": row["id"],
        "creator_id": row["creator_id"],
        "fingers": row["fingers"],
        "status": row["status"],
        "boss_hp": row["boss_hp"],
        "boss_max_hp": row["boss_max_hp"],
        "turn_order": json.loads(row["turn_order_json"]),
        "turn_idx": row["turn_idx"],
        "log": json.loads(row["log_json"] or "[]"),
        "created_at": row["created_at"],
        "finished_at": row["finished_at"],
    }


def _save_raid(raid: dict):
    conn = database.get_conn()
    conn.execute(
        "UPDATE raids SET status = ?, boss_hp = ?, turn_idx = ?, "
        "log_json = ?, finished_at = ? WHERE id = ?",
        (
            raid["status"],
            raid["boss_hp"],
            raid["turn_idx"],
            json.dumps(raid["log"], ensure_ascii=False),
            raid["finished_at"],
            raid["id"],
        ),
    )
    conn.commit()


def get_participants(raid_id: int) -> list[dict]:
    _ensure_tables()
    conn = database.get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM raid_participants WHERE raid_id = ? ORDER BY joined_at",
        (raid_id,),
    )
    return [dict(r) for r in cur.fetchall()]


def create_raid(creator_id: int, fingers: int) -> dict:
    if fingers < 1 or fingers > 3:
        return {"ok": False, "msg": "Можно создать рейд на 1, 2 или 3 пальца."}
    if not can_use_fingers(creator_id):
        cd = get_cooldown_until(creator_id)
        if cd:
            left = cd - int(time.time())
            return {"ok": False, "msg": f"Твои пальцы в КД ещё {format_cooldown(left)}."}
        return {"ok": False, "msg": "У тебя нет пальцев Сукуны. Их дропают сюжетные боссы."}

    if get_active_raid_for_user(creator_id):
        return {"ok": False, "msg": "Ты уже в активном рейде."}

    available = get_available_fingers(creator_id)
    if fingers > available:
        return {"ok": False, "msg": f"У тебя только {available} пальцев."}

    player = database.get_or_create_player(creator_id, "")
    phase = SUKUNA_PHASES[fingers]
    _ensure_tables()
    conn = database.get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO raids (creator_id, fingers, status, boss_hp, boss_max_hp,
                           turn_order_json, turn_idx, log_json, created_at)
        VALUES (?, ?, 'lobby', ?, ?, '[]', 0, '[]', ?)
    """, (creator_id, fingers, phase["hp"], phase["hp"], int(time.time())))
    raid_id = cur.lastrowid

    cur.execute("""
        INSERT INTO raid_participants (raid_id, user_id, hp, max_hp, alive, joined_at)
        VALUES (?, ?, ?, ?, 1, ?)
    """, (raid_id, creator_id, player["hp"], player["max_hp"], int(time.time())))
    conn.commit()

    return {"ok": True, "raid_id": raid_id}


def join_raid(raid_id: int, user_id: int) -> dict:
    raid_row = _get_raid_row(raid_id)
    if not raid_row:
        return {"ok": False, "msg": "Рейд не найден."}
    raid = _row_to_raid(raid_row)
    if raid["status"] != "lobby":
        return {"ok": False, "msg": "Рейд уже начался."}

    parts = get_participants(raid_id)
    if any(p["user_id"] == user_id for p in parts):
        return {"ok": True, "msg": "Ты уже в рейде."}
    if len(parts) >= MAX_PLAYERS:
        return {"ok": False, "msg": "В рейде уже максимум игроков."}

    if not can_use_fingers(user_id):
        cd = get_cooldown_until(user_id)
        if cd:
            left = cd - int(time.time())
            return {"ok": False, "msg": f"Твои пальцы в КД ещё {format_cooldown(left)}."}
        return {"ok": False, "msg": "У тебя нет пальцев Сукуны."}

    required = raid["fingers"]
    have = _get_finger_count(user_id)
    if have < required:
        return {"ok": False, "msg": (
            f"Этот рейд на <b>{required}</b> 🩸 — Сукуна будет "
            f"{required}-пальцевым.\n"
            f"У тебя только <b>{have}</b> 🩸. Чтобы войти, нужно "
            f"минимум {required} пальцев."
        )}

    if get_active_raid_for_user(user_id):
        return {"ok": False, "msg": "Ты уже в другом рейде."}

    player = database.get_or_create_player(user_id, "")
    conn = database.get_conn()
    conn.execute("""
        INSERT INTO raid_participants (raid_id, user_id, hp, max_hp, alive, joined_at)
        VALUES (?, ?, ?, ?, 1, ?)
    """, (raid_id, user_id, player["hp"], player["max_hp"], int(time.time())))
    conn.commit()
    return {"ok": True, "msg": f"Ты присоединился к рейду на {required} 🩸."}


def leave_raid(raid_id: int, user_id: int) -> dict:
    raid_row = _get_raid_row(raid_id)
    if not raid_row:
        return {"ok": False, "msg": "Рейд не найден."}
    raid = _row_to_raid(raid_row)
    if raid["status"] != "lobby":
        return {"ok": False, "msg": "Нельзя выйти из начавшегося боя."}

    conn = database.get_conn()
    conn.execute("DELETE FROM raid_participants WHERE raid_id = ? AND user_id = ?",
                 (raid_id, user_id))
    conn.commit()

    parts = get_participants(raid_id)
    if not parts:
        conn.execute("UPDATE raids SET status = 'finished', finished_at = ? WHERE id = ?",
                     (int(time.time()), raid_id))
        conn.commit()
        return {"ok": True, "msg": "Ты вышел. Рейд распущен.", "disband": True}
    return {"ok": True, "msg": "Ты вышел из лобби."}


def _get_raid_row(raid_id: int):
    _ensure_tables()
    conn = database.get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM raids WHERE id = ?", (raid_id,))
    return cur.fetchone()


def get_raid(raid_id: int) -> dict | None:
    row = _get_raid_row(raid_id)
    return _row_to_raid(row) if row else None


# ============================================================
#  БОЙ
# ============================================================

def start_battle(raid_id: int, user_id: int) -> dict:
    raid_row = _get_raid_row(raid_id)
    if not raid_row:
        return {"ok": False, "msg": "Рейд не найден."}
    raid = _row_to_raid(raid_row)
    if raid["creator_id"] != user_id:
        return {"ok": False, "msg": "Только создатель может начать бой."}
    if raid["status"] != "lobby":
        return {"ok": False, "msg": "Бой уже начат."}

    parts = get_participants(raid_id)
    if not parts:
        return {"ok": False, "msg": "В рейде нет игроков."}

    for p in parts:
        start_finger_cooldown(p["user_id"])

    order = [p["user_id"] for p in parts]
    conn = database.get_conn()
    conn.execute(
        "UPDATE raids SET status = 'battle', turn_order_json = ?, turn_idx = 0, "
        "log_json = ?, created_at = ? WHERE id = ?",
        (json.dumps(order),
         json.dumps([f"👹 <b>{SUKUNA_NAME}</b> пробудился! Бой начался."], ensure_ascii=False),
         int(time.time()), raid_id),
    )
    conn.commit()

    return {"ok": True, "msg": "Бой начался!"}


def _current_player(raid: dict) -> int | None:
    order = raid["turn_order"]
    parts = {p["user_id"]: p for p in get_participants(raid["id"])}
    idx = raid["turn_idx"]
    while idx < len(order):
        uid = order[idx]
        if parts.get(uid, {}).get("alive"):
            return uid
        idx += 1
    return None


def is_player_turn(raid_id: int, user_id: int) -> bool:
    raid = get_raid(raid_id)
    if not raid or raid["status"] != "battle":
        return False
    return _current_player(raid) == user_id


def player_attack(raid_id: int, user_id: int, technique_name: str | None = None) -> dict:
    """Атака игрока. Если technique_name задано — используется врождённая
    техника (тратится ПЭ, урон считается по формуле техники). Иначе — обычная
    физическая атака."""
    raid = get_raid(raid_id)
    if not raid or raid["status"] != "battle":
        return {"ok": False, "msg": "Бой не идёт."}
    if not is_player_turn(raid_id, user_id):
        return {"ok": False, "msg": "Сейчас не твой ход."}

    player = database.get_or_create_player(user_id, "")
    from combat import _physical_damage, _technique_damage, _black_flash_chance
    from config import PLAYER_CRIT_MULT

    technique = None
    if technique_name:
        technique = gacha.get_technique(technique_name)
        if not technique or technique_name not in gacha.get_equipped(user_id):
            return {"ok": False, "msg": "Эта техника недоступна в бою."}
        if player["ce"] < technique["ce_cost"]:
            return {"ok": False, "msg": (
                f"Не хватает ПЭ: нужно {technique['ce_cost']}🔵, "
                f"у тебя {player['ce']}🔵."
            )}

    if technique:
        dmg = _technique_damage(user_id, player, technique)
        verb = f"использовал «{technique_name}»"
    else:
        dmg = _physical_damage(user_id, player)
        verb = "атаковал"

    black_flash = random.random() < _black_flash_chance(user_id)
    if black_flash:
        dmg = int(dmg * PLAYER_CRIT_MULT)

    # Списываем ПЭ, если использовали технику
    if technique:
        database.update_player_ce(user_id, player["ce"] - technique["ce_cost"])

    raid["boss_hp"] = max(0, raid["boss_hp"] - dmg)
    nick = player["username"] or f"Игрок {user_id}"
    line = (f"{technique['emoji'] + ' ' if technique else '🗡 '}<b>{nick}</b> "
            + (f"использовал «{technique_name}» " if technique else "атаковал ")
            + ("⚫⚡ <b>ЧЁРНАЯ ВСПЫШКА!</b> " if black_flash else "")
            + f"и нанёс <b>{dmg}</b> урона Сукуне.")
    raid["log"].append(line)
    raid["log"] = raid["log"][-12:]

    if raid["boss_hp"] <= 0:
        return _finish_victory(raid)

    raid["turn_idx"] += 1
    _save_raid(raid)

    if _current_player(raid) is None:
        return _sukuna_turn(raid)

    next_id = _current_player(raid)
    return {"ok": True, "msg": line, "notify": [next_id] if next_id else []}


def _sukuna_turn(raid: dict) -> dict:
    phase = SUKUNA_PHASES[raid["fingers"]]
    parts = [p for p in get_participants(raid["id"]) if p["alive"]]
    if not parts:
        return _finish_defeat(raid)

    attack_type = random.choice(["strike", "dismantle"])
    if attack_type == "strike":
        targets = [random.choice(parts)]
        header = "👊 <b>Обычный удар</b>"
    else:
        if len(parts) >= 2:
            targets = random.sample(parts, 2)
        else:
            targets = parts[:]
        header = "🩸 <b>Рассечение</b>"

    raid["log"].append(f"👹 <b>{SUKUNA_NAME}</b> применяет: {header}")

    for t in targets:
        raw = random.randint(phase["dmg_min"], phase["dmg_max"])
        crit = random.random() < phase["crit_chance"]
        if crit:
            raw = int(raw * phase["crit_mult"])

        new_hp = t["hp"] - raw
        alive = 1
        if new_hp <= 0:
            new_hp = 0
            alive = 0

        conn = database.get_conn()
        conn.execute(
            "UPDATE raid_participants SET hp = ?, alive = ? WHERE raid_id = ? AND user_id = ?",
            (new_hp, alive, raid["id"], t["user_id"]),
        )
        conn.commit()

        nick = database.get_or_create_player(t["user_id"], "")["username"] or f"Игрок {t['user_id']}"
        crit_txt = " 💥<b>КРИТ!</b>" if crit else ""
        if alive:
            raid["log"].append(f"   └ {nick} получает <b>{raw}</b> урона (HP: {new_hp}).{crit_txt}")
        else:
            raid["log"].append(f"   └ 💀 {nick} падает! (было {raw} урона).{crit_txt}")

    raid["log"] = raid["log"][-12:]

    raid["turn_idx"] = 0
    _save_raid(raid)

    alive_parts = [p for p in get_participants(raid["id"]) if p["alive"]]
    if not alive_parts:
        return _finish_defeat(raid)

    next_id = _current_player(raid)
    return {"ok": True, "msg": "Ход Сукуны", "notify": [next_id] if next_id else []}


def _send_all_to_school(raid_id: int):
    for p in get_participants(raid_id):
        database.update_player_x(p["user_id"], 0)
        database.clear_encounter(p["user_id"])


def _finish_victory(raid: dict) -> dict:
    """Награда каждому выжившему. VIP даёт ×2 к золоту, опыту и дропу.
    Пальцев Сукуны в дропе рейда нет — их выдают только сюжетные боссы."""
    phase = SUKUNA_PHASES[raid["fingers"]]
    parts = get_participants(raid["id"])
    survivors = [p for p in parts if p["alive"]]

    for p in survivors:
        vip = database.vip_mult(p["user_id"])
        gold = int(phase["reward_gold"] * vip)
        exp = int(phase["reward_exp"] * vip)
        database.add_gold(p["user_id"], gold)
        database.add_exp_and_level(p["user_id"], exp)
        dn, dr, dq = phase["drop"]
        if vip > 1.0:
            dq *= 2
        database.add_item(p["user_id"], dn, dr, dq)

    raid["log"].append("🏆 <b>Сукуна изгнан! Победа!</b>")
    raid["status"] = "finished"
    raid["finished_at"] = int(time.time())
    _save_raid(raid)

    _send_all_to_school(raid["id"])

    return {
        "ok": True,
        "msg": "Победа!",
        "finished": True,
        "notify": [p["user_id"] for p in parts],
    }


def _finish_defeat(raid: dict) -> dict:
    raid["log"].append("☠️ <b>Все игроки пали. Сукуна победил.</b>")
    raid["status"] = "finished"
    raid["finished_at"] = int(time.time())
    _save_raid(raid)

    _send_all_to_school(raid["id"])

    return {
        "ok": True,
        "msg": "Поражение",
        "finished": True,
        "notify": [p["user_id"] for p in get_participants(raid["id"])],
    }


# ============================================================
#  UI-ТЕКСТЫ
# ============================================================

def format_lobby(raid_id: int) -> str:
    raid = get_raid(raid_id)
    if not raid:
        return "Рейд не найден."
    parts = get_participants(raid_id)
    lines = [
        "👺 <b>Рейд на Сукуну</b>",
        f"🔴 Пальцев: <b>{raid['fingers']}</b>",
        f"👥 Игроков: <b>{len(parts)}/{MAX_PLAYERS}</b>",
        "",
        f"<i>Чтобы присоединиться, у каждого должно быть минимум "
        f"{raid['fingers']} 🩸 (уровень рейда задаёт сложность Сукуны).</i>",
        "",
        "<b>Участники:</b>",
    ]
    for p in parts:
        nick = database.get_or_create_player(p["user_id"], "")["username"] or f"Игрок {p['user_id']}"
        creator_mark = " 👑" if p["user_id"] == raid["creator_id"] else ""
        vip_mark = " 💎" if database.has_vip(p["user_id"]) else ""
        lines.append(f"• {nick}{creator_mark}{vip_mark} — ❤️ {p['hp']}/{p['max_hp']}")
    lines.append("")
    lines.append("<i>Создатель жмёт «▶️ Начать бой». Все пальцы участников уйдут в КД на 12 часов.</i>")
    lines.append("<i>Скинь друзьям ссылку-приглашение кнопкой ниже 👇</i>")
    return "\n".join(lines)


def format_battle(raid_id: int, viewer_id: int) -> str:
    raid = get_raid(raid_id)
    if not raid:
        return "Рейд не найден."

    parts = get_participants(raid_id)
    cur_id = _current_player(raid)
    viewer = next((p for p in parts if p["user_id"] == viewer_id), None)

    lines = [
        "👺 <b>Рейд на Сукуну</b>",
        f"🔴 Пальцев: {raid['fingers']}",
        f"❤️ HP Сукуны: <b>{raid['boss_hp']}/{raid['boss_max_hp']}</b>",
        "",
    ]

    if viewer:
        vp = database.get_or_create_player(viewer_id, "")
        from equipment import get_equipped
        w = get_equipped(viewer_id)
        weapon_txt = f"{w['emoji']} {w['name']}" if w else "нет"
        alive_txt = "жив" if viewer["alive"] else "💀 выбыл"
        vip_txt = " 💎" if database.has_vip(viewer_id) else ""
        lines.append(f"👤 <b>Ты</b>{vip_txt}")
        lines.append(f"   ❤️ HP: {viewer['hp']}/{viewer['max_hp']} | "
                     f"🔵 ПЭ: {vp['ce']}/{vp['max_ce']} | 🧬 Ур. {vp['level']} | {alive_txt}")
        lines.append(f"   ⚔️ Оружие: {weapon_txt}")
        lines.append("")

    lines.append("<b>Отряд:</b>")
    for p in parts:
        nick = database.get_or_create_player(p["user_id"], "")["username"] or f"Игрок {p['user_id']}"
        vip_mark = " 💎" if database.has_vip(p["user_id"]) else ""
        if not p["alive"]:
            marker = "💀"
        elif p["user_id"] == cur_id:
            marker = "🎯"
        elif p["user_id"] == viewer_id:
            marker = "👤"
        else:
            marker = "❤️"
        lines.append(f"{marker} {nick}{vip_mark}: {p['hp']}/{p['max_hp']}")

    lines.append("")
    if cur_id:
        cur_nick = database.get_or_create_player(cur_id, "")["username"] or f"Игрок {cur_id}"
        if cur_id == viewer_id:
            lines.append("⏳ <b>Сейчас твой ход!</b>")
        else:
            lines.append(f"⏳ Ход: <b>{cur_nick}</b>")
    else:
        lines.append("⏳ Ход Сукуны...")

    lines.append("")
    lines.append("<b>Лог:</b>")
    for l in raid["log"][-5:]:
        lines.append(l)

    return "\n".join(lines)


def format_finished(raid_id: int) -> str:
    raid = get_raid(raid_id)
    if not raid:
        return "Рейд не найден."
    phase = SUKUNA_PHASES[raid["fingers"]]
    lines = ["🏁 <b>Рейд завершён</b>", ""]
    lines.extend(raid["log"][-10:])
    lines.append("")
    lines.append(f"💠 Базовая награда выжившему: {phase['reward_gold']}")
    lines.append(f"🧬 Опыт: {phase['reward_exp']}")
    lines.append(f"🎁 Дроп: {phase['drop'][0]}")
    lines.append("")
    lines.append("💎 <b>VIP-игроки получают ×2</b> к золоту, опыту и дропу.")
    lines.append("")
    lines.append("<i>Все участники возвращаются в Токийскую школу магии.</i>")
    return "\n".join(lines)
